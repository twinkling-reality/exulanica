"""Writing a claim, under exactly one of the four provenance classes.

This is the one place assertions are written. It was inside the ingest repository, which was
fine while ingest was the only writer; it is not fine now that the identity path writes the
``kind='user'`` naming assertion that ``entity.display_name`` depends on. A second
implementation of "insert an assertion" would be a second place for the support-span rule, the
allows-kind check and the tombstone translation to drift out of step, and each of those is an
invariant rather than a detail.

The four classes are never flattened, and each has a different obligation:

*   ``capture`` and ``inference`` must cite at least one evidence span. A model output with no
    evidence is not an inference, it is a rumour, and the schema refuses it as
    ``inference_support_required``.
*   ``inference`` must name the run that produced it.
*   ``user`` must name the person who said it, and must NOT name a run: migration 0002 adds
    ``a_user_statement_has_no_producing_run`` because a claim the user made was not produced by
    a pipeline, and the laundering route that motivated it kept exactly that column set.
*   ``external`` is a claim about a public entity in the present, never about the user's past.

What is checked here duplicates nothing the database does not also check. The database is the
guarantee; these checks exist for the error message, and the difference matters because a
refusal that says "predicate 'name_is' does not accept an 'inference' assertion; it allows
['user']" is actionable and ``SQLSTATE 23000`` is not.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.db.guards import terminal_if_tombstoned
from exulanica.db.session import set_workspace
from exulanica.errors import EpistemicViolation, TombstonedError

__all__ = ["AssertionWriter"]

#: The kinds that are worthless without evidence. A user statement is not in this set: the user
#: pointing at a photograph is welcome to cite it, and the user stating something from memory is
#: making a claim about their own life that no span supports and that is still theirs to make.
_SUPPORT_REQUIRED = frozenset({"capture", "inference"})


class AssertionWriter:
    """Assertions and the predicate vocabulary, for every caller that writes one."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self._db = connection
        self._db.row_factory = dict_row
        self.workspace_id = workspace_id
        set_workspace(connection, workspace_id)

    def predicate_id(self, key: str) -> int:
        row = self._db.execute(
            "select predicate_id from predicate where key = %s", (key,)
        ).fetchone()
        if row is None:
            raise EpistemicViolation(f"no predicate {key!r} in the vocabulary")
        return int(row["predicate_id"])

    def check_allows_kind(self, predicate_key: str, kind: str) -> int:
        """Refuse early, with a sentence rather than an SQLSTATE.

        ``tg_assertion_kind_is_allowed()`` refuses the same write inside the transaction and is
        the actual guarantee, including on write paths that never reach this class. This exists
        so the common case fails with an explanation of the rule.
        """
        # allows_kind::text[] rather than allows_kind. It is an assertion_kind[], a type
        # psycopg has no adapter for, so it comes back as the literal string '{capture}' and
        # list() over that yields one entry per character. The cast is the fix; registering an
        # enum adapter would be a second place for the vocabulary to be defined.
        row = self._db.execute(
            "select predicate_id, allows_kind::text[] as allows_kind from predicate "
            "where key = %s",
            (predicate_key,),
        ).fetchone()
        if row is None:
            raise EpistemicViolation(f"no predicate {predicate_key!r} in the vocabulary")
        allowed = list(row["allows_kind"])
        if kind not in allowed:
            raise EpistemicViolation(
                f"predicate {predicate_key!r} does not accept a {kind!r} assertion; it allows "
                f"{allowed}. A detection is an inference no matter how confident it is, and a "
                "name comes only from the account holder."
            )
        return int(row["predicate_id"])

    def insert(
        self,
        *,
        kind: str,
        predicate_key: str,
        subject_ref: dict[str, Any],
        emit_key: str,
        support_span_ids: Sequence[uuid.UUID],
        object_value: Any = None,
        object_ref: dict[str, Any] | None = None,
        produced_by_run: uuid.UUID | None = None,
        stated_by_user: uuid.UUID | None = None,
        external_source: dict[str, Any] | None = None,
        raw_score: float | None = None,
        valid_time: str | None = None,
    ) -> uuid.UUID | None:
        """Write one claim. Returns None when this ``emit_key`` was already emitted.

        ``raw_score`` is whatever the model emitted and nothing else. It is never rendered to a
        user and never thresholds a factual claim. When a model emits a qualitative band rather
        than a number, this stays None: converting a band to a number would invent a frequency
        guarantee nobody can honour.

        ``valid_time`` is a ``tstzrange`` literal, for example ``'[2019-04-01,2019-04-08)'``.
        """
        predicate_id = self.check_allows_kind(predicate_key, kind)
        span_ids = list(support_span_ids)
        if kind in _SUPPORT_REQUIRED and not span_ids:
            raise EpistemicViolation(
                f"a {kind} assertion must cite at least one evidence span; "
                f"{predicate_key!r} arrived with none"
            )
        self.refuse_if_support_is_absent_or_tombstoned(span_ids)
        with terminal_if_tombstoned():
            row = self._db.execute(
                "insert into assertion (workspace_id, kind, predicate_id, subject_ref, "
                "object_ref, object_value, valid_time, support_span_ids, produced_by_run, "
                "stated_by_user, external_source, raw_score, status, emit_key) "
                "values (%s, %s, %s, %s, %s, %s, %s::tstzrange, %s::uuid[], %s, %s, %s, %s, "
                "'active', %s) "
                "on conflict (workspace_id, emit_key) do nothing returning assertion_id",
                (
                    self.workspace_id,
                    kind,
                    predicate_id,
                    Jsonb(subject_ref),
                    Jsonb(object_ref) if object_ref is not None else None,
                    Jsonb(object_value) if object_value is not None else None,
                    valid_time,
                    span_ids,
                    produced_by_run,
                    stated_by_user,
                    Jsonb(external_source) if external_source else None,
                    raw_score,
                    emit_key,
                ),
            ).fetchone()
        return row["assertion_id"] if row is not None else None

    def refuse_if_support_is_absent_or_tombstoned(
        self, span_ids: Sequence[uuid.UUID]
    ) -> None:
        """Both checks in one round trip, because both are questions about the same set.

        The workspace check is not redundant with row-level security. RLS makes another
        workspace's span invisible, so the set simply comes back short; without counting, a
        claim citing a span it does not own would be written citing nothing.
        """
        if not span_ids:
            return
        row = self._db.execute(
            "select count(*) as visible, "
            "       tombstone_blocks_any_span(%s, %s::uuid[]) as blocked "
            "from evidence_span where span_id = any(%s::uuid[]) and workspace_id = %s",
            (self.workspace_id, list(span_ids), list(span_ids), self.workspace_id),
        ).fetchone()
        assert row is not None
        if row["visible"] != len(set(span_ids)):
            raise EpistemicViolation(
                f"support span set {[str(s) for s in span_ids]} is not entirely in this "
                "workspace"
            )
        if row["blocked"]:
            raise TombstonedError("a support span of this assertion is covered by a tombstone")

    def active_naming_assertion(
        self, entity_id: uuid.UUID, display_name: str
    ) -> uuid.UUID | None:
        """The assertion, if any, that currently supports this entity carrying this name.

        Matched on ``predicate.writes_a_name`` rather than on the key ``name_is``, for the same
        reason the trigger is: the vocabulary churns, and a later ``nickname_is`` must be
        governed by the same rule rather than escaping it by being spelled differently.
        """
        row = self._db.execute(
            "select a.assertion_id from assertion a "
            "join predicate p on p.predicate_id = a.predicate_id "
            "where a.workspace_id = %s and a.kind = 'user' and a.status = 'active' "
            "and p.writes_a_name "
            "and a.subject_ref = jsonb_build_object('type','entity','id', %s::text) "
            "and a.object_value = to_jsonb(%s::text) limit 1",
            (self.workspace_id, str(entity_id), display_name),
        ).fetchone()
        return None if row is None else row["assertion_id"]

    def retract(
        self,
        assertion_id: uuid.UUID,
        *,
        retracted_by: uuid.UUID,
        reason: str,
        retraction_id: uuid.UUID | None = None,
        retracted_at: dt.datetime | None = None,
    ) -> uuid.UUID:
        """Withdraw a claim without erasing that it was made.

        Two rows change together and neither is optional. ``assertion.status`` becomes
        ``retracted``, which is the only column on that table an update may touch; and a
        ``retraction`` row records who withdrew it and why. Rewriting the assertion in place
        instead is refused outright by ``tg_assertion_no_in_place_rewrite``, because every
        citation already issued against the row would then point at a different claim.

        ``retraction_id`` and ``retracted_at`` are the table's own defaults when omitted. A
        restore names both, so the retraction it writes again is the one the person made
        (``exulanica.deletion.withdrawals``).
        """
        given = {
            column: value
            for column, value in (("retraction_id", retraction_id), ("retracted_at", retracted_at))
            if value is not None
        }
        columns = ["workspace_id", "assertion_id", "retracted_by", "reason", *given]
        row = self._db.execute(
            f"insert into retraction ({', '.join(columns)}) "
            f"values ({', '.join(['%s'] * len(columns))}) returning retraction_id",
            (self.workspace_id, assertion_id, retracted_by, reason, *given.values()),
        ).fetchone()
        assert row is not None
        self._db.execute(
            "update assertion set status = 'retracted' "
            "where workspace_id = %s and assertion_id = %s",
            (self.workspace_id, assertion_id),
        )
        return row["retraction_id"]
