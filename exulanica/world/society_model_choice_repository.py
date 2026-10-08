"""Who decides for which subjects of a society, for each decision role: the owner's choices.

A choice names, for one subject or a group of a role's subjects, who decides for them: the world's
own rules (the routine), a model the manifest offers the role, by provider and identifier, or an
outside program deciding under a grant the world's owner issued (:mod:`exulanica.world.deciders`).
Choices are appended in order and never changed (migration 0110, ``world_society_model_choice``),
each naming who made it and when, and each recorded under its role's own choice profile, so a
subject's decider at any time is the latest choice of their role naming them, and a society with no
choice is run by its rules alone.

A choice of the role's first profile names ``model``, a model or none; one of the second names
``decider``, the descriptor (migration 0146). Both are read for as long as they are stored: every
read of a choice gives its ``decider`` and the ``model`` it names, which is none for the routine and
for an outside program, so every reader that asks which model runs somebody reads the answer it
always did, and an outside program spends nothing.

A choice of the second profile may name a group instead of subjects (``group``, with no subjects;
the migration "a choice may name a gate's visitors"): ``arrivals_under_grant``, every visitor that
arrives under one grant and whose arrival said the world decides for it, which is how the world's
owner names the mind a gate's travellers get. A choice naming a subject comes before a group's, and
a group's comes before the routine; the bound on the subjects models run is applied to a group's
when a minute asks (:meth:`SocietyModelChoiceRepository.deciding`).

What a choice may name is checked here, by name: the society's engine must host the role; every
subject must be one the role may decide for in its state, and never one that came in from outside
whose own program decides for it; the model must be declared, offered to the role (a chat model a
probe verified to answer a choice, with the use cases the role needs) and askable under the role's
contract by a mechanism it was verified for; and the subjects models run stay within the bound the
role's contract names. An outside program is chosen only by the route that records its grant
(:meth:`SocietyModelChoiceRepository.record_external_choice`), in the grant's own transaction.
Whether this process can reach the model's provider, or the program's door, is the host's to say,
not the world's: a choice outlives a deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest
from exulanica.world.deciders import (
    decided_by_world,
    decided_from_outside,
    decider,
    model_of,
    of_model,
)
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.society import UnknownSociety
from exulanica.world.society_engines import society_engine
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_things import kind_allows

__all__ = [
    "CHOICE_REFUSALS",
    "GROUPS",
    "ModelChoiceRefused",
    "SocietyModelChoiceRepository",
    "decider_of",
    "decides_at",
]

#: How a gate's choice states its end: an RFC 3339 instant in UTC, to the second.
_ENDS_AT: Final = "%Y-%m-%dT%H:%M:%SZ"
#: The groups a choice may name instead of subjects: every visitor that arrives under one grant and
#: whose arrival said the world decides for it.
GROUPS: Final = ("arrivals_under_grant",)

#: Why a choice is refused, by the code the route answers with, and the detail.
CHOICE_REFUSALS: Final = {
    "engine_takes_no_model_choice": (
        "this society's engine hosts no role a chosen model decides for; the engine table says "
        "which do"
    ),
    "person_not_in_this_world": "a choice names somebody who is not one of this society's people",
    "person_named_twice": "a choice names one person more than once",
    "model_not_declared": "the model is not one the manifest declares",
    "model_not_offered": (
        "the model is not offered to a person's decisions: it is not a chat model a probe verified "
        "to answer a choice"
    ),
    "model_not_askable": "the decision contract accepts no mechanism the model was verified for",
    "too_many_model_people": "the choice would run more people by models than the contract allows",
    "choice_key_reused": "this idempotency key already names another choice",
    "subject_chosen_under_another_role": (
        "one subject cannot be run by chosen models under two decision roles"
    ),
    "decided_from_outside": (
        "somebody this choice names came into the world from outside, and the program they came "
        "with decides for them; end its grant or send them away instead"
    ),
    "engine_takes_no_traveller_choice": (
        "only a society of things takes visitors, so only its engine takes the mind a gate's "
        "travellers get"
    ),
    "decider_not_allowed": (
        "somebody this choice names is a kind of thing that kind of decider may not decide for"
    ),
}


def decides_at(ends_at: str | None, now: datetime) -> bool:
    """Whether a gate's choice ending at ``ends_at`` (as the group states it, to the second in
    UTC, or None for a group stored with no end) decides at ``now``: strictly before its end."""
    return ends_at is None or now < datetime.strptime(ends_at, _ENDS_AT).replace(tzinfo=UTC)


class ModelChoiceRefused(ValueError):
    """A choice this world may not record, by a code a caller can act on."""

    def __init__(self, code: str) -> None:
        super().__init__(CHOICE_REFUSALS[code])
        self.code = code
        self.detail = CHOICE_REFUSALS[code]


def _came_from_outside(state: Mapping[str, Any], subject_id: str) -> bool:
    return any(
        person.get("id") == subject_id and person.get("came_by") == "crossed"
        for person in state.get("inhabitants", ())
    )


def _counted(
    society: Mapping[str, Any], role: DecisionRole, choices: Mapping[str, Any]
) -> list[str]:
    """The subjects whose choices count toward the bound on the subjects models run: in a society
    of things only those still in it, since a visitor that left never comes back by its id;
    in any other society every subject a choice names, a person sent away among them, who may
    be brought back."""
    if society_engine(str(society["engine_version"])).state_family != "things":
        return list(choices)
    present = set(role.adapter.subjects(society["state"]))
    return [subject for subject in choices if subject in present]


def decider_of(document: Mapping[str, Any]) -> dict[str, Any]:
    """Who a stored choice names to decide: its ``decider``, or for a choice of a role's first
    profile the routine or the model its ``model`` names."""
    if "decider" in document:
        return decider(document["decider"])
    return of_model(document["model"])


def _view(document: Mapping[str, Any], recorded_at: Any) -> dict[str, Any]:
    """A stored choice as every reader reads it: as stored, with its decider and the model it
    names, and when it was recorded."""
    described = decider_of(document)
    return {
        **document,
        "decider": described,
        "model": model_of(described),
        "recorded_at": recorded_at,
    }


def _asked_model(model: Any) -> dict[str, Any] | None:
    """The decider an owner's choice of ``model`` asks for, before anything checks the model: the
    routine for none, the model it names, or None for a body that names no model at all, which
    matches no recorded choice and is refused when it is checked."""
    if model is None:
        return {"kind": "routine"}
    if not isinstance(model, Mapping) or set(model) != {"provider", "model_id"}:
        return None
    try:
        return of_model(model)
    except ValueError:
        return None


def _model_record(
    role: DecisionRole, manifest: Manifest, contract: DecisionContract, model: Any
) -> dict | None:
    if model is None:
        return None
    if not isinstance(model, Mapping) or set(model) != {"provider", "model_id"}:
        raise ModelChoiceRefused("model_not_declared")
    model_id, provider = model["model_id"], model["provider"]
    if not isinstance(model_id, str) or model_id not in manifest.models:
        raise ModelChoiceRefused("model_not_declared")
    spec = manifest.spec(model_id)
    if spec.provider != provider:
        raise ModelChoiceRefused("model_not_declared")
    try:
        manifest.offered(role.chosen, model_id)
    except ManifestError as exc:
        raise ModelChoiceRefused("model_not_offered") from exc
    if contract.mechanism_for(spec) is None:
        raise ModelChoiceRefused("model_not_askable")
    return {"provider": provider, "model_id": model_id}


class SocietyModelChoiceRepository:
    """The owner's choices for one world's societies, over a workspace-scoped connection."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, *, world_id: str
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    def _society(self, version_id: uuid.UUID, *, lock: bool) -> dict[str, Any]:
        row = self.connection.execute(
            "select society_id,engine_version,state from world_society where workspace_id=%s "
            "and world_id=%s and version_id=%s" + (" for update" if lock else ""),
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownSociety("society is unavailable")
        return row

    def _rows(self, society_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select choice_seq,request_id,document,document_sha256,chosen_by,recorded_at "
            "from world_society_model_choice where workspace_id=%s and world_id=%s "
            "and society_id=%s order by choice_seq",
            (self.workspace_id, self.world_id, society_id),
        ).fetchall()

    @staticmethod
    def _of(role: DecisionRole, rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """The rows of ``role``'s choices, of its profile now or an earlier one; a choice of a
        profile no registered role writes is refused by name, never read as anybody's."""
        found = []
        for row in rows:
            profile = row["document"]["profile"]
            if decision_roles().for_choice(profile) is None:
                raise ValueError(f"a model choice of profile {profile!r} names no registered role")
            if role.reads_choice(profile):
                found.append(row)
        return found

    @staticmethod
    def _current(
        role: DecisionRole, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        current: dict[str, dict[str, Any]] = {}
        for row in SocietyModelChoiceRepository._of(role, rows):
            document = row["document"]
            described = decider_of(document)
            for subject in document[role.choice_subjects]:
                current[subject] = {
                    "decider": described,
                    "model": model_of(described),
                    "choice_seq": document["choice_seq"],
                    "chosen_by": document["chosen_by"],
                    "recorded_at": row["recorded_at"],
                }
        return current

    @staticmethod
    def _groups(role: DecisionRole, rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice of ``role``, by grant id."""
        found: dict[str, dict[str, Any]] = {}
        for row in SocietyModelChoiceRepository._of(role, rows):
            document = row["document"]
            group = document.get("group")
            if group is None:
                continue
            described = decider_of(document)
            found[group["grant_id"]] = {
                "ends_at": group.get("ends_at"),
                "decider": described,
                "model": model_of(described),
                "choice_seq": document["choice_seq"],
                "chosen_by": document["chosen_by"],
                "recorded_at": row["recorded_at"],
            }
        return found

    def traveller_choices(
        self, version_id: uuid.UUID, role: DecisionRole
    ) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice of ``role`` that still decides: the mind its arriving
        visitors get when their arrival says the world decides for them, by grant id; one past
        its end is left out, as :meth:`deciding` leaves it out."""
        rows = self._rows(self._society(version_id, lock=False)["society_id"])
        return self._deciding_groups(role, rows)

    def _deciding_groups(
        self, role: DecisionRole, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice that decides now: strictly before its end, as the
        database's clock reads it, or with no end."""
        now = self.connection.execute("select statement_timestamp() as now").fetchone()["now"]
        return {
            grant_id: choice
            for grant_id, choice in self._groups(role, rows).items()
            if decides_at(choice["ends_at"], now)
        }

    def deciding(
        self, version_id: uuid.UUID, role: DecisionRole, contract: DecisionContract
    ) -> dict[str, dict[str, Any]]:
        """Who decides for each of ``role``'s subjects a choice decides for, by subject id: its own
        latest choice, else, for a visitor the world decides for, the latest choice naming the
        group of arrivals under its grant (``from``: ``choice`` or ``travellers``), where its kind
        allows that kind of decider. A group's model runs a visitor only while the subjects models
        run stay within the contract's bound, in the order the visitors came; past it the routine
        decides for the rest (``travellers_over_bound``). A subject no choice names is absent, as
        from :meth:`current`."""
        society = self._society(version_id, lock=False)
        rows = self._rows(society["society_id"])
        found = {
            subject: {**choice, "from": "choice"}
            for subject, choice in self._current(role, rows).items()
        }
        # A gate's choice decides strictly before its end, as the database's clock reads it.
        groups = self._deciding_groups(role, rows)
        if not groups:
            return found
        state = society["state"]
        room = contract.value(role.subjects_bound) - sum(
            1
            for subject in _counted(society, role, found)
            if found[subject]["decider"]["kind"] == "model"
        )
        present = set(role.adapter.subjects(state))
        visitors = sorted(
            (
                person
                for person in state.get("inhabitants", ())
                if person.get("id") in present
                and person["id"] not in found
                and decided_by_world(person)
                and person["crossing"]["grant_id"] in groups
            ),
            key=lambda person: person["ordinal"],
        )
        for person in visitors:
            choice = groups[person["crossing"]["grant_id"]]
            if not kind_allows(state, person["id"], choice["decider"]["kind"]):
                # A kind that takes no such decider is decided for as its kind says.
                continue
            if choice["decider"]["kind"] == "model":
                if room <= 0:
                    if not kind_allows(state, person["id"], "routine"):
                        # Past the bound, a kind the routine may not run is run by nobody here.
                        continue
                    found[person["id"]] = {
                        **choice,
                        "decider": {"kind": "routine"},
                        "model": None,
                        "from": "travellers_over_bound",
                    }
                    continue
                room -= 1
            found[person["id"]] = {**choice, "from": "travellers"}
        return found

    def current(self, version_id: uuid.UUID, role: DecisionRole) -> dict[str, dict[str, Any]]:
        """Each subject's latest choice of ``role``, by subject id, with who decides for them and
        the model that is, if any; one never chosen for is absent."""
        return self._current(role, self._rows(self._society(version_id, lock=False)["society_id"]))

    def history(self, version_id: uuid.UUID, role: DecisionRole) -> list[dict[str, Any]]:
        """Every choice made for ``role`` in this society, in order, as stored, each with its
        decider and the model it names."""
        return [
            _view(row["document"], row["recorded_at"])
            for row in self._of(
                role, self._rows(self._society(version_id, lock=False)["society_id"])
            )
        ]

    def record_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
        manifest: Manifest,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record the owner's choice of a model, or of the routine with none, for ``subjects``, or
        return the one this idempotency key already recorded.

        An exact retry is answered with the recorded choice before anything else is checked, so
        it still returns after the model stops being offered.
        """

        def described() -> dict[str, Any]:
            return of_model(_model_record(role, manifest, contract, model))

        recorded = self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=subjects,
            asked=_asked_model(model),
            described=described,
            chosen_by=chosen_by,
            contract=contract,
        )
        assert recorded is not None
        return recorded

    def record_external_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        bridge: str,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record that the outside program behind ``bridge`` decides for ``subjects`` under the
        grant ``grant_id``: called by the route that records the grant, in its transaction, never
        by the models route. Returns the choice, or the one this key already recorded."""
        external = decider({"kind": "external", "bridge": bridge, "grant_id": str(grant_id)})
        recorded = self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=subjects,
            asked=external,
            described=lambda: external,
            chosen_by=chosen_by,
            contract=contract,
        )
        assert recorded is not None
        return recorded

    def record_traveller_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
        manifest: Manifest,
        contract: DecisionContract,
        ends_at: datetime,
    ) -> dict[str, Any]:
        """Record the mind every visitor arriving under ``grant_id`` gets when its arrival says the
        world decides for it: a model the manifest offers the role, or the routine for none.
        Called by the route that records the grant, in its transaction, which holds the grant to
        this world; refused as any owner's choice of a model is. Returns the choice, or the one
        this key already recorded. ``ends_at``, the grant's own end (aware, in UTC; every grant
        ends), ends the choice: it decides strictly before then, to the second, by the database's
        clock, so no host reserves an ask under it for the grant's visitors once the grant has
        ended, whenever their departures are written. An ask reserved before the end runs as
        reserved, and an owner's own choice naming a visitor is not ended by it."""

        def described() -> dict[str, Any]:
            return of_model(_model_record(role, manifest, contract, model))

        if ends_at.tzinfo is None or ends_at.utcoffset() != timedelta(0):
            raise ValueError("a gate's choice ends at an instant stated in UTC")
        group = {
            "kind": "arrivals_under_grant",
            "grant_id": str(grant_id),
            "ends_at": ends_at.strftime(_ENDS_AT),
        }
        return self._record_group(
            version_id,
            role,
            request_id=request_id,
            group=group,
            asked=_asked_model(model),
            described=described,
            chosen_by=chosen_by,
            contract=contract,
        )

    def release_traveller_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any] | None:
        """Hand the visitors arriving under ``grant_id`` back to the routine, as one group choice:
        called by the route that revokes the grant, in its transaction, so no later grant of the
        same id inherits a mind. It ends with the grant, as the choice it releases does. None,
        recording nothing, when no group choice names the grant."""
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            latest = self._groups(role, rows).get(str(grant_id))
            if existing is None and latest is None:
                return None
            ends_at = (
                existing["document"]["group"]["ends_at"]
                if existing is not None and "group" in existing["document"]
                else None
                if latest is None
                else latest["ends_at"]
            )
            group = {"kind": "arrivals_under_grant", "grant_id": str(grant_id)}
            if ends_at is not None:
                group["ends_at"] = ends_at
            return self._record_group(
                version_id,
                role,
                request_id=request_id,
                group=group,
                asked={"kind": "routine"},
                described=lambda: {"kind": "routine"},
                chosen_by=chosen_by,
                contract=contract,
            )

    def _record_group(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        group: Mapping[str, str],
        asked: Mapping[str, Any] | None,
        described: Any,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record one choice of ``role`` naming ``group`` rather than subjects, checked as
        ``described()`` checks it, or return the one this idempotency key already recorded."""
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    not role.reads_choice(document["profile"])
                    or document.get("group") != dict(group)
                    or asked is None
                    or decider_of(document) != dict(asked)
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return _view(document, existing["recorded_at"])
            if not role.hosted_by(society["engine_version"]):
                raise ModelChoiceRefused("engine_takes_no_model_choice")
            if society_engine(str(society["engine_version"])).state_family != "things":
                raise ModelChoiceRefused("engine_takes_no_traveller_choice")
            record = described()
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: [],
                "group": dict(group),
                "decider": record,
                "contract": contract.binding(),
                "chosen_by": str(chosen_by),
            }
            document["document_sha256"] = input_sha256(document)
            return self._insert(society["society_id"], sequence, request_id, document, chosen_by)

    def _insert(
        self,
        society_id: uuid.UUID,
        sequence: int,
        request_id: uuid.UUID,
        document: dict[str, Any],
        chosen_by: uuid.UUID,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            "insert into world_society_model_choice(workspace_id,world_id,society_id,"
            "choice_seq,request_id,document,document_sha256,chosen_by) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s) returning recorded_at",
            (
                self.workspace_id,
                self.world_id,
                society_id,
                sequence,
                request_id,
                Jsonb(document),
                document["document_sha256"],
                chosen_by,
            ),
        ).fetchone()
        return _view(document, row["recorded_at"])

    def release_external_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any] | None:
        """Hand every subject the grant ``grant_id`` still decides for back to their routine, as
        one choice: called by the route that revokes the grant, in its transaction. Who the grant
        decides for is read under the society's lock, so a choice committed meanwhile is never
        overwritten; a retry of this key returns the choice it recorded. None when the grant
        decides for nobody now, because a later choice already replaced it."""

        def held(rows: Sequence[Mapping[str, Any]]) -> list[str]:
            return [
                subject
                for subject, choice in sorted(self._current(role, rows).items())
                if choice["decider"]["kind"] == "external"
                and choice["decider"]["grant_id"] == str(grant_id)
            ]

        return self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=held,
            asked={"kind": "routine"},
            described=lambda: {"kind": "routine"},
            chosen_by=chosen_by,
            contract=contract,
        )

    def _record(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str] | Callable[[Sequence[Mapping[str, Any]]], Sequence[str]],
        asked: Mapping[str, Any] | None,
        described: Any,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any] | None:
        """Record one choice of ``role`` naming ``asked``, checked as ``described()`` checks it,
        or return the one this idempotency key already recorded. ``subjects`` may be read from
        the society's choices under its lock instead: then a key already recorded is answered
        whoever it named, and None is returned, recording nothing, when they name nobody."""
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            derived = callable(subjects)
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    not role.reads_choice(document["profile"])
                    or (
                        not derived
                        and (
                            document[role.choice_subjects] != sorted(set(subjects))
                            or len(set(subjects)) != len(subjects)
                        )
                    )
                    or asked is None
                    or decider_of(document) != dict(asked)
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return _view(document, existing["recorded_at"])
            named = list(subjects(rows) if callable(subjects) else subjects)
            if derived and not named:
                return None
            chosen = sorted(set(named))
            if not role.hosted_by(society["engine_version"]):
                raise ModelChoiceRefused("engine_takes_no_model_choice")
            if len(chosen) != len(named):
                raise ModelChoiceRefused("person_named_twice")
            record = described()
            present = set(role.adapter.subjects(society["state"]))
            if not chosen or not set(chosen) <= present:
                raise ModelChoiceRefused("person_not_in_this_world")
            if any(decided_from_outside(society["state"], subject) for subject in chosen):
                raise ModelChoiceRefused("decided_from_outside")
            if record["kind"] == "external" and any(
                _came_from_outside(society["state"], subject) for subject in chosen
            ):
                # A visitor is never handed to another outside program: its own program, or the
                # world, decides for it.
                raise ModelChoiceRefused("decided_from_outside")
            state = society["state"]
            if not all(kind_allows(state, subject, record["kind"]) for subject in chosen):
                raise ModelChoiceRefused("decider_not_allowed")
            if record["kind"] != "routine":
                occupied: dict[tuple[str, str], bool] = {}
                for row in rows:
                    document = row["document"]
                    other = decision_roles().for_choice(document["profile"])
                    if other is None:
                        raise ValueError("a model choice names no registered role")
                    if other.key == role.key:
                        continue
                    for subject in document[other.choice_subjects]:
                        if subject in chosen:
                            occupied[(other.key, subject)] = (
                                decider_of(document)["kind"] != "routine"
                            )
                if any(occupied.values()):
                    raise ModelChoiceRefused("subject_chosen_under_another_role")
            after = self._current(role, rows)
            for subject in chosen:
                after[subject] = {"decider": record}
            counted = _counted(society, role, after)
            run = sum(1 for subject in counted if after[subject]["decider"]["kind"] == "model")
            if run > contract.value(role.subjects_bound):
                raise ModelChoiceRefused("too_many_model_people")
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: chosen,
                "decider": record,
                "contract": contract.binding(),
                "chosen_by": str(chosen_by),
            }
            document["document_sha256"] = input_sha256(document)
            return self._insert(society["society_id"], sequence, request_id, document, chosen_by)
