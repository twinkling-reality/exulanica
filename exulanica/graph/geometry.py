"""What geometry a region has, and the bytes of it. The read behind the delivery route.

ADR-0009 D10: "There is no production path by which any point map reaches the renderer: no route
serves artifact bytes, and the only loader in the workspace is a development preview... The
delivery route is the first item of work, before any of the above, and it carries the
authentication and digest rules that the residency design already assumes: bytes in hand, a
bearer in the header, and the content hash verified against the descriptor that named it."

This module is the read half of that. Seven decisions in it are load bearing.

**This list is the legacy unposed path and holds only point maps that are not members of a
reconstruction scene.** The descriptor query inner-joins ``capture`` on ``source_blob_sha256``,
which is the identity scheme ADR-0009 D9 says a pose receipt, splat and placement record have no
home in: those are facts about N photographs and use a scene identity. Once a capture belongs to
such a scene, ``GET /graph`` carries its exact digest-bound placement and this list must not offer
the same bytes as an unrelated shell at the island origin. That exclusion also makes deletion
terminal for presentation: a scene withdrawn by one member cannot reappear as one surviving
member's unposed point map.

**A descriptor is keyed by CAPTURE, never by island.** ``exulanica.graph``'s own docstring says why:
"Islands are not a server concept... A server that shipped an island id would be settling that
question by accident." ADR-0005 leaves it open, the client already maps captures to islands
through an injectable function, and geometry has to arrive on the same key the graph does or the
two would disagree about which region a shell belongs to.

**A descriptor carries no rung.** The recorded rung claim already reaches the client on the graph
payload, per scene group and worst-first, which is the granularity a region is drawn at. ADR-0009
D11's complaint is that a second, divergent copy of the rung vocabulary exists in the frontend;
answering it with a second copy on the wire would be the same mistake one layer down. What a
descriptor says is what geometry exists and how to check the bytes, and nothing about how good
it is.

**Liveness is asked of the database's own guard, not re-implemented here.**
``tombstone_blocks_capture`` is the predicate migration 0001's ``before insert`` triggers call on
``occurrence``, so what this refuses to serve is a rule that exists once and in SQL. It covers
workspace, capture and interval scope. It does **not** cover entity scope, and that is correct
rather than an omission: deleting a person is not deleting the photograph, which
``domain-and-evidence-model.md`` section 6.4 states as a consequence that "must not be softened".
What that section promises for entity scope and does not do is recorded there under CORRECTED,
and it is a gap in the cascade rather than in this read.

**Not ``tombstone_blocks_derivative``, and the difference is the interval branch.** That
predicate is what refuses to WRITE a derivative, and migration 0011 deliberately leaves the
interval scope out of it, "because a redaction removes a moment and not a photograph": the
designed behaviour is a derivative marked ``needs_repair`` and regenerated from the surviving
intervals. A still photograph has no surviving interval. Section 1.5 gives every image the
interval ``[0, 1)``, so an interval tombstone over an image covers the whole frame, and a point
map of it is a derivative of nothing but redacted content. Reading is therefore stricter than
writing here, on purpose. **The day a derivative covers part of a track rather than all of one,
this predicate is the wrong one** and the right one is a question about the spans the artifact
actually drew from, which nothing records yet.

**``artifact.purged_at`` is not sufficient on its own and is checked anyway.** A tombstone is
authoritative the moment it commits and the bytes catch up later, so between the two there is a
window in which the artifact row is unpurged and the capture is deleted. Serving in that window
would be serving something the user has already deleted. Both are therefore checked, and the
tombstone is checked first because it is the one that is true earlier.

**The store is passed in.** ``exulanica.graph`` sits above ``exulanica.store`` in the layering and
below ``exulanica.api``, and the API owns which store an instance is wired to. Handing the store to
the function rather than letting the module reach for one is the same arrangement
``WorldStyleRepository.source_media`` uses, and for the same reason: a read module that could
resolve its own bytes is a read module that could resolve somebody else's.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import psycopg

from exulanica.errors import IntegrityError, TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time, final_check, point_allowed
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "POINT_MAP_KIND",
    "GeometryBytes",
    "GeometryDescriptor",
    "GeometryState",
    "point_map_descriptors",
    "read_point_map",
]

#: The ``artifact.kind`` a rung 3 point map is written under. It is the ``output_kind`` of the
#: depth stage in :mod:`exulanica.ingest.stages`, spelled here rather than imported because
#: ``exulanica.graph`` and ``exulanica.ingest`` are siblings in the layering contract and may not
#: import each other. ``tests/test_geometry_delivery.py`` pins the two spellings together, so a
#: rename that reached only one of them fails rather than serving an empty list for ever.
POINT_MAP_KIND: Final = "point_map"


class GeometryState(StrEnum):
    """Whether the bytes a descriptor names can actually be fetched.

    Two states rather than a boolean, and no third. ``bytes_missing`` is an artifact row whose
    object is not in the store: the row records what was produced and the object is gone, which
    is a different fact from a region having no geometry at all and must not be flattened into
    it. Deleted and purged are not states here, because a deleted region's geometry is not in
    the list at all.
    """

    AVAILABLE = "available"
    BYTES_MISSING = "bytes_missing"


@dataclass(frozen=True, slots=True)
class GeometryDescriptor:
    """One derivative a region could be drawn from, and everything needed to verify it."""

    capture_id: uuid.UUID
    artifact_id: uuid.UUID
    kind: str
    stage_key: str
    stage_version: int
    #: The container the artifact was actually written under, read from the stage definition
    #: carrying the exact ``params_digest`` on the row rather than from today's registry. None
    #: when no definition was recorded for that digest, which is the honest answer for a corpus
    #: ingested before migration 0018 rather than a guess at what it must have been.
    container: str | None
    #: Lowercase hex. **This is the digest the client verifies the bytes against**, and it is the
    #: reason a descriptor exists at all rather than a bare list of hrefs.
    content_sha256: str
    byte_size: int
    state: GeometryState
    reason: str | None
    #: True when a recompute of a deterministic stage failed to reproduce these bytes and the
    #: stored object was already gone. Carried rather than filtered, because a region whose
    #: geometry is known to be unreproducible is a fact an interface may want to show.
    #:
    #: It never appears beside ``available`` today, and that is a property of the one writer
    #: rather than of this type: ``mark_needs_repair`` is called only where the object is already
    #: absent, so ``store.exists`` has already made the state ``bytes_missing``. **A second
    #: writer would have to decide whether a flagged row may still be served**, and if the answer
    #: is no then the filter belongs in the query rather than in a reader's judgement.
    needs_repair: bool

    @property
    def href(self) -> str:
        """Where the bytes are. One expression, so the list and the route cannot disagree."""
        return f"/geometry/{self.artifact_id}"


@dataclass(frozen=True, slots=True)
class GeometryBytes:
    """The bytes of one artifact, and the hash they were verified against on the way out."""

    artifact_id: uuid.UUID
    content_sha256: str
    container: str | None
    payload: bytes


#: Every artifact this workspace may be served, one per live capture.
#:
#: ``distinct on (c.capture_id)`` with the ordering below takes the highest stage version, then
#: the most recently created row. Two artifacts of one capture at one stage version is the
#: nondeterminism case ``persist_artifact`` records rather than absorbs, and taking the newest is
#: the same choice ``rung_by_capture`` makes for a capture carrying two active rungs.
#:
#: The ``capture`` join is not a formality: an artifact is keyed to a source blob, and two live
#: captures of identical bytes share one artifact row, so one artifact legitimately becomes two
#: descriptors. Collapsing them would drop one region's geometry on the grounds that another
#: region already had it.
_DESCRIPTORS: Final = """
select distinct on (c.capture_id)
       c.capture_id,
       c.started_at,
       a.artifact_id,
       a.kind,
       a.stage_key,
       a.stage_version,
       a.content_sha256,
       a.byte_size,
       a.needs_repair,
       sd.params ->> 'container' as container
  from artifact a
  join capture c
    on c.workspace_id = a.workspace_id
   and c.blob_sha256 = a.source_blob_sha256
   and c.deleted_at is null
  left join stage_definition sd
    on sd.stage_key = a.stage_key
   and sd.stage_version = a.stage_version
   and sd.params_digest = a.params_digest
 where a.workspace_id = %s
   and a.kind = %s
   and a.purged_at is null
   and a.superseded_by is null
   and a.content_sha256 is not null
   and a.byte_size is not null
   and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
   and not person_withdrawal_blocks_artifact(a.workspace_id, a.artifact_id)
   and not exists (
     select 1 from reconstruction_scene_member m
      where m.workspace_id = a.workspace_id
        and m.capture_id = c.capture_id
   )
 order by c.capture_id, a.stage_version desc, a.created_at desc, a.artifact_id
