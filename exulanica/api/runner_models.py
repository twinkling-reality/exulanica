"""A person's own runner's models in an install that checks them (L1): offered beside the
manifest's own, listed with their checks, named by them, and asked for one minute.

Where an install keeps its checks (``EXULANICA_LOCAL_CHECKS_DIR``) and its decision client reads a
provider on this computer, :class:`~exulanica.api.services.Services` holds its
:class:`~exulanica.models.local_runner.LocalChecks`. A society whose engine asks its people under
the terms the checks were made under is offered every model the runner serves now that a kept
check finds able (:func:`runner_specs`); its models read lists every one with its state
(:func:`runner_rows`); a choice naming one is named by its kept check (:func:`runner_model_name`);
and the decision host asks the chosen ones through :func:`local_execution_source`.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from exulanica.canonical import canonical_json
from exulanica.models.client import ModelClient
from exulanica.models.local_runner import (
    CheckStore,
    LocalChecks,
    able_specs,
    check_cases,
    checks_directory,
    runner_models,
    with_runner_models,
)
from exulanica.models.local_runner import runner_rows as rows_of
from exulanica.models.manifest import MANIFEST_PATH, Manifest, ModelSpec, load_manifest
from exulanica.world.decision_roles import decision_roles

if TYPE_CHECKING:
    from exulanica.api.services import Services

__all__ = [
    "install_checks",
    "local_execution_source",
    "runner_model_name",
    "runner_rows",
    "runner_specs",
]


def install_checks(client: ModelClient | None, environ: Mapping[str, str]) -> LocalChecks | None:
    """The checks of the models a person's runner holds, kept in the install's check directory and
    asked through ``client``'s own transport, under the cases and the host's own rule for an
    answer; None where the install states no directory or the client reads no runner."""
    from exulanica.world.role_decisions import answer_outcome

    directory = checks_directory(environ)
    if client is None or directory is None:
        return None
    cases = check_cases()
    role = decision_roles().role(cases["role"])
    versions = cases["contract_versions"]
    return client.local_checks(
        CheckStore(directory),
        role=role,
        contract=role.contract(versions),
        cases=cases,
        judge=lambda case, label, line: answer_outcome(role, case, versions, label, line),
    )


def runner_specs(
    services: Services, engine: str | None, only: frozenset[str] | None = None
) -> tuple[ModelSpec, ...]:
    """The models a person's runner serves now whose kept check finds them able, for a society
    whose engine asks its people under the terms they were checked under; none elsewhere. A
    model with no current check is queued, and offered once its check is kept; with ``only``, just
    the models it names are asked about."""
    checks, client = services.local_checks, services.decision_client
    if checks is None or client is None or engine != checks.engine:
        return ()
    catalog = client.runner_catalog(checks.provider.provider_id)
    return () if catalog is None else able_specs(load_manifest(), catalog, checks, only)


def runner_rows(services: Services, engine: str | None) -> list[dict[str, Any]]:
    """Every model a person's runner serves now beside the manifest's own, each able, being
    checked, or not able and why (:func:`~exulanica.models.local_runner.runner_rows`), for a
    society whose engine asks under the terms they are checked under; none elsewhere."""
    checks, client = services.local_checks, services.decision_client
    if checks is None or client is None or engine != checks.engine:
        return []
    catalog = client.runner_catalog(checks.provider.provider_id)
    return [] if catalog is None else rows_of(load_manifest(), catalog, checks)


def runner_model_name(services: Services, model_id: str) -> str | None:
    """How a person reads a runner's model a choice names, from its kept check, whether or not
    the runner still holds it; None for any other model."""
    return None if services.local_checks is None else services.local_checks.name(model_id)


def local_execution_source(
    services: Services, workspace_id: uuid.UUID, engine: str, selected: frozenset[str]
) -> tuple[ModelClient, Manifest, str] | None:
    """The chosen models a person's runner serves now and a kept check finds able, bound for
    one minute's asks: each asked by the name serving its weights now, only for the role and
    prompt it was checked under, and only while that name still serves those weights."""
    checks, client = services.local_checks, services.decision_client
    if checks is None or client is None:
        return None
    # Only the models the minute chose are asked about: a minute never begins a check of the rest,
    # which begins the first time a list shows them.
    specs = runner_specs(services, engine, only=selected)
    if not specs:
        return None
    manifest = with_runner_models(load_manifest(), specs)
    provider = checks.provider.provider_id

    def guard() -> bool:
        serving = {
            model.model_id: model.tag for model in runner_models(client.runner_catalog(provider))
        }
        return all(serving.get(spec.model_id) == spec.served_as for spec in specs)

    bound = client.with_chosen_manifest(
        manifest, dict.fromkeys((spec.model_id for spec in specs), checks.scope), guard=guard
    )
    # What a decision records it was asked under: the shipped manifest and every runner model
    # the minute adds, by its weights and how it is asked.
    digest = hashlib.sha256(
        canonical_json(
            {
                "base_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
                "runner_models": [
                    {
                        "model_id": spec.model_id,
                        "served_as": spec.served_as,
                        "num_ctx": spec.context_window_tokens,
                        "reasoning_off": spec.served_with_reasoning_off,
                    }
                    for spec in specs
                ],
            }
        )
    ).hexdigest()
    return bound, manifest, digest
