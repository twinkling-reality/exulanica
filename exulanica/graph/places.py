"""One place read back: its versions in capture order, and the frame each one is expressed in.

``docs/place-identity.md`` decides what a place is and ``0038_a_place_is_more_than_one_capture.sql``
records it. This is the read seam over that plane, and it is built the way
:mod:`exulanica.graph.reconstruction_scenes` is built, for the same reason: the database says what
was bound and the object store says what can be drawn, and a transform crosses the boundary between
them only after the receipt that measured it reproduces its digest and agrees with the row that
names it.

Four things here are decisions rather than plumbing.

**The anchor's transform is identity, and it is not a measurement.** A place's shared frame is its
anchor scene's own recovered frame, so ``place_from_scene`` for the anchor is the identity matrix by
construction, with ``frame_hops`` 0 and no admitting alignment. It is reported with its own state,
``identity``, rather than as an ``available`` fit, because a reader that could not tell the two
apart would be told a measurement had been made where none was.

**A transform that cannot be read is never identity.** Every other state a version's transform can
be in says so: a receipt whose bytes are gone is ``unavailable``, one that disagrees with the row
that names it is ``invalid``. The failure this rule exists to prevent is a place drawn as though
its captures coincided, which is what a missing transform silently substituted with identity would
produce, and it would look exactly like a good alignment.

**The tombstone guard is in SQL and it is asked at two scopes.** ``tombstone_blocks_place`` covers
the place, because a place's frame is its anchor's and a withdrawn anchor takes every version's
frame with it. ``tombstone_blocks_scene`` covers each version, because a place is a join
and never a merge: one withdrawn capture removes its own version and leaves the others standing.
Both are ``where`` clauses rather than a reduction in Python. ``exulanica/graph/observations.py``
records why that matters for a fact about a set: a per-capture predicate is an OR over the captures
sharing a blob, and one live capture would keep serving a fact about a set another was withdrawn
from.

**A refusal is readable.** A joint reconstruction that could not reconcile two frames writes a row
like any other, and this seam returns it, so the world can say that two captures are of related
places whose frames could not be reconciled and name the reason the fitter gave. That outcome is
the one ``docs/place-identity.md`` exists to make readable, and a seam that returned only the
accepted versions would make a refusal indistinguishable from a join nobody attempted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.canonical import canonical_json
from exulanica.capture.instructions import INSTRUCTION_VOCABULARY, Instruction, instruction
from exulanica.capture.recovery import (
    RECOVERY_STATES,
    Basis,
    RecoveryState,
    outcome_from_pose_receipt,
)
from exulanica.capture.verdict import PredictedCeiling
from exulanica.errors import BlobNotFoundError, CanonicalisationError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time
from exulanica.graph.payload import SceneUnposedPhotographRow
from exulanica.graph.reconstruction_scenes import _viewer_photograph
from exulanica.graph.wire_numbers import decimal_string as _decimal
from exulanica.graph.wire_numbers import decimal_strings as _decimals
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "PLACE_ALIGNMENT_RECEIPT_PROFILE",
    "PlaceHistory",
    "PlacePosition",
    "PlaceRecord",
    "PlaceTransform",
    "PlaceVersion",
    "RecordPhotograph",
    "RecordReason",
    "RecordStateChange",
    "RecordVerdict",
    "RefusedAlignment",
    "SceneMembership",
    "place_history",
    "place_record",
    "place_record_ids",
    "scene_place_membership",
]

#: The profile string the place-alignment receipt shape fixes. Restated here rather than imported
#: from the stage that writes it, because this is the reader's half of that agreement: a receipt
#: carrying some other profile is refused as ``invalid`` and says so, instead of being read under
#: an interpretation nobody agreed to.
PLACE_ALIGNMENT_RECEIPT_PROFILE: Final = "exulanica.place-alignment-receipt/v1"

#: Row-major 4x4 identity. The anchor scene's frame IS the place frame, so this is exact rather
#: than fitted, and no fold, residual or tolerance was involved in producing it.
_IDENTITY: Final = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)  # fmt: skip

_PLACE: Final = """
select p.place_id
  from place p
 where p.workspace_id = %s
   and p.place_id = %s
   and not tombstone_blocks_place(p.workspace_id, p.place_id)
