"""Run native kind drafts under durable claims and the existing bounded model/check pipeline."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from exulanica.api.kind_drafts import (
    KIND_DRAFT_CODES,
    KindDraft,
    KindDraftCapacity,
    KindDrafts,
    _free_key,
    drafted_kind,
)
from exulanica.api.world_draft_worker import manifest_sha256
from exulanica.db.session import Database
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused, spending_request_key
from exulanica.selection.calls import CallLog, ModelCall, admitted_model_call
from exulanica.selection.kind_drafting import kind_drafting_prompt
from exulanica.selection.world_drafting import sendable
from exulanica.world.kind_draft_jobs import ClaimedKindDraft, KindDraftRepository
from exulanica.world.kinds.document import KIND_CODES
from exulanica.world.workspace_model_bindings import _document
from exulanica.world.world_draft_jobs import WorldDraftRefused

_LOG = logging.getLogger(__name__)
_MEANINGS = dict(KIND_DRAFT_CODES)
_CHECKS = dict(KIND_CODES)


def safe_refusal(value: dict) -> dict:
    """Keep catalog codes and sentences, never provider text or an echoed description."""
    code = value.get("code")
    if code not in _MEANINGS:
        code = "kind_not_drafted"
    check = value.get("check")
    check = check if isinstance(check, str) and check in _CHECKS else None
    return dict(
        code=code,
        detail=_MEANINGS[code] if check is None else _CHECKS[check],
        check=check if check in _CHECKS else None,
        where=None,
    )


def safe_calls(calls: Iterable[ModelCall], client: ModelClient | None) -> list[dict]:
    """Retain measured counters, withholding unadmitted provider-echoed model text."""
    manifest = load_manifest() if client is None else client.manifest
    return [_document(admitted_model_call(call, manifest)) for call in calls]


class KindDraftSpending:
    def __init__(self, worker: KindDraftWorker, claimed: ClaimedKindDraft) -> None:
        self.worker, self.claimed = worker, claimed
        self.workspace_id = claimed.workspace_id
        self.gate = worker.spending.for_workspace(self.workspace_id)

    def admit(self, request: Any) -> Any:
        return self.gate.admit(request)

    def dispatch(self, ticket: Any) -> None:
        def guard(connection: Any) -> None:
            repo = KindDraftRepository(connection, self.workspace_id)
            try:
                repo.attempt(
                    self.claimed,
                    dict(
                        kind="dispatch_authorized",
                        reservation_id=str(ticket.reservation_id),
                        key=ticket.key,
                    ),
                )
            except WorldDraftRefused as failed:
                raise SpendingRefused("spending_revoked", detail=failed.code) from failed

        self.gate.dispatch(ticket, guard=guard)

    def settle(self, ticket: Any, usage: Any) -> None:
        # Financial liability remains even when a withdrawal wins before the result arrives.
        self.gate.settle(ticket, usage)

    def release(self, ticket: Any) -> None:
        self.gate.release(ticket)


class _Recorder:
    def __init__(self, worker: KindDraftWorker, claimed: ClaimedKindDraft) -> None:
        self.worker, self.claimed = worker, claimed

    @property
    def closing(self) -> bool:
        return self.worker.holder.closing

    def finish(self, draft: KindDraft, **fields: Any) -> None:
        refusal = safe_refusal(fields.get("refusal") or {})
        model_id = fields.get("model_id")
        calls = safe_calls(fields.get("calls", ()), self.worker.client)
        document = dict(
            state="refused",
            refusal=refusal,
            calls=calls,
            model_id=model_id if any(call["served_model"] == model_id for call in calls) else None,
        )
        with self.worker.database.session(self.claimed.workspace_id) as connection:
            KindDraftRepository(connection, self.claimed.workspace_id).finish(
                self.claimed, document
            )
        self.worker.holder.finish(draft, state="refused", refusal=refusal)


class KindDraftWorker:
    def __init__(
        self,
        database: Database,
        *,
        client: ModelClient | None,
        spending: Any,
        holder: KindDrafts,
        policy_for: Callable,
        workspaces: Callable[[], Iterable[uuid.UUID]],
    ) -> None:
        self.database, self.client, self.spending = database, client, spending
        self.holder, self.policy_for, self.workspaces = holder, policy_for, workspaces
        self._watched: set[uuid.UUID] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()

    def notify(self, workspace_id: uuid.UUID) -> None:
        with self._lock:
            self._watched.add(workspace_id)
        self._wake.set()

    def run_once(self, workspace_id: uuid.UUID) -> bool:
        try:
            with self.holder.execution_slot():
                return self._run_once(workspace_id)
        except (KindDraftCapacity, WorldDraftRefused):
            return False

    def _run_once(self, workspace_id: uuid.UUID) -> bool:
        with self.database.session(workspace_id) as connection:
            repo = KindDraftRepository(connection, workspace_id)
            repo.expire()
            claimed = repo.claim(expired_only=self.client is None)
        if claimed is None:
            return False
        now = self.holder.clock()
        draft = KindDraft(
            claimed.draft_id,
            workspace_id,
            claimed.actor,
            claimed.description,
            datetime.now(UTC),
            now,
            changed=now,
            deadline=claimed.deadline_seconds,
        )
        if claimed.recovery or claimed.expired or self.client is None:
            _Recorder(self, claimed).finish(draft, refusal={"code": "kind_draft_failed"})
        else:
            self.holder.start(
                workspace_id,
                claimed.actor,
                claimed.description,
                lambda draft, holder: self._work(claimed, draft),
                deadline=claimed.deadline_seconds,
                guest=claimed.guest,
                identity=claimed.draft_id,
                admitted=True,
                reserved=True,
            )
        return True

    def _work(self, claimed: ClaimedKindDraft, draft: KindDraft) -> None:
        workspace_id = claimed.workspace_id
        recorder = _Recorder(self, claimed)
        log = CallLog()
        try:
            client = self.client
            if (
                claimed.recovery
                or claimed.expired
                or client is None
                or manifest_sha256(client) != claimed.manifest_sha256
                or kind_drafting_prompt().prompt_version != claimed.prompt_version
            ):
                recorder.finish(draft, refusal={"code": "kind_draft_failed"})
                return
            sender = client.with_policy(self.policy_for(workspace_id))
            if self.spending is not None:
                sender = sender.with_spending(KindDraftSpending(self, claimed))
            with self.database.session(workspace_id) as connection:
                KindDraftRepository(connection, workspace_id).require_claim(claimed)
                sent = sendable(connection, workspace_id, claimed.description)
            with spending_request_key(f"kind-draft:{claimed.draft_id}"):
                outcome = drafted_kind(
                    draft,
                    recorder,
                    client=sender,
                    text=sent.text,
                    placeholders=sent.placeholders,
                    log=log,
                    key_for=_free_key(lambda: self.database.session(workspace_id), workspace_id),
                )
            if outcome is not None and outcome.kind is not None and outcome.report is not None:
                if outcome.model_id is None or not any(
                    call["served_model"] == outcome.model_id
                    for call in safe_calls(outcome.calls, client)
                ):
                    recorder.finish(
                        draft, refusal={"code": "kind_draft_model_failed"}, calls=log.calls
                    )
                    return
                with self.database.session(workspace_id) as connection:
                    KindDraftRepository(connection, workspace_id).publish(
                        claimed,
                        outcome.kind,
                        outcome.report,
                        calls=safe_calls(log.calls, client),
                        model_id=outcome.model_id,
                    )
                self.holder.finish(draft, state="ready")
        except Exception as failure:
            _LOG.warning("a durable kind draft stopped: %s", type(failure).__name__)
            if draft.state == "drafting":
                with suppress(WorldDraftRefused):
                    recorder.finish(
                        draft,
                        refusal={"code": getattr(failure, "code", "kind_draft_failed")},
                        calls=log.calls,
                    )

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            # A listing that fails costs this pass the workspaces it lists, never the worker.
            try:
                listed = set(self.workspaces())
            except Exception as failure:
                _LOG.warning(
                    "a kind draft worker could not list workspaces: %s", type(failure).__name__
                )
                listed = set()
            with self._lock:
                workspaces = listed | self._watched
            for workspace in sorted(workspaces):
                if stop.is_set():
                    break
                try:
                    self.run_once(workspace)
                except Exception as failure:
                    _LOG.warning("a kind draft worker pass failed: %s", type(failure).__name__)
            self._wake.wait(0.5)
            self._wake.clear()