"""

#: One artifact by id, scoped to the caller's workspace. No capture join: whether anything live
#: still holds these bytes is a separate question and is asked separately, because a filtering
#: join answers "no rows" both for "the user deleted it" and for "there is no such artifact",
#: and those are the two answers this route exists to keep apart.
#:
#: **There is no ``superseded_by`` filter here and there deliberately is one in the list**, and
#: the asymmetry is load bearing. The list answers "what should this world draw", so it offers
#: the current version. This answers "give me the bytes that hash to what this id names", and a
#: superseded row is not a wrong answer to that: migration 0001 keeps the old row precisely so
#: "old citations, old anchor resolutions and old Assembly Replays stay intact". ADR-0009 D6's
#: placement record will name its members by content hash across a stage bump, and adding the
#: filter here is what would leave it holding hashes nothing will serve.
_ONE: Final = """
select a.artifact_id,
       a.source_blob_sha256,
       a.read_source_sha256,
       a.privacy_screening_id,
       a.input_digest,
       a.content_sha256,
       a.byte_size,
       a.purged_at,
       sd.params ->> 'container' as container
  from artifact a
  left join stage_definition sd
    on sd.stage_key = a.stage_key
   and sd.stage_version = a.stage_version
   and sd.params_digest = a.params_digest
 where a.workspace_id = %s
   and a.artifact_id = %s
   and a.kind = %s
