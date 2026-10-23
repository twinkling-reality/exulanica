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
A choice asks no model itself: playing the world does. Beside the bound stands what an ask
typically cost where that engine and model were measured (:mod:`exulanica.world.minds_typical`),
each figure with its class, so an estimate is served as one.

The same object states what a budget for the world's minds would come to before a person sets it
(``set_minds_budget``, :meth:`WorldMinds.budget_sheet`): both ceilings, which of them runs out
first at the most an answer can cost and at the typical price, what the hour just past already
holds, how long the budget lasts for the beings a model decides for here, and what this server
allows above any budget.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Final

import psycopg

from exulanica.api.decision_host import ask_bound_usd, hour_refusal, world_hour
from exulanica.api.routes.society_models import offered_models
from exulanica.api.services import Services
from exulanica.models.manifest import ManifestError, load_manifest
from exulanica.models.usage import usd_string
from exulanica.selection.action_minds import MindChoice
from exulanica.spending.status import SpendingRefusals, read_workspace_status
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.minds_budget import MindsBudget, MindsBudgetRepository, default_budget
from exulanica.world.minds_typical import TypicalAsk, typical_ask
from exulanica.world.society import UnknownSociety
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository

__all__ = ["WorldMinds", "world_minds"]

_LOG = logging.getLogger(__name__)
_MILLISECONDS_AN_HOUR: Final = 3_600_000
_MINUTES_AN_HOUR: Final = 60


def _whole(value: Decimal, rounding: str = ROUND_FLOOR) -> int:
    return int(value.to_integral_value(rounding))


