"""Which host serves each decision role, as the models read and a model choice meet it.

A decision role is registry data and one adapter module (:mod:`exulanica.world.decision_roles`).
Which process asks the models a world's owner chose is a host's business: the society playback
host asks for a society's people (:mod:`exulanica.api.decision_host`), and the traffic signal
controller for a town's junction signals (:mod:`exulanica.api.traffic_signal_controller`). This
module is the seam between a role and its host for ``/world/versions/{version_id}/models``:
:data:`ROLE_HOSTS` names one host for each word a role's subjects are known by, in code. Nothing a
catalog or a request states chooses code here. A registered role whose subject no host serves is
listed as unsupported by the read and refused by a choice, both as ``role_subject_unsupported``.

Each host says three things the same way for its role: whether its owner may choose a model for
the role's subjects now (:meth:`RoleHost.availability`, from the checks its choice path makes), the
fields the read has always served for the role (:meth:`RoleHost.read`), and the choice itself
(:meth:`RoleHost.record_choice`). A choice is refused by a code, answered with the status
:func:`choice_status` gives it, whichever role it is for. Whether this host then asks the chosen
model is the host's refusal (``Services.model_host_refusal``), never a reason to refuse the choice.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol

import psycopg
from fastapi import Request

from exulanica.api.capabilities import (
    AVAILABLE,
    Availability,
    Endpoint,
    Subjects,
    unavailable,
    unsupported,
)
from exulanica.api.dependencies import get_services
from exulanica.api.routes.society import society as society_read
from exulanica.api.routes.society_models import (
    CHOICE_CONFLICTS,
    offered_models,
    society_models_view,
)
from exulanica.models.manifest import load_manifest
from exulanica.selection.validation import Session
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole, RoleRefused
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.traffic_episodes import TrafficInput, TrafficRefused
from exulanica.world.traffic_host import saved_world_roads, traffic_clock
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository

__all__ = [
    "ROLE_HOSTS",
    "ROLE_SUBJECT_UNSUPPORTED",
    "RoleChoiceRefused",
    "RoleContext",
    "RoleHost",
    "RoleRead",
    "choice_status",
]

#: A registered role whose subject no host here serves: listed as unsupported, never chosen.
ROLE_SUBJECT_UNSUPPORTED: Final = "role_subject_unsupported"
#: A society not yet brought into the version: the models read's reason for the people's role.
_SOCIETY_UNAVAILABLE: Final = "society_unavailable"
#: Choice refusals answered 503: this server cannot take a choice now, whatever it names.
_HOST_UNAVAILABLE: Final = frozenset(
    {"traffic_controller_unavailable", "traffic_worker_unavailable"}
)
#: Choice refusals answered 409 beside the people's: the world's roads, not the body.
_ROAD_CONFLICTS: Final = frozenset({"roads_unavailable"})


def choice_status(code: str) -> int:
    """The status a refused choice of any role is answered with: 503 where this server cannot
    take one now, 409 where the world or the key refuses it (the people's route's rule,
    :data:`~exulanica.api.routes.society_models.CHOICE_CONFLICTS`, and the world's roads), 422
    where the body names something the world does not offer."""
    if code in _HOST_UNAVAILABLE:
        return 503
    if code in CHOICE_CONFLICTS or code in _ROAD_CONFLICTS:
        return 409
    return 422


class RoleChoiceRefused(Exception):
    """A choice refused by a stable code, with the detail its body carries."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class RoleContext:
    """One models read or choice: who asks, in which world and version, from which source."""

    connection: psycopg.Connection
    session: Session
    request: Request
    world_id: str
    version_id: uuid.UUID
    snapshot_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RoleRead:
    """A role as the models read serves it: whether a choice can be made now, and the fields the
    read has always served for the role."""

    availability: Availability
    fields: Mapping[str, Any]


class RoleHost(Protocol):
    """The code one kind of subject needs between the generic read and its host."""

    #: The word the registry's roles name these subjects by.
    subject: str

    def availability(self, context: RoleContext, role: DecisionRole) -> Availability: ...

    def read(self, context: RoleContext, role: DecisionRole) -> RoleRead: ...

    def subjects(self, role: DecisionRole, models_read: Endpoint) -> Subjects: ...

    def record_choice(
        self,
        context: RoleContext,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
    ) -> dict[str, Any]: ...


def _named(model: Mapping[str, str]) -> dict[str, str]:
    return {**model, "name": load_manifest().model_name(model["model_id"])}


class _People:
    """A society's people, whose chosen models the society playback host asks."""

    subject: Final = "person"

    def _engine(self, context: RoleContext) -> str | None:
        row = context.connection.execute(
            "select engine_version from world_society where workspace_id=%s and world_id=%s "
            "and version_id=%s",
            (context.session.workspace_id, context.world_id, context.version_id),
        ).fetchone()
        return None if row is None else str(row["engine_version"])

    def availability(self, context: RoleContext, role: DecisionRole) -> Availability:
        # The checks a choice makes before its body: a society in the version, whose engine hosts
        # the role (SocietyModelChoiceRepository.record_choice).
        engine = self._engine(context)
        if engine is None:
            return unavailable(_SOCIETY_UNAVAILABLE)
        if not role.hosted_by(engine):
            return unsupported("engine_takes_no_model_choice")
        return AVAILABLE

    def read(self, context: RoleContext, role: DecisionRole) -> RoleRead:
        view = None
        reason = None
        if self._engine(context) is None:
            reason = _SOCIETY_UNAVAILABLE
        else:
            try:
                view = society_models_view(
                    context.version_id,
                    context.connection,
                    context.session,
                    context.request,
                    context.world_id,
                )
            except UnavailableSocietyInput:
                reason = "unavailable_society_input"
            except RoleRefused as exc:
                reason = exc.code
        return RoleRead(
            self.availability(context, role),
            {"label": "People", "available": view is not None, "reason": reason, "view": view},
        )

    def subjects(self, role: DecisionRole, models_read: Endpoint) -> Subjects:
        return Subjects(society_read, "state.inhabitants")

    def record_choice(
        self,
        context: RoleContext,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        try:
            people = [str(uuid.UUID(value)) for value in subjects]
        except ValueError as exc:
            raise RoleChoiceRefused("person_id_invalid", "A person id is a UUID.") from exc
        repository = SocietyModelChoiceRepository(
            context.connection, context.session.workspace_id, world_id=context.world_id
        )
        try:
            return repository.record_choice(
                context.version_id,
                role,
                request_id=request_id,
                subjects=people,
                model=model,
                chosen_by=context.session.actor,
                manifest=load_manifest(),
                contract=role.contract(),
            )
        except ModelChoiceRefused as exc:
            raise RoleChoiceRefused(exc.code, exc.detail) from exc
        except UnknownSociety as exc:
            raise RoleChoiceRefused(_SOCIETY_UNAVAILABLE, str(exc)) from exc


class _Signals:
    """A town's junction signals, whose chosen models the traffic signal controller asks."""

    subject: Final = "signal"
    #: A choice names one light: each is scheduled from its own next prepared minute.
    subjects_per_choice: Final = 1

    def _roads(self, context: RoleContext) -> tuple[TrafficInput | None, str | None]:
        """The version's compiled roads, or the refusal naming why there are none to drive."""
        if getattr(context.request.app.state, "traffic_signal_controller", None) is None:
            return None, "traffic_controller_unavailable"
        try:
            return (
                saved_world_roads(
                    context.connection,
                    context.session.workspace_id,
                    context.world_id,
                    context.snapshot_id,
                ),
                None,
            )
        except (InvalidStructuralData, TrafficRefused, UnsupportedNetworkError) as exc:
            # A world without roads still has the registered role; its subjects are unavailable
            # by the traffic compiler's named refusal, beside the people's role.
            return None, getattr(exc, "code", "roads_unavailable")

    def availability(self, context: RoleContext, role: DecisionRole) -> Availability:
        _, refusal = self._roads(context)
        return AVAILABLE if refusal is None else unavailable(refusal)

    def read(self, context: RoleContext, role: DecisionRole) -> RoleRead:
        value, refusal = self._roads(context)
        controller = getattr(context.request.app.state, "traffic_signal_controller", None)
        subjects: list[dict[str, Any]] = []
        if value is not None and controller is not None:
            try:
                subjects = [
                    {**signal, "label": f"High street crossing {index}"}
                    for index, signal in enumerate(controller.signals(value), 1)
                ]
            except SignalChoiceRefused as exc:
                refusal = exc.code
        availability = AVAILABLE if refusal is None else unavailable(refusal)
        fields: dict[str, Any] = {
            "label": "Traffic lights",
            "available": refusal is None,
            "reason": refusal,
            "subjects": subjects,
            "models": [],
            "choices": [],
        }
        if controller is None:
            return RoleRead(availability, fields)
        services = get_services(context.request)
        repository = TrafficSignalRepository(
            context.connection, context.session.workspace_id, context.world_id, context.version_id
        )
        latest = repository.current_choices()
        active = repository.activations()
        now = traffic_clock()
        effective = repository.choices_at(now)
        choices = []
        for signal_id, choice in sorted(latest.items()):
            model = choice["model"]
            target = choice["effective_second"]
            activated = active.get(choice["choice_seq"])
            running = effective.get(signal_id)
            running_active = None if running is None else active.get(running["choice_seq"])
            running_model = (
                None
                if running is None
                or running["model"] is None
                or running_active is None
                or running_active > now
                else _named(running["model"])
            )
            if target > now:
                status = "pending"
            elif model is None:
                status = "fixed"
            elif activated is None or activated > now:
                status = "preparing"
            else:
                status = "active"
            choices.append(
                {
                    "subject_id": signal_id,
                    "choice_seq": choice["choice_seq"],
                    "model": None if model is None else _named(model),
                    "effective_second": target,
                    "active_second": activated,
                    "running_model": running_model,
                    "running_choice_seq": None if running_model is None else running["choice_seq"],
                    "status": status,
                    "refusal": None
                    if model is None
                    else services.choice_refusal(
                        role, model, context.connection, context.session.workspace_id
                    ),
                }
            )
        policy = signal_actuation()
        fields |= {
            "models": offered_models(role, services),
            "choices": choices,
            "timing": {
                "segment_seconds": policy.segment_seconds,
                "target_preparation_seconds": policy.preparation_lead_seconds,
            },
        }
        return RoleRead(availability, fields)

    def subjects(self, role: DecisionRole, models_read: Endpoint) -> Subjects:
        return Subjects(models_read, f"roles[key={role.key}].subjects")

    def record_choice(
        self,
        context: RoleContext,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        if len(subjects) != self.subjects_per_choice:
            raise RoleChoiceRefused("one_signal_per_choice", "Choose one traffic light.")
        controller = getattr(context.request.app.state, "traffic_signal_controller", None)
        if controller is None:
            raise RoleChoiceRefused(
                "traffic_controller_unavailable", "Traffic preparation is unavailable."
            )
        try:
            value = saved_world_roads(
                context.connection,
                context.session.workspace_id,
                context.world_id,
                context.snapshot_id,
            )
            signals = controller.signals(value)
            repository = TrafficSignalRepository(
                context.connection,
                context.session.workspace_id,
                context.world_id,
                context.version_id,
            )
            return repository.record_choice(
                role,
                load_manifest(),
                request_id=request_id,
                signal_id=subjects[0],
                known_signals=[row["signal_id"] for row in signals],
                model=model,
                chosen_by=context.session.actor,
            )
        except SignalChoiceRefused as exc:
            raise RoleChoiceRefused(exc.code, exc.code) from exc
        except (InvalidStructuralData, TrafficRefused, UnsupportedNetworkError) as exc:
            raise RoleChoiceRefused("roads_unavailable", type(exc).__name__) from exc


#: The host of each kind of subject, by the word a registered role names its subjects by. Fixed in
#: code: a role the registry adds is served only once its host is written and named here.
ROLE_HOSTS: Final[Mapping[str, RoleHost]] = MappingProxyType(
    {"person": _People(), "signal": _Signals()}
)
