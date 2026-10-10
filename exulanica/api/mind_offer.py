"""Who may decide for one version's beings, as the actions route hands the Companion's planner.

The Companion's world-edit drafter may name ``choose_mind`` (``exulanica.selection.action_plan``):
an open model, or their own routine, for a being or a group of them. The step is one request to
``POST /world/versions/{version_id}/models/{role_key}``. :class:`WorldMinds` is what the planner
asks, since it may import neither this package nor the host: the models the server offers the
people's role under the contract this version's society is asked under, why this host asks none of
them here, what a choice would meet (the choice record's own checks, read with no lock and
recording nothing), and what one would cost.

The cost is stated from what the host itself reserves and bounds: the most one answer may reserve
(:func:`exulanica.api.decision_host.ask_bound_usd`, the figure the playback worker reserves before
it asks), once a being a simulated minute at most; and the world's own ceilings an hour, in dollars
and in decisions, past which the routine decides (:func:`exulanica.api.decision_host.hour_refusal`).
A choice asks no model itself: playing the world does.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from exulanica.api.decision_host import ask_bound_usd
from exulanica.api.routes.society_models import offered_models
from exulanica.api.services import Services
from exulanica.models.manifest import ManifestError, load_manifest
from exulanica.models.usage import usd_string
from exulanica.selection.action_minds import MindChoice
from exulanica.spending.status import SpendingRefusals
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.minds_budget import MindsBudgetRepository
from exulanica.world.society import UnknownSociety
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository

__all__ = ["WorldMinds", "world_minds"]

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorldMinds:
    """Who may decide for the beings of one version's society, for one caller's workspace."""

    connection: psycopg.Connection
    workspace_id: uuid.UUID
    world_id: str
    version_id: uuid.UUID
    role: DecisionRole
    #: The engine of the version's society, or None where it holds none.
    engine: str | None
    services: Services
    #: Who asks: the account a play would name.
    actor: uuid.UUID | None = None
    #: What the durable spending authority would answer the workspace's next attempt, by provider,
    #: read once for the plan (:func:`world_minds`); None where no authority admits or the read
    #: failed, and then no model is said to be refused by an allowance.
    spent: SpendingRefusals | None = None

    @property
    def role_key(self) -> str:
        return self.role.key

    def _asked(self) -> DecisionContract:
        """The contract this version's beings are asked under: its engine's terms."""
        if self.engine is None or not self.role.hosted_by(self.engine):
            return self.role.contract()
        return self.role.contract(self.role.terms(self.engine).versions)

    def models(self) -> Sequence[MindChoice]:
        """Every model the server offers the people's role that this version's contract can ask,
        each with why nothing its provider serves is asked for this workspace now, if nothing is:
        this process's own refusal of the provider, else the durable spending authority's once
        the workspace's allowance for that provider is used up (``spent``). A step naming such a
        model states no cost: nothing would be asked."""
        spent = self.spent
        found = []
        for model in offered_models(self.role, self.services, self._asked()):
            provider = str(model["provider"])
            used_up = None if spent is None else spent.every((provider,))
            found.append(
                MindChoice(
                    provider=provider,
                    model_id=str(model["model_id"]),
                    name=str(model["name"]),
                    description=str(model["description"]),
                    refusal=model["refusal"] or (None if used_up is None else used_up.reason),
                )
            )
        return tuple(found)

    def host_refusal(self) -> str | None:
        """Why this host asks no chosen model for this workspace's beings, or None when it asks."""
        hosting = self.engine if self.engine and self.role.hosted_by(self.engine) else None
        return self.services.model_host_refusal(self.workspace_id, self.role, hosting)

    def preview(
        self, subjects: Sequence[str], model: Mapping[str, str] | None
    ) -> Mapping[str, Any]:
        """What the models route would meet for this choice now, recording nothing: as that route
        records it, under the role's own contract."""
        repository = SocietyModelChoiceRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        )
        try:
            return repository.preview_choice(
                self.version_id,
                self.role,
                subjects=subjects,
                model=model,
                manifest=load_manifest(),
                contract=self.role.contract(),
            )
        except UnknownSociety:
            return {
                "code": "society_unavailable",
                "subjects": [],
                "left_out": {},
                "run_now": 0,
                "run_after": 0,
                "bound": self.role.contract().value(self.role.subjects_bound),
                "choice_seq": 0,
            }

    def play_preview(self, subject: str | None) -> Mapping[str, Any]:
        """What the play route would meet for the caller starting to play ``subject`` now, and
        whom the caller plays, recording nothing."""
        empty = {"code": "society_unavailable", "playing": False, "played": [], "choice_seq": 0}
        if self.actor is None:
            return empty
        repository = SocietyModelChoiceRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        )
        try:
            return repository.preview_play(
                self.version_id, self.role, subject=subject, account_id=self.actor
            )
        except UnknownSociety:
            return empty

    def cost(self, model: Mapping[str, str], subjects: int) -> Mapping[str, Any] | None:
        """What ``model`` deciding for ``subjects`` beings may cost while the world plays, from the
        host's own figures; None where this process has no model client to reserve with."""
        client = self.services.model_client
        if client is None:
            return None
        manifest = load_manifest()
        try:
            spec = manifest.offered(self.role.chosen, model["model_id"])
        except ManifestError:
            return None
        contract = self._asked()
        one = ask_bound_usd(self.role, client.budget, spec, contract)
        # The world's own budget for its minds, or the contract's figures where nobody set one.
        budget = MindsBudgetRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        ).current(self.role, contract)
        return {
            # A being is asked at most once a simulated minute, at its own choice points.
            "per": "simulated_minute",
            "provider": spec.provider,
            "provider_description": manifest.provider(spec.provider).description,
            "subjects": subjects,
            "usd_per_answer_at_most": usd_string(one),
            "usd_at_most": usd_string(one * subjects),
            # No measured figure of a typical minute is recorded for this world yet.
            "usd_typical": None,
            "basis": {
                "kind": "reservation_bound",
                "answers_per_ask_at_most": contract.value("answer_attempts_maximum"),
            },
            "ceilings": {
                "usd_per_world_hour": budget.view()["usd_per_hour"],
                "decisions_per_world_hour": budget.decisions_per_hour,
                "set_by_a_person": budget.set_by_a_person,
            },
        }


def world_minds(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    services: Services,
    actor: uuid.UUID | None = None,
) -> WorldMinds | None:
    """Who may decide for ``version_id``'s beings, read once for a plan on the route's connection;
    None where the registry states no one role deciding for people.

    The workspace's allowance is read once here. A read that fails is an allowance not known, never
    a failed plan: no model is then said to be refused by it, and admission still refuses each
    attempt it would (as the playback host reads it, ``DecisionHost._spent_providers``)."""
    found = [role for role in decision_roles() if role.subject == "person"]
    if len(found) != 1:
        return None
    try:
        with connection.transaction():
            spent = services.spending_refusals(connection, workspace_id)
    except Exception as exc:
        # Never the exception's text, which may carry a connection string.
        _LOG.warning("the spending state could not be read: %s", type(exc).__qualname__)
        spent = None
    row = connection.execute(
        "select engine_version from world_society where workspace_id=%s and world_id=%s "
        "and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    return WorldMinds(
        connection,
        workspace_id,
        world_id,
        version_id,
        found[0],
        None if row is None else str(row["engine_version"]),
        services,
        actor,
        spent,
    )