def _answers_for(usd: Decimal, bound: Decimal, price: Decimal) -> int | None:
    """How many asks ``usd`` admits in one hour when each is weighed at ``bound`` before it is
    made and then costs ``price``: the host admits an ask while what the hour has cost plus the
    ask's bound stays within the dollars (``hour_refusal``). None where an answer costs nothing
    (a model on this computer): the dollars then bound no number of answers."""
    if usd < bound:
        return 0
    if price == 0:
        return None
    return _whole((usd - bound) / price) + 1


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
        typical = typical_ask(self.engine, spec.provider, str(model["model_id"]))
        asked, spent = world_hour(self.connection, self.workspace_id, self.world_id, self.role)
        return {
            # A being is asked at most once a simulated minute, at its own choice points.
            "per": "simulated_minute",
            "provider": spec.provider,
            "provider_description": manifest.provider(spec.provider).description,
            "subjects": subjects,
            "usd_per_answer_at_most": usd_string(one),
            "usd_at_most": usd_string(one * subjects),
            # What these beings typically cost a simulated minute where this engine and model
            # were measured, and one ask of them; None where they were not. ``typical`` states
            # each figure's class and its record: a rate from a cut arm is an estimate.
            "usd_typical": None
            if typical is None
            else usd_string(typical.usd_per_ask * typical.asks_per_being_minute * subjects),
            "usd_per_answer_typical": None if typical is None else usd_string(typical.usd_per_ask),
            "typical": None if typical is None else typical.view(),
            "basis": {
                "kind": "reservation_bound",
                "answers_per_ask_at_most": contract.value("answer_attempts_maximum"),
            },
            "ceilings": {
                "usd_per_world_hour": budget.view()["usd_per_hour"],
                "decisions_per_world_hour": budget.decisions_per_hour,
                "set_by_a_person": budget.set_by_a_person,
            },
            # What the host would answer one more ask of this model now: the world's hour is
            # counted over the hour of real time just past, so a choice made while it is spent
            # asks nobody until it moves on, whatever a capability read says of the role.
            "hour_so_far": {"decisions": asked, "usd": str(spent.quantize(Decimal("0.000001")))},
            "refused_now": hour_refusal(asked, spent, one, contract, budget),
        }

    def budget(self) -> Mapping[str, Any]:
        """The world's budget for its minds now, and what a world has before anyone sets one."""
        contract = self._asked()
        held = MindsBudgetRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        ).current(self.role, contract)
        return {"now": held.view(), "default": default_budget(contract).view()}

    def _minded(self) -> dict[tuple[str, str], int]:
        """How many of this version's beings each model decides for now."""
        repository = SocietyModelChoiceRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        )
        try:
            deciding = repository.deciding(self.version_id, self.role, self.role.contract())
        except UnknownSociety:
            return {}
        found: dict[tuple[str, str], int] = {}
        for choice in deciding.values():
            model = choice.get("model")
            if model is not None:
                key = (str(model["provider"]), str(model["model_id"]))
                found[key] = found.get(key, 0) + 1
        return found

    def _beings(self) -> int | None:
        """How many beings this version's society holds, as its own state counts the role's
        subjects, whatever its engine; None where the version holds no society."""
        row = self.connection.execute(
            "select state from world_society where workspace_id=%s and world_id=%s "
            "and version_id=%s",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchone()
        if row is None:
            return None
        return len(tuple(self.role.adapter.subjects(row["state"])))

    def _minutes_a_real_hour(self) -> int | None:
        """How many simulated minutes this version's society plays in an hour of real time at
        the speed its control holds now, at most: None where it holds no society. A society
        whose control nobody configured plays at speed 1 on the host's base interval, as its
        control read says."""
        row = self.connection.execute(
            "select c.speed,c.base_tick_interval_ms from world_society s "
            "left join world_society_control c using(workspace_id,society_id) "
            "where s.workspace_id=%s and s.world_id=%s and s.version_id=%s",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchone()
        if row is None:
            return None
        if row["speed"] is None:
            interval = self.services.society_base_tick_interval_ms
        else:
            interval = int(row["base_tick_interval_ms"]) // int(row["speed"])
        return _MILLISECONDS_AN_HOUR // interval

    def _allowance(self, providers: Sequence[str]) -> list[dict[str, Any]] | None:
        """What the workspace's allowance has left by provider under the durable spending
        authority; None where no authority admits, or where it could not be read."""
        if self.spent is None or not providers:
            return None
        try:
            with self.connection.transaction():
                status = read_workspace_status(
                    self.connection, self.workspace_id, providers=sorted(set(providers))
                )
        except Exception as exc:
            # Never the exception's text, which may carry a connection string.
            _LOG.warning("the workspace's allowance could not be read: %s", type(exc).__qualname__)
            return None
        return [
            {
                "provider": str(entry["provider"]),
                "available_usd": str(entry["available_usd"]),
                "available_calls": int(entry["available_calls"]),
            }
            for entry in status["providers"]
        ]

    def budget_sheet(
        self, usd_per_hour: str, decisions_per_hour: int, beings: int | None
    ) -> Mapping[str, Any]:
        """What a budget of ``usd_per_hour`` and ``decisions_per_hour`` would come to for this
        world as it stands, recording nothing: every figure the sheet says before the yes.

        ``beings`` is how many beings the version's society holds, as its own state counts them
        (read here where the caller has no count of its own).
        ``models`` are the models that decide for beings here now, each with the most one answer
        can cost and what one typically cost where that was measured. ``answers_for_usd`` and
        ``binds`` are stated twice, at the most an answer can cost and at the typical price,
        because the host weighs each ask at its bound before it is made: the dearest model here
        decides both, so neither is said better than it is. Where every model here answers for
        nothing, the dollars bound no number of answers: ``answers_for_usd`` is None at both prices
        and the decisions are what runs out. ``demand`` is how often these beings
        typically ask in an hour of real time at the speed the world's control holds, and how
        many minutes of the hour the budget covers; it is None where a model here has no measured
        rate. ``refused_now`` is what the host would answer the next ask under this budget.
        """
        contract = self._asked()
        usd = Decimal(usd_per_hour)
        asked = MindsBudget(usd, decisions_per_hour)
        if beings is None:
            # The planner's own read counts a society of things; a living town's people are
            # counted here, from the society's state, so the sheet never lacks this town's number.
            beings = self._beings()
        so_far, spent = world_hour(self.connection, self.workspace_id, self.world_id, self.role)
        client = self.services.model_client
        manifest = load_manifest()
        names = {(model.provider, model.model_id): model.name for model in self.models()}
        models: list[dict[str, Any]] = []
        bounds: list[Decimal] = []
        typicals: list[TypicalAsk | None] = []
        counts: list[int] = []
        for (provider, model_id), count in sorted(self._minded().items()):
            try:
                spec = manifest.offered(self.role.chosen, model_id)
            except ManifestError:
                spec = None
            bound = (
                None
                if client is None or spec is None
                else ask_bound_usd(self.role, client.budget, spec, contract)
            )
            typical = typical_ask(self.engine, provider, model_id)
            if bound is not None:
                bounds.append(bound)
            typicals.append(typical)
            counts.append(count)
            models.append(
                {
                    "provider": provider,
                    "model_id": model_id,
                    "name": names.get((provider, model_id), model_id),
                    "beings": count,
                    "usd_per_answer_at_most": None if bound is None else usd_string(bound),
                    "usd_per_answer_typical": None
                    if typical is None
                    else usd_string(typical.usd_per_ask),
                    "typical": None if typical is None else typical.view(),
                }
            )
        minded = sum(counts)
        priced = bool(models) and len(bounds) == len(models)
        measured = [typical for typical in typicals if typical is not None]
        every_typical = bool(models) and len(measured) == len(models)
        dearest = max(bounds) if priced else None
        # Every model deciding here answers for nothing: only the decisions can run out.
        free = dearest == 0
        at_most = None if dearest is None else _answers_for(usd, dearest, dearest)
        typically = (
            None
            if dearest is None or not every_typical
            else _answers_for(usd, dearest, max(entry.usd_per_ask for entry in measured))
        )

        def binds(answers: int | None) -> str | None:
            if free:
                return "decisions"
            if answers is None:
                return None
            return "usd" if answers < decisions_per_hour else "decisions"

        minutes = self._minutes_a_real_hour()
        demand: dict[str, Any] | None = None
        if every_typical and minutes is not None and (typically is not None or free):
            rate = sum(
                (
                    entry.asks_per_being_minute * count
                    for entry, count in zip(measured, counts, strict=True)
                ),
                Decimal(0),
            )
            capacity = (
                decisions_per_hour if typically is None else min(decisions_per_hour, typically)
            )

            def lasts(asks: Decimal) -> int:
                if asks <= capacity:
                    return _MINUTES_AN_HOUR
                return _whole(Decimal(_MINUTES_AN_HOUR * capacity) / asks)

            hourly = rate * minutes
            demand = {
                "simulated_minutes_per_real_hour": minutes,
                "minded": {
                    "beings": minded,
                    "asks_per_real_hour": _whole(hourly, ROUND_HALF_UP),
                    "minutes_covered": lasts(hourly),
                },
                # Everyone here given the one mind beings here have now: only where one model
                # decides here, since no figure is carried from one model to another.
                "everyone": None,
                # A rate measured on another world's beings, multiplied by this one's head count
                # and speed: never called measured for this world, whatever the rate's own class.
                "rate_class": "estimate"
                if any(entry.rate_is_an_estimate for entry in measured)
                else "projected",
            }
            if beings is not None and len(measured) == 1:
                all_asks = measured[0].asks_per_being_minute * beings * minutes
                demand["everyone"] = {
                    "beings": beings,
                    "asks_per_real_hour": _whole(all_asks, ROUND_HALF_UP),
                    "minutes_covered": lasts(all_asks),
                }
        allowance = self._allowance([model["provider"] for model in models])
        now = MindsBudgetRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        ).current(self.role, contract)
        held = now.view()
        return {
            # The budget is the world's, whoever has it open: who set it is said as "you" or not,
            # never by an account's id, so the sheet reads true for a visitor too.
            "now": {key: value for key, value in held.items() if key != "set_by"}
            | {
                "set_by_you": held["set_by"] is not None
                and self.actor is not None
                and held["set_by"] == str(self.actor)
            },
            "asked": {
                "usd_per_hour": asked.view()["usd_per_hour"],
                "decisions_per_hour": decisions_per_hour,
                "hour": "real_time",
            },
            "default": default_budget(contract).view(),
            "hour_so_far": {"decisions": so_far, "usd": str(spent.quantize(Decimal("0.000001")))},
            "left_this_hour": {
                "decisions": max(0, decisions_per_hour - so_far),
                "usd": str(max(Decimal(0), usd - spent).quantize(Decimal("0.000001"))),
            },
            "beings": beings,
            "minded": minded,
            "models": models,
            "answers_for_usd": {"at_most_price": at_most, "at_typical_price": typically},
            "binds": {"at_most_price": binds(at_most), "at_typical_price": binds(typically)},
            "demand": demand,
            "refused_now": hour_refusal(
                so_far, spent, dearest if dearest is not None else Decimal(0), contract, asked
            ),
            "host": {
                "refusal": self.host_refusal(),
                "allowance": allowance,
                "allowance_below_an_hour_of_budget": None
                if allowance is None
                else any(Decimal(entry["available_usd"]) < usd for entry in allowance),
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
