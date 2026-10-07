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

What a choice may name is checked here, by name: the society's engine must host the role; every
subject must be one the role may decide for in its state, and never one that came in from outside,
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
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest
from exulanica.world.deciders import arrived_from_outside, decider, model_of, of_model
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.society import UnknownSociety
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_things import kind_allows

__all__ = [
    "CHOICE_REFUSALS",
    "ModelChoiceRefused",
    "SocietyModelChoiceRepository",
    "decider_of",
]

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
    "decider_not_allowed": (
        "somebody this choice names is a kind of thing that kind of decider may not decide for"
    ),
}


class ModelChoiceRefused(ValueError):
    """A choice this world may not record, by a code a caller can act on."""

    def __init__(self, code: str) -> None:
        super().__init__(CHOICE_REFUSALS[code])
        self.code = code
        self.detail = CHOICE_REFUSALS[code]


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
            if any(arrived_from_outside(society["state"], subject) for subject in chosen):
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
            run = sum(1 for choice in after.values() if choice["decider"]["kind"] == "model")
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
            row = self.connection.execute(
                "insert into world_society_model_choice(workspace_id,world_id,society_id,"
                "choice_seq,request_id,document,document_sha256,chosen_by) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s) returning recorded_at",
                (
                    self.workspace_id,
                    self.world_id,
                    society["society_id"],
                    sequence,
                    request_id,
                    Jsonb(document),
                    document["document_sha256"],
                    chosen_by,
                ),
            ).fetchone()
            return _view(document, row["recorded_at"])
