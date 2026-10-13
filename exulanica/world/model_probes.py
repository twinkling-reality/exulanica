"""Workspace probe records and the existing leased job queue.

Transactions never enclose inference. A receipt is appended only by the current lease holder;
every completion is recomputed from stored receipts. Removing or adding the model again makes
an old probe stale. Financial admission belongs to the existing durable spending authority.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.model_probe_contract import (
    OUTCOME_PROFILE,
    replay_outcome,
    seal,
    validate_definition,
)
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.workspace_models import (
    PROBE_NOT_FINISHED,
    PROBED,
    WorkspaceModelRepository,
)

JOB_KIND: Final = "model_probe"
LEASE_SECONDS: Final = 900
MAXIMUM_CLAIMS: Final = 2


class ModelProbeRefused(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ClaimedProbe:
    workspace_id: uuid.UUID
    probe_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    definition: Mapping[str, Any]
    bound_id: uuid.UUID


class ModelProbeRepository:
    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def _live(self) -> None:
        lock_workspace(self.connection, self.workspace_id)
        if self.connection.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace'",
            (self.workspace_id,),
        ).fetchone():
            raise ModelProbeRefused("workspace_erased")

    def by_request(self, request_id: uuid.UUID) -> dict | None:
        return self.connection.execute(
            "select * from model_probe where workspace_id=%s and request_id=%s",
            (self.workspace_id, request_id),
        ).fetchone()

    def get(self, probe_id: uuid.UUID) -> dict:
        row = self.connection.execute(
            "select p.*,j.state,j.attempts,j.failure_class from model_probe p "
            "join job j on j.job_id=p.job_id and j.workspace_id=p.workspace_id "
            "where p.workspace_id=%s and p.probe_id=%s",
            (self.workspace_id, probe_id),
        ).fetchone()
        if row is None:
            raise ModelProbeRefused("model_probe_not_found")
        return row

    def current(self, definition: Mapping[str, Any]) -> bool:
        state = WorkspaceModelRepository(self.connection, self.workspace_id).state(
            definition["provider"], definition["model_id"]
        )
        return (
            state is not None
            and not state.removed
            and state.added_seq == definition["added_seq"]
            and state.added_sha256 == definition["added_sha256"]
        )

    def prepare(
        self, definition: Mapping[str, Any], *, request_id: uuid.UUID, actor: uuid.UUID
    ) -> uuid.UUID:
        validate_definition(definition)
        with self.connection.transaction():
            self._live()
            prior = self.by_request(request_id)
            if prior is not None:
                if (
                    prior["provider"] != definition["provider"]
                    or prior["model_id"] != definition["model_id"]
                    or prior["recorded_by"] != actor
                ):
                    raise ModelProbeRefused("model_probe_key_reused")
                return prior["probe_id"]
            if not self.current(definition):
                raise ModelProbeRefused("model_probe_stale")
            probe_id, job_id = uuid.uuid4(), uuid.uuid4()
            self.connection.execute(
                "insert into job(job_id,workspace_id,kind,payload,state,run_after) "
                "values(%s,%s,%s,%s,'queued','9999-01-01')",
                (job_id, self.workspace_id, JOB_KIND, Jsonb({"probe_id": str(probe_id)})),
            )
            self.connection.execute(
                "insert into "
                "model_probe(workspace_id,probe_id,job_id,request_id,recorded_by,provider,model_id,"
                "added_seq,added_sha256,definition,definition_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    probe_id,
                    job_id,
                    request_id,
                    actor,
                    definition["provider"],
                    definition["model_id"],
                    definition["added_seq"],
                    definition["added_sha256"],
                    Jsonb(dict(definition)),
                    definition["document_sha256"],
                ),
            )
            return probe_id

    def start_record(self, probe_id: uuid.UUID) -> dict | None:
        return self.connection.execute(
            "select * from model_probe_start where workspace_id=%s and probe_id=%s",
            (self.workspace_id, probe_id),
        ).fetchone()

    def start(
        self,
        probe_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        actor: uuid.UUID,
        definition_sha256: str,
        bound_id: uuid.UUID,
        ceiling_usd: Decimal,
    ) -> None:
        with self.connection.transaction():
            self._live()
            row = self.get(probe_id)
            self.connection.execute(
                "select job_id from job where job_id=%s for update", (row["job_id"],)
            )
            prior = self.start_record(probe_id)
            if prior is not None:
                if (
                    prior["request_id"] != request_id
                    or prior["recorded_by"] != actor
                    or prior["definition_sha256"] != definition_sha256
                    or prior["bound_id"] != bound_id
                    or prior["ceiling_usd"] != ceiling_usd
                ):
                    raise ModelProbeRefused("model_probe_key_reused")
                return
            if row["definition_sha256"] != definition_sha256:
                raise ModelProbeRefused("model_probe_definition_changed")
            if not self.current(row["definition"]):
                raise ModelProbeRefused("model_probe_stale")
            if row["state"] != "queued":
                raise ModelProbeRefused("model_probe_terminal")
            validate_definition(row["definition"])
            ceiling = Decimal(row["definition"]["operation_estimate"]["ceiling_usd"])
            if not ceiling_usd.is_finite() or ceiling_usd < ceiling or not 0 < ceiling_usd <= 1000:
                raise ModelProbeRefused("model_probe_bound_too_small")
            self.connection.execute(
                "insert into "
                "model_probe_start(workspace_id,probe_id,request_id,recorded_by,bound_id,ceiling_usd,"
                "definition_sha256) values(%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    probe_id,
                    request_id,
                    actor,
                    bound_id,
                    ceiling_usd,
                    definition_sha256,
                ),
            )
            self.connection.execute(
                "update job set run_after=now() where job_id=%s", (row["job_id"],)
            )

    def receipts(self, probe_id: uuid.UUID) -> list[dict]:
        return [
            row["document"]
            for row in self.connection.execute(
                "select document from model_probe_receipt where "
                "workspace_id=%s and probe_id=%s order by case_seq",
                (self.workspace_id, probe_id),
            ).fetchall()
        ]

    def claim(self, holder: str) -> ClaimedProbe | None:
        with self.connection.transaction():
            self._live()
            # A prepared quote is not due until a start exists. An expired lease may resume;
            # spending keys still identify the original case, never a new paid retry.
            row = self.connection.execute(
                "select p.*,s.bound_id from job j join model_probe p on p.job_id=j.job_id "
                "and p.workspace_id=j.workspace_id join model_probe_start s "
                "on s.probe_id=p.probe_id "
                "and s.workspace_id=p.workspace_id where j.workspace_id=%s and j.kind=%s "
                "and ((j.state='queued' and j.run_after<=now()) or "
                "(j.state='running' and j.lease_expires_at<now())) and j.attempts<%s "
                "order by j.created_at,j.job_id for update of j skip locked limit 1",
                (self.workspace_id, JOB_KIND, MAXIMUM_CLAIMS),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4()
            self.connection.execute(
                "update job set state='running',claimed_by=%s,claimed_at=now(),claim_token=%s,"
                "lease_expires_at=now()+%s*interval '1 second',attempts=attempts+1 where job_id=%s",
                (holder, token, LEASE_SECONDS, row["job_id"]),
            )
            return ClaimedProbe(
                self.workspace_id,
                row["probe_id"],
                row["job_id"],
                token,
                row["definition"],
                row["bound_id"],
            )

    def holds(self, claimed: ClaimedProbe) -> bool:
        row = self.connection.execute(
            "select state,claim_token,lease_expires_at>now() as live from job "
            "where workspace_id=%s and job_id=%s for update",
            (self.workspace_id, claimed.job_id),
        ).fetchone()
        return bool(
            row
            and row["state"] == "running"
            and row["claim_token"] == claimed.claim_token
            and row["live"]
        )

    def before_case(self, claimed: ClaimedProbe) -> str | None:
        """Renew the current lease, then release every lock before a model is asked."""
        with self.connection.transaction():
            self._live()
            if not self.holds(claimed):
                return "model_probe_lease_lost"
            if not self.current(claimed.definition):
                return "model_probe_stale"
            self.connection.execute(
                "update job set lease_expires_at=now()+%s*interval '1 second' where job_id=%s",
                (LEASE_SECONDS, claimed.job_id),
            )
        return None

    def append(self, claimed: ClaimedProbe, document: Mapping[str, Any]) -> bool:
        with self.connection.transaction():
            self._live()
            if not self.holds(claimed):
                return False
            existing = self.receipts(claimed.probe_id)
            replay_outcome(claimed.definition, [*existing, document])
            self.connection.execute(
                "insert into "
                "model_probe_receipt(workspace_id,probe_id,case_seq,document,document_sha256) "
                "values(%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    claimed.probe_id,
                    document["request"]["case_seq"],
                    Jsonb(dict(document)),
                    document["document_sha256"],
                ),
            )
            return True

    def finish(self, claimed: ClaimedProbe, *, reason: str | None = None) -> bool:
        with self.connection.transaction():
            self._live()
            if not self.holds(claimed):
                return False
            row = self.get(claimed.probe_id)
            return self._finish(row, reason=reason)

    def _finish(self, row: dict, *, reason: str | None = None, cancelled: bool = False) -> bool:
        definition = row["definition"]
        # The same per-model lock as adding/removing: the verdict cannot race a new epoch.
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
            (
                str(self.workspace_id),
                f"{definition['provider']}|workspace-model|{definition['model_id']}",
            ),
        )
        receipts = self.receipts(row["probe_id"])
        try:
            outcome = replay_outcome(definition, receipts)
        except ValueError:
            # An upgraded role may no longer reconstruct the prepared bytes. Preserve evidence,
            # end the job, and publish no verdict instead of stranding the lease forever.
            reason = "model_probe_replay_unavailable"
            outcome = {
                "profile": OUTCOME_PROFILE,
                "definition_sha256": row["definition_sha256"],
                "receipt_sha256s": [r["document_sha256"] for r in receipts],
                "finished": False,
                "verified": False,
                "mechanisms": {},
            }
        current = self.current(definition)
        code = (
            "cancelled"
            if cancelled
            else "stale"
            if not current
            else "completed"
            if outcome["finished"] and reason is None
            else "not_finished"
        )
        # Interruptions retain receipts, but never a quality verdict.
        if code != "completed":
            outcome = {**outcome, "finished": False, "verified": False}
            for result in outcome["mechanisms"].values():
                result["answers"] = result["answers_lines"] = False
        outcome = seal({**outcome, "code": code, "reason": reason})
        self.connection.execute(
            "insert into "
            "model_probe_outcome(workspace_id,probe_id,code,document,document_sha256) "
            "values(%s,%s,%s,%s,%s)",
            (self.workspace_id, row["probe_id"], code, Jsonb(outcome), outcome["document_sha256"]),
        )
        if current:
            WorkspaceModelRepository(self.connection, self.workspace_id).record(
                definition["provider"],
                definition["model_id"],
                request_id=row["probe_id"],
                kind=PROBED if code == "completed" else PROBE_NOT_FINISHED,
                facts={
                    "profile": "exulanica.workspace-model-probe/v1",
                    "probe_id": str(row["probe_id"]),
                    "added_seq": definition["added_seq"],
                    "added_sha256": definition["added_sha256"],
                    "outcome_sha256": outcome["document_sha256"],
                    "verified": outcome["verified"],
                    "mechanisms": outcome["mechanisms"],
                },
                recorded_by=row["recorded_by"],
            )
        self.connection.execute(
            "update job set state=%s,completed_at=now(),claim_token=null,lease_expires_at=null,"
            "claimed_by=null,failure_class=%s,last_error=%s where job_id=%s",
            (
                "done" if code == "completed" else "cancelled" if code == "cancelled" else "failed",
                None if code == "completed" else code,
                "model_probe_bound_close_due" if self.start_record(row["probe_id"]) else reason,
                row["job_id"],
            ),
        )
        return True

    def sweep(self) -> int:
        """End jobs whose last allowed claim expired, preserving every durable receipt."""
        with self.connection.transaction():
            self._live()
            rows = self.connection.execute(
                "select p.* from job j join model_probe p on p.job_id=j.job_id "
                "and p.workspace_id=j.workspace_id where j.workspace_id=%s and j.kind=%s "
                "and j.state='running' and j.lease_expires_at<now() and j.attempts>=%s "
                "for update of j skip locked",
                (self.workspace_id, JOB_KIND, MAXIMUM_CLAIMS),
            ).fetchall()
            for row in rows:
                self._finish(row, reason="model_probe_claims_exhausted")
            return len(rows)

    def bound_close_due(self) -> list[dict]:
        return self.connection.execute(
            "select p.probe_id,s.bound_id from job j join model_probe p on p.job_id=j.job_id "
            "and p.workspace_id=j.workspace_id join model_probe_start s on s.probe_id=p.probe_id "
            "and s.workspace_id=p.workspace_id where j.workspace_id=%s and j.kind=%s "
            "and j.state in ('done','failed','cancelled') "
            "and j.last_error='model_probe_bound_close_due' "
            "order by j.completed_at limit 1",
            (self.workspace_id, JOB_KIND),
        ).fetchall()

    def bound_closed(self, probe_id: uuid.UUID) -> None:
        self.connection.execute(
            "update job set last_error=null where workspace_id=%s and job_id="
            "(select job_id from model_probe where workspace_id=%s and probe_id=%s) "
            "and state in ('done','failed','cancelled') "
            "and last_error='model_probe_bound_close_due'",
            (self.workspace_id, self.workspace_id, probe_id),
        )

    def cancel(self, probe_id: uuid.UUID) -> bool:
        with self.connection.transaction():
            self._live()
            row = self.get(probe_id)
            self.connection.execute(
                "select job_id from job where job_id=%s for update", (row["job_id"],)
            )
            row = self.get(probe_id)
            if row["state"] not in ("queued", "running"):
                return False
            return self._finish(row, reason="cancelled_by_owner", cancelled=True)

    def view(self, probe_id: uuid.UUID) -> dict:
        row = self.get(probe_id)
        start = self.start_record(probe_id)
        end = self.connection.execute(
            "select document from model_probe_outcome where workspace_id=%s and probe_id=%s",
            (self.workspace_id, probe_id),
        ).fetchone()
        return {
            "probe_id": str(probe_id),
            "state": "prepared" if row["state"] == "queued" and start is None else row["state"],
            "definition": row["definition"],
            "start": None
            if start is None
            else {
                "ceiling_usd": str(start["ceiling_usd"]),
                "bound_id": str(start["bound_id"]),
                "created_at": start["created_at"].isoformat(),
            },
            "receipts": self.receipts(probe_id),
            "outcome": None if end is None else end["document"],
            "execution_admitted": False,
        }
