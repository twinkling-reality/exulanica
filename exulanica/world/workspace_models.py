"""The models a workspace added to those that may decide for a being: an appended record.

The shipped manifest states the models every installation has. A workspace may add more of the
models its provider serves. What it knows of each is a row of ``workspace_model`` (migration
0193), one fact a row: the model was *added* (with what the provider stated of it and its price as
read that day), it was *probed* (the verdict of the product's own probe), a probe was *not
finished* (cut short, which is no verdict), or it was *removed*. Rows of one model are appended
in order and never changed; the newest is the model's state and the history stays.

What this module holds by construction:

*   **A fact follows the facts before it.** A model is probed only after it was added and while
    it is not removed; it is removed only while it is not already; it may be added again after
    it was removed, and added anew at any time, which is how a price that moved is recorded.
*   **A request records once.** The same request id asked again for the same model answers the
    row it recorded; with another fact it is refused by name.
*   **A verdict is only a verdict.** A cut probe records ``probe_not_finished`` and preserves
    the newest finished verdict of the same adding. A recorded ``verified`` figure is evidence
    to inspect, never an executable binding; execution reconstructs the complete probe.
*   **Removing is ordinary state.** It takes back no permission and no consent, so a restore
    carries nothing of it: whether a model's licence lets this product call it is the shipped
    catalog's class for its identifier (:mod:`exulanica.models.provider_catalog`), never a row.
*   **Nothing a person wrote.** The facts are a provider's statements, figures and digests.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world.society_planner import input_sha256

__all__ = [
    "ADDED",
    "KINDS",
    "MODEL_REFUSALS",
    "PROBED",
    "PROBE_NOT_FINISHED",
    "PROFILE",
    "REMOVED",
    "WorkspaceModel",
    "WorkspaceModelRefused",
    "WorkspaceModelRepository",
]

PROFILE: Final = "exulanica.workspace-model/v1"
ADDED: Final = "added"
PROBED: Final = "probed"
PROBE_NOT_FINISHED: Final = "probe_not_finished"
REMOVED: Final = "removed"
KINDS: Final = (ADDED, PROBED, PROBE_NOT_FINISHED, REMOVED)
MODEL_REFUSALS: Final[Mapping[str, str]] = {
    "model_not_added": "this workspace has not added the model, so there is nothing to try or "
    "to remove",
    "model_removed": "the model was removed from this workspace; add it again first",
    "model_key_reused": "this request id recorded another fact about this model",
    "model_probe_stale": "this probe belongs to a different adding of the model",
}


class WorkspaceModelRefused(Exception):
    """A fact about a model that cannot be recorded, by the code a route answers with."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.detail = MODEL_REFUSALS[code]
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class WorkspaceModel:
    """One model of a workspace as its newest fact leaves it, with what was read when it was last
    added and its newest finished verdict, where it has one."""

    provider: str
    model_id: str
    #: The newest fact: its kind, sequence, facts, digest, who recorded it and when.
    kind: str
    model_seq: int
    facts: Mapping[str, Any]
    document_sha256: str
    recorded_by: str
    recorded_at: str
    #: The facts of the newest ``added`` row, and of the newest ``probed`` row after it (None
    #: where the model was not tried since it was last added, or every try was cut short).
    added: Mapping[str, Any]
    verdict: Mapping[str, Any] | None

    added_seq: int = 0
    added_sha256: str = ""

    @property
    def removed(self) -> bool:
        return self.kind == REMOVED

    @property
    def verified(self) -> bool:
        """Whether the recorded finished verdict says it answered; no execution permission."""
        return (
            not self.removed and self.verdict is not None and self.verdict.get("verified") is True
        )

    def view(self) -> dict[str, Any]:
        """The model as a read serves it: no account's identifier is in it."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "state": self.kind,
            "model_seq": self.model_seq,
            "added_seq": self.added_seq,
            "added_sha256": self.added_sha256,
            "verified": self.verified,
            "added": dict(self.added),
            "verdict": None if self.verdict is None else dict(self.verdict),
            "recorded_at": self.recorded_at,
            "document_sha256": self.document_sha256,
        }


_COLUMNS: Final = (
    "provider,model_id,model_seq,request_id,kind,document,document_sha256,recorded_by,recorded_at"
)


class WorkspaceModelRepository:
    """One workspace's facts about the models it added, under the workspace's row security."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def _rows(self, provider: str, model_id: str) -> list[dict[str, Any]]:
        return self.connection.execute(
            f"select {_COLUMNS} from workspace_model where workspace_id=%s and provider=%s "
            "and model_id=%s order by model_seq",
            (self.workspace_id, provider, model_id),
        ).fetchall()

    def state(self, provider: str, model_id: str) -> WorkspaceModel | None:
        """The model as its newest fact leaves it, or None where the workspace never added it."""
        rows = self._rows(provider, model_id)
        return _state(rows) if rows else None

    def listing(self) -> list[WorkspaceModel]:
        """Every model the workspace has a fact about, in the order each was first added."""
        rows = self.connection.execute(
            f"select {_COLUMNS} from workspace_model where workspace_id=%s "
            "order by provider, model_id, model_seq",
            (self.workspace_id,),
        ).fetchall()
        by_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            by_model.setdefault((row["provider"], row["model_id"]), []).append(row)
        found = [_state(history) for history in by_model.values()]
        first = {
            (history[0]["provider"], history[0]["model_id"]): history[0]["recorded_at"]
            for history in by_model.values()
        }
        return sorted(
            found, key=lambda model: (first[(model.provider, model.model_id)], model.model_id)
        )

    def record(
        self,
        provider: str,
        model_id: str,
        *,
        request_id: uuid.UUID,
        kind: str,
        facts: Mapping[str, Any],
        recorded_by: uuid.UUID,
    ) -> WorkspaceModel:
        """Record one fact about a model, or answer the state the same request already left.

        Refused by name: ``model_not_added`` for a try or a removal of a model the workspace
        never added; ``model_removed`` for a try, or a second removal, of a removed one;
        ``model_key_reused`` for a request id that recorded another fact about this model."""
        if kind not in KINDS:
            raise ValueError(f"no such fact about a model: {kind!r}")
        facts = json.loads(canonical_json(facts))
        with self.connection.transaction():
            # The lock the insert's trigger takes, taken first: one writer a workspace and model
            # reads the key and the newest sequence at a time.
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (str(self.workspace_id), f"{provider}|workspace-model|{model_id}"),
            )
            rows = self._rows(provider, model_id)
            for index, row in enumerate(rows):
                if row["request_id"] == request_id:
                    same = (
                        row["kind"] == kind
                        and dict(row["document"]["facts"]) == dict(facts)
                        and row["recorded_by"] == recorded_by
                    )
                    if not same:
                        raise WorkspaceModelRefused("model_key_reused")
                    return _state(rows[: index + 1])
            newest = rows[-1]["kind"] if rows else None
            if kind != ADDED:
                if newest is None:
                    raise WorkspaceModelRefused("model_not_added")
                if newest == REMOVED:
                    raise WorkspaceModelRefused("model_removed")
            if kind in (PROBED, PROBE_NOT_FINISHED) and "added_seq" in facts:
                added = next(row for row in reversed(rows) if row["kind"] == ADDED)
                if (
                    facts["added_seq"] != added["model_seq"]
                    or facts.get("added_sha256") != added["document_sha256"]
                ):
                    raise WorkspaceModelRefused("model_probe_stale")
            sequence = len(rows) + 1
            document: dict[str, Any] = {
                "profile": PROFILE,
                "provider": provider,
                "model_id": model_id,
                "model_seq": sequence,
                "request_id": str(request_id),
                "kind": kind,
                "facts": dict(facts),
                "recorded_by": str(recorded_by),
            }
            document["document_sha256"] = input_sha256(document)
            self.connection.execute(
                "insert into workspace_model(workspace_id,provider,model_id,model_seq,request_id,"
                "kind,document,document_sha256,recorded_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    provider,
                    model_id,
                    sequence,
                    request_id,
                    kind,
                    Jsonb(document),
                    document["document_sha256"],
                    recorded_by,
                ),
            )
            return _state(self._rows(provider, model_id))


def _state(rows: list[dict[str, Any]]) -> WorkspaceModel:
    """A model's state from its whole history, oldest first."""
    newest = rows[-1]
    added_at = max(index for index, row in enumerate(rows) if row["kind"] == ADDED)
    added = rows[added_at]
    verdicts = [
        row
        for row in rows[added_at + 1 :]
        if row["kind"] == PROBED
        and (
            "added_seq" not in row["document"]["facts"]
            or (
                row["document"]["facts"]["added_seq"] == added["model_seq"]
                and row["document"]["facts"].get("added_sha256") == added["document_sha256"]
            )
        )
    ]
    return WorkspaceModel(
        provider=newest["provider"],
        model_id=newest["model_id"],
        kind=newest["kind"],
        model_seq=int(newest["model_seq"]),
        facts=dict(newest["document"]["facts"]),
        document_sha256=newest["document_sha256"],
        recorded_by=str(newest["recorded_by"]),
        recorded_at=newest["recorded_at"].isoformat(),
        added=dict(added["document"]["facts"]),
        added_seq=int(added["model_seq"]),
        added_sha256=added["document_sha256"],
        verdict=dict(verdicts[-1]["document"]["facts"]) if verdicts else None,
    )