"""

_VERSIONS: Final = """
select v.scene_id,
       v.ordinal,
       v.ordered_by_utc,
       v.ordered_by_basis,
       v.frame_hops,
       v.admitted_by_alignment_id,
       al.candidate_scene_id,
       al.against_scene_id,
       al.accepted,
       receipt.content_sha256 as receipt_sha256
  from place_version v
  left join place_alignment al
    on al.workspace_id = v.workspace_id
   and al.alignment_id = v.admitted_by_alignment_id
  left join artifact receipt
    on receipt.workspace_id = al.workspace_id
   and receipt.artifact_id = al.receipt_artifact_id
   and receipt.place_id = al.place_id
   and receipt.kind = 'place_alignment_receipt'
   and receipt.purged_at is null
   and not person_withdrawal_blocks_artifact(receipt.workspace_id, receipt.artifact_id)
 where v.workspace_id = %s
   and v.place_id = %s
   and not tombstone_blocks_scene(v.workspace_id, v.scene_id)
 order by v.ordinal
"""

# A refusal names two scenes, and both have to still be there for it to be sayable. Serving
# "these two captures are of related places" over a capture somebody withdrew would route around
# the withdrawal with a sentence rather than with geometry, which is the same thing.
_REFUSALS: Final = """
select al.alignment_id,
       al.candidate_scene_id,
       al.against_scene_id,
       al.reason,
       receipt.content_sha256 as receipt_sha256
  from place_alignment al
  left join artifact receipt
    on receipt.workspace_id = al.workspace_id
   and receipt.artifact_id = al.receipt_artifact_id
   and receipt.place_id = al.place_id
   and receipt.kind = 'place_alignment_receipt'
   and receipt.purged_at is null
   and not person_withdrawal_blocks_artifact(receipt.workspace_id, receipt.artifact_id)
 where al.workspace_id = %s
   and al.place_id = %s
   and not al.accepted
   and not tombstone_blocks_scene(al.workspace_id, al.candidate_scene_id)
   and not tombstone_blocks_scene(al.workspace_id, al.against_scene_id)
 order by al.created_at, al.alignment_id
"""


@dataclass(frozen=True, slots=True)
class PlaceTransform:
    """``place_from_scene`` for one version, or the reason this reader has no transform for it.

    ``state`` is the field a consumer must read first.

    *   ``identity`` is the anchor. The numbers are exact and nothing measured them.
    *   ``available`` is a fit an accepted alignment receipt measured and this reader verified.
    *   ``unavailable`` is a receipt whose bytes this reader could not obtain.
    *   ``invalid`` is a receipt that disagrees with the row naming it, or whose numbers this
        encoding cannot carry.

    The numbers are fixed-precision decimal strings, the same encoding every other measured number
    in this package leaves in. ``scene_units_to_place_units`` is already applied inside the linear
    block above it and must not be applied a second time, which is the rule ``scene_from_opm``
    states for its own scalar.
    """

    state: Literal["identity", "available", "unavailable", "invalid"]
    place_from_scene_row_major: list[str] | None
    scene_units_to_place_units: str | None
    receipt_sha256: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PlaceVersion:
    """One scene's membership of one place, with the frame it was admitted in.

    ``frame_hops`` is the honesty field, and it is the reason this row carries a number rather than
    a boolean: 0 is the anchor, 1 is a frame one joint reconstruction measured against the anchor,
    and n is a frame composed through n measurements. A reader without it takes a composition for a
    measurement.
    """

    scene_id: uuid.UUID
    ordinal: int
    ordered_by_utc: dt.datetime | None
    ordered_by_basis: Literal["capture_exif", "reviewer", "unavailable"]
    frame_hops: int
    admitted_by_alignment_id: uuid.UUID | None
    transform: PlaceTransform


@dataclass(frozen=True, slots=True)
class RefusedAlignment:
    """A joint reconstruction that ran and did not reconcile two frames.

    Kept because it is a result. ``reason`` is one of the three
    :mod:`exulanica.reconstruction.place_alignment` can return, and the schema refuses any other,
    so a refusal nobody anticipated fails loudly rather than arriving as free text.
    """

    alignment_id: uuid.UUID
    candidate_scene_id: uuid.UUID
    against_scene_id: uuid.UUID
    reason: str
    receipt_sha256: str | None


# Reduce over distinct captures in live versions, not over membership rows: two versions may
# share a photograph. Filtering the whole scene also withholds fixes from the surviving members
# of a withdrawn version, matching the version list this answer accompanies.
_POSITION_MEMBERS: Final = """
with members as (
  select distinct m.capture_id
    from place_version v
    join reconstruction_scene_member m
      on m.workspace_id = v.workspace_id and m.scene_id = v.scene_id
   where v.workspace_id = %s and v.place_id = %s
     and not tombstone_blocks_scene(v.workspace_id, v.scene_id)
)
select m.capture_id, a.object_value
  from members m
  left join assertion a
    on a.workspace_id = %s
   and a.subject_ref ->> 'type' = 'capture'
   and a.subject_ref ->> 'id' = m.capture_id::text
   and a.predicate_id = (select predicate_id from predicate where key = 'gps_position_is')
   and a.status = 'active'
   and a.valid_time is null
 order by m.capture_id
