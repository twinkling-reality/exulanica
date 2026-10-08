"""World-scoped, append-only choices and receipts for a town's signal controller.

The owner chooses a model for a signal, with an effective time ahead of the server clock. A
worker's observation names a choice point in that world and road version. Its reservation and
receipt have one identity, a deadline and a state digest; a second answer, a late answer and a
point already sealed for viewers cannot replace the first result. The traffic step checks an
accepted proposal again, so persistence does not make a model's answer authoritative.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.role_decisions import (
    role_receipt,
    role_request,
    seal,
    validate_role_receipt,
)
from exulanica.world.traffic_episodes import EPISODE
from exulanica.world.world_clock import Era

__all__ = ["SignalChoiceRefused", "TrafficSignalRepository"]

_REQUEST_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/signals")


class SignalChoiceRefused(ValueError):
    """A signal choice or decision this world cannot record, by a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sealed_end(clock: Mapping[str, Any]) -> int:
    """Where a coupled version's sealed traffic ends, on its traffic timeline."""
    era = Era(
        clock["era"],
        clock["era_start_tick"],
        clock["seconds_per_tick"],
        clock["timeline_origin_second"],
    )
    return era.traffic_second(era.world_second_of_tick(clock["traffic_sealed_through_tick"]))


class TrafficSignalRepository:
    """The signal controller's world/version facts through a scoped database connection."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.version_id = version_id

    def _choices(self) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select choice_seq,request_id,signal_id,effective_second,model,document,"
            "chosen_by,recorded_at from world_traffic_signal_choice "
            "where workspace_id=%s and world_id=%s and version_id=%s order by choice_seq",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchall()

    def _lock_version(self) -> None:
        held = self.connection.execute(
            "select version_id from world_alternate_version where workspace_id=%s "
            "and world_id=%s and version_id=%s for update",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchone()
        if held is None:
            raise SignalChoiceRefused("world_version_unavailable")

    def clock(self) -> dict[str, Any] | None:
        """The version's coupled clock with traffic, or None while its traffic keeps shared real
        time (:mod:`exulanica.world.world_clock`)."""
        return self.connection.execute(
            "select * from world_clock where workspace_id=%s and world_id=%s and version_id=%s "
            "and roads_version is not null",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchone()

    def wall_second(self) -> int:
        """The database's wall clock, to the whole second: where a choice for traffic that keeps
        shared real time takes effect from."""
        return int(
            self.connection.execute(
                "select floor(extract(epoch from clock_timestamp()))::bigint as second"
            ).fetchone()["second"]
        )

    def present(self, wall_second: int) -> tuple[int, str]:
        """The second the version's traffic stands at, and the timeline it is on, which every
        choice's and activation's seconds share: ``wall_second`` while the traffic keeps shared
        real time (``unix``), or where its coupled traffic is sealed (``world``)."""
        clock = self.clock()
        if clock is None:
            return wall_second, "unix"
        return _sealed_end(clock), "world"

    def current_choices(self) -> dict[str, dict[str, Any]]:
        """The last owner choice for each signal, including its future effective second."""
        result = {}
        for row in self._choices():
            result[row["signal_id"]] = row
        return result

    def choices_at(self, second: int) -> dict[str, dict[str, Any]]:
        """Owner generations effective at this second of the version's traffic timeline, per
        signal (:meth:`present`)."""
        result = {}
        for row in self._choices():
            if row["effective_second"] <= second:
                result[row["signal_id"]] = row
        return result

    def segment(self, episode: int, segment: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from world_traffic_signal_segment where workspace_id=%s and world_id=%s "
            "and version_id=%s and episode=%s and segment=%s",
            (self.workspace_id, self.world_id, self.version_id, episode, segment),
        ).fetchone()

    def latest_segment(self, episode: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from world_traffic_signal_segment where workspace_id=%s and world_id=%s "
            "and version_id=%s and episode=%s order by segment desc limit 1",
            (self.workspace_id, self.world_id, self.version_id, episode),
        ).fetchone()

    def latest_any_segment(self) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from world_traffic_signal_segment where workspace_id=%s and world_id=%s "
            "and version_id=%s order by episode desc,segment desc limit 1",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchone()

    def point_receipt(
        self, episode: int, signal_id: str, choice_second: int, choice_seq: int
    ) -> dict[str, Any] | None:
        return self.connection.execute(
            "select r.request_id,r.deadline_at,r.document as request,d.document as decision "
            "from world_traffic_signal_decision_request r left join "
            "world_traffic_signal_decision d using(workspace_id,world_id,version_id,request_id) "
            "where r.workspace_id=%s and r.world_id=%s and r.version_id=%s and r.episode=%s "
            "and r.signal_id=%s and r.choice_second=%s and r.choice_seq=%s",
            (
                self.workspace_id,
                self.world_id,
                self.version_id,
                episode,
                signal_id,
                choice_second,
                choice_seq,
            ),
        ).fetchone()

    def decision_for(self, request_id: uuid.UUID) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select document from world_traffic_signal_decision where workspace_id=%s "
            "and world_id=%s and version_id=%s and request_id=%s",
            (self.workspace_id, self.world_id, self.version_id, request_id),
        ).fetchone()
        return None if row is None else row["document"]

    def world_hour(self) -> tuple[int, Decimal]:
        row = self.connection.execute(
            "select count(*) filter (where d.document->'provider' <> 'null'::jsonb "
            "or (d.request_id is null and r.budget_bound_usd>0)) as asked,"
            "coalesce(sum(case when d.document->'provider' <> 'null'::jsonb "
            "then (d.document->'provider'->>'cost_usd')::numeric "
            "when d.request_id is null then r.budget_bound_usd else 0 end),0) as spent "
            "from world_traffic_signal_decision_request r left join "
            "world_traffic_signal_decision d using(workspace_id,world_id,version_id,request_id) "
            "where r.workspace_id=%s and r.world_id=%s "
            "and r.recorded_at>clock_timestamp()-interval '1 hour'",
            (self.workspace_id, self.world_id),
        ).fetchone()
        return int(row["asked"]), Decimal(row["spent"])

    def activations(self) -> dict[int, int]:
        """First sealed accepted choice point for each owner generation, in a legacy segment or
        a coupled minute."""
        rows = self.connection.execute(
            "select r.choice_seq,min(r.choice_second) as active_second "
            "from world_traffic_signal_decision_request r "
            "join world_traffic_signal_decision d "
            "using(workspace_id,world_id,version_id,request_id) "
            "where r.workspace_id=%s and r.world_id=%s and r.version_id=%s "
            "and d.document->>'status'='accepted' and ("
            "exists (select 1 from world_traffic_signal_segment s "
            "where s.workspace_id=r.workspace_id and s.world_id=r.world_id "
            "and s.version_id=r.version_id and s.episode=r.episode "
            "and s.start_second<=r.choice_second and r.choice_second<s.end_second) "
            "or exists (select 1 from world_clock_traffic_minute m "
            "where m.workspace_id=r.workspace_id and m.world_id=r.world_id "
            "and m.version_id=r.version_id and m.episode=r.episode "
            "and m.start_second<=r.choice_second and r.choice_second<m.end_second)) "
            "group by r.choice_seq",
            (self.workspace_id, self.world_id, self.version_id),
        ).fetchall()
        return {int(row["choice_seq"]): int(row["active_second"]) for row in rows}

    def record_choice(
        self,
        role: DecisionRole,
        manifest: Manifest,
        *,
        request_id: uuid.UUID,
        signal_id: str,
        known_signals: Sequence[str],
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
    ) -> dict[str, Any]:
        """Choose a model or fixed timing, effective at the next prepared minute boundary.

        ``known_signals`` comes from this version's compiled roads, never from the request body.
        An exact retry returns the first row and its original effective time.
        """
        if signal_id not in known_signals:
            raise SignalChoiceRefused("signal_not_in_world")
        contract = role.contract()
        record: dict[str, str] | None = None
        if model is not None:
            if set(model) != {"provider", "model_id"}:
                raise SignalChoiceRefused("model_not_declared")
            try:
                spec = manifest.offered(role.chosen, model["model_id"])
            except (KeyError, ManifestError) as exc:
                raise SignalChoiceRefused("model_not_offered") from exc
            if spec.provider != model["provider"] or contract.mechanism_for(spec) is None:
                raise SignalChoiceRefused("model_not_askable")
            record = {"provider": spec.provider, "model_id": spec.model_id}
        with self.connection.transaction():
            # A world-version row is the serialization point for choices and seals. It is
            # already an UPDATE-granted runtime relation because authored edits lock it too.
            self._lock_version()
            rows = self._choices()
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                if (
                    existing["signal_id"] != signal_id
                    or existing["model"] != record
                    or existing["chosen_by"] != chosen_by
                ):
                    raise SignalChoiceRefused("choice_key_reused")
                return {**existing["document"], "recorded_at": existing["recorded_at"]}
            current = {row["signal_id"]: row for row in rows}
            if record is not None:
                running = (
                    sum(
                        1
                        for subject, choice in current.items()
                        if subject != signal_id and choice["model"] is not None
                    )
                    + 1
                )
                if running > contract.value(role.subjects_bound):
                    raise SignalChoiceRefused("too_many_model_signals")
            policy = signal_actuation()
            segment = policy.segment_seconds
            clock = self.clock()
            if clock is not None:
                # A coupled version's traffic seconds are simulated: the choice takes effect one
                # minute of preparation after the traffic already sealed, never by the wall clock.
                target = _sealed_end(clock) + policy.preparation_lead_seconds
            else:
                now = self.wall_second()
                target = (
                    (now + policy.preparation_lead_seconds + segment - 1) // segment
                ) * segment
                latest = self.latest_any_segment()
                if latest is not None:
                    target = max(target, latest["end_second"])
            sequence = 1 if not rows else rows[-1]["choice_seq"] + 1
            document = seal(
                {
                    "profile": role.choice_profile,
                    "world_id": self.world_id,
                    "version_id": str(self.version_id),
                    "signal_id": signal_id,
                    "choice_seq": sequence,
                    "request_id": str(request_id),
                    "effective_second": target,
                    "model": record,
                    "contract": contract.binding(),
                    "chosen_by": str(chosen_by),
                }
            )
            row = self.connection.execute(
                "insert into world_traffic_signal_choice(workspace_id,world_id,version_id,"
                "choice_seq,request_id,signal_id,effective_second,model,document,document_sha256,"
                "chosen_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning recorded_at",
                (
                    self.workspace_id,
                    self.world_id,
                    self.version_id,
                    sequence,
                    request_id,
                    signal_id,
                    target,
                    Jsonb(record),
                    Jsonb(document),
                    document["document_sha256"],
                    chosen_by,
                ),
            ).fetchone()
            return {**document, "recorded_at": row["recorded_at"]}

    def reserve_point(
        self,
        role: DecisionRole,
        *,
        roads_version: str,
        episode: int,
        segment: int,
        choice: Mapping[str, Any],
        choice_second: int,
        state_sha256: str,
        observation: Mapping[str, int],
        manifest_sha256: str,
        mechanism: str,
        budget_bound_usd: Decimal = Decimal(0),
    ) -> dict[str, Any] | None:
        """Reserve one due point, or none with no nearby vehicle to choose for.

        The controller calls this from its time-driven preparation, never from a viewer read.
        The database's unique point key makes a restarted probe idempotent.
        """
        model = choice["model"]
        if model is None or choice_second < choice["effective_second"]:
            return None
        contract = role.contract()
        request_id = uuid.uuid5(
            _REQUEST_NAMESPACE,
            f"{self.workspace_id}:{self.world_id}:{self.version_id}:{roads_version}:"
            f"{episode}:{choice['signal_id']}:{choice_second}:{choice['choice_seq']}",
        )
        with self.connection.transaction():
            self._lock_version()
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
                (str(self.workspace_id), self.world_id),
            )
            current = self.choices_at(choice_second).get(choice["signal_id"])
            if current is None or current["choice_seq"] != choice["choice_seq"]:
                raise SignalChoiceRefused("segment_choice_changed")
            existing = self.connection.execute(
                "select document,deadline_at,budget_bound_usd,state_sha256,"
                "roads_version,episode,segment,"
                "choice_seq,choice_second from world_traffic_signal_decision_request "
                "where workspace_id=%s and world_id=%s and version_id=%s and request_id=%s",
                (self.workspace_id, self.world_id, self.version_id, request_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["state_sha256"] != state_sha256
                    or existing["roads_version"] != roads_version
                    or existing["episode"] != episode
                    or existing["segment"] != segment
                    or existing["choice_seq"] != choice["choice_seq"]
                    or existing["choice_second"] != choice_second
                ):
                    raise SignalChoiceRefused("point_changed_after_reservation")
                return {
                    "request": existing["document"],
                    "deadline_at": existing["deadline_at"],
                    "budget_refusal": (
                        "world_hour_spend_spent"
                        if budget_bound_usd > existing["budget_bound_usd"]
                        else None
                    ),
                }
            asked, spent = self.world_hour()
            refusal = None
            if asked >= contract.value("decisions_per_world_hour_maximum"):
                refusal = "world_hour_decisions_spent"
            elif spent + budget_bound_usd > Decimal(
                contract.value("spend_per_world_hour_microusd")
            ) / Decimal(1_000_000):
                refusal = "world_hour_spend_spent"
            held_bound = Decimal(0) if refusal is not None else budget_bound_usd
            now = self.connection.execute("select clock_timestamp() as now").fetchone()["now"]
            deadline_at = now + timedelta(milliseconds=contract.value("decision_deadline_ms"))
            context_source = seal(
                {
                    "profile": "exulanica.junction-signal-observation/v1",
                    "world_id": self.world_id,
                    "roads_version": roads_version,
                    "episode": episode,
                    "segment": segment,
                    "choice_generation": choice["choice_seq"],
                    "choice_second": choice_second,
                    "signal_id": choice["signal_id"],
                    "state_sha256": state_sha256,
                    "observation": dict(observation),
                    "input_seq": choice["choice_seq"],
                }
            )
            state = {
                "branch_id": str(self.version_id),
                "tick": choice_second,
                "signals": [choice["signal_id"]],
                "choice_points": [choice["signal_id"]],
            }
            request, _status = role_request(
                role,
                state,
                context_source,
                choice["signal_id"],
                request_id=request_id,
                contract=contract,
                seed="0" * 64,
                provider_config={
                    "provider": model["provider"],
                    "model_id": model["model_id"],
                    "mechanism": mechanism,
                    "choice_seq": choice["choice_seq"],
                    "manifest_sha256": manifest_sha256,
                    "prompt_version": role.prompt_version,
                    "contract": contract.binding(),
                    "deadline_ms": contract.value("decision_deadline_ms"),
                },
            )
            if request is None:
                return None
            self.connection.execute(
                "insert into world_traffic_signal_decision_request(workspace_id,world_id,"
                "version_id,roads_version,episode,segment,choice_seq,signal_id,choice_second,"
                "request_id,state_sha256,deadline_at,budget_bound_usd,document,document_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    self.version_id,
                    roads_version,
                    episode,
                    segment,
                    choice["choice_seq"],
                    choice["signal_id"],
                    choice_second,
                    request_id,
                    state_sha256,
                    deadline_at,
                    held_bound,
                    Jsonb(request),
                    request["document_sha256"],
                ),
            )
            return {"request": request, "deadline_at": deadline_at, "budget_refusal": refusal}

    def record_result(
        self, role: DecisionRole, request_id: uuid.UUID, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Append one receipt; late or duplicate results are refused by their identity."""
        with self.connection.transaction():
            self._lock_version()
            row = self.connection.execute(
                "select document,deadline_at,signal_id,choice_second,choice_seq "
                "from world_traffic_signal_decision_request "
                "where workspace_id=%s and world_id=%s and version_id=%s and request_id=%s",
                (self.workspace_id, self.world_id, self.version_id, request_id),
            ).fetchone()
            if row is None:
                raise SignalChoiceRefused("point_not_reserved")
            existing = self.connection.execute(
                "select request_id from world_traffic_signal_decision "
                "where workspace_id=%s and world_id=%s and version_id=%s and request_id=%s",
                (self.workspace_id, self.world_id, self.version_id, request_id),
            ).fetchone()
            if existing is not None:
                raise SignalChoiceRefused("duplicate_answer")
            now = self.connection.execute("select clock_timestamp() as now").fetchone()["now"]
            if result["status"] == "accepted" and now > row["deadline_at"]:
                raise SignalChoiceRefused("answer_after_deadline")
            current = self.choices_at(row["choice_second"]).get(row["signal_id"])
            if result["status"] == "accepted" and (
                current is None or current["choice_seq"] != row["choice_seq"]
            ):
                raise SignalChoiceRefused("choice_generation_changed")
            receipt = role_receipt(role, row["document"], 1, result)
            validate_role_receipt(role, receipt, row["document"])
            self.connection.execute(
                "insert into world_traffic_signal_decision(workspace_id,world_id,version_id,"
                "request_id,document,document_sha256) values(%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    self.version_id,
                    request_id,
                    Jsonb(receipt),
                    receipt["document_sha256"],
                ),
            )
            return receipt

    def check_generations(
        self, absolute_start: int, selected_generations: Mapping[str, int]
    ) -> None:
        """Refuse a minute prepared under owner choices other than those effective at its start."""
        current_generations = {
            signal: row["choice_seq"] for signal, row in self.choices_at(absolute_start).items()
        }
        if current_generations != dict(selected_generations):
            raise SignalChoiceRefused("segment_choice_changed")

    def finalize_requests(
        self,
        role: DecisionRole,
        *,
        episode: int,
        absolute_start: int,
        absolute_end: int,
        selected_generations: Mapping[str, int],
        signal_choices: Mapping[str, Mapping[str, str]],
    ) -> dict[str, Any]:
        """Finish every reserved point of one minute before it is sealed, and digest them.

        A reservation of a superseded choice, or one unanswered past its deadline, receives its
        fallback receipt; one still inside its deadline refuses the seal (``point_pending``); each
        recorded action must be what its receipt decided. The caller holds the version row.
        Answers the minute's first accepted choice second and generation and the decisions digest.
        """
        requests = self.connection.execute(
            "select r.choice_seq,r.signal_id,r.choice_second,r.request_id,"
            "r.document as request,r.document_sha256 as request_sha,"
            "r.deadline_at,d.document as decision,d.document_sha256 as decision_sha "
            "from world_traffic_signal_decision_request r left join "
            "world_traffic_signal_decision d "
            "using(workspace_id,world_id,version_id,request_id) "
            "where r.workspace_id=%s and r.world_id=%s and r.version_id=%s and r.episode=%s "
            "and r.choice_second >= %s and r.choice_second < %s "
            "order by r.choice_second,r.signal_id",
            (
                self.workspace_id,
                self.world_id,
                self.version_id,
                episode,
                absolute_start,
                absolute_end,
            ),
        ).fetchall()
        # A changed choice can supersede a reserved future point before this minute
        # seals. Finish that reservation too: the seal trigger forbids later receipts.
        selected_requests = []
        for row in requests:
            if selected_generations.get(row["signal_id"]) == row["choice_seq"]:
                selected_requests.append(row)
                continue
            if row["decision"] is None:
                fallback = role_receipt(
                    role,
                    row["request"],
                    1,
                    {
                        "status": "unavailable",
                        "reason": "point_stale",
                        "proposal": None,
                        "provider": None,
                    },
                )
                validate_role_receipt(role, fallback, row["request"])
                self.connection.execute(
                    "insert into world_traffic_signal_decision(workspace_id,world_id,"
                    "version_id,request_id,document,document_sha256) "
                    "values(%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        self.world_id,
                        self.version_id,
                        row["request_id"],
                        Jsonb(fallback),
                        fallback["document_sha256"],
                    ),
                )
        requests = []
        unreachable = []
        for row in selected_requests:
            recorded = signal_choices.get(row["signal_id"], {})
            if str(row["choice_second"] - episode * EPISODE) in recorded:
                requests.append(row)
                continue
            # A point the traffic never stopped at: the green it would extend had no extension
            # left, and a worker that offered it anyway left its request behind. Its answer
            # moved no light, so it is finished by that name and kept out of the choices.
            if row["decision"] is None:
                fallback = role_receipt(
                    role,
                    row["request"],
                    1,
                    {
                        "status": "unavailable",
                        "reason": "green_not_eligible",
                        "proposal": None,
                        "provider": None,
                    },
                )
                validate_role_receipt(role, fallback, row["request"])
                self.connection.execute(
                    "insert into world_traffic_signal_decision(workspace_id,world_id,"
                    "version_id,request_id,document,document_sha256) "
                    "values(%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        self.world_id,
                        self.version_id,
                        row["request_id"],
                        Jsonb(fallback),
                        fallback["document_sha256"],
                    ),
                )
                row = {**row, "decision": fallback, "decision_sha": fallback["document_sha256"]}
            unreachable.append(row)
        now = self.connection.execute("select clock_timestamp() as now").fetchone()["now"]
        active = None
        generation = None
        for index, row in enumerate(requests):
            if row["decision"] is None and now < row["deadline_at"]:
                raise SignalChoiceRefused("point_pending")
            if row["decision"] is None:
                fallback = role_receipt(
                    role,
                    row["request"],
                    1,
                    {
                        "status": "unavailable",
                        "reason": "unanswered_in_its_minute",
                        "proposal": None,
                        "provider": None,
                    },
                )
                validate_role_receipt(role, fallback, row["request"])
                self.connection.execute(
                    "insert into world_traffic_signal_decision(workspace_id,world_id,"
                    "version_id,request_id,document,document_sha256) "
                    "values(%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        self.world_id,
                        self.version_id,
                        row["request_id"],
                        Jsonb(fallback),
                        fallback["document_sha256"],
                    ),
                )
                row = {**row, "decision": fallback, "decision_sha": fallback["document_sha256"]}
                requests[index] = row
            action = signal_choices.get(row["signal_id"], {}).get(
                str(row["choice_second"] - episode * EPISODE)
            )
            expected = (
                row["decision"]["proposal"]["option"]["kind"]
                if row["decision"] is not None and row["decision"]["status"] == "accepted"
                else "switch"
            )
            if action != expected:
                raise SignalChoiceRefused("segment_decisions_changed")
            if (
                active is None
                and row["decision"] is not None
                and (row["decision"]["status"] == "accepted")
            ):
                active = row["choice_second"]
                generation = row["choice_seq"]
        facts: dict[str, Any] = {
            "choices": signal_choices,
            "requests": [[row["request_sha"], row["decision_sha"]] for row in requests],
        }
        if unreachable:
            # Named only when present, so every minute sealed without one digests as before.
            facts["not_applied"] = [
                [row["request_sha"], row["decision_sha"]] for row in unreachable
            ]
        decisions_sha = hashlib.sha256(canonical_json(facts)).hexdigest()
        return {
            "active_second": active,
            "choice_seq": generation,
            "decisions_sha256": decisions_sha,
        }

    def seal_segment(
        self,
        *,
        role: DecisionRole,
        roads_version: str,
        input_sha256: str,
        episode: int,
        segment: int,
        states: Sequence[Mapping[str, Any]],
        continuation: Mapping[str, Any],
        selected_generations: Mapping[str, int],
    ) -> dict[str, Any]:
        """Seal one completed minute and the result or expired fallback of every reserved point.

        A version-row lock serializes this seal with accepting an answer and changing a model.
        An exact retry returns the prior fact; a different replay cannot replace displayed time.
        """
        if not 0 <= segment < EPISODE // signal_actuation().segment_seconds:
            raise SignalChoiceRefused("segment_out_of_range")
        local_start = segment * signal_actuation().segment_seconds
        local_end = local_start + signal_actuation().segment_seconds
        absolute_start = episode * EPISODE + local_start
        absolute_end = episode * EPISODE + local_end
        document = dict(continuation)
        digest = document.pop("document_sha256", None)
        if (
            document.get("profile") != "exulanica.traffic-continuation/v1"
            or document.get("input_sha256") != input_sha256
            or document.get("episode") != episode
            or document.get("next_second") != local_end
            or document.get("state", {}).get("second") != local_end - 1
            or hashlib.sha256(canonical_json(document)).hexdigest() != digest
            or len(states) != signal_actuation().segment_seconds
            or [state["second"] for state in states] != list(range(local_start, local_end))
        ):
            raise SignalChoiceRefused("segment_replay_changed")
        frames_sha = hashlib.sha256(
            canonical_json(
                {
                    "states": list(states),
                    "signal_choices": document["signal_choices"],
                    "initial_signal_cursors": document["initial_signal_cursors"],
                }
            )
        ).hexdigest()
        with self.connection.transaction():
            self._lock_version()
            coupled = self.clock()
            if coupled is not None and absolute_end > coupled["timeline_origin_second"]:
                raise SignalChoiceRefused("segment_after_clock_transition")
            self.check_generations(absolute_start, selected_generations)
            previous_sha = None
            if segment:
                previous = self.segment(episode, segment - 1)
                if previous is None:
                    raise SignalChoiceRefused("previous_segment_missing")
                if (
                    previous["input_sha256"] != input_sha256
                    or previous["roads_version"] != roads_version
                ):
                    raise SignalChoiceRefused("segment_input_changed")
                previous_sha = previous["continuation_sha256"]
            decided = self.finalize_requests(
                role,
                episode=episode,
                absolute_start=absolute_start,
                absolute_end=absolute_end,
                selected_generations=selected_generations,
                signal_choices=document["signal_choices"],
            )
            active, generation, decisions_sha = (
                decided["active_second"],
                decided["choice_seq"],
                decided["decisions_sha256"],
            )
            existing = self.segment(episode, segment)
            if existing is not None:
                if (
                    existing["continuation_sha256"] != digest
                    or existing["frames_sha256"] != frames_sha
                    or existing["decisions_sha256"] != decisions_sha
                ):
                    raise SignalChoiceRefused("segment_already_sealed_differently")
                return existing
            return self.connection.execute(
                "insert into world_traffic_signal_segment(workspace_id,world_id,version_id,"
                "roads_version,input_sha256,episode,segment,start_second,end_second,"
                "previous_sha256,choice_seq,active_second,decisions_sha256,frames_sha256,"
                "continuation,continuation_sha256) values("
                + ",".join(["%s"] * 16)
                + ") returning *",
                (
                    self.workspace_id,
                    self.world_id,
                    self.version_id,
                    roads_version,
                    input_sha256,
                    episode,
                    segment,
                    absolute_start,
                    absolute_end,
                    previous_sha,
                    generation,
                    active,
                    decisions_sha,
                    frames_sha,
                    Jsonb(dict(continuation)),
                    digest,
                ),
            ).fetchone()
