"""Short committed reservations and immutable results around lock-free provider inference.

A society whose engine hosts a decision role reserves that role's request over what a subject may
do next under the role's contract (:meth:`SocietyDecisionRepository.prepare_role`), naming the
model its world's owner chose: a person's in a purposeful society (``exulanica-society/v2``)
first. It is finished once, in a later short transaction, with the exact state and input checked
again. Every read of a role's rows names the role's own profile. A social society
(``exulanica-society/v3``) keeps the v1 requests and receipts its retired proposal route stored,
each read back with the memories its context named; nothing reserves or answers a new one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final

from psycopg.types.json import Jsonb

from exulanica.world.deciders import EXTERNAL_REASONS, is_external, is_person_ask
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleOption,
    decision_roles,
)
from exulanica.world.role_decisions import role_request
from exulanica.world.society import (
    SocietyBytesNotRead,
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    inputs_ahead,
)
from exulanica.world.society_controls import MAX_CATCHUP_TICKS
from exulanica.world.society_decisions import (
    REQUEST_PROFILE,
    receipt_for,
    validate_decision_receipt,
    validate_decision_request,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_repository import SocietyRepository

#: What a role's receipt must say of the call to match its request: the model it asked, how.
_ROLE_PROVENANCE = ("provider", "model_id", "mechanism", "prompt_version")
#: What a receipt of an outside program's answer must say to match its request: the door, and the
#: grant and mapping file it was asked under.
_OUTSIDE_PROVENANCE = ("kind", "bridge", "grant_id", "grant_seq", "mapping_sha256")
#: A person's answer names only its kind: no account, model or program.
_PERSON_PROVENANCE = ("kind",)


#: How many minutes back a claim looks for a role's request its host never answered: the
#: minutes one claim can advance, and one more. A host that stops between reserving a request and
#: recording its answer is followed by a claim well within that.
UNANSWERED_WINDOW_TICKS: Final = MAX_CATCHUP_TICKS + 1


class SocietyDecisionRepository:
    def __init__(self, society: SocietyRepository) -> None:
        self.society = society
        self.connection = society.connection

    def _row(self, version_id: uuid.UUID) -> dict:
        self.society._lock()
        row = self.society._row(version_id, lock=True)
        if row is None:
            raise UnknownSociety("society is unavailable")
        if not society_engine(row["engine_version"]).model_decisions:
            raise ValueError(f"{row['engine_version']} takes no model decisions")
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
        request = self._request(row, request_id)
        documents = {} if request is None else self._context_inputs(row, request)[0]
        with inputs_ahead(self.connection, documents.values()):
            self.society.snapshot(version_id)
            if request is None:
                raise UnknownSociety("decision request is unavailable")
            self._authorize_context(request, documents)
        return self._result(row, request)

    def _context_ahead(self, row: dict, request: dict | None) -> Iterable[dict]:
        """The inputs reading ``request`` back authorizes, announced before the state's are asked,
        which takes the asset read lock (:func:`~exulanica.world.society.inputs_ahead`)."""
        return () if request is None else self._context_inputs(row, request)[0].values()

    def _context_inputs(self, row: dict, request: dict) -> tuple[dict[int, dict], dict]:
        """The inputs a request's context was asked over, and the latest, never the history
        between them: a role's one input, or a social request's input and its memories'."""
        latest_seq = self.society._chain(row)
        wanted = {request["input_seq"], latest_seq}
        if request["profile"] == REQUEST_PROFILE:
            context = request["context"]
            wanted |= {
                memory["input_seq"]
                for memory in [*context["own_observations"], *context["own_beliefs"]]
            }
        documents = self.society._inputs(row, wanted)
        return documents, documents[latest_seq]

    def _authorize_context(self, request: dict, documents: Mapping[int, dict]) -> None:
        self.society._authorize(documents[request["input_seq"]])
        if request["profile"] != REQUEST_PROFILE:
            # A role's context is read from the one input it was asked over, and no memory.
            return
        context = request["context"]
        for memory in [*context["own_observations"], *context["own_beliefs"]]:
            document = documents[memory["input_seq"]]
            if document["document_sha256"] != memory["input_sha256"]:
                raise ValueError("decision memory input binding mismatch")
            self.society._authorize(document)

    def role_decisions(
        self,
        role: DecisionRole,
        version_id: uuid.UUID,
        *,
        latest: int | None = None,
        authorized: Mapping[str, Any] | None = None,
    ) -> list[dict]:
        """``role``'s decisions this society recorded, in order, with what their minutes did.

        One row per receipt: whose, which model it asked (the request's, so a decision refused
        before any call still names it), how it ended, the call's cost and time, the option it
        chose, and the disposition of the minute that consumed it with that minute's reason, from
        the ``decision_applied`` event it recorded, or ``None`` while none has. The read a
        comparison of models is made from. ``latest`` keeps only that many of the most recent,
        for a reader that must not grow with the world's age.

        Reading the society's snapshot authorizes its inputs. ``authorized`` is the snapshot the
        caller read through this same society in this transaction; when it is this society's,
        for this version, that read is the authorization and the snapshot is not read again.
        """
        row = self._row(version_id)
        if (
            authorized is None
            or authorized.get("society_id") != row["society_id"]
            or authorized.get("version_id") != version_id
        ):
            self.society.snapshot(version_id)
        rows = self.connection.execute(
            "select d.decision_seq,d.document,r.document as request,d.recorded_at,"
            "t.disposition,t.tick,(select e.document->>'reason' from world_society_event e "
            "where e.workspace_id=d.workspace_id and e.society_id=d.society_id "
            "and e.tick=t.tick and e.event_kind='decision_applied' "
            "and (e.document->>'decision_seq')::bigint=d.decision_seq) as disposition_reason "
            "from world_society_decision d "
            "join world_society_decision_request r using(workspace_id,society_id,request_id) "
            "left join world_society_transition_decision t "
            "using(workspace_id,society_id,decision_seq) "
            "where d.workspace_id=%s and d.society_id=%s and d.document->>'profile'=%s "
            "order by d.decision_seq desc limit %s",
            (row["workspace_id"], row["society_id"], role.receipt_profile, latest),
        ).fetchall()
        decisions = []
        for value in reversed(rows):
            receipt, request = value["document"], value["request"]
            validate_decision_receipt(receipt, request)
            asked, provider = request["provider_config"], receipt["provider"]
            call = provider or {}
            outside = is_external(asked)
            played = is_person_ask(asked)
            decisions.append(
                {
                    "decision_seq": receipt["decision_seq"],
                    "subject_id": receipt["subject_id"],
                    "base_tick": receipt["base_tick"],
                    "consumed_tick": value["tick"],
                    # Who was asked: a model, an outside program under its grant, or a person
                    # playing the being (never which account), which no model's name, mechanism
                    # or cost describes.
                    "decider": (
                        {
                            "kind": "external",
                            "bridge": asked["bridge"],
                            "grant_id": asked["grant_id"],
                        }
                        if outside
                        else {"kind": "person"}
                        if played
                        else {
                            "kind": "model",
                            "provider": asked["provider"],
                            "model_id": asked["model_id"],
                        }
                    ),
                    "provider": None if outside or played else asked["provider"],
                    "model_id": None if outside or played else asked["model_id"],
                    "mechanism": None if outside or played else asked["mechanism"],
                    "status": receipt["status"],
                    "reason": receipt["reason"],
                    "disposition": value["disposition"],
                    "disposition_reason": value["disposition_reason"],
                    "chose": None if receipt["proposal"] is None else receipt["proposal"]["label"],
                    "asked_model": provider is not None and not played,
                    "answers_asked": call.get("answers_asked"),
                    "latency_ms": call.get("latency_ms"),
                    "cost_usd": call.get("cost_usd"),
                    "cost_known": call.get("cost_known"),
                    "prompt_tokens": call.get("prompt_tokens"),
                    "completion_tokens": call.get("completion_tokens"),
                    "recorded_at": value["recorded_at"],
                }
            )
        return decisions

    def prepare_role(
        self,
        role: DecisionRole,
        version_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        subject_id: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
        contract: DecisionContract,
        provider_config: dict,
        offer: Callable[[Sequence[RoleOption]], Sequence[RoleOption]] | None = None,
        withhold: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> tuple[dict, bool]:
        """Reserve a subject's request of ``role`` over the options they have now, or return the
        one reserved.

        ``offer`` keeps the options that may be offered, in their order: the caller leaves out
        any the rules its ask is sent under would change; ``withhold`` takes out of the observation
        what the one asked may not be shown (:func:`~exulanica.world.role_decisions.role_request`).
        ``None`` in place of a request when the subject has nothing to choose this minute, fewer
        than two options or nothing but the role's idle action among what is offered: nothing is
        reserved and no model is asked. The context is refused before any reservation when it is
        larger than the contract's bound. The caller commits and closes its connection before asking
        the model.
        """
        row = self._row(version_id)
        if not role.hosted_by(row["engine_version"]):
            raise ValueError(f"{row['engine_version']} takes no {role.subject} decisions")
        existing = self._request(row, request_id)
        with inputs_ahead(self.connection, self._context_ahead(row, existing)):
            self.society.snapshot(version_id)
            if existing:
                if (
                    existing["subject_id"],
                    existing["base_tick"],
                    existing["base_state_sha256"],
                ) != (str(subject_id), base_tick, base_state_sha256):
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
            return {"request": None, "decision": None, "status": "subject_already_decided"}, False
        latest_seq = self.society._chain(row)
        document = self.society._inputs(row, [latest_seq])[latest_seq]
        request, status = role_request(
            role,
            row["state"],
            document,
            str(subject_id),
            request_id=request_id,
            contract=contract,
            seed=row["seed"],
            provider_config=provider_config,
            offer=offer,
            withhold=withhold,
        )
        if request is None:
            return {"request": None, "decision": None, "status": status}, False
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

    def finish(
        self,
        version_id: uuid.UUID,
        request_id: uuid.UUID,
        result: dict,
        *,
        last_try: bool = True,
    ) -> dict:
        """Record the answer to a reserved request, checked against the state and inputs now.

        A request whose inputs can no longer be authorized is recorded as
        ``decision_sources_unavailable``, with no proposal and with the call that was made, if one
        was. So is one whose finish meets the race between reading its inputs' bytes and the asset
        read lock on its ``last_try``
        (``asked_again_after_a_race`` in :mod:`exulanica.world.society`): what the subject could
        see could not be read, and the request is closed rather than left in progress. A try
        before the last raises the race, to be asked again. A request an outside program did not
        answer keeps an outside reason whatever else changed: its own, or
        ``decider_disconnected``.
        """
        answered_for = result["reason"]
        row = self._row(version_id)
        request = self._request(row, request_id)
        if request is None:
            raise UnknownSociety("decision request is unavailable")
        existing = self._result(row, request)
        if existing["decision"] is not None:
            return existing
        if decision_roles().for_request(request["profile"]) is None:
            # A social society's stored request: its proposal route is retired, and nothing
            # answers one now.
            raise ValueError("only a decision role's request is answered")
        documents, latest = self._context_inputs(row, request)
        try:
            with inputs_ahead(self.connection, [*documents.values(), latest]):
                self._authorize_context(request, documents)
                self.society._authorize(latest)
        except (UnavailableSocietyInput, SocietyBytesNotRead) as refused:
            if isinstance(refused, SocietyBytesNotRead) and not last_try:
                raise
            # The call that was made, and what it cost, stay on the receipt: a world's hourly
            # bounds count every call a receipt names.
            result = {
                "status": "unavailable",
                "reason": "decision_sources_unavailable",
                "proposal": None,
                "provider": result["provider"],
            }
        else:
            if (
                row["current_tick"] != request["base_tick"]
                or row["state_sha256"] != request["base_state_sha256"]
                or latest["document_sha256"] != request["input_sha256"]
            ):
                result = {**result, "status": "stale", "reason": "decision_context_changed"}
            elif result["status"] == "accepted":
                played = is_person_ask(request["provider_config"])
                provenance = (
                    _OUTSIDE_PROVENANCE
                    if is_external(request["provider_config"])
                    else _PERSON_PROVENANCE
                    if played
                    else _ROLE_PROVENANCE
                )
                if result["provider"] is None or any(
                    result["provider"].get(key) != request["provider_config"][key]
                    for key in provenance
                ):
                    result = {
                        **result,
                        "status": "rejected",
                        "reason": "provider_configuration_changed",
                        "proposal": None,
                    }
                elif not (played and result["reason"] == "person_no_answer"):
                    # A played being that carried on, its person posting nothing, says so.
                    result = {**result, "reason": "validated_choice"}
        if result["status"] != "accepted":
            # Only an accepted answer is kept as a proposal; the rest record why none applies.
            result = {**result, "proposal": None}
        if is_external(request["provider_config"]) and result["provider"] is None:
            # Nothing the program said is recorded, so its receipt, and the event its minute
            # writes, say who was asked in the program's own terms.
            result = {
                **result,
                "status": "unavailable",
                "reason": answered_for
                if answered_for in EXTERNAL_REASONS
                else "decider_disconnected",
            }
        return self._record_receipt(row, request, request_id, result)

    def unanswered_requests(self, role: DecisionRole, version_id: uuid.UUID) -> list[uuid.UUID]:
        """``role``'s requests reserved in the last few minutes before the current one that no
        receipt answers.

        A host that stopped between reserving a request and recording its answer leaves one; the
        minute it was reserved for has already run with the routine deciding. The next claim
        follows within ``UNANSWERED_WINDOW_TICKS`` minutes, so only those are read, and a read
        costs the same however old the world is. An older one stays unanswered: nothing consumes
        or replays a request without a receipt. Oldest first.
        """
        row = self._row(version_id)
        return [
            value["request_id"]
            for value in self.connection.execute(
                "select r.request_id from world_society_decision_request r "
                "left join world_society_decision d "
                "using(workspace_id,society_id,request_id) "
                "where r.workspace_id=%s and r.society_id=%s and d.request_id is null "
                "and r.document->>'profile'=%s and r.base_tick>=%s and r.base_tick<%s "
                "order by r.base_tick,r.request_id",
                (
                    row["workspace_id"],
                    row["society_id"],
                    role.request_profile,
                    row["current_tick"] - UNANSWERED_WINDOW_TICKS,
                    row["current_tick"],
                ),
            ).fetchall()
        ]

    def close_unanswered(self, version_id: uuid.UUID, request_id: uuid.UUID) -> dict:
        """Record that a role's request was never answered in the minute it was asked for.

        Its receipt says so by name (``unanswered_in_its_minute``; an outside program's,
        ``no_answer_in_time``), and the next minute consumes it like any other unaccepted receipt,
        so the history closes what was left open.
        """
        row = self._row(version_id)
        request = self._request(row, request_id)
        if request is None or decision_roles().for_request(request["profile"]) is None:
            raise UnknownSociety("decision request is unavailable")
        existing = self._result(row, request)
        if existing["decision"] is not None:
            return existing
        result = {
            "status": "unavailable",
            "reason": "no_answer_in_time"
            if is_external(request["provider_config"])
            else "unanswered_in_its_minute",
            "proposal": None,
            "provider": None,
        }
        return self._record_receipt(row, request, request_id, result)

    def _record_receipt(
        self, row: dict, request: dict, request_id: uuid.UUID, result: dict
    ) -> dict:
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