"""


@dataclass(frozen=True, slots=True)
class PlacePosition:
    """Current photographer fixes, never a georeference for the recovered frame.

    Coordinate-wise lower medians select an observed integer even for an even-sized set. Bounds
    are ordinary numeric longitude bounds, not a shortest arc across the antimeridian. Invalid or
    legacy claims without exact integer coordinates are counted separately, never guessed from
    decimal text. This trades coverage for an exact, checkable basis.
    """

    state: Literal["available", "unavailable"]
    member_captures: int
    captures_with_fix: int
    unusable_fix_claims: int
    bounding_box_e7: dict[str, int] | None
    median_e7: dict[str, int] | None
    reason: str | None
    basis: str = "exif-capture-fixes/v1"
    reduction: str = "coordinate-wise lower median; numeric longitude bounds"
    means: str = (
        "A fix says where a photographer stood, not where the place is, how large it is, "
        "or which way it faces. The recovered frame stays ungeoreferenced. "
        "This position uses current claims over all live versions, "
        "independent of the requested time."
    )


def _position(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    place_id: uuid.UUID,
) -> PlacePosition:
    rows = connection.execute(_POSITION_MEMBERS, (workspace, place_id, workspace)).fetchall()
    fixes = []
    unusable = 0
    for row in rows:
        value = row["object_value"]
        if value is None:
            continue
        lat = value.get("lat_e7") if isinstance(value, dict) else None
        lon = value.get("lon_e7") if isinstance(value, dict) else None
        if (
            type(lat) is not int
            or type(lon) is not int
            or not -900_000_000 <= lat <= 900_000_000
            or not -1_800_000_000 <= lon <= 1_800_000_000
        ):
            unusable += 1
            continue
        fixes.append((lat, lon))
    bounds = median = None
    if fixes:
        latitudes = sorted(lat for lat, _ in fixes)
        longitudes = sorted(lon for _, lon in fixes)
        middle = (len(fixes) - 1) // 2
        median = {"lat": latitudes[middle], "lon": longitudes[middle]}
        bounds = {
            "south": latitudes[0],
            "north": latitudes[-1],
            "west": longitudes[0],
            "east": longitudes[-1],
        }
    return PlacePosition(
        state="available" if fixes else "unavailable",
        member_captures=len(rows),
        captures_with_fix=len(fixes),
        unusable_fix_claims=unusable,
        bounding_box_e7=bounds,
        median_e7=median,
        reason=None if fixes else "no live member capture has a usable integer GPS fix",
    )


@dataclass(frozen=True, slots=True)
class PlaceHistory:
    """A place, its live versions in capture order, and the joins that were refused."""

    place_id: uuid.UUID
    versions: list[PlaceVersion]
    refused_alignments: list[RefusedAlignment]
    position: PlacePosition

    @property
    def anchor(self) -> PlaceVersion:
        """The version whose own recovered frame is the place frame.

        Always present. ``tombstone_blocks_place`` fails closed on a place with no anchor and on
        one whose anchor is withdrawn, and it is applied in the query that produced this object,
        so a ``PlaceHistory`` exists only where an unblocked anchor does.
        """
        return next(version for version in self.versions if version.frame_hops == 0)

    @property
    def undated_versions(self) -> int:
        """Versions whose capture time could not be established, and which time cannot address.

        A scene has no capture-time column, so a version's time was recorded at bind time from
        something, and a version admitted as ``unavailable`` has nothing to compare against a
        requested time. Counted rather than hidden: an addressing answer that silently omitted
        them would be answering over a smaller history than the place has.
        """
        return sum(1 for version in self.versions if version.ordered_by_utc is None)

    def at(self, when: dt.datetime | None) -> PlaceVersion | None:
        """The version in force at ``when``, or None when the place had none yet.

        The latest version whose ``ordered_by_utc`` is at or before ``when``. A time between two
        versions resolves to the earlier one, because that is the capture that was the latest
        record of this place at that moment, and rounding forward would answer with photographs
        that did not exist yet.

        ``when`` of None means the latest dated version. It deliberately does not mean "now": a
        read whose answer depends on the clock produces a digest that moves with no write behind
        it, and ``exulanica/graph/world_read.py`` records what that costs a recipient who quoted
        one.
        """
        dated = [version for version in self.versions if version.ordered_by_utc is not None]
        if not dated:
            return None
        if when is None:
            return dated[-1]
        eligible = [version for version in dated if version.ordered_by_utc <= when]
        return eligible[-1] if eligible else None


def place_history(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    place_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> PlaceHistory | None:
    """Return one place's live history, or ``None`` when it is not readable.

    ``None`` covers a place that does not exist, a place in another workspace, a place whose
    anchor was withdrawn and a place with no anchor at all, so a caller cannot turn this into an
    existence oracle. The route above separates those cases only among ids it has already
    established belong to the asking workspace.
    """
    if connection.execute(_PLACE, (workspace, place_id)).fetchone() is None:
        return None
    versions = [
        _version(place_id, row, store)
        for row in connection.execute(_VERSIONS, (workspace, place_id)).fetchall()
    ]
    refusals = [
        RefusedAlignment(
            alignment_id=row["alignment_id"],
            candidate_scene_id=row["candidate_scene_id"],
            against_scene_id=row["against_scene_id"],
            reason=row["reason"],
            receipt_sha256=_hex(row["receipt_sha256"]),
        )
        for row in connection.execute(_REFUSALS, (workspace, place_id)).fetchall()
    ]
    return PlaceHistory(
        place_id=place_id,
        versions=versions,
        refused_alignments=refusals,
        position=_position(connection, workspace, place_id),
    )


def _version(
    place_id: uuid.UUID,
    row: dict[str, Any],
    store: ContentAddressedStore | None,
) -> PlaceVersion:
    return PlaceVersion(
        scene_id=row["scene_id"],
        ordinal=int(row["ordinal"]),
        ordered_by_utc=row["ordered_by_utc"],
        ordered_by_basis=row["ordered_by_basis"],
        frame_hops=int(row["frame_hops"]),
        admitted_by_alignment_id=row["admitted_by_alignment_id"],
        transform=_transform(place_id, row, store),
    )


def _transform(
    place_id: uuid.UUID,
    row: dict[str, Any],
    store: ContentAddressedStore | None,
) -> PlaceTransform:
    """Read one version's ``place_from_scene``, or say why this reader has none.

    The receipt is checked against the row that names it before its numbers are used. Both halves
    are needed and neither is enough: the row says which scene was admitted at how many hops, the
    receipt says what was measured, and a receipt read without that comparison would let a
    transform measured for one scene be served as another's.
    """
    if row["frame_hops"] == 0:
        return PlaceTransform(
            state="identity",
            place_from_scene_row_major=_decimals(list(_IDENTITY)),
            scene_units_to_place_units=_decimal(1.0),
            receipt_sha256=None,
            reason=None,
        )
    digest = row["receipt_sha256"]
    if store is None or digest is None:
        return PlaceTransform(
            state="unavailable",
            place_from_scene_row_major=None,
            scene_units_to_place_units=None,
            receipt_sha256=_hex(digest),
            reason=(
                "the alignment receipt that admitted this version is not available to this reader"
            ),
        )
    try:
        payload = store.get(BlobId(bytes(digest)))
    except BlobNotFoundError:
        return PlaceTransform(
            state="unavailable",
            place_from_scene_row_major=None,
            scene_units_to_place_units=None,
            receipt_sha256=_hex(digest),
            reason="the alignment receipt is missing from object storage",
        )
    except IntegrityError:
        return PlaceTransform(
            state="invalid",
            place_from_scene_row_major=None,
            scene_units_to_place_units=None,
            receipt_sha256=_hex(digest),
            reason="the alignment receipt failed its content digest",
        )

    try:
        matrix, scale = _fit_from_receipt(payload, place_id, row)
    except (CanonicalisationError, KeyError, TypeError, ValueError) as error:
        return PlaceTransform(
            state="invalid",
            place_from_scene_row_major=None,
            scene_units_to_place_units=None,
            receipt_sha256=_hex(digest),
            reason=f"the alignment receipt does not describe this version: {error}",
        )
    return PlaceTransform(
        state="available",
        place_from_scene_row_major=matrix,
        scene_units_to_place_units=scale,
        receipt_sha256=_hex(digest),
        reason=None,
    )


def _fit_from_receipt(
    payload: bytes, place_id: uuid.UUID, row: dict[str, Any]
) -> tuple[list[str], str]:
    """The transform this receipt measured, or a raised error naming the disagreement.

    Every check here is a way the receipt and the row could describe different things. The scale
    is required to be positive because the fitter's own refusal path returns no transform at all
    for a non-positive one, so a receipt carrying one was not written by that fitter.
    """
    receipt = json.loads(payload)
    if not isinstance(receipt, dict):
        raise ValueError("the receipt is not one JSON object")
    if receipt.get("profile") != PLACE_ALIGNMENT_RECEIPT_PROFILE:
        raise ValueError(f"unexpected receipt profile {receipt.get('profile')!r}")
    if receipt.get("place_id") != str(place_id):
        raise ValueError("the receipt was written for another place")
    if receipt.get("candidate_scene_id") != str(row["candidate_scene_id"]):
        raise ValueError("the receipt's candidate is not the scene this alignment admitted")
    if str(row["candidate_scene_id"]) != str(row["scene_id"]):
        raise ValueError("the admitting alignment measured a different scene than this version")
    if receipt.get("against_scene_id") != str(row["against_scene_id"]):
        raise ValueError("the receipt was measured against a different member")
    if receipt.get("accepted") is not True or row["accepted"] is not True:
        raise ValueError("the receipt records a refusal, which admits nothing")
    if receipt.get("frame_hops") != row["frame_hops"]:
        raise ValueError("the receipt and the version disagree about how many frames were composed")
    matrix = receipt.get("place_from_candidate_row_major")
    scale = receipt.get("candidate_units_to_place_units")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise ValueError("an accepted receipt with no 4x4 transform admits nothing")
    if any(isinstance(value, bool) or not isinstance(value, int | float) for value in matrix):
        raise ValueError("a transform component is not a number")
    if isinstance(scale, bool) or not isinstance(scale, int | float) or scale <= 0:
        raise ValueError("an accepted receipt carries one positive scale")
    return _decimals([float(value) for value in matrix]), _decimal(float(scale))


def _hex(value: object) -> str | None:
    return bytes(value).hex() if value is not None else None


#: One scene's membership, asked from the scene's side. Counts are over LIVE versions only, the
#: same set :func:`place_history` returns, so a scene bundle and a place bundle never disagree
#: about how many versions a place has.
_MEMBERSHIP: Final = """
select v.place_id,
       v.ordinal,
       v.frame_hops,
       tombstone_blocks_place(v.workspace_id, v.place_id) as blocked,
       (select count(*) from place_version w
         where w.workspace_id = v.workspace_id
           and w.place_id = v.place_id
           and not tombstone_blocks_scene(w.workspace_id, w.scene_id)) as version_count,
       (select count(*) from place_version w
         where w.workspace_id = v.workspace_id
           and w.place_id = v.place_id
           and w.ordered_by_utc is null
           and not tombstone_blocks_scene(w.workspace_id, w.scene_id)) as undated_version_count
  from place_version v
 where v.workspace_id = %s
   and v.scene_id = %s
