"""Which model runs which subjects of a society, for each decision role: the owner's choices.

A choice names a model the manifest offers a decision role (:mod:`exulanica.world.decision_roles`),
by provider and identifier, or the world's own rules (no model), for one subject or a group of the
role's subjects: a person's decisions in a purposeful society first. Choices are appended in order
and never changed (migration 0110, ``world_society_model_choice``), each naming who made it and
when, and each recorded under its role's own choice profile, so a subject's model at any time is
the latest choice of their role naming them, and a society with no choice is run by its rules
alone.

What a choice may name is checked here, by name: the society's engine must host the role; every
subject must be one the role may decide for in its state; the model must be declared, offered to
the role (a chat model a probe verified to answer a choice, with the use cases the role needs) and
askable under the role's contract by a mechanism it was verified for; and the subjects models run
stay within the bound the role's contract names. Whether this process can reach the model's
provider is the host's to say, not the world's: a choice outlives a deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.society import UnknownSociety
from exulanica.world.society_planner import input_sha256

__all__ = [
    "CHOICE_REFUSALS",
    "ModelChoiceRefused",
    "SocietyModelChoiceRepository",
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
}


class ModelChoiceRefused(ValueError):
    """A choice this world may not record, by a code a caller can act on."""

    def __init__(self, code: str) -> None:
        super().__init__(CHOICE_REFUSALS[code])
        self.code = code
        self.detail = CHOICE_REFUSALS[code]


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
        """The rows of ``role``'s choices; a choice of a profile no registered role writes is
        refused by name, never read as anybody's."""
        found = []
        for row in rows:
            profile = row["document"]["profile"]
            if decision_roles().for_choice(profile) is None:
                raise ValueError(f"a model choice of profile {profile!r} names no registered role")
            if profile == role.choice_profile:
                found.append(row)
        return found

    @staticmethod
    def _current(
        role: DecisionRole, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        current: dict[str, dict[str, Any]] = {}
        for row in SocietyModelChoiceRepository._of(role, rows):
            document = row["document"]
            for subject in document[role.choice_subjects]:
                current[subject] = {
                    "model": document["model"],
                    "choice_seq": document["choice_seq"],
                    "chosen_by": document["chosen_by"],
                    "recorded_at": row["recorded_at"],
                }
        return current

    def current(self, version_id: uuid.UUID, role: DecisionRole) -> dict[str, dict[str, Any]]:
        """Each subject's latest choice of ``role``, by subject id; one never chosen for is
        absent."""
        return self._current(role, self._rows(self._society(version_id, lock=False)["society_id"]))

    def history(self, version_id: uuid.UUID, role: DecisionRole) -> list[dict[str, Any]]:
        """Every choice made for ``role`` in this society, in order, as stored."""
        return [
            {**row["document"], "recorded_at": row["recorded_at"]}
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
        """Record one choice of ``role``, or return the one this idempotency key already recorded.

        An exact retry is answered with the recorded choice before anything else is checked, so
        it still returns after the model stops being offered.
        """
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            chosen = sorted(set(subjects))
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    document["profile"] != role.choice_profile
                    or document[role.choice_subjects] != chosen
                    or len(chosen) != len(subjects)
                    or document["model"] != (None if model is None else dict(model))
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return {**document, "recorded_at": existing["recorded_at"]}
            if not role.hosted_by(society["engine_version"]):
                raise ModelChoiceRefused("engine_takes_no_model_choice")
            if len(chosen) != len(subjects):
                raise ModelChoiceRefused("person_named_twice")
            record = _model_record(role, manifest, contract, model)
            present = set(role.adapter.subjects(society["state"]))
            if not chosen or not set(chosen) <= present:
                raise ModelChoiceRefused("person_not_in_this_world")
            after = self._current(role, rows)
            for subject in chosen:
                after[subject] = {"model": record}
            run = sum(1 for choice in after.values() if choice["model"] is not None)
            if run > contract.value(role.subjects_bound):
                raise ModelChoiceRefused("too_many_model_people")
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: chosen,
                "model": record,
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
            return {**document, "recorded_at": row["recorded_at"]}
