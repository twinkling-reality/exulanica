"""What a standpoint scene records, and the one reader both the pipeline and the graph use.

A standpoint scene is several photographs taken from about one place, joined by the rotation
between them: each photograph keeps the depth the depth model gave it and is turned to face the
way it faced, with every photograph's depth brought to one scale where two of them overlap. It is
an estimate from those photographs, never an observation of anything they did not show.

**Why this module is separate from the method.** The method (:mod:`exulanica.reconstruction.
standpoint`) needs numpy and a feature extractor. Reading a recorded scene needs neither, and the
graph reader that serves one to a browser runs in processes that install no numeric stack. So the
record's shape, its validation and the transform a renderer applies live here, in the standard
library only, and the producer builds exactly this record.

**Integers only.** The record is digest bound and canonical JSON refuses floats, so every number
is fixed point in the unit its field names: rotations in parts per billion, scales in parts per
million, angles in millidegrees, distances in millimetres, focal lengths in micropixels.

**What the record claims and what it does not.** It claims the rotation between photographs that
share enough of one view, measured from matched features, and the depth scale that makes their
overlaps agree. It does not claim metric size (the scale is the depth model's own, never
measured), it does not claim anything behind or beside what the photographs showed, and it
promotes no rung. ``DECLARED`` says so inside the bytes.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "DECLARED",
    "PAIR_REFUSALS",
    "STANDPOINT_KIND",
    "STANDPOINT_PROFILE",
    "STANDPOINT_STAGE",
    "ArrangedMember",
    "Arrangement",
    "MemberIntrinsics",
    "MemberReading",
    "StandpointMember",
    "StandpointPair",
    "StandpointRecord",
    "StandpointRecordError",
    "member_refusal",
    "parse_standpoint_record",
    "scene_from_opm_row_major",
]

#: The artifact kind and stage key. Spelled once here, below both the pipeline and the graph.
STANDPOINT_KIND: Final = "standpoint_scene"
STANDPOINT_STAGE: Final = "scene_standpoint"
STANDPOINT_PROFILE: Final = "exulanica.standpoint-scene/v1"

#: Fixed-point units, each named once.
PARTS_PER_BILLION: Final = 1_000_000_000
PARTS_PER_MILLION: Final = 1_000_000
MILLIDEGREES: Final = 1_000
MICROPIXELS: Final = 1_000_000

#: How far a recorded rotation may be from orthonormal and still be read as one. A matrix written
#: in parts per billion is off by at most half a unit per entry, so a row's length is off by about
#: 1e-9; anything past 1e-6 was not written by the producer.
_ORTHONORMAL_TOLERANCE: Final = 1e-6

#: Why a pair of photographs was not joined. Each code is a situation a person can recognise.
PairOutcome = Literal[
    "joined",
    "insufficient_overlap",
    "moved_between_photographs",
    "scene_changed",
    "inconsistent_with_set",
]
PAIR_REFUSALS: Final = frozenset(
    {
        "insufficient_overlap",
        "moved_between_photographs",
        "scene_changed",
        "inconsistent_with_set",
    }
)
_PAIR_OUTCOMES: Final = frozenset({"joined", *PAIR_REFUSALS})

#: What became of each member photograph. ``not_joined`` photographs were read and matched and
#: overlap nothing enough (the pairs say why); the other three were never read at all, and the
#: record holds nothing derived from them: ``not_permitted`` has no current permission for its 3D
#: estimate to be used, ``point_map_unreadable`` has an estimate this join cannot read as one
#: camera's, and ``focal_length_unstated`` does not say what lens took it, without which a turn
#: between photographs cannot be measured.
MemberOutcome = Literal[
    "joined", "not_joined", "not_permitted", "point_map_unreadable", "focal_length_unstated"
]
_READ_OUTCOMES: Final = frozenset({"joined", "not_joined"})
_UNREAD_OUTCOMES: Final = frozenset(
    {"not_permitted", "point_map_unreadable", "focal_length_unstated"}
)
_MEMBER_OUTCOMES: Final = frozenset({*_READ_OUTCOMES, *_UNREAD_OUTCOMES})

IntrinsicsSource = Literal["exif-35mm-equivalent"]
_INTRINSICS_SOURCES: Final = frozenset({"exif-35mm-equivalent"})

#: What the bytes say about themselves, so a reader never has to infer it.
DECLARED: Final[Mapping[str, Any]] = {
    "arrangement": "one standpoint; rotations measured from matched features",
    "citable": False,
    "metric_scale": "the depth model's own scale, never measured",
    "physically_validated": False,
    "promotes_rung": False,
    "unseen_surfaces": "absent; nothing outside the photographs is drawn or filled",
}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StandpointRecordError(ValueError):
    """The bytes are not a standpoint scene this reader can present without guessing."""


@dataclass(frozen=True, slots=True)
class MemberIntrinsics:
    """The lens a member was joined through, the one it states, and the depth model's.

    ``stated_focal_micropixels`` is the photograph's own EXIF 35 mm equivalent in its pixels;
    ``focal_micropixels`` is that value refined from the photograph's overlaps with the others,
    which the join used. The depth model estimated a third, and a renderer re-projects the depth
    into the join's lens with :attr:`lateral_scale`, the ratio of the two: the depth model's points
    keep their distance along the view axis and move sideways onto the photograph's own rays.
    """

    source: IntrinsicsSource
    stated_focal_micropixels: int
    focal_micropixels: int
    depth_model_focal_micropixels: int

    @property
    def lateral_scale(self) -> float:
        return self.depth_model_focal_micropixels / self.focal_micropixels

    def as_payload(self) -> dict[str, Any]:
        return {
            "depth_model_focal_micropixels": self.depth_model_focal_micropixels,
            "focal_micropixels": self.focal_micropixels,
            "source": self.source,
            "stated_focal_micropixels": self.stated_focal_micropixels,
        }


@dataclass(frozen=True, slots=True)
class MemberReading:
    """What the join read from one member: the pixels, the depth grid and the camera."""

    image_sha256: str
    source_size: tuple[int, int]
    model_size: tuple[int, int]
    intrinsics: MemberIntrinsics
    features: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "features": self.features,
            "image_sha256": self.image_sha256,
            "intrinsics": self.intrinsics.as_payload(),
            "model_size": list(self.model_size),
            "source_size": list(self.source_size),
        }


@dataclass(frozen=True, slots=True)
class StandpointMember:
    """One member photograph of the scene, in the scene's own order.

    ``point_map_artifact_ref`` and ``point_map_sha256`` name the estimate the join was offered
    and are absent only for ``not_permitted``, where nothing was offered. ``reading`` is present
    exactly when the photograph was read (``joined`` and ``not_joined``).
    """

    ordinal: int
    member_ref: str
    outcome: MemberOutcome
    point_map_artifact_ref: str | None = None
    point_map_sha256: str | None = None
    reading: MemberReading | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "member_ref": self.member_ref,
            "ordinal": self.ordinal,
            "outcome": self.outcome,
            "point_map_artifact_ref": self.point_map_artifact_ref,
            "point_map_sha256": self.point_map_sha256,
            "reading": None if self.reading is None else self.reading.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class StandpointPair:
    """Everything measured about two photographs, joined or not.

    ``rotation_ppb`` maps directions in photograph ``b``'s camera into photograph ``a``'s, row
    major. ``translation_mm`` is where ``b``'s camera stood in ``a``'s frame, in the depth model's
    units: an estimate from depth, used to recognise photographs taken from different places and
    never to place anything. ``standpoint_residual`` is what a person standing at the standpoint
    would see at the seam: the angle between where the two photographs put one matched point once
    both are turned into place, and ``residual`` is the same after the estimated translation.
    """

    a: int
    b: int
    outcome: PairOutcome
    matches: int
    inliers: int
    inlier_cells: int
    rotation_ppb: tuple[int, ...] | None
    residual_millidegrees: Mapping[str, int] | None
    standpoint_residual_millidegrees: Mapping[str, int] | None
    translation_mm: tuple[int, int, int] | None
    translation_sigma_mm: int | None
    depth_ratio_ppm: int | None
    changed_ppm: int | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "changed_ppm": self.changed_ppm,
            "depth_ratio_ppm": self.depth_ratio_ppm,
            "inlier_cells": self.inlier_cells,
            "inliers": self.inliers,
            "matches": self.matches,
            "outcome": self.outcome,
            "residual_millidegrees": (
                None if self.residual_millidegrees is None else dict(self.residual_millidegrees)
            ),
            "rotation_ppb": None if self.rotation_ppb is None else list(self.rotation_ppb),
            "standpoint_residual_millidegrees": (
                None
                if self.standpoint_residual_millidegrees is None
                else dict(self.standpoint_residual_millidegrees)
            ),
            "translation_mm": None if self.translation_mm is None else list(self.translation_mm),
            "translation_sigma_mm": self.translation_sigma_mm,
        }


@dataclass(frozen=True, slots=True)
class ArrangedMember:
    """One photograph's place in the standpoint: which way it faced, and its depth scale.

    ``scene_from_camera_ppb`` turns directions in the photograph's own camera frame (OPM axes: +X
    right, +Y up, -Z forward) into the scene frame, whose +Y is the estimated up and whose -Z is
    the reference photograph's heading. Every camera stands at the scene origin.
    """

    ordinal: int
    scene_from_camera_ppb: tuple[int, ...]
    depth_scale_ppm: int
    lateral_scale_ppm: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "depth_scale_ppm": self.depth_scale_ppm,
            "lateral_scale_ppm": self.lateral_scale_ppm,
            "ordinal": self.ordinal,
            "scene_from_camera_ppb": list(self.scene_from_camera_ppb),
        }


@dataclass(frozen=True, slots=True)
class Arrangement:
    """The joined standpoint: the largest set of photographs every accepted pair connects."""

    reference: int
    members: tuple[ArrangedMember, ...]
    up: Mapping[str, Any]
    rotation_solve: Mapping[str, Any]
    scale_solve: Mapping[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "members": [member.as_payload() for member in self.members],
            "reference": self.reference,
            "rotation_solve": dict(self.rotation_solve),
            "scale_solve": dict(self.scale_solve),
            "up": dict(self.up),
        }


@dataclass(frozen=True, slots=True)
class StandpointRecord:
    scene_ref: str
    policy_sha256: str
    stage_version: int
    feature_extractor: Mapping[str, str]
    members: tuple[StandpointMember, ...]
    pairs: tuple[StandpointPair, ...]
    components: tuple[tuple[int, ...], ...]
    arrangement: Arrangement | None
    refusal: Literal["nothing_joined"] | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "arrangement": None if self.arrangement is None else self.arrangement.as_payload(),
            "components": [list(component) for component in self.components],
            "declared": dict(DECLARED),
            "feature_extractor": dict(self.feature_extractor),
            "members": [member.as_payload() for member in self.members],
            "pairs": [pair.as_payload() for pair in self.pairs],
            "policy_sha256": self.policy_sha256,
            "profile": STANDPOINT_PROFILE,
            "refusal": self.refusal,
            "scene_ref": self.scene_ref,
            "stage": {"key": STANDPOINT_STAGE, "version": self.stage_version},
        }

    def to_bytes(self) -> bytes:
        return _canonical(self.as_payload())

    def member(self, ordinal: int) -> StandpointMember:
        for member in self.members:
            if member.ordinal == ordinal:
                return member
        raise KeyError(ordinal)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    """Sorted keys, no whitespace, UTF-8: the repository's canonical JSON, integers only."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _int(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StandpointRecordError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise StandpointRecordError(f"{field} must be at least {minimum}")
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise StandpointRecordError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise StandpointRecordError(f"{field} must be a list")
    return value


