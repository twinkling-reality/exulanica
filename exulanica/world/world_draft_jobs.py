"""Durable identities and fenced records for the normal world-drafting authority."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world import draft_admission
from exulanica.world.model_probe_contract import seal
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.world_draft_contract import validate_definition

TABLES = (
    "world_draft_start",
    "world_draft_request",
    "world_draft_input",
    "world_draft_bound",
    "world_draft_bound_closed",
    "world_draft_progress",
    "world_draft_attempt",
    "world_draft_outcome",
)


class WorldDraftRefused(ValueError):
    def __init__(self, code: str, retry_after_seconds: int | None = None) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


@dataclass(frozen=True)
class ClaimedDraft:
    workspace_id: uuid.UUID
    draft_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    actor: uuid.UUID
    world_id: str
    description: str
    definition: Mapping[str, Any]
    recovery: bool
    guest: bool


class WorldDraftRepository:
    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection, self.workspace_id = connection, workspace_id

    def _live(self) -> None:
        lock_workspace(self.connection, self.workspace_id)
        if self.connection.execute(
            "select 1 from tombstone where workspace_id=%s and scope::text='workspace'",
            (self.workspace_id,),
        ).fetchone():
            raise WorldDraftRefused("workspace_erased")

    def by_request(self, actor: uuid.UUID, request_id: uuid.UUID) -> dict | None:
        return self.connection.execute(
            "select * from world_draft_start where workspace_id=%s "
            "and actor_id=%s and request_id=%s",
            (self.workspace_id, actor, request_id),
        ).fetchone()

    def get(self, actor: uuid.UUID, draft_id: uuid.UUID) -> dict:
        row = self.connection.execute(
            "select s.*,j.state,j.attempts,j.failure_class, "
            "r.terms_sha256,r.document as definition, "
            # A draft that made its world keeps its sentence with it (0222) once its input is gone.
            "coalesce(i.description, m.sentence) as description, o.document as outcome, "
            "(select p.document from world_draft_progress p where p.workspace_id=s.workspace_id "
            "and p.draft_id=s.draft_id order by event_seq desc limit 1) as progress "
            "from world_draft_start s join world_draft_request r using(workspace_id,draft_id) "
            "left join world_draft_input i using(workspace_id,draft_id) "
            "left join world_made_from m using(workspace_id,draft_id) "
            "left join world_draft_outcome o using(workspace_id,draft_id) "
            "join job j on j.job_id=s.job_id "
            "where s.workspace_id=%s and s.actor_id=%s and s.draft_id=%s",
            (self.workspace_id, actor, draft_id),
        ).fetchone()
        if row is None:
            raise WorldDraftRefused("world_draft_unknown")
        return row

    def allowance(self, actor: uuid.UUID, maximum: int) -> dict:
        return draft_admission.allowance(self.connection, self.workspace_id, actor, maximum)

    def submit(
        self,
        *,
        actor: uuid.UUID,
        request_id: uuid.UUID,
        description: str,
        terms_sha256: str,
        definition: Mapping[str, Any],
        guest: bool,
        starts_maximum: int,
        workspace_maximum: int = 1,
    ) -> uuid.UUID:
        validate_definition(definition)
        with self.connection.transaction():
            self._live()
            prior = self.by_request(actor, request_id)
            if prior is not None:
                row = self.get(actor, prior["draft_id"])
                if row["terms_sha256"] != terms_sha256:
                    raise WorldDraftRefused("world_draft_key_reused")
                return prior["draft_id"]
            allowance = self.allowance(actor, starts_maximum)
            if allowance["running_count"] >= workspace_maximum:
                raise WorldDraftRefused("kind_draft_busy")
            if not allowance["left"]:
                raise WorldDraftRefused("kind_draft_limit")
            draft_id = uuid.uuid5(self.workspace_id, f"world-draft|{actor}|{request_id}")
            job_id = uuid.uuid4()
            world_id = f"world:generated:{draft_id}"
            self.connection.execute(
                "insert into job(job_id,workspace_id,kind,payload,run_after) "
                "values(%s,%s,'world_draft',%s,'9999-01-01')",
                (job_id, self.workspace_id, Jsonb(dict(draft_id=str(draft_id), world_id=world_id))),
            )
            draft_admission.bind(self.connection, actor, starts_maximum, workspace_maximum)
            try:
                with self.connection.transaction():
                    self.connection.execute(
                        "insert into world_draft_start "
                        "(workspace_id,draft_id,request_id,actor_id,job_id,world_id,guest) "
                        "values(%s,%s,%s,%s,%s,%s,%s)",
                        (self.workspace_id, draft_id, request_id, actor, job_id, world_id, guest),
                    )
            except psycopg.errors.RaiseException as failure:
                refused = draft_admission.refusal(failure)
                if refused is not None:
                    raise WorldDraftRefused(*refused) from failure
                raise
            self.connection.execute(
                "insert into world_draft_request "
                "(workspace_id,draft_id,terms_sha256,document) values(%s,%s,%s,%s)",
                (self.workspace_id, draft_id, terms_sha256, Jsonb(dict(definition))),
            )
            self.connection.execute(
                "insert into world_draft_input "
                "(workspace_id,draft_id,description) values(%s,%s,%s)",
                (self.workspace_id, draft_id, description),
            )
            return draft_id

    def attach_bound(
        self, actor: uuid.UUID, draft_id: uuid.UUID, provider: str, bound_id: uuid.UUID
    ) -> None:
        with self.connection.transaction():
            self._live()
            self.get(actor, draft_id)
            prior = self.connection.execute(
                "select bound_id from world_draft_bound "
                "where workspace_id=%s and draft_id=%s and provider=%s",
                (self.workspace_id, draft_id, provider),
            ).fetchone()
            if prior is not None:
                if prior["bound_id"] != bound_id:
                    raise WorldDraftRefused("world_draft_key_reused")
                return
            self.connection.execute(
                "insert into world_draft_bound values(%s,%s,%s,%s)",
                (self.workspace_id, draft_id, provider, bound_id),
            )

    def end_unstarted(self, actor: uuid.UUID, draft_id: uuid.UUID, code: str) -> None:
        with self.connection.transaction():
            self._live()
            row = self.get(actor, draft_id)
            if row["state"] != "queued":
                return
            token = uuid.uuid4()
            self.connection.execute(
                "update job set state='running',claim_token=%s,"
                "lease_expires_at=now()+interval '1 minute' where job_id=%s",
                (token, row["job_id"]),
            )
            claimed = ClaimedDraft(
                self.workspace_id,
                draft_id,
                row["job_id"],
                token,
                actor,
                row["world_id"],
                row["description"] or "",
                row["definition"],
                False,
                row["guest"],
            )
            self.finish(
                claimed,
                dict(
                    profile="exulanica.world-draft-result/v1",
                    state="refused",
                    entry_id=None,
                    calls=[],
                    refusal={"code": code, "detail": "The draft was refused before work."},
                ),
            )

    def bounds(self, draft_id: uuid.UUID) -> dict[str, uuid.UUID]:
        return {
            r["provider"]: r["bound_id"]
            for r in self.connection.execute(
                "select provider,bound_id from world_draft_bound "
                "where workspace_id=%s and draft_id=%s",
                (self.workspace_id, draft_id),
            ).fetchall()
        }

    def enqueue(self, actor: uuid.UUID, draft_id: uuid.UUID) -> None:
        with self.connection.transaction():
            self._live()
            row = self.get(actor, draft_id)
            wanted = {p["provider"] for p in row["definition"]["quote"]["providers"]}
            if wanted != set(self.bounds(draft_id)):
                raise WorldDraftRefused("world_draft_bounds_missing")
            self.connection.execute(
                "update job set run_after=now() where workspace_id=%s "
                "and job_id=%s and state='queued'",
                (self.workspace_id, row["job_id"]),
            )

    def funding_due(self) -> list[dict]:
        return self.connection.execute(
            "select s.actor_id,s.draft_id from world_draft_start s "
            "join job j on j.job_id=s.job_id where s.workspace_id=%s "
            "and j.state='queued' and j.run_after>now()+interval '1 day'",
            (self.workspace_id,),
        ).fetchall()

    def _claimable(self, *, lock: bool = False) -> dict | None:
        return self.connection.execute(
            "select s.*,r.document,i.description,j.attempts "
            "from world_draft_start s join world_draft_request r using(workspace_id,draft_id) "
            "join world_draft_input i using(workspace_id,draft_id) "
            "join job j on j.job_id=s.job_id "
            "where s.workspace_id=%s and j.kind='world_draft' and "
            "((j.state='queued' and j.run_after<=now()) or "
            "(j.state='running' and j.lease_expires_at<now())) "
            "order by s.started_at " + ("for update of j skip locked " if lock else "") + "limit 1",
            (self.workspace_id,),
        ).fetchone()

    def claim(self) -> ClaimedDraft | None:
        with self.connection.transaction():
            # An idle poll is an observation, not a workspace mutation: it takes no workspace
            # lock, so a deletion written meanwhile is not refused "workspace in use" (migration
            # 0137), as the kind draft queue holds. A positive observation is only a hint:
            # preserve workspace-before-job lock order and reread under that fence.
            if self._claimable() is None:
                return None
            self._live()
            row = self._claimable(lock=True)
            if row is None:
                return None
            token = uuid.uuid4()
            self.connection.execute(
                "update job set state='running',claim_token=%s,claimed_by=%s, "
                "claimed_at=now(),attempts=attempts+1,"
                "lease_expires_at=now()+%s*interval '1 second' "
                "where job_id=%s",
                (token, "world-draft-worker", row["document"]["deadline_seconds"], row["job_id"]),
            )
            return ClaimedDraft(
                self.workspace_id,
                row["draft_id"],
                row["job_id"],
                token,
                row["actor_id"],
                row["world_id"],
                row["description"],
                row["document"],
                row["attempts"] > 0,
                row["guest"],
            )

    def holds(self, claimed: ClaimedDraft) -> bool:
        self._live()
        row = self.connection.execute(
            "select state,claim_token,lease_expires_at>clock_timestamp() as live "
            "from job where workspace_id=%s and job_id=%s for update",
            (self.workspace_id, claimed.job_id),
        ).fetchone()
        return bool(
            row
            and row["state"] == "running"
            and row["claim_token"] == claimed.claim_token
            and row["live"]
        )

    def require_claim(self, claimed: ClaimedDraft) -> None:
        if not self.holds(claimed):
            raise WorldDraftRefused("world_draft_lease_lost")

    def progress(self, claimed: ClaimedDraft, document: Mapping[str, Any]) -> None:
        self._append("world_draft_progress", claimed, document)

    def attempt(self, claimed: ClaimedDraft, document: Mapping[str, Any]) -> None:
        self._append("world_draft_attempt", claimed, document)

    def _append(self, table: str, claimed: ClaimedDraft, document: Mapping[str, Any]) -> None:
        # Only these two authority-owned table names reach statement construction.
        if table not in {"world_draft_progress", "world_draft_attempt"}:
            raise ValueError(table)
        from psycopg import sql

        with self.connection.transaction():
            self.require_claim(claimed)
            query = sql.SQL(
                "insert into {}(workspace_id,draft_id,event_seq,claim_token,document) "
                "select %s,%s,coalesce(max(event_seq),0)+1,%s,%s from {} "
                "where workspace_id=%s and draft_id=%s"
            ).format(sql.Identifier(table), sql.Identifier(table))
            self.connection.execute(
                query,
                (
                    self.workspace_id,
                    claimed.draft_id,
                    claimed.claim_token,
                    Jsonb(dict(document)),
                    self.workspace_id,
                    claimed.draft_id,
                ),
            )

    def finish(self, claimed: ClaimedDraft, document: Mapping[str, Any]) -> None:
        with self.connection.transaction():
            self.require_claim(claimed)
            sealed = seal(dict(document))
            self.connection.execute(
                "insert into world_draft_outcome values(%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    claimed.draft_id,
                    claimed.claim_token,
                    Jsonb(sealed),
                    sealed["document_sha256"],
                ),
            )
            ready = document["state"] == "ready"
            self.connection.execute(
                "update job set state=%s,completed_at=now(),claim_token=null, "
                "lease_expires_at=null,claimed_by=null,failure_class=%s, "
                "last_error='world_draft_bound_close_due' where job_id=%s",
                (
                    "done" if ready else "failed",
                    None if ready else document["refusal"]["code"],
                    claimed.job_id,
                ),
            )
            # A draft that made its world keeps its sentence with that world; then the draft's
            # input is forgotten, as for every draft that ends.
            self.connection.execute("select world_draft_keep_sentence(%s)", (claimed.draft_id,))
            self.connection.execute("select world_draft_forget_input(%s)", (claimed.draft_id,))

    def accounting(self, actor: uuid.UUID, draft_id: uuid.UUID) -> dict[str, Any]:
        """The actor's native financial records, including unknown and held exposure."""
        from decimal import Decimal

        self.get(actor, draft_id)
        rows = self.connection.execute(
            "select r.provider,r.model_id,r.role,r.state,r.reserved_usd,r.settled_usd,"
            "r.cost_basis,r.prompt_tokens,r.completion_tokens from spending_reservation r "
            "join world_draft_bound b on b.workspace_id=r.workspace_id and b.bound_id=r.bound_id "
            "where b.workspace_id=%s and b.draft_id=%s order by r.admitted_at,r.reservation_id",
            (self.workspace_id, draft_id),
        ).fetchall()
        reported = held = unknown = reconciled = Decimal(0)
        attempts = []
        for row in rows:
            if row["state"] == "admitted":
                held += row["reserved_usd"]
            elif row["state"] in ("dispatched", "unknown"):
                unknown += row["reserved_usd"]
            elif row["cost_basis"] == "reported":
                reported += row["settled_usd"] or Decimal(0)
            elif row["cost_basis"] == "reconciled":
                reconciled += row["settled_usd"] or Decimal(0)
            attempts.append(
                {
                    key: (str(value) if isinstance(value, Decimal) else value)
                    for key, value in row.items()
                }
            )
        return dict(
            profile="exulanica.world-draft-accounting/v1",
            reported_usd=str(reported),
            held_usd=str(held),
            unknown_liability_usd=str(unknown),
            reconciled_usd=str(reconciled),
            total_known=not (held or unknown),
            attempts=attempts,
        )

    def close_due(self) -> list[dict]:
        return self.connection.execute(
            "select b.* from world_draft_bound b "
            "join world_draft_start s using(workspace_id,draft_id) "
            "left join world_draft_bound_closed c using(workspace_id,draft_id,provider) "
            "join job j on j.job_id=s.job_id "
            "where b.workspace_id=%s and j.state in ('done','failed','cancelled') "
            "and c.provider is null",
            (self.workspace_id,),
        ).fetchall()

    def bound_closed(self, draft_id: uuid.UUID, provider: str) -> None:
        self.connection.execute(
            "insert into world_draft_bound_closed values(%s,%s,%s) on conflict do nothing",
            (self.workspace_id, draft_id, provider),
        )


def terms_sha256(
    description: str, quoted: Mapping[str, Any] | None, maximum_usd: str | None
) -> str:
    import hashlib

    return hashlib.sha256(
        canonical_json(dict(description=description, quote=quoted, maximum_usd=maximum_usd))
    ).hexdigest()
