"""Which model runs which people of a purposeful society: the world owner's choices, as world data.

A choice names a model the manifest offers a person's decisions (``Role.SOCIETY_DECISION``), by
provider and identifier, or the built-in planner (no model), for one person or a group of the
society's people. Choices are appended in order and never changed (migration 0110,
``world_society_model_choice``), each naming who made it and when, so a person's model at any
time is the latest choice naming them, and a society with no choice is run by its routine alone.

What a choice may name is checked here, by name: the society must be a purposeful one of this
world; every person must be one of its people; the model must be declared, offered to the role
(a chat model a probe verified to answer a choice) and askable under the decision contract by a
mechanism it was verified for; and the people a model runs stay within the contract's
``model_people_maximum``. Whether this process can reach the model's provider is the host's to
say, not the world's: a choice outlives a deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest, Role
from exulanica.world.society import UnknownSociety
from exulanica.world.society_decision_contract import DecisionContract
from exulanica.world.society_planner import PURPOSEFUL_PROFILE, input_sha256

__all__ = [
    "CHOICE_PROFILE",
    "CHOICE_REFUSALS",
    "ModelChoiceRefused",
    "SocietyModelChoiceRepository",
]

CHOICE_PROFILE: Final = "exulanica.society-model-choice/v1"
#: Why a choice is refused, by the code the route answers with, and the detail.
CHOICE_REFUSALS: Final = {
    "engine_takes_no_model_choice": "only a purposeful society's people are run by chosen models",
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


def _model_record(manifest: Manifest, contract: DecisionContract, model: Any) -> dict | None:
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
        manifest.offered(Role.SOCIETY_DECISION, model_id)
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
    def _current(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        current: dict[str, dict[str, Any]] = {}
        for row in rows:
            document = row["document"]
            for person in document["people"]:
                current[person] = {
                    "model": document["model"],
                    "choice_seq": document["choice_seq"],
                    "chosen_by": document["chosen_by"],
                    "recorded_at": row["recorded_at"],
                }
        return current

    def current(self, version_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        """Each person's latest choice, by subject id; a person never chosen for is absent."""
        return self._current(self._rows(self._society(version_id, lock=False)["society_id"]))

    def history(self, version_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every choice made for this society, in order, as stored."""
        return [
            {**row["document"], "recorded_at": row["recorded_at"]}
            for row in self._rows(self._society(version_id, lock=False)["society_id"])
        ]

    def record_choice(
        self,
        version_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        people: Sequence[str],
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
        manifest: Manifest,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record one choice, or return the one this idempotency key already recorded.

        An exact retry is answered with the recorded choice before anything else is checked, so
        it still returns after the model stops being offered.
        """
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            chosen = sorted(set(people))
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    document["people"] != chosen
                    or len(chosen) != len(people)
                    or document["model"] != (None if model is None else dict(model))
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return {**document, "recorded_at": existing["recorded_at"]}
            if society["engine_version"] != PURPOSEFUL_PROFILE:
                raise ModelChoiceRefused("engine_takes_no_model_choice")
            if len(chosen) != len(people):
                raise ModelChoiceRefused("person_named_twice")
            record = _model_record(manifest, contract, model)
            inhabitants = {person["id"] for person in society["state"]["inhabitants"]}
            if not chosen or not set(chosen) <= inhabitants:
                raise ModelChoiceRefused("person_not_in_this_world")
            after = self._current(rows)
            for person in chosen:
                after[person] = {"model": record}
            run = sum(1 for choice in after.values() if choice["model"] is not None)
            if run > contract.value("model_people_maximum"):
                raise ModelChoiceRefused("too_many_model_people")
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": CHOICE_PROFILE,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                "people": chosen,
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