"""

#: Does anything the user still holds stand behind these bytes? Asked of the same guard the
#: write path asks, so a derivative that could not be produced today is not one that can be
#: served today.
#:
#: **An OR over the captures that hold one blob, which is right here and is the WRONG reduction
#: for a scene artifact.** It matches ``purge_releases_bytes``: a photograph imported twice is
#: one artifact and two captures, and one of them being deleted does not withdraw it. ADR-0009 D9
#: requires the opposite for a fact about N photographs, "a tombstone path that reaches a scene
#: artifact through any of its members", so deleting ONE member must withdraw a pose receipt, a
#: splat or a placement record. Copying this predicate to one of those would serve a corridor
#: after a member was deleted, and it would pass a test that only deleted every member. Stated
#: here rather than left to be discovered, because copying the nearest existing reader is exactly
#: what a sixth reader of this table will do.
_LIVE_HOLDER: Final = """
select exists (
  select 1 from capture c
   where c.workspace_id = %s
     and c.blob_sha256 = %s
     and c.deleted_at is null
     and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
) as live
"""


def point_map_descriptors(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore,
) -> tuple[GeometryDescriptor, ...]:
    """Every point map this workspace may be served, in a stable presentation order.

    **The order is documented because a client depends on it.** A region can hold several point
    maps and the renderer takes one per region, so something has to choose; the choice is made
    once here rather than separately on every client. It is ``capture.started_at`` and then
    ``capture_id``, which is the first photograph of a visit followed by ingest order, because
    ``capture_id`` is a uuidv7. ``started_at`` is "best estimate only" in migration 0001's own
    words and is used here as a presentation order rather than as a measurement: nothing
    downstream reads it as a capture time, and the list ships no capture time for that reason.
    A capture with no usable clock sorts last rather than being dropped or read as the oldest.

    ``store.exists`` is asked per artifact, as ``source_media`` asks it per source slot, and it is
    what makes ``available`` mean that the bytes are there rather than that a row says they once
    were. **Per artifact, not per region**: this returns one row per live capture and the whole
    list is unpaginated, so eighty photographs are eighty rows and eighty stat calls on every
    request. That is affordable at the scale of a personal library and it is a bound this route
    does not have, which is worth knowing before the first corpus that is not one.
    """
    _require_workspace_context(connection, workspace)
    rows = connection.execute(_DESCRIPTORS, (workspace, POINT_MAP_KIND)).fetchall()
    ordered = sorted(rows, key=_presentation_order)
    at = evaluation_time(connection)
    return tuple(
        _descriptor(row, store)
        for row in ordered
        if point_allowed(connection, workspace, row["artifact_id"], at)
    )


def read_point_map(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    artifact_id: uuid.UUID,
    store: ContentAddressedStore,
) -> GeometryBytes | None:
    """The bytes of one point map, hash-verified on the way out, or None when there is no such row.

    None rather than an exception for the unknown case, because the route turns it into the same
    404 a foreign artifact id gets. That is not a courtesy: ``evaluation-methodology.md`` M10
    requires "404, never 403, so the surface is not an existence oracle", and it is achieved the
    way the evidence route achieves it, by the query being scoped to the caller's workspace so a
    foreign artifact is simply not there.

    ``artifact_id`` is ``uuid5`` over an idempotency key that contains no workspace, so two
    workspaces that ingested the same photograph hold rows under the SAME artifact id. Guessing
    one is therefore easy and buys nothing: the row is fetched under the caller's workspace, and
    what another workspace holds under that id is byte-identical content the caller already has.
    The scoping is what makes that true, not the id being hard to guess.

    Raises :class:`~exulanica.errors.TombstonedError` when the user deleted it, which the API
    answers with 410 rather than 404, and :class:`~exulanica.errors.BlobNotFoundError` when the
    row survived and the object did not.

    Bytes are buffered and verified before a fresh serialized final permission check.
    """
    _require_workspace_context(connection, workspace)
    row = connection.execute(_ONE, (workspace, artifact_id, POINT_MAP_KIND)).fetchone()
    if row is None or row["content_sha256"] is None or row["byte_size"] is None:
        # A row that never recorded a content hash produced no bytes, so there is nothing to
        # serve and nothing was deleted. It is indistinguishable from absence, and is answered
        # as absence rather than as a fault the caller could do anything about.
        return None
    if row["source_blob_sha256"] is None:
        # A scene artifact, reaching a read that has no way to answer for one. Migration 0024
        # made ``source_blob_sha256`` nullable so that a fact about N photographs can name a
        # scene instead, and the liveness question below is an OR over the captures holding one
        # blob, which is the WRONG reduction for a set: ``tombstone_blocks_scene`` is the right
        # one and this function does not ask it.
        #
        # **Unreachable today, and guarded rather than asserted.** ``_ONE`` filters on
        # ``POINT_MAP_KIND`` and a point map is always a derivative of one photograph, so the
        # only way here is a caller passing a different kind, which no route does. But the
        # protection is a filter on another line, and the failure without this was a TypeError
        # inside ``bytes(None)`` rather than a refusal: a 500 on a read whose whole job is to
        # refuse safely. Answered as absence, which is what it is to this reader.
        return None
    holder = connection.execute(
        _LIVE_HOLDER, (workspace, bytes(row["source_blob_sha256"]))
    ).fetchone()
    assert holder is not None
    withdrawn = connection.execute(
        "select person_withdrawal_blocks_artifact(%s, %s) as blocked",
        (workspace, artifact_id),
    ).fetchone()
    assert withdrawn is not None
    if row["purged_at"] is not None or not holder["live"] or withdrawn["blocked"]:
        raise TombstonedError(
            f"geometry {artifact_id} was deleted. Its photograph is gone, a confirmed person "
            "withdrew, or its bytes have already been destroyed."
        )
    # `store.get` re-hashes what it read against the key it was asked for, and that key is the
    # artifact's own recorded content hash. So the bytes leaving this function are the bytes the
    # descriptor names, or nothing leaves it: a mismatch raises IntegrityError, which the API
    # answers with a loud 500 rather than serving content nobody chose.
    digest = bytes(row["content_sha256"])
    payload = store.get(BlobId(digest))
    if len(payload) != row["byte_size"]:
        raise IntegrityError("point-map bytes disagree with their recorded size")
    with final_check(connection) as at:
        if not point_allowed(connection, workspace, artifact_id, at):
            return None
        current = connection.execute(_ONE, (workspace, artifact_id, POINT_MAP_KIND)).fetchone()
        if current != row:
            return None
    return GeometryBytes(
        artifact_id=row["artifact_id"],
        content_sha256=digest.hex(),
        container=row["container"],
        payload=payload,
    )


def _require_workspace_context(connection: psycopg.Connection, workspace: uuid.UUID) -> None:
    """Refuse a connection that has not declared the workspace it is reading for.

    The same assertion migration 0001 puts in front of every tombstone guard, and for the reason
    written there: ``tombstone`` carries FORCE row-level security, so "a session that never set
    exulanica.workspace_id sees those tables as empty, so the guard would find no tombstone and
    fail OPEN, which is the worst possible direction for it to fail in". The API's own dependency
    always declares one, so this never fires today. It is here because a read whose whole job is
    to refuse deleted content must fail closed when it cannot see what was deleted, and being
    unreachable is not the same as being unnecessary.
    """
    connection.execute("select assert_workspace_context(%s)", (workspace,))


def _presentation_order(row: Mapping[str, Any]) -> tuple[bool, dt.datetime, str]:
    """See :func:`point_map_descriptors`. None sorts last, then by uuidv7 ingest order."""
    started: dt.datetime | None = row["started_at"]
    return (
        started is None,
        started or dt.datetime.min.replace(tzinfo=dt.UTC),
        str(row["capture_id"]),
    )


def _descriptor(row: Mapping[str, Any], store: ContentAddressedStore) -> GeometryDescriptor:
    present = store.exists(BlobId(bytes(row["content_sha256"])))
    return GeometryDescriptor(
        capture_id=row["capture_id"],
        artifact_id=row["artifact_id"],
        kind=row["kind"],
        stage_key=row["stage_key"],
        stage_version=row["stage_version"],
        container=row["container"],
        content_sha256=bytes(row["content_sha256"]).hex(),
        byte_size=int(row["byte_size"]),
        state=GeometryState.AVAILABLE if present else GeometryState.BYTES_MISSING,
        reason=None if present else "the artifact row survived and its stored object did not",
        needs_repair=bool(row["needs_repair"]),
    )
