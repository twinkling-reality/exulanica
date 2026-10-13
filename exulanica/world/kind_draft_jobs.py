"""Requester-scoped native kind jobs, with atomic checked-kind publication."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world import draft_admission
from exulanica.world.kinds.document import KindDocument
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.world_draft_jobs import WorldDraftRefused


@dataclass(frozen=True)
class ClaimedKindDraft:
    workspace_id: uuid.UUID
    draft_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    actor: uuid.UUID
    description: str
    deadline_seconds: int
    manifest_sha256: str
    prompt_version: str
    recovery: bool
    guest: bool
    expired: bool = False


class KindDraftRepository:
    def __init__(self, connection: psycopg.Connection[Any], workspace_id: uuid.UUID) -> None:
        self.connection, self.workspace_id = connection, workspace_id

    def _live(self) -> None:
        lock_workspace(self.connection, self.workspace_id)
        if self.connection.execute(
            "select 1 from tombstone where workspace_id=%s and scope::text='workspace'",
            (self.workspace_id,),
        ).fetchone():
            raise WorldDraftRefused("workspace_erased")

    def submit(
        self,
        *,
        actor: uuid.UUID,
        description: str,
        guest: bool,
        starts_maximum: int,
        workspace_maximum: int,
        deadline_seconds: int,
        manifest_sha256: str,
        prompt_version: str,
    ) -> uuid.UUID:
        with self.connection.transaction():
            self._live()
            WorkspaceKinds(self.connection, self.workspace_id).refuse_when_full()
            draft_admission.bind(self.connection, actor, starts_maximum, workspace_maximum)
            draft_id, job_id = uuid.uuid4(), uuid.uuid4()
            try:
                with self.connection.transaction():
                    self.connection.execute(
                        "insert into job(job_id,workspace_id,kind,payload) "
                        "values(%s,%s,'kind_draft',%s)",
                        (job_id, self.workspace_id, Jsonb(dict(draft_id=str(draft_id)))),
                    )
                    self.connection.execute(
                        "insert into kind_draft_start(workspace_id,draft_id,actor_id,job_id,guest,"
                        "deadline_seconds,manifest_sha256,prompt_version) "
                        "values(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            self.workspace_id,
                            draft_id,
                            actor,
                            job_id,
                            guest,
                            deadline_seconds,
                            manifest_sha256,
                            prompt_version,
                        ),
                    )
                    self.connection.execute(
                        "insert into kind_draft_input values(%s,%s,%s)",
                        (self.workspace_id, draft_id, description),
                    )
            except psycopg.errors.RaiseException as failure:
                refused = draft_admission.refusal(failure)
                if refused is not None:
                    raise WorldDraftRefused(*refused) from failure
                raise
            return draft_id

    def get(self, actor: uuid.UUID, draft_id: uuid.UUID) -> dict | None:
        rows = self._rows(actor, draft_id)
        return rows[0] if rows else None

    def _rows(self, actor: uuid.UUID, draft_id: uuid.UUID | None = None) -> list[dict]:
        return self.connection.execute(
            "select s.*,j.state,j.completed_at,i.description,o.document as outcome "
            "from kind_draft_start s join job j using(job_id) "
            "left join kind_draft_input i on i.workspace_id=s.workspace_id and "
            "i.draft_id=s.draft_id "
            "left join kind_draft_outcome o on o.workspace_id=s.workspace_id and "
            "o.draft_id=s.draft_id "
            "where s.workspace_id=%s and s.actor_id=%s "
            "and (%s::uuid is null or s.draft_id=%s) "
            "and (i.draft_id is not null or o.draft_id is not null) "
            "and (j.completed_at is null or j.completed_at>statement_timestamp()-interval '1 "
            "hour') "
            "and not exists(select 1 from tombstone t where t.workspace_id=s.workspace_id and "
            "t.scope::text='workspace')",
            (self.workspace_id, actor, draft_id, draft_id),
        ).fetchall()

    def listing(self, actor: uuid.UUID) -> list[dict]:
        return sorted(self._rows(actor), key=lambda row: row["started_at"], reverse=True)

    def _claimable(self, expired_only: bool, *, lock: bool = False) -> dict | None:
        return self.connection.execute(
            "select s.*,i.description,j.attempts,"
            "s.started_at+(s.deadline_seconds+120)*interval '1 second'<=clock_timestamp() "
            "as expired "
            "from kind_draft_start s join kind_draft_input i using(workspace_id,draft_id) "
            "join job j using(job_id) where s.workspace_id=%s and "
            "((j.state='queued' and j.run_after<=clock_timestamp()) or "
            "(j.state='running' and j.lease_expires_at<=clock_timestamp())) "
            "and (not %s or j.state='running' or "
            "s.started_at+(s.deadline_seconds+120)*interval '1 second'<=clock_timestamp()) "
            "order by s.started_at " + ("for update of j skip locked " if lock else "") + "limit 1",
            (self.workspace_id, expired_only),
        ).fetchone()

    def claim(
        self, worker_id: str = "kind-draft-worker", *, expired_only: bool = False
    ) -> ClaimedKindDraft | None:
        with self.connection.transaction():
            # An idle poll is an observation, not a workspace mutation. A positive observation
            # is only a hint: preserve workspace-before-job lock order and reread under that fence.
            if self._claimable(expired_only) is None:
                return None
            self._live()
            row = self._claimable(expired_only, lock=True)
            if row is None:
                return None
            token = uuid.uuid4()
            self.connection.execute(
                "update job set "
                "state='running',claim_token=%s,claimed_by=%s,claimed_at=clock_timestamp(),"
                "attempts=attempts+1,lease_expires_at=clock_timestamp()+%s*interval '1 second' "
                "where job_id=%s",
                (token, worker_id, row["deadline_seconds"], row["job_id"]),
            )
            return ClaimedKindDraft(
                self.workspace_id,
                row["draft_id"],
                row["job_id"],
                token,
                row["actor_id"],
                row["description"],
                row["deadline_seconds"],
                row["manifest_sha256"],
                row["prompt_version"],
                row["attempts"] > 0,
                row["guest"],
                row["expired"],
            )

    def require_claim(self, claimed: ClaimedKindDraft) -> None:
        self._live()
        row = self.connection.execute(
            "select j.state,j.claim_token,j.lease_expires_at>clock_timestamp() as live "
            "from job j join kind_draft_start s using(job_id) where s.workspace_id=%s "
            "and s.draft_id=%s and s.actor_id=%s and j.job_id=%s for update of j",
            (self.workspace_id, claimed.draft_id, claimed.actor, claimed.job_id),
        ).fetchone()
        if (
            claimed.workspace_id != self.workspace_id
            or not row
            or row["state"] != "running"
            or row["claim_token"] != claimed.claim_token
            or not row["live"]
        ):
            raise WorldDraftRefused("kind_draft_lease_lost")

    def attempt(self, claimed: ClaimedKindDraft, document: Mapping[str, Any]) -> None:
        with self.connection.transaction():
            self.require_claim(claimed)
            self.connection.execute(
                "insert into kind_draft_attempt select %s,%s,coalesce(max(event_seq),0)+1,%s,%s "
                "from kind_draft_attempt where workspace_id=%s and draft_id=%s",
                (
                    self.workspace_id,
                    claimed.draft_id,
                    claimed.claim_token,
                    Jsonb(dict(document)),
                    self.workspace_id,
                    claimed.draft_id,
                ),
            )

    def finish(self, claimed: ClaimedKindDraft, document: Mapping[str, Any]) -> None:
        with self.connection.transaction():
            self.require_claim(claimed)
            self.connection.execute(
                "insert into kind_draft_outcome(workspace_id,draft_id,claim_token,document) "
                "values(%s,%s,%s,%s)",
                (self.workspace_id, claimed.draft_id, claimed.claim_token, Jsonb(dict(document))),
            )
            ready = document["state"] == "ready"
            self.connection.execute(
                "update job set "
                "state=%s,completed_at=clock_timestamp(),claim_token=null,lease_expires_at=null,"
                "claimed_by=null,failure_class=%s,last_error=null where job_id=%s",
                (
                    "done" if ready else "failed",
                    None if ready else document["refusal"]["code"],
                    claimed.job_id,
                ),
            )
            self.connection.execute("select kind_draft_forget_input(%s)", (claimed.draft_id,))

    def publish(
        self,
        claimed: ClaimedKindDraft,
        kind: KindDocument,
        report: Mapping[str, Any],
        *,
        calls: list,
        model_id: str | None,
    ) -> dict:
        with self.connection.transaction():
            self.require_claim(claimed)
            self.connection.execute(
                "select set_config('exulanica.kind_draft_claim',%s,true)",
                (str(claimed.claim_token),),
            )
            kept = WorkspaceKinds(self.connection, self.workspace_id).append(
                kind, report, created_by=claimed.actor
            )
            self.connection.execute("select set_config('exulanica.kind_draft_claim','',true)")
            self.finish(
                claimed,
                dict(
                    state="ready",
                    kind=kept.kind.kind,
                    version=kept.kind.version,
                    kind_sha256=kept.kind.sha256,
                    calls=calls,
                    model_id=model_id,
                    refusal=None,
                ),
            )
            row = self.get(claimed.actor, claimed.draft_id)
            assert row is not None
            return row

    def expire(self) -> None:
        """Discard ended content beyond retention; workers terminalize overdue claims."""
        # The pruning function owns its workspace lock. Do not call it on every idle tick when
        # there is no content to discard; a later arrival is safely picked up on the next pass.
        pending = self.connection.execute(
            "select exists(select 1 from kind_draft_input i "
            "join kind_draft_start s using(workspace_id,draft_id) join job j using(job_id) "
            "where i.workspace_id=%s and j.state in ('done','failed','cancelled')) "
            "or exists(select 1 from kind_draft_attempt a "
            "join kind_draft_start s using(workspace_id,draft_id) join job j using(job_id) "
            "where a.workspace_id=%s and j.completed_at<statement_timestamp()-interval '1 hour') "
            "or exists(select 1 from kind_draft_outcome o where o.workspace_id=%s "
            "and o.completed_at<statement_timestamp()-interval '1 hour') as pending",
            (self.workspace_id, self.workspace_id, self.workspace_id),
        ).fetchone()["pending"]
        if pending:
            self.connection.execute("select kind_draft_prune()")
