"""A bounded asynchronous probe through the product client and durable spending authority."""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from exulanica.db.session import Database
from exulanica.models.choice import ChoiceRefused
from exulanica.models.client import ModelClient
from exulanica.models.manifest import AnsweringMechanism
from exulanica.models.policy import HostedRequestPolicy
from exulanica.models.spending import spending_request_key
from exulanica.models.usage import CallUsage, CostBasis, usd_string
from exulanica.spending.ledger import DurableSpending
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_admission import eligible
from exulanica.world.model_probe_contract import (
    RECEIPT_PROFILE,
    candidate_spec,
    probe_requests,
    seal,
    validate_definition,
)
from exulanica.world.model_probes import ClaimedProbe, ModelProbeRepository

_LOG = logging.getLogger(__name__)


def _call_record(usage: CallUsage, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    reported = raw.get("usage") if raw is not None else None
    reported = reported if isinstance(reported, Mapping) else {}

    def count(key: str) -> int | None:
        value = reported.get(key)
        return value if type(value) is int and value >= 0 else None

    served = raw.get("model") if raw is not None else None
    return {
        "provider": usage.provider,
        "role": str(usage.role),
        "requested_model": usage.model_id,
        "served_model": served if isinstance(served, str) and served else None,
        "outcome": str(usage.outcome),
        "used_fallback": usage.used_fallback,
        "attempts": 0 if usage.cache_hit else 1,
        "latency_ms": round(usage.latency_s * 1000),
        "prompt_tokens": count("prompt_tokens"),
        "completion_tokens": count("completion_tokens"),
        "cost_usd": usd_string(usage.usd) if usage.cost_basis == CostBasis.REPORTED else None,
        "cost_known": usage.cost_basis == CostBasis.REPORTED,
        "accounting": usage.as_cost_json(),
    }


class ModelProbeWorker:
    def __init__(
        self,
        database: Database,
        *,
        client: ModelClient,
        spending: DurableSpending,
        policy_for: Callable[[uuid.UUID], HostedRequestPolicy],
        workspaces: Callable[[], Iterable[uuid.UUID]],
    ) -> None:
        self.database, self.client, self.spending = database, client, spending
        self.policy_for, self.workspaces = policy_for, workspaces

    def _finish(self, claimed: ClaimedProbe, reason: str | None) -> None:
        with self.database.session(claimed.workspace_id) as connection:
            finished = ModelProbeRepository(connection, claimed.workspace_id).finish(
                claimed, reason=reason
            )
        if finished:
            self.spending.close_bound(
                claimed.workspace_id, claimed.bound_id, reason="The model probe ended."
            )
            with self.database.session(claimed.workspace_id) as connection:
                ModelProbeRepository(connection, claimed.workspace_id).bound_closed(
                    claimed.probe_id
                )

    def close_due(self, workspace_id: uuid.UUID) -> bool:
        with self.database.session(workspace_id) as connection:
            due = ModelProbeRepository(connection, workspace_id).bound_close_due()
        for row in due:
            self.spending.close_bound(
                workspace_id, row["bound_id"], reason="The model probe ended."
            )
            with self.database.session(workspace_id) as connection:
                ModelProbeRepository(connection, workspace_id).bound_closed(row["probe_id"])
        return bool(due)

    def turn(self, workspace_id: uuid.UUID, stop: threading.Event | None = None) -> bool:
        with self.database.session(workspace_id) as connection:
            repository = ModelProbeRepository(connection, workspace_id)
            repository.sweep()
            claimed = repository.claim("model-probe-worker")
            if claimed is None:
                return self.close_due(workspace_id)
            saved = repository.receipts(claimed.probe_id)
        definition = claimed.definition
        try:
            book = validate_definition(definition)
            eligible(definition["provider"], definition["model_id"])
            read_at = dt.datetime.fromisoformat(definition["price"]["read_at"])
            if dt.datetime.now(dt.UTC) >= read_at + dt.timedelta(hours=1):
                self._finish(claimed, "model_probe_price_expired")
                return True
            spec = candidate_spec(definition)
            role = decision_roles().role(book["role"])
            sender = self.client.with_policy(self.policy_for(workspace_id)).with_spending(
                self.spending.for_workspace(workspace_id).within(claimed.bound_id)
            )
            requests = probe_requests(definition)
            for request in requests[len(saved) :]:
                if stop is not None and stop.is_set():
                    self._finish(claimed, "model_probe_host_stopped")
                    return True
                with self.database.session(workspace_id) as connection:
                    repository = ModelProbeRepository(connection, workspace_id)
                    refusal = repository.before_case(claimed)
                if refusal is not None:
                    self._finish(claimed, refusal)
                    return True
                eligible(definition["provider"], definition["model_id"])
                context = book["cases"][request["case_index"]]
                mechanism = AnsweringMechanism(request["mechanism"])
                messages = role.adapter.messages(role, context, mechanism)
                attempts: list[CallUsage] = []
                responses: list[Mapping[str, Any]] = []
                answer, outcome, reason = None, "answered", None
                try:
                    # A reclaimed case uses the same durable key. An uncertain prior dispatch
                    # is refused by the authority instead of silently paying to try again.
                    with spending_request_key(
                        f"model-probe:{claimed.probe_id}:case:{request['case_seq']}"
                    ):
                        result = sender.with_attempts(attempts.append).probe_choice(
                            spec,
                            role.chosen,
                            messages,
                            role.choice(context),
                            mechanism=mechanism,
                            prompt_version=definition["prompt_version"],
                            timeout=definition["deadline_ms"] / 1000,
                            max_tokens=definition["answer_tokens"],
                            response_received=responses.append,
                        )
                    answer = {"action": result.label}
                    if role.takes_line(context):
                        answer["line"] = result.line
                except ChoiceRefused:
                    outcome = "invalid"
                except Exception as failure:
                    outcome, reason = "unavailable", type(failure).__name__
                document = seal(
                    {
                        "profile": RECEIPT_PROFILE,
                        "request": request,
                        "answer": answer,
                        "outcome": outcome,
                        "reason": reason,
                        "calls": [
                            _call_record(usage, responses[0] if responses else None)
                            for usage in attempts
                        ],
                    }
                )
                with self.database.session(workspace_id) as connection:
                    if not ModelProbeRepository(connection, workspace_id).append(claimed, document):
                        return True
                if outcome == "unavailable":
                    self._finish(claimed, "model_probe_call_unavailable")
                    return True
            self._finish(claimed, None)
        except Exception as failure:
            # Error text may contain response bytes or credentials. Only the class is logged.
            _LOG.warning(
                "a model probe could not continue", extra={"failure": type(failure).__name__}
            )
            self._finish(claimed, "model_probe_host_failed")
        return True

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            worked = False
            for workspace_id in self.workspaces():
                if stop.is_set():
                    break
                try:
                    worked = self.turn(workspace_id, stop) or worked
                except Exception as failure:
                    _LOG.warning(
                        "a model probe worker turn failed",
                        extra={"failure": type(failure).__name__},
                    )
            if not worked:
                stop.wait(0.5)
