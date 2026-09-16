"""Short committed reservations and immutable results around lock-free provider inference."""

from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

from exulanica.world.society import (
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    society_state_sha256,
)
from exulanica.world.society_decisions import (
    REQUEST_PROFILE,
    receipt_for,
    seal,
    validate_decision_receipt,
    validate_decision_request,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_social import SOCIAL_PROFILE, decision_context, validate_proposal


class SocietyDecisionRepository:
    def __init__(self, society: SocietyRepository) -> None:
        self.society = society
        self.connection = society.connection

    def _row(self, version_id: uuid.UUID) -> dict:
        self.society._lock()
        row = self.society._row(version_id, lock=True)
        if row is None:
            raise UnknownSociety("society is unavailable")
        if row["engine_version"] != SOCIAL_PROFILE:
            raise ValueError("model decisions require a v3 society")
        return row

    def _request(self, row: dict, request_id: uuid.UUID) -> dict | None:
        value = self.connection.execute(
            "select document from world_society_decision_request where workspace_id=%s "
            "and society_id=%s and request_id=%s",
            (row["workspace_id"], row["society_id"], request_id),
        ).fetchone()
        if value:
            validate_decision_request(value["document"])
            return value["document"]
        return None

    def _result(self, row: dict, request: dict) -> dict:
        value = self.connection.execute(
            "select document from world_society_decision where workspace_id=%s and society_id=%s "
            "and request_id=%s",
            (row["workspace_id"], row["society_id"], request["request_id"]),
        ).fetchone()
        receipt = None if value is None else value["document"]
        if receipt:
            validate_decision_receipt(receipt, request)
        return {
            "request": request,
            "decision": receipt,
            "status": "in_progress" if receipt is None else "completed",
        }

    def read(self, version_id: uuid.UUID, request_id: uuid.UUID) -> dict:
        row = self._row(version_id)
        self.society.snapshot(version_id)
        request = self._request(row, request_id)
        if request is None:
            raise UnknownSociety("decision request is unavailable")
        documents = self.society._validated_inputs(row)
        self._authorize_context(request, documents)
        return self._result(row, request)

    def _authorize_context(self, request: dict, documents: list[dict]) -> None:
        self.society._authorize(documents[request["input_seq"] - 1])
        context = request["context"]
        for memory in [*context["own_observations"], *context["own_beliefs"]]:
            document = documents[memory["input_seq"] - 1]
            if document["document_sha256"] != memory["input_sha256"]:
                raise ValueError("decision memory input binding mismatch")
            self.society._authorize(document)

    def prepare(
        self,
        version_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        subject_id: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
        provider_config: dict | None,
    ) -> tuple[dict, bool]:
        """Caller must commit and close its connection before using the returned context."""
        row = self._row(version_id)
        self.society.snapshot(version_id)
        existing = self._request(row, request_id)
        if existing:
            if (existing["subject_id"], existing["base_tick"], existing["base_state_sha256"]) != (
                str(subject_id),
                base_tick,
                base_state_sha256,
            ):
                raise StaleSocietyState("idempotency key already binds a different request")
            return self.read(version_id, request_id), False
        if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
            raise StaleSocietyState("society changed before decision request")
        occupied = self.connection.execute(
            "select request_id from world_society_decision_request where workspace_id=%s "
            "and society_id=%s and subject_id=%s and base_tick=%s",
            (row["workspace_id"], row["society_id"], subject_id, base_tick),
        ).fetchone()
        if occupied:
            raise StaleSocietyState("subject already has a decision reservation at this tick")
        document = self.society._validated_inputs(row)[-1]
        context = decision_context(row["state"], document, str(subject_id))
        request = seal(
            {
                "profile": REQUEST_PROFILE,
                "request_id": str(request_id),
                "subject_id": str(subject_id),
                "branch_id": str(version_id),
                "base_tick": base_tick,
                "base_state_sha256": base_state_sha256,
                "input_seq": document["input_seq"],
                "input_sha256": document["document_sha256"],
                "context": context,
                "context_sha256": society_state_sha256(context),
                "provider_config": provider_config,
            }
        )
        validate_decision_request(request)
        self.connection.execute(
            "insert into world_society_decision_request("
            "workspace_id,society_id,request_id,subject_id,"
            "base_tick,input_seq,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                row["workspace_id"],
                row["society_id"],
                request_id,
                subject_id,
                base_tick,
                document["input_seq"],
                Jsonb(request),
                request["document_sha256"],
            ),
        )
        return {"request": request, "decision": None, "status": "in_progress"}, True

    def finish(self, version_id: uuid.UUID, request_id: uuid.UUID, result: dict) -> dict:
        row = self._row(version_id)
        request = self._request(row, request_id)
        if request is None:
            raise UnknownSociety("decision request is unavailable")
        existing = self._result(row, request)
        if existing["decision"] is not None:
            return existing
        documents = self.society._validated_inputs(row)
        latest = documents[-1]
        try:
            self._authorize_context(request, documents)
            self.society._authorize(latest)
        except UnavailableSocietyInput:
            result = {
                "status": "unavailable",
                "reason": "decision_sources_unavailable",
                "proposal": None,
                "provider": None,
            }
        else:
            if (
                row["current_tick"] != request["base_tick"]
                or row["state_sha256"] != request["base_state_sha256"]
                or latest["document_sha256"] != request["input_sha256"]
            ):
                result = {**result, "status": "stale", "reason": "decision_context_changed"}
            elif result["status"] == "accepted":
                if request["provider_config"] is None or result["provider"] is None:
                    result = {
                        **result,
                        "status": "rejected",
                        "reason": "missing_provider_provenance",
                    }
                elif any(
                    result["provider"].get(key) != request["provider_config"][key]
                    for key in ("role", "manifest_sha256")
                ):
                    result = {
                        **result,
                        "status": "rejected",
                        "reason": "provider_configuration_changed",
                    }
                else:
                    reason = validate_proposal(request["context"], latest, result["proposal"])
                    result = {
                        **result,
                        "status": "rejected" if reason else "accepted",
                        "reason": reason or "validated_known_affordance_choice",
                    }
        sequence = self.connection.execute(
            "select coalesce(max(decision_seq),0)+1 as seq from world_society_decision "
            "where workspace_id=%s and society_id=%s",
            (row["workspace_id"], row["society_id"]),
        ).fetchone()["seq"]
        receipt = receipt_for(request, sequence, result)
        validate_decision_receipt(receipt, request)
        self.connection.execute(
            "insert into world_society_decision("
            "workspace_id,society_id,decision_seq,request_id,document,"
            "document_sha256) values(%s,%s,%s,%s,%s,%s)",
            (
                row["workspace_id"],
                row["society_id"],
                sequence,
                request_id,
                Jsonb(receipt),
                receipt["document_sha256"],
            ),
        )
        return {"request": request, "decision": receipt, "status": "completed"}