def _text(value: object, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or (pattern is not None and not pattern.fullmatch(value)):
        raise StandpointRecordError(f"{field} is not a valid value")
    return value


def _pair_of_ints(value: object, field: str) -> tuple[int, int]:
    items = _list(value, field)
    if len(items) != 2:
        raise StandpointRecordError(f"{field} must hold two integers")
    return (_int(items[0], field, minimum=1), _int(items[1], field, minimum=1))


def _rotation(value: object, field: str) -> tuple[int, ...]:
    items = _list(value, field)
    if len(items) != 9:
        raise StandpointRecordError(f"{field} must hold nine integers")
    entries = tuple(_int(item, field) for item in items)
    m = [entry / PARTS_PER_BILLION for entry in entries]
    for row in range(3):
        for other in range(3):
            dot = sum(m[row * 3 + k] * m[other * 3 + k] for k in range(3))
            if abs(dot - (1.0 if row == other else 0.0)) > _ORTHONORMAL_TOLERANCE:
                raise StandpointRecordError(f"{field} is not a rotation")
    determinant = (
        m[0] * (m[4] * m[8] - m[5] * m[7])
        - m[1] * (m[3] * m[8] - m[5] * m[6])
        + m[2] * (m[3] * m[7] - m[4] * m[6])
    )
    if abs(determinant - 1.0) > _ORTHONORMAL_TOLERANCE:
        raise StandpointRecordError(f"{field} is a reflection, not a rotation")
    return entries


def _stats(value: object, field: str) -> Mapping[str, int] | None:
    if value is None:
        return None
    stats = _mapping(value, field)
    return {str(key): _int(item, f"{field}.{key}", minimum=0) for key, item in stats.items()}


def _parse_reading(raw: object, field: str) -> MemberReading:
    item = _mapping(raw, field)
    intrinsics_raw = _mapping(item.get("intrinsics"), f"{field}.intrinsics")
    source = intrinsics_raw.get("source")
    if source not in _INTRINSICS_SOURCES:
        raise StandpointRecordError(f"{field}.intrinsics.source is not one this reader knows")
    return MemberReading(
        image_sha256=_text(item.get("image_sha256"), f"{field}.image_sha256", _SHA256),
        source_size=_pair_of_ints(item.get("source_size"), f"{field}.source_size"),
        model_size=_pair_of_ints(item.get("model_size"), f"{field}.model_size"),
        intrinsics=MemberIntrinsics(
            source=source,
            stated_focal_micropixels=_int(
                intrinsics_raw.get("stated_focal_micropixels"), f"{field}.stated_focal", minimum=1
            ),
            focal_micropixels=_int(
                intrinsics_raw.get("focal_micropixels"), f"{field}.focal", minimum=1
            ),
            depth_model_focal_micropixels=_int(
                intrinsics_raw.get("depth_model_focal_micropixels"),
                f"{field}.depth_model_focal",
                minimum=1,
            ),
        ),
        features=_int(item.get("features"), f"{field}.features", minimum=0),
    )


def _parse_member(raw: object, index: int) -> StandpointMember:
    field = f"members[{index}]"
    item = _mapping(raw, field)
    outcome = item.get("outcome")
    if outcome not in _MEMBER_OUTCOMES:
        raise StandpointRecordError(f"{field}.outcome is not one this reader knows")
    artifact = item.get("point_map_artifact_ref")
    digest = item.get("point_map_sha256")
    reading = item.get("reading")
    if outcome == "not_permitted":
        if artifact is not None or digest is not None or reading is not None:
            raise StandpointRecordError(f"{field} was not permitted and still records a reading")
    elif artifact is None or digest is None:
        raise StandpointRecordError(f"{field} does not name the estimate it was offered")
    if (outcome in _READ_OUTCOMES) != (reading is not None):
        raise StandpointRecordError(f"{field} records a reading exactly when it was read")
    return StandpointMember(
        ordinal=_int(item.get("ordinal"), f"{field}.ordinal", minimum=0),
        member_ref=_text(item.get("member_ref"), f"{field}.member_ref", _UUID),
        outcome=outcome,
        point_map_artifact_ref=(
            None if artifact is None else _text(artifact, f"{field}.point_map_artifact_ref", _UUID)
        ),
        point_map_sha256=None if digest is None else _text(digest, f"{field}.sha256", _SHA256),
        reading=None if reading is None else _parse_reading(reading, f"{field}.reading"),
    )


def _parse_pair(raw: object, index: int, ordinals: frozenset[int]) -> StandpointPair:
    field = f"pairs[{index}]"
    item = _mapping(raw, field)
    a = _int(item.get("a"), f"{field}.a", minimum=0)
    b = _int(item.get("b"), f"{field}.b", minimum=0)
    if a not in ordinals or b not in ordinals or a >= b:
        raise StandpointRecordError(f"{field} does not name two members in order")
    outcome = item.get("outcome")
    if outcome not in _PAIR_OUTCOMES:
        raise StandpointRecordError(f"{field}.outcome is not one this reader knows")
    rotation = item.get("rotation_ppb")
    translation = item.get("translation_mm")
    parsed_translation: tuple[int, int, int] | None = None
    if translation is not None:
        values = _list(translation, f"{field}.translation_mm")
        if len(values) != 3:
            raise StandpointRecordError(f"{field}.translation_mm must hold three integers")
        parsed_translation = (
            _int(values[0], field),
            _int(values[1], field),
            _int(values[2], field),
        )
    sigma = item.get("translation_sigma_mm")
    ratio = item.get("depth_ratio_ppm")
    changed = item.get("changed_ppm")
    pair = StandpointPair(
        a=a,
        b=b,
        outcome=outcome,
        matches=_int(item.get("matches"), f"{field}.matches", minimum=0),
        inliers=_int(item.get("inliers"), f"{field}.inliers", minimum=0),
        inlier_cells=_int(item.get("inlier_cells"), f"{field}.inlier_cells", minimum=0),
        rotation_ppb=None if rotation is None else _rotation(rotation, f"{field}.rotation_ppb"),
        residual_millidegrees=_stats(item.get("residual_millidegrees"), f"{field}.residual"),
        standpoint_residual_millidegrees=_stats(
            item.get("standpoint_residual_millidegrees"), f"{field}.standpoint_residual"
        ),
        translation_mm=parsed_translation,
        translation_sigma_mm=None if sigma is None else _int(sigma, field, minimum=0),
        depth_ratio_ppm=None if ratio is None else _int(ratio, field, minimum=1),
        changed_ppm=None if changed is None else _int(changed, field, minimum=0),
    )
    if pair.outcome == "joined" and (pair.rotation_ppb is None or pair.depth_ratio_ppm is None):
        raise StandpointRecordError(f"{field} is joined without a rotation and a depth ratio")
    return pair


def _parse_arrangement(raw: object, ordinals: frozenset[int]) -> Arrangement:
    item = _mapping(raw, "arrangement")
    members: list[ArrangedMember] = []
    for index, member_raw in enumerate(_list(item.get("members"), "arrangement.members")):
        field = f"arrangement.members[{index}]"
        member = _mapping(member_raw, field)
        ordinal = _int(member.get("ordinal"), f"{field}.ordinal", minimum=0)
        if ordinal not in ordinals:
            raise StandpointRecordError(f"{field} names no member")
        members.append(
            ArrangedMember(
                ordinal=ordinal,
                scene_from_camera_ppb=_rotation(
                    member.get("scene_from_camera_ppb"), f"{field}.scene_from_camera_ppb"
                ),
                depth_scale_ppm=_int(member.get("depth_scale_ppm"), f"{field}.depth", minimum=1),
                lateral_scale_ppm=_int(
                    member.get("lateral_scale_ppm"), f"{field}.lateral", minimum=1
                ),
            )
        )
    if len(members) < 2:
        raise StandpointRecordError("an arrangement joins at least two photographs")
    if len({member.ordinal for member in members}) != len(members):
        raise StandpointRecordError("an arrangement names a photograph twice")
    reference = _int(item.get("reference"), "arrangement.reference", minimum=0)
    if reference not in {member.ordinal for member in members}:
        raise StandpointRecordError("the arrangement's reference is not one of its photographs")
    return Arrangement(
        reference=reference,
        members=tuple(members),
        up=_mapping(item.get("up"), "arrangement.up"),
        rotation_solve=_mapping(item.get("rotation_solve"), "arrangement.rotation_solve"),
        scale_solve=_mapping(item.get("scale_solve"), "arrangement.scale_solve"),
    )


def parse_standpoint_record(
    data: bytes,
    *,
    expected_scene_ref: str | None = None,
    expected_members: Sequence[tuple[str, str | None, str | None]] | None = None,
) -> StandpointRecord:
    """Read a recorded standpoint scene, or refuse it by name.

    ``expected_members`` is ``(member_ref, point_map_artifact_ref, point_map_sha256)`` in
    ordinal order, as the reader's own live rows say, with ``None`` for a member that has no
    estimate. A record naming anything else describes some
    other set of photographs, and a transform read out of it would be placed on the wrong ones.
    The bytes must also be exactly the canonical encoding of what they parse to, so two readers can
    never disagree about what one digest said.
    """
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StandpointRecordError("the standpoint record is not JSON") from error
    document = _mapping(payload, "record")
    if document.get("profile") != STANDPOINT_PROFILE:
        raise StandpointRecordError(f"the record is not {STANDPOINT_PROFILE}")
    if document.get("declared") != dict(DECLARED):
        raise StandpointRecordError("the record does not declare what a standpoint scene is")
    stage = _mapping(document.get("stage"), "stage")
    if stage.get("key") != STANDPOINT_STAGE:
        raise StandpointRecordError("the record was not written by the standpoint stage")
    scene_ref = _text(document.get("scene_ref"), "scene_ref", _UUID)
    if expected_scene_ref is not None and scene_ref != expected_scene_ref:
        raise StandpointRecordError("the record belongs to another scene")
    members = tuple(
        _parse_member(raw, index) for index, raw in enumerate(_list(document.get("members"), "m"))
    )
    if [member.ordinal for member in members] != list(range(len(members))):
        raise StandpointRecordError("members must be listed once each, in ordinal order")
    if expected_members is not None and [
        (m.member_ref, m.point_map_artifact_ref, m.point_map_sha256) for m in members
    ] != list(expected_members):
        raise StandpointRecordError("the record names other photographs or other point maps")
    ordinals = frozenset(member.ordinal for member in members)
    pairs = tuple(
        _parse_pair(raw, index, ordinals)
        for index, raw in enumerate(_list(document.get("pairs"), "pairs"))
    )
    if len({(pair.a, pair.b) for pair in pairs}) != len(pairs):
        raise StandpointRecordError("a pair is recorded twice")
    components = tuple(
        tuple(_int(o, "components", minimum=0) for o in _list(component, "components"))
        for component in _list(document.get("components"), "components")
    )
    seen = [ordinal for component in components for ordinal in component]
    if sorted(seen) != sorted(ordinals):
        raise StandpointRecordError("components must partition the members")
    refusal = document.get("refusal")
    arrangement_raw = document.get("arrangement")
    if arrangement_raw is None:
        if refusal != "nothing_joined":
            raise StandpointRecordError("a record with no arrangement names why")
        arrangement = None
    else:
        if refusal is not None:
            raise StandpointRecordError("a record with an arrangement refuses nothing")
        arrangement = _parse_arrangement(arrangement_raw, ordinals)
        joined = {member.ordinal for member in arrangement.members}
        if tuple(sorted(joined)) not in {tuple(sorted(c)) for c in components}:
            raise StandpointRecordError("the arrangement is not one of the recorded components")
        for member in members:
            if (member.outcome == "joined") != (member.ordinal in joined):
                raise StandpointRecordError("member outcomes disagree with the arrangement")
    record = StandpointRecord(
        scene_ref=scene_ref,
        policy_sha256=_text(document.get("policy_sha256"), "policy_sha256", _SHA256),
        stage_version=_int(stage.get("version"), "stage.version", minimum=1),
        feature_extractor={
            str(key): _text(value, "feature_extractor")
            for key, value in _mapping(document.get("feature_extractor"), "fe").items()
        },
        members=members,
        pairs=pairs,
        components=components,
        arrangement=arrangement,
        refusal=refusal,
    )
    if record.to_bytes() != data:
        raise StandpointRecordError("the bytes are not the canonical encoding of the record")
    return record


#: When a member photograph is refused against several others, the reason a person can act on
#: first: having moved is the one they can fix by standing still, a change by taking the photographs
#: together, and too little overlap by turning less between photographs.
_REFUSAL_PRECEDENCE: Final = (
    "moved_between_photographs",
    "scene_changed",
    "inconsistent_with_set",
    "insufficient_overlap",
)


def member_refusal(record: StandpointRecord, ordinal: int) -> str | None:
    """Why this member is not in the arrangement, or None when it is.

    A member that was never read says why (``not_permitted``, ``point_map_unreadable``,
    ``focal_length_unstated``). One that
    was read and not joined takes the first of its pairs' refusals in :data:`_REFUSAL_PRECEDENCE`;
    a member of a smaller group joined among itself was still refused against the arrangement,
    and those refusals are the ones that say why it is apart.
    """
    member = record.member(ordinal)
    if member.outcome in _UNREAD_OUTCOMES:
        return member.outcome
    if member.outcome == "joined":
        return None
    refused = {pair.outcome for pair in record.pairs if ordinal in (pair.a, pair.b)}
    for reason in _REFUSAL_PRECEDENCE:
        if reason in refused:
            return reason
    return "insufficient_overlap"


def scene_from_opm_row_major(
    member: ArrangedMember, camera_position: Sequence[float] = (0.0, 0.0, 0.0)
) -> tuple[float, ...]:
    """The affine a renderer applies to one member's raw OPM positions, row major, 4 x 4.

    ``R diag(s l, s l, s) T(-camera)``: the point map is moved so its camera is at the standpoint,
    its depth is brought to the scene's scale ``s``, its lateral extent is re-projected onto the
    photograph's own rays by ``l`` (see :class:`MemberIntrinsics`), and it is turned to face the
    way the photograph faced. Not a similarity when ``l`` is not 1, which is why it is stated as a
    full affine rather than as a rotation and one scale.
    """
    r = [value / PARTS_PER_BILLION for value in member.scene_from_camera_ppb]
    depth = member.depth_scale_ppm / PARTS_PER_MILLION
    lateral = depth * member.lateral_scale_ppm / PARTS_PER_MILLION
    column_scales = (lateral, lateral, depth)
    linear = [
        r[row * 3 + column] * column_scales[column] for row in range(3) for column in range(3)
    ]
    cx, cy, cz = (float(value) for value in camera_position)
    translation = [
        -(linear[row * 3] * cx + linear[row * 3 + 1] * cy + linear[row * 3 + 2] * cz)
        for row in range(3)
    ]
    matrix = (
        linear[0], linear[1], linear[2], translation[0],
        linear[3], linear[4], linear[5], translation[1],
        linear[6], linear[7], linear[8], translation[2],
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip
    if not all(math.isfinite(value) for value in matrix):
        raise StandpointRecordError("the member's transform is not finite")
    return matrix