"""


@dataclass(frozen=True, slots=True)
class SceneMembership:
    """Whether one scene belongs to a place, asked from the scene's side.

    ``blocked`` is the place's own guard rather than this scene's. A scene whose place has a
    withdrawn anchor is still perfectly readable on its own, and saying so is the point: a place
    is a join, so withdrawing the anchor takes the shared frame away and leaves every scene
    exactly as readable as it was before it joined.
    """

    place_id: uuid.UUID
    ordinal: int
    frame_hops: int
    version_count: int
    undated_version_count: int
    blocked: bool


def scene_place_membership(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
) -> SceneMembership | None:
    """The place this scene belongs to, or ``None`` when it belongs to none.

    None is the ordinary case and stays the ordinary case: ``docs/place-identity.md`` says a scene
    may belong to at most one place and may belong to none. A caller must not read None as "this
    scene's place could not be determined".
    """
    row = connection.execute(_MEMBERSHIP, (workspace, scene_id)).fetchone()
    if row is None:
        return None
    return SceneMembership(
        place_id=row["place_id"],
        ordinal=int(row["ordinal"]),
        frame_hops=int(row["frame_hops"]),
        version_count=int(row["version_count"]),
        undated_version_count=int(row["undated_version_count"]),
        blocked=bool(row["blocked"]),
    )


# --------------------------------------------------------------------------------------------
# A set of photographs that has a recovery state, and possibly no place at all.
#
# ``0063_place_recovery_state.sql`` is the schema. A record at ``insufficient_overlap`` is a
# room of its own photographs with a stated reason, and this is the read that makes it one: the
# record, its state, why it is in that state, and the member photographs through the viewer
# route every other photograph is served through. The discipline above holds here too. A verdict
# whose bytes do not reproduce its digest is ``invalid``, a receipt this reader cannot obtain is
# ``unavailable``, a photograph the viewer route would not serve now is ``unavailable``, and none
# of them is replaced by something that reads as fine.
# --------------------------------------------------------------------------------------------

_RECORD: Final = """
select r.record_id, r.recovery_state, r.state_seq, r.member_count, r.created_at,
       r.verdict_policy, r.verdict_canonical, r.verdict_sha256, r.verdict_refusal_authorised,
       r.predicted_ceiling, r.verdict_worth_attempting, r.verdict_fault,
       r.photograph_count, r.measured_count, r.edge_min_score, r.edge_count,
       r.largest_component, r.group_count, r.isolated_count
  from place_record r
 where r.workspace_id = %s
   and r.record_id = %s
   and not tombstone_blocks_place_record(r.workspace_id, r.record_id)
