"""Private cleanup adapters, invoked only after separately verified clone preflight.

No resource constructors or launcher. Pause uses an explicit outer transaction around the
repository's own transaction/savepoint, then verifies on a distinct fresh session. Revoke
uses the operator's committed operation and checks its witness under the existing lock order.
Neither operation settles, releases, reconciles, or deletes provider liability.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from exulanica.spending.status import read_workspace_status
from exulanica.world.society import StaleSocietyState
from exulanica.world.society_control_repository import SocietyControlRepository
from pilot_guard import PilotStop

# Administrative read only; no new SQL function or production access privilege.
_GRANT = """
select g.authority_id, g.workspace_id, g.grant_id, g.parent_grant_id,
       g.ceiling_usd, g.max_calls, a.provider, a.witnessed,
       s.sequence, encode(s.head_sha256, 'hex') as head_sha256, s.witness_directory_id,
       exists(select 1 from spending_grant_revocation r
              where r.workspace_id=g.workspace_id and r.grant_id=g.grant_id) as revoked
  from spending_grant g join spending_authority a using(authority_id)
  join spending_authority_state s using(authority_id)
 where g.workspace_id=%s and g.grant_id=%s and g.authority_id=%s
"""


def _endpoint(url: Any) -> Any:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port, parsed.path, parsed.query


class CleanupAdapters:
    def __init__(
        self: Any,
        *,
        database: Any,
        operator: Any,
        binding: Any,
        identity: Any,
        actor: Any,
        grant_id: Any,
        repository_factory: Any=SocietyControlRepository,
        status_reader: Any=read_workspace_status,
    ) -> None:
        self.database, self.operator = database, operator
        self.binding, self.identity, self.actor, self.grant_id = binding, identity, actor, grant_id
        self.repository_factory, self.status_reader = repository_factory, status_reader

    def _bound(self: Any) -> Any:
        self.binding.validate()
        if self.database.url != self.binding.database_url:
            raise PilotStop("cleanup_database_differs")
        if _endpoint(self.operator.database.url) != _endpoint(self.binding.database_url):
            raise PilotStop("cleanup_operator_database_differs")
        if (
            self.operator.witness is None
            or Path(self.operator.witness.directory).resolve()
            != self.binding.witness_path.resolve()
        ):
            raise PilotStop("cleanup_witness_differs")

    def _repository(self: Any, connection: Any) -> Any:
        return self.repository_factory(
            connection, self.identity.workspace_id, world_id=self.identity.world_id
        )

    def _society(self: Any, row: Any) -> Any:
        if row.get("society_id") != str(self.identity.society_id):
            raise PilotStop("cleanup_society_differs")

    def pause(self: Any, *, retries: Any=3) -> Any:
        self._bound()
        if type(retries) is not int or not 1 <= retries <= 3:
            raise PilotStop("cleanup_retry_bound_invalid")
        for attempt in range(retries):
            try:
                with self.database.session(self.identity.workspace_id) as connection:  # noqa: SIM117, explicit commit scope
                    # Database.session is autocommit. This explicit outer unit owns commit;
                    # configure's transaction is nested and cannot confirm this commit early.
                    with connection.transaction():
                        repository = self._repository(connection)
                        prior = repository.read(self.identity.version_id)
                        self._society(prior)
                        repository.configure(
                            self.identity.version_id,
                            actor=self.actor,
                            base_revision=prior["revision"],
                            mode="paused",
                            speed=1,
                        )
                break
            except StaleSocietyState:
                if attempt + 1 == retries:
                    raise
        # No connection/transaction is reused for the committed readback.
        with self.database.session(self.identity.workspace_id) as fresh:
            after = self._repository(fresh).read(self.identity.version_id, lock=False)
            self._society(after)
            if after["mode"] != "paused" or after["lease_expires_at"] is not None:
                raise PilotStop("cleanup_pause_not_verified")
        return {
            "mode": "paused",
            "lease_expires_at": None,
            "revision": after["revision"],
            "workspace_id": str(self.identity.workspace_id),
            "world_id": self.identity.world_id,
            "version_id": str(self.identity.version_id),
            "society_id": str(self.identity.society_id),
            "commit_verified": True,
        }

    def _grant(self: Any, connection: Any) -> Any:
        row = connection.execute(
            _GRANT, (self.identity.workspace_id, self.grant_id, self.binding.authority_id)
        ).fetchone()
        if (
            row is None
            or (row["authority_id"], row["workspace_id"], row["grant_id"])
            != (self.binding.authority_id, self.identity.workspace_id, self.grant_id)
            or row["parent_grant_id"] is not None
            or row["provider"] != self.identity.provider
            or row["witnessed"] is not True
        ):
            raise PilotStop("cleanup_grant_differs")
        if (
            row["ceiling_usd"] != self.binding.workspace_allowance_usd
            or row["max_calls"] != self.binding.workspace_allowance_calls
        ):
            raise PilotStop("cleanup_allowance_differs")
        return row

    def revoke(self: Any) -> Any:
        self._bound()
        with self.operator.database.session(self.identity.workspace_id) as connection:
            self._grant(connection)
        # Production operator locks witness before its database transaction and commits before
        # returning. Do not repeat automatically on error or unknown post-commit confirmation.
        outcome = self.operator.revoke(
            self.binding.authority_id,
            workspace_id=self.identity.workspace_id,
            grant_id=self.grant_id,
            operator="duck-pilot-cleanup",
            reason="Bounded isolated pilot stopped",
        )
        if outcome not in {"revoked", "already"}:
            raise PilotStop("cleanup_revoke_outcome_unknown")
        with self.operator.witness.hold(self.binding.authority_id) as held:
            document = held.document
            with self.operator.database.session(self.identity.workspace_id) as fresh:  # noqa: SIM117 (explicit commit scope)
                with fresh.transaction():
                    row = self._grant(fresh)
                    status = self.status_reader(
                        fresh, self.identity.workspace_id, providers=(self.identity.provider,)
                    )
                    key = f"grant:{self.identity.workspace_id}/{self.grant_id}"
                    if (
                        not row["revoked"]
                        or not isinstance(document, dict)
                        or (
                            document.get("status") != "live"
                            or document.get("confirmed") is not True
                            or document.get("authority_id") != str(self.binding.authority_id)
                            or document.get("directory_id") != str(row["witness_directory_id"])
                            or document.get("sequence") != row["sequence"]
                            or document.get("head_sha256") != row["head_sha256"]
                            or key not in document.get("revoked", ())
                        )
                    ):
                        raise PilotStop("cleanup_witness_not_confirmed")
                    entries = status.get("providers", [])
                    if (
                        status.get("workspace_id") != str(self.identity.workspace_id)
                        or len(entries) != 1
                    ):
                        raise PilotStop("cleanup_status_differs")
                    entry = entries[0]
                    if (
                        entry.get("provider") != self.identity.provider
                        or entry.get("grant", {}).get("grant_id") != str(self.grant_id)
                        or entry["grant"].get("state") != "revoked"
                    ):
                        raise PilotStop("cleanup_revocation_not_verified")
        return {
            "revoked": True,
            "scope": "workspace_grant",
            "authority_id": str(self.binding.authority_id),
            "workspace_id": str(self.identity.workspace_id),
            "grant_id": str(self.grant_id),
            "witness_confirmed": True,
            "witness_sequence": row["sequence"],
            "witness_head_sha256": row["head_sha256"],
            "status": entry,
            "liability_reconciliation_required": bool(
                entry["unresolved"]["count"] or Decimal(entry["in_flight_usd"]) > 0
            ),
        }
