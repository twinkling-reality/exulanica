"""Local checkpoints, dependency inspection and selected evidence playback without providers."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError
from exulanica.things.kinds import read_thing_kind, shipped_thing_kinds
from exulanica.world.decision_roles import decision_roles
from exulanica.world_package.projects.schema import Checkpoint, ShippedKind, Source

MAX_BYTES = 2 * 1024 * 1024


class ProjectError(ExulanicaError):
    """A checkpoint, dependency, review or repository operation was refused."""


class Conflict(ProjectError):
    """A reviewed base no longer matches; nothing may silently replace it."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError("duplicate JSON field")
        result[key] = value
    return result


def decode(data: bytes) -> Any:
    if len(data) > MAX_BYTES:
        raise ProjectError("checkpoint or dependency exceeds the 2 MiB limit")
    try:
        value = json.loads(data, object_pairs_hook=_pairs)
        canonical_json(value)
        return value
    except (ValueError, UnicodeError, RecursionError, ExulanicaError) as exc:
        raise ProjectError("invalid strict JSON document") from exc


def validate(value: Any) -> Checkpoint:
    try:
        # Validate even a previously constructed/mutated Pydantic instance.
        raw = value.model_dump() if isinstance(value, Checkpoint) else value
        model = Checkpoint.model_validate(raw)
        if len(canonical_json(model.model_dump())) > MAX_BYTES:
            raise ProjectError("checkpoint exceeds the 2 MiB limit")
        return model
    except (ValidationError, ValueError, ExulanicaError) as exc:
        # Pydantic errors include the rejected input; never echo it to a terminal/log.
        raise ProjectError(
            "checkpoint violates its closed schema or native placement rules"
        ) from exc


def document(value: Any) -> dict[str, Any]:
    result = validate(value).model_dump()
    result["region_ids"].sort()
    for section, key in (
        ("things", "thing_id"),
        ("dependencies", "sha256"),
        ("models", "thing_id"),
        ("decisions", "record_id"),
    ):
        result[section].sort(key=lambda item: item[key])
    return result


def checkpoint_digest(value: Any) -> str:
    return digest(canonical_json(document(value)))


def pretty(value: Any) -> bytes:
    data = (
        json.dumps(document(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    if len(data) > MAX_BYTES:
        raise ProjectError("formatted checkpoint exceeds the 2 MiB limit")
    return data


def read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProjectError("checkpoint must be a regular file, not a symlink")
    with path.open("rb") as stream:
        return document(decode(stream.read(MAX_BYTES + 1)))


def save(path: Path, value: Any) -> str:
    """Save to a new private local file; never overwrite a checkpoint or publish it."""
    data = pretty(value)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Conflict("local destination exists; choose a new checkpoint path") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return checkpoint_digest(value)


def changes(before: Any | None, after: Any) -> str:
    """Stable, readable field diff over only the explicitly selected checkpoint."""
    old = [] if before is None else pretty(before).decode().splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old,
            pretty(after).decode().splitlines(keepends=True),
            fromfile="saved-checkpoint",
            tofile="selected-checkpoint",
        )
    )


def fork(value: Any, project_id: str) -> dict[str, Any]:
    parent = document(value)
    result = dict(parent)
    result["project_id"] = project_id
    result["forked_from"] = {
        "project_id": parent["project_id"],
        "checkpoint_sha256": checkpoint_digest(parent),
    }
    return document(result)


def inspect(
    value: Any,
    *,
    dependencies: Mapping[str, bytes],
    expected_source: Source | None = None,
) -> dict[str, Any]:
    """Validate local dependency bytes; never fetch, execute, or install anything.

    Source identity is only compared with a caller-supplied base, not read from a running world.
    Availability and compatible syntax never confer rights to use an asset or call a provider.
    """
    project = validate(value)
    if expected_source is not None and project.source != expected_source:
        raise Conflict("source world, version, state or snapshot differs from the expected base")
    builtins = {
        kind.sha256: canonical_json(dict(kind.document)) for kind in shipped_thing_kinds().values()
    }
    missing, invalid, unsupported = [], [], []
    resolved: dict[str, Any] = {}
    for dependency in project.dependencies:
        raw = dependencies.get(dependency.sha256, builtins.get(dependency.sha256))
        if raw is None:
            missing.append(dependency.sha256)
            continue
        if digest(raw) != dependency.sha256:
            invalid.append(dependency.sha256)
            continue
        try:
            decoded = decode(raw)
            if not isinstance(decoded, dict):
                raise ProjectError("dependency must be a JSON object")
            resolved[dependency.sha256] = decoded
        except ProjectError:
            invalid.append(dependency.sha256)

    for thing in project.things:
        data = resolved.get(thing.kind.sha256)
        if data is not None:
            try:
                kind = read_thing_kind(data)
                if kind.sha256 != thing.kind.sha256:
                    raise ValueError("noncanonical dependency")
                if any(m.thing_id == thing.thing_id for m in project.models):
                    deciders = kind.document["deciders"]
                    if (
                        kind.klass != "being"
                        or deciders is None
                        or "model" not in deciders["allowed"]
                    ):
                        unsupported.append(f"model-role:{thing.thing_id}")
            except (ValueError, ExulanicaError):
                invalid.append(thing.kind.sha256)
        elif not isinstance(thing.kind, ShippedKind):
            unsupported.append(f"unresolved-kind:{thing.thing_id}")
    for binding in project.models:
        contract = resolved.get(binding.contract_sha256)
        if contract is not None:
            try:
                role = decision_roles().for_contract(contract)
                if role.key != binding.role or role.subject != "person":
                    unsupported.append(f"decision-role:{binding.thing_id}")
            except ValueError:
                unsupported.append(f"decision-contract:{binding.thing_id}")
        manifest = resolved.get(binding.model_manifest_sha256)
        if manifest is not None and manifest != {
            "provider": binding.provider,
            "model_id": binding.model_id,
            "revision": binding.revision,
        }:
            invalid.append(binding.model_manifest_sha256)
    return {
        "checkpoint_sha256": checkpoint_digest(value),
        "missing_dependencies": sorted(set(missing)),
        "invalid_dependencies": sorted(set(invalid)),
        "unsupported": sorted(set(unsupported)),
        "dependencies_ready": not (missing or invalid or unsupported),
        "source_binding_verified": False,
        "model_availability_verified": False,
        "runtime_loadable": False,
        "runtime_boundary": "Offline selection only; live import and model compatibility require "
        "the receiving world's authorization and version authorities.",
    }


def playback(value: Any) -> dict[str, Any]:
    """Return selected records in order. This is not deterministic simulation replay."""
    project = validate(value)
    return {
        "mode": "selected-evidence-playback",
        "checkpoint_sha256": checkpoint_digest(value),
        "provider_calls": 0,
        "engine_replay_verified": False,
        "source_records_verified": False,
        "records": [
            d.model_dump()
            for d in sorted(
                project.decisions,
                key=lambda d: (d.tick, d.record_id),
            )
        ],
    }