"""

# The record's own predicate withdraws the whole set when any member is withdrawn. The member's
# own predicates are asked as well, so this list never relies on a caller having asked first.
_RECORD_MEMBERS: Final = """
select m.capture_id, m.ordinal, c.blob_sha256
  from place_record_member m
  join capture c on c.workspace_id = m.workspace_id and c.capture_id = m.capture_id
 where m.workspace_id = %s
   and m.record_id = %s
   and c.deleted_at is null
   and not tombstone_blocks_capture(m.workspace_id, m.capture_id)
   and not person_withdrawal_blocks_capture(m.workspace_id, m.capture_id)
   and not tombstone_blocks_place_record(m.workspace_id, m.record_id)
 order by m.ordinal
"""

_RECORD_EVENTS: Final = """
select e.seq, e.from_state, e.to_state, e.basis, e.verdict_sha256, e.receipt_artifact_id,
       e.registered_count, e.receipt_accepted, e.withdrawal_tombstone_id, e.recorded_at,
       receipt.content_sha256 as receipt_sha256
  from place_record_state_event e
  left join artifact receipt
    on receipt.workspace_id = e.workspace_id
   and receipt.artifact_id = e.receipt_artifact_id
   and receipt.purged_at is null
   and not person_withdrawal_blocks_artifact(receipt.workspace_id, receipt.artifact_id)
 where e.workspace_id = %s
   and e.record_id = %s
   and not tombstone_blocks_place_record(e.workspace_id, e.record_id)
 order by e.seq
