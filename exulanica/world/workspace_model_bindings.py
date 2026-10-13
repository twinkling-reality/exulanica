"""Executable workspace choices derived from exact probe replay, never asserted verdicts.

A binding is limited to the role and engine the fixed probe exercised. Runtime snapshots
retain the candidate's full parameters and fresh rates beside the shipped manifest digest;
a snapshot is historical evidence, not permission to execute after removal or restore.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models import provider_catalog
from exulanica.models.manifest import MANIFEST_PATH, AnsweringMechanism, Manifest, ModelSpec
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_probe_contract import candidate_spec, replay_terminal, seal
from exulanica.world.model_probes import ModelProbeRepository
from exulanica.world.society_planner import input_sha256
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.workspace_models import WorkspaceModel, WorkspaceModelRepository

PROFILE: Final = "exulanica.workspace-model-binding/v1"


@dataclass(frozen=True, slots=True)
class ProvenBinding:
    spec: ModelSpec
    role: str
    engine: str
    prompt_version: str
    added_seq: int
    added_sha256: str
    probe_id: uuid.UUID
    definition_sha256: str
    outcome_sha256: str

    def source(self) -> dict[str, Any]:
        return {
            "provider": self.spec.provider,
            "model_id": self.spec.model_id,
            "role": self.role,
            "engine": self.engine,
            "prompt_version": self.prompt_version,
            "added_seq": self.added_seq,
            "added_sha256": self.added_sha256,
            "probe_id": str(self.probe_id),
            "definition_sha256": self.definition_sha256,
            "outcome_sha256": self.outcome_sha256,
        }


def proof(
    state: WorkspaceModel,
    definition: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any],
    *,
    engine: str,
    manifest: Manifest,
) -> ProvenBinding:
    """Rebuild a current, licensed role binding from all independently rechecked answers."""
    verdict = state.verdict
    if (
        state.removed
        or verdict is None
        or verdict.get("profile") != "exulanica.workspace-model-probe/v1"
    ):
        raise ValueError("model_binding_unverified")
    if (
        definition["provider"] != state.provider
        or definition["model_id"] != state.model_id
        or definition["added_seq"] != state.added_seq
        or definition["added_sha256"] != state.added_sha256
        or verdict.get("added_seq") != state.added_seq
        or verdict.get("added_sha256") != state.added_sha256
        or verdict.get("outcome_sha256") != outcome["document_sha256"]
    ):
        raise ValueError("model_binding_stale")
    if state.model_id in manifest.models or state.provider not in manifest.providers:
        raise ValueError("model_binding_provider_or_identifier")
    role = decision_roles().role(definition["role"])
    if definition["engine"] != engine:
        raise ValueError("model_binding_engine_not_probed")
    stated = provider_catalog.provider_model(state.provider, state.model_id)
    if (
        stated is None
        or provider_catalog.licence_class(state.provider, state.model_id)
        != provider_catalog.ACCEPTED
        or not provider_catalog.decision_capable(stated, role.chosen.required_use_cases)
    ):
        raise ValueError("licence_or_capability_not_admitted")
    rebuilt = replay_terminal(definition, receipts, outcome)
    if rebuilt["code"] != "completed" or not rebuilt["finished"]:
        raise ValueError("model_binding_unverified")
    # Both tasks must pass by the same mechanism. Keep the role's own mechanism order;
    # the probe makes no comparative quality or ordering claim.
    mechanisms = {
        AnsweringMechanism(key): f"model-probe:{verdict['probe_id']}:{outcome['document_sha256']}"
        for key, value in rebuilt["mechanisms"].items()
        if value["answers"] and value["answers_lines"]
    }
    if not mechanisms:
        raise ValueError("model_binding_lines_not_verified")
    spec = replace(candidate_spec(definition), answering=mechanisms)
    if role.contract_for(engine).mechanism_for(spec) is None:
        raise ValueError("model_binding_contract_not_probed")
    return ProvenBinding(
        spec,
        role.key,
        engine,
        definition["prompt_version"],
        state.added_seq,
        state.added_sha256,
        uuid.UUID(verdict["probe_id"]),
        definition["document_sha256"],
        outcome["document_sha256"],
    )


def proven_bindings(
    connection: psycopg.Connection, workspace_id: uuid.UUID, engine: str, manifest: Manifest
) -> tuple[ProvenBinding, ...]:
    """Read only, no provider query or appended fact; malformed or obsolete proof grants nothing."""
    if connection.execute(
        "select 1 from tombstone where workspace_id=%s and scope='workspace'", (workspace_id,)
    ).fetchone():
        return ()
    found = []
    probes = ModelProbeRepository(connection, workspace_id)
    for state in WorkspaceModelRepository(connection, workspace_id).listing():
        if state.verdict is None or state.model_id in manifest.models:
            continue
        try:
            probe_id = uuid.UUID(state.verdict["probe_id"])
            recorded = probes.get(probe_id)
            outcome = connection.execute(
                "select document from model_probe_outcome where workspace_id=%s and probe_id=%s",
                (workspace_id, probe_id),
            ).fetchone()
            if outcome is None:
                continue
            found.append(
                proof(
                    state,
                    recorded["definition"],
                    probes.receipts(probe_id),
                    outcome["document"],
                    engine=engine,
                    manifest=manifest,
                )
            )
        except (ValueError, KeyError, TypeError):
            continue
    return tuple(found)


def with_bindings(manifest: Manifest, bindings: Sequence[ProvenBinding]) -> Manifest:
    return replace(
        manifest, models={**manifest.models, **{b.spec.model_id: b.spec for b in bindings}}
    )


def _document(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return {f.name: _document(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _document(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_document(item) for item in value]
    return value


def priced_snapshot(
    manifest: Manifest,
    bindings: Sequence[ProvenBinding],
    prices: Mapping[str, ProviderPrice],
    *,
    read_at: dt.datetime,
) -> tuple[Manifest, dict[str, Any]]:
    """Bind actual runtime rates and every execution parameter to a resolvable digest."""
    current = []
    sources = []
    for binding in bindings:
        price = prices[binding.spec.model_id]
        if price.model_id != binding.spec.model_id or price.context_window_tokens < (
            binding.spec.min_max_tokens or 0
        ):
            raise ValueError("model_binding_price_unavailable")
        current.append(
            replace(
                binding,
                spec=replace(
                    binding.spec,
                    input_usd_per_mtok=price.input_usd_per_mtok,
                    output_usd_per_mtok=price.output_usd_per_mtok,
                    context_window_tokens=price.context_window_tokens,
                ),
            )
        )
        sources.append(
            {
                **binding.source(),
                "rate_response_sha256": price.response_sha256,
                "rate_read_at": read_at.isoformat(),
            }
        )
    scoped = with_bindings(manifest, current)
    return scoped, seal(
        {
            "profile": PROFILE,
            "base_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            "catalog_sha256": provider_catalog.catalog_sha256(),
            "sources": sources,
            "manifest": _document(scoped),
        }
    )


class BindingSnapshotRepository:
    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection, self.workspace_id = connection, workspace_id

    def record(self, document: Mapping[str, Any]) -> str:
        digest = document["document_sha256"]
        if document["profile"] != PROFILE or digest != input_sha256(document):
            raise ValueError("model_binding_snapshot_invalid")
        with self.connection.transaction():
            lock_workspace(self.connection, self.workspace_id)
            if self.connection.execute(
                "select 1 from restore_control where state<>'complete'"
            ).fetchone():
                raise ValueError("model_binding_restore_not_complete")
            self.connection.execute(
                "insert into workspace_model_binding_snapshot"
                "(workspace_id,binding_sha256,document) "
                "values(%s,%s,%s) on conflict do nothing",
                (self.workspace_id, digest, Jsonb(dict(document))),
            )
        return digest

    def read(self, digest: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select document from workspace_model_binding_snapshot where workspace_id=%s "
            "and binding_sha256=%s",
            (self.workspace_id, digest),
        ).fetchone()
        if row is None:
            return None
        document = row["document"]
        if document["document_sha256"] != digest or digest != input_sha256(document):
            raise ValueError("model_binding_snapshot_invalid")
        return document