"""

_RECORD_IDS: Final = """
select r.record_id
  from place_record r
 where r.workspace_id = %s
   and r.recovery_state = %s
   and not tombstone_blocks_place_record(r.workspace_id, r.record_id)
 order by r.created_at, r.record_id
"""


@dataclass(frozen=True, slots=True)
class RecordVerdict:
    """The overlap verdict stored with a record, re-checked before anything reads it.

    ``state`` is ``verified`` when the stored bytes reproduce the stored digest and parse as the
    canonical document they claim to be, and ``invalid`` otherwise, in which case nothing below
    ``reason`` is trusted and ``instructions`` is empty. ``refusal_authorised`` is False for a
    policy that has not passed a held-out set, and such a verdict's instructions are for
    evaluation only: :class:`PlaceRecord` never offers them as advice or as a reason.
    """

    state: Literal["verified", "invalid"]
    policy: str
    refusal_authorised: bool
    sha256: str
    predicted_ceiling: PredictedCeiling
    worth_attempting: bool
    fault: str | None
    photograph_count: int
    measured_count: int
    edge_min_score: int
    edge_count: int
    largest_component: int
    groups: int
    isolated: int
    instructions: list[Instruction]
    reason: str | None


@dataclass(frozen=True, slots=True)
class RecordPhotograph:
    """One member photograph, as the viewer route would serve it now, or why it would not."""

    capture_id: uuid.UUID
    ordinal: int
    state: Literal["available", "unavailable"]
    photograph: SceneUnposedPhotographRow | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class RecordStateChange:
    """One applied state event: what moved, on what basis, and what that basis points at."""

    seq: int
    from_state: RecoveryState
    to_state: RecoveryState
    basis: Basis
    verdict_sha256: str | None
    receipt_artifact_id: uuid.UUID | None
    receipt_sha256: str | None
    registered_count: int | None
    receipt_accepted: bool | None
    withdrawal_tombstone_id: uuid.UUID | None
    recorded_at: dt.datetime


@dataclass(frozen=True, slots=True)
class RecordReason:
    """Why a record is in a state that needs a reason, in the instruction vocabulary.

    ``stated`` carries sentences built only from counts this reader re-read. ``unavailable``
    means the evidence the state rests on could not be obtained, and ``invalid`` that it was
    obtained and disagrees with the event naming it; neither carries a sentence, because a
    sentence built from evidence that cannot be checked would be a reason nobody measured.
    """

    state: Literal["stated", "unavailable", "invalid"]
    basis: Basis
    instructions: list[Instruction]
    reason: str | None


@dataclass(frozen=True, slots=True)
class PlaceRecord:
    """A set of photographs, what became of it, why, and the photographs themselves.

    ``reason`` is present for ``insufficient_overlap`` and ``registered_partial``, the two states
    a person needs told what to do about, and for any state a withdrawal lowered. ``advice`` is a
    verified verdict's instructions when the record's state does not rest on that verdict, and
    only when the verdict's policy is authorised to refuse. A policy that has not passed a
    held-out set does not speak to a person at all: its verdict is still returned, under
    ``verdict``, for evaluation, and nothing in it is presented as what to do.
    """

    record_id: uuid.UUID
    recovery_state: RecoveryState
    member_count: int
    created_at: dt.datetime
    photographs: list[RecordPhotograph]
    verdict: RecordVerdict | None
    reason: RecordReason | None
    advice: list[Instruction]
    history: list[RecordStateChange]


def place_record(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    record_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> PlaceRecord | None:
    """Return one record as a room of its photographs, or ``None`` when it is not readable.

    ``None`` covers a record that does not exist, one in another workspace and one any member of
    which was withdrawn, so a caller cannot turn this into an existence oracle. The withdrawal is
    decided by ``tombstone_blocks_place_record`` in the query, never by filtering here.
    """
    row = connection.execute(_RECORD, (workspace, record_id)).fetchone()
    if row is None:
        return None
    viewed_at = evaluation_time(connection)
    members = connection.execute(_RECORD_MEMBERS, (workspace, record_id)).fetchall()
    photographs = [
        _record_photograph(connection, workspace, member, viewed_at) for member in members
    ]
    member_bytes = sorted(bytes(member["blob_sha256"]).hex() for member in members)
    history = [
        RecordStateChange(
            seq=int(event["seq"]),
            from_state=event["from_state"],
            to_state=event["to_state"],
            basis=event["basis"],
            verdict_sha256=_hex(event["verdict_sha256"]),
            receipt_artifact_id=event["receipt_artifact_id"],
            receipt_sha256=_hex(event["receipt_sha256"]),
            registered_count=event["registered_count"],
            receipt_accepted=event["receipt_accepted"],
            withdrawal_tombstone_id=event["withdrawal_tombstone_id"],
            recorded_at=event["recorded_at"],
        )
        for event in connection.execute(_RECORD_EVENTS, (workspace, record_id)).fetchall()
    ]
    verdict = _record_verdict(row)
    current = history[-1] if history else None
    if current is not None and current.seq != int(row["state_seq"]):
        # The schema applies an event in the statement that admits it, so this is a record the
        # reader cannot establish, and it says so rather than reading one of the two.
        raise IntegrityError(f"place record {record_id} and its newest state event disagree")
    reason = None
    if current is not None and (
        row["recovery_state"] in ("insufficient_overlap", "registered_partial")
        or current.basis == "withdrawal"
    ):
        reason = _record_reason(current, verdict, member_bytes, store)
    advice: list[Instruction] = []
    if (
        verdict is not None
        and verdict.state == "verified"
        and verdict.refusal_authorised
        and (reason is None or reason.basis != "verdict")
    ):
        advice = verdict.instructions
    return PlaceRecord(
        record_id=row["record_id"],
        recovery_state=row["recovery_state"],
        member_count=int(row["member_count"]),
        created_at=row["created_at"],
        photographs=photographs,
        verdict=verdict,
        reason=reason,
        advice=advice,
        history=history,
    )


def place_record_ids(
    connection: psycopg.Connection, workspace: uuid.UUID, recovery_state: RecoveryState
) -> list[uuid.UUID]:
    """The readable records in one state, oldest first."""
    if recovery_state not in RECOVERY_STATES:
        raise ValueError(f"{recovery_state!r} is not a recovery state")
    return [
        row["record_id"]
        for row in connection.execute(_RECORD_IDS, (workspace, recovery_state)).fetchall()
    ]


def _record_photograph(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    member: dict[str, Any],
    viewed_at: dt.datetime,
) -> RecordPhotograph:
    photograph = _viewer_photograph(connection, workspace, str(member["capture_id"]), viewed_at)
    return RecordPhotograph(
        capture_id=member["capture_id"],
        ordinal=int(member["ordinal"]),
        state="available" if photograph is not None else "unavailable",
        photograph=photograph,
        reason=None
        if photograph is not None
        else "the viewer route would not serve this photograph now",
    )


def _record_verdict(row: dict[str, Any]) -> RecordVerdict | None:
    if row["verdict_canonical"] is None:
        return None
    canonical = bytes(row["verdict_canonical"])
    digest = bytes(row["verdict_sha256"])
    common = {
        "policy": row["verdict_policy"],
        "refusal_authorised": bool(row["verdict_refusal_authorised"]),
        "sha256": digest.hex(),
        "predicted_ceiling": row["predicted_ceiling"],
        "worth_attempting": bool(row["verdict_worth_attempting"]),
        "fault": row["verdict_fault"],
        "photograph_count": int(row["photograph_count"]),
        "measured_count": int(row["measured_count"]),
        "edge_min_score": int(row["edge_min_score"]),
        "edge_count": int(row["edge_count"]),
        "largest_component": int(row["largest_component"]),
        "groups": int(row["group_count"]),
        "isolated": int(row["isolated_count"]),
    }
    try:
        if hashlib.sha256(canonical).digest() != digest:
            raise ValueError("the stored verdict bytes do not reproduce its digest")
        document = json.loads(canonical)
        if canonical_json(document) != canonical:
            raise ValueError("the stored verdict is not in canonical form")
        items = document["instructions"]["items"]
        if document["instructions"]["vocabulary"] != INSTRUCTION_VOCABULARY:
            raise ValueError("the verdict's instructions use another vocabulary")
        instructions = [instruction(item["key"], item["counts"]) for item in items]
    except (CanonicalisationError, KeyError, TypeError, ValueError) as error:
        return RecordVerdict(state="invalid", instructions=[], reason=str(error), **common)
    return RecordVerdict(state="verified", instructions=instructions, reason=None, **common)


def _record_reason(
    event: RecordStateChange,
    verdict: RecordVerdict | None,
    member_bytes: list[str],
    store: ContentAddressedStore | None,
) -> RecordReason:
    member_count = len(member_bytes)
    if event.basis == "withdrawal":
        return RecordReason("stated", "withdrawal", [], None)
    if event.basis == "verdict":
        if verdict is None or verdict.state != "verified" or verdict.sha256 != event.verdict_sha256:
            return RecordReason(
                "invalid", "verdict", [], "the refusing verdict does not verify against its event"
            )
        return RecordReason("stated", "verdict", verdict.instructions, None)
    if event.basis != "pose_receipt":
        return RecordReason("stated", event.basis, [], None)
    if store is None or event.receipt_sha256 is None:
        return RecordReason(
            "unavailable", "pose_receipt", [], "the pose receipt is not available to this reader"
        )
    try:
        payload = store.get(BlobId(bytes.fromhex(event.receipt_sha256)))
    except BlobNotFoundError:
        return RecordReason(
            "unavailable", "pose_receipt", [], "the pose receipt is missing from object storage"
        )
    except IntegrityError:
        return RecordReason(
            "invalid", "pose_receipt", [], "the pose receipt failed its content digest"
        )
    try:
        receipt = json.loads(payload)
        outcome = outcome_from_pose_receipt(receipt)
        frames = sorted(frame["sha256"] for frame in receipt["manifest"]["frames"])
    except (KeyError, TypeError, ValueError) as error:
        return RecordReason(
            "invalid", "pose_receipt", [], f"the pose receipt is unreadable: {error}"
        )
    if frames != member_bytes:
        return RecordReason(
            "invalid", "pose_receipt", [], "the pose receipt was made from other photographs"
        )
    if (
        outcome.state != event.to_state
        or outcome.registered_count != event.registered_count
        or outcome.accepted != event.receipt_accepted
        or outcome.member_count != member_count
    ):
        return RecordReason(
            "invalid", "pose_receipt", [], "the pose receipt disagrees with the event naming it"
        )
    if outcome.state == "insufficient_overlap":
        said = instruction("run_placed_none", {"photographs": member_count})
    elif outcome.state == "registered_partial":
        said = instruction(
            "run_placed_some",
            {"registered": outcome.registered_count, "photographs": member_count},
        )
    else:
        return RecordReason("stated", "pose_receipt", [], None)
    return RecordReason("stated", "pose_receipt", [said], None)
