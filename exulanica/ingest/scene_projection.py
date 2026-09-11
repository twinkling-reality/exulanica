"""What a graph reader would rebuild from a published scene, written down when it publishes.

A cold ``GET /graph`` used to rebuild the same answer in every fresh process. It re-fetched and
re-verified every point map, parsed the pose receipt, refitted each member's scale and walked
every retained point in Python, all to reach a placement outcome the worker had already
computed and verified minutes earlier, and a set of recovered cameras that are a pure function
of a pose receipt which by then could not change. MEASURED 2026-09-09 and recorded in
``docs/evaluation/2026-09-09-graph-read-memo.json``: 48 seconds for the 210 member volcanic scene,
780 MB of point maps and a 108 MB pose receipt, none of it depending on anything mutable. The
in-process memo added that day fixed the second request and left the first exactly as it was.

So the worker writes the answer down. This module is that format.

WHAT IS BOUND, and why each one is. A reader must be able to establish, without opening a point
map or a pose receipt, that this projection still answers for the scene in front of it:

*   ``pose_receipt_sha256``, ``placement_receipt_sha256`` and ``gate_receipt_sha256`` are the
    three content addresses the scene row already carries. A rebuilt scene has different ones, so
    a projection belonging to a superseded build cannot be mistaken for the current one.
*   ``member_capture_refs`` is the scene's member list, in scene order. It is bound because it is
    the one input to the placement that no digest covers: withdrawing a member leaves all three
    receipts byte-identical, and the projection has to stop answering.
*   ``point_map_inputs`` is the placement's point-map references, in record order. This one is
    a self-check rather than an independent fact: a reader derives its side from the placement
    bytes, which the digest above already pins, so it cannot refuse a projection that digest
    accepts. It is carried because it makes the artifact auditable on its own and because this
    module checks its own output against it before publishing. What sees a superseded,
    re-pointed or purged point-map ARTIFACT ROW is the reader's live query, not this.

WHAT IS DELIBERATELY NOT BOUND. Whether a point map's bytes are still in the store is a live
fact, not a property of any digest, so presence is checked per request by the reader and is
absent from this artifact. A projection therefore never asserts availability; it asserts what the
geometry WOULD be for the members whose bytes are there.

WHAT MAY NOT ENTER IT. Nothing privacy-bearing. No person region, no review state, no source
photograph digest, no pose manifest frame. The source digests matter most and are the reason this
is stated as a rule rather than left to notice: re-masking a withdrawn person changes
``read_source_sha256``, and ``scene_allowed`` in ``exulanica/graph/asset_read_policy.py`` denies a
scene by comparing the pose manifest's frame digest against the live artifact row. A copy of
those digests in a durable artifact would be a second, stale answer to a question the asset-read
policy exists to ask fresh. This artifact carries capture and artifact identifiers, content
digests of point maps, placement transforms and camera calibration, every one of which the graph
response already contains, and nothing else.

WHAT IT IS NOT. It is not a receipt and it promotes nothing. The gate decides the rung and the
placement record remains the durable statement of where each point map sits; this only saves a
reader from recomputing a conclusion those two already stand behind. A reader that refuses a
projection loses time and nothing else, which is why every check below fails closed.

ITS IDENTITY HAS GENERATIONS. The artifact id is ``uuid5`` over an identity key derived from the
scene and the three receipt digests, and ``artifact`` is unique on that key over EVERY row,
purged or not. So a purged projection occupies its id forever: the insert that would replace it is
``on conflict do nothing``, and removing or un-purging the row to make room would erase the record
that its bytes were destroyed. ``projection_identity_key`` gives the replacement the next
generation of the same key instead. Generation 0 is the key itself, so every projection written
before generations existed keeps its identity, and the worker, which writes a set of receipts'
projection in the same acceptance that publishes those receipts, never needs any other.

The reader half lives in ``exulanica/graph/reconstruction_scenes.py`` and parses these bytes
independently rather than calling into this module, because ``graph`` and ``ingest`` are
siblings in the ``pyproject.toml`` layers contract and neither may import the other.
``POINT_MAP_KIND`` is spelled twice for the same reason and a test pins those spellings, and a
test pins these.

That is not the only shape available and it is not the best one. ``GENERATED_SCENE_KIND`` is
spelled ONCE, in ``exulanica/reconstruction/generated.py``, and imported by both siblings,
because ``exulanica.reconstruction`` sits below both. This module imports nothing but the
standard library and ``exulanica.reconstruction.placement``, so it would be legal there today,
unmoved, and putting it there would delete the reader's copy of the parser outright. The brief
that asked for this work named this path, so this is where it is.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.reconstruction.placement import PlacementRecord, recovered_camera_records

__all__ = [
    "SCENE_PROJECTION_ENVELOPE",
    "SCENE_PROJECTION_KIND",
    "SCENE_PROJECTION_PROFILE",
    "SCENE_PROJECTION_STAGE",
    "SceneProjection",
    "build_scene_projection",
    "projection_identity_key",
    "projection_point_map_inputs",
    "validate_scene_projection",
]

#: The payload profile. The envelope carries its own, one level out, exactly as the placement
#: record does, so that a payload digest can be checked before anything inside it is read.
SCENE_PROJECTION_PROFILE: Final = "exulanica.scene-graph-projection/v1"
SCENE_PROJECTION_ENVELOPE: Final = "exulanica.scene-graph-projection-envelope/v1"

#: Spelled here and again in ``exulanica/graph/reconstruction_scenes.py``, for the same reason
#: ``POINT_MAP_KIND`` is spelled twice: the layers contract forbids ``graph`` and ``ingest``
#: from importing each other, and a test pins the two spellings together.
#:
#: The stage itself is declared in ``exulanica/ingest/stages/__init__.py`` with every other
#: stage, so ``pipeline_digest`` covers it and ``stage_definition`` records it. A test pins that
#: entry's ``output_kind`` to the constant above.
SCENE_PROJECTION_KIND: Final = "scene_projection"
SCENE_PROJECTION_STAGE: Final = "scene_projection"


def _canonical(value: object) -> bytes:
    # `allow_nan=False` because the default would write `NaN` and `Infinity`, which are not JSON
    # and which no reader here accepts. Every number is guarded before it gets this far; this is
    # the bar behind the guard.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def projection_identity_key(base_key: str, generation: int) -> str:
    """The identity key of the ``generation``-th projection written under ``base_key``.

    ``base_key`` is the scene artifact key the worker derives from the scene and the three
    receipt digests, and generation 0 returns it unchanged. A later generation exists only
    because every one before it can no longer answer a reader, which a writer establishes from the
    rows before it takes one; this function only names it. Length-prefixed like the base key, so
    no generation of one key can be spelled as a generation of another.
    """
    _require_digest(base_key, "projection base key")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("a projection generation is a non-negative integer")
    if generation == 0:
        return base_key
    hasher = hashlib.sha256()
    for part in (
        b"exulanica/scene-projection-generation",
        b"1",
        base_key.encode("ascii"),
        str(generation).encode("ascii"),
    ):
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)
    return hasher.hexdigest()


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be lowercase SHA-256 hex")


def _finite(value: object, field: str) -> float:
    """Refuse a value that ``json.dumps`` would write as ``NaN`` or ``Infinity``.

    Those are not JSON, and a projection is read back by a parser that is entitled to refuse
    them. Refusing here means a scene fails to publish a projection rather than publishing bytes
    no reader will accept, which is the direction this whole module fails in.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class ProjectedPlacement:
    """One member's geometry, as the graph would emit it."""

    capture_ref: str
    point_map_artifact_ref: str
    point_map_content_sha256: str
    scene_from_opm_row_major: tuple[float, ...]
    local_units_to_scene_units: float
    scale_status: str


@dataclass(frozen=True, slots=True)
class ProjectedExclusion:
    """One member the placement did not place, and why."""

    capture_ref: str
    registered: bool
    reason: str


@dataclass(frozen=True, slots=True)
class SceneProjection:
    """A validated projection, as its reader gets it back."""

    scene_ref: str
    pose_receipt_sha256: str
    placement_receipt_sha256: str
    gate_receipt_sha256: str
    member_capture_refs: tuple[str, ...]
    point_map_inputs: tuple[tuple[str, str, str], ...]
    placed: tuple[ProjectedPlacement, ...]
    excluded: tuple[ProjectedExclusion, ...]
    recovered_cameras: dict[str, dict[str, Any]]


def projection_point_map_inputs(
    placement: PlacementRecord,
) -> tuple[tuple[str, str, str], ...]:
    """The placement's point-map references in record order, as the binding spells them.

    In record order rather than sorted, because the reader builds the same tuple by walking the
    placement JSON it already parses and the two must agree exactly.
    """
    return tuple(
        (item.capture_ref, item.artifact_ref, item.content_sha256)
        for item in placement.point_map_inputs
    )


def build_scene_projection(
    *,
    scene_ref: str,
    pose_receipt: bytes,
    pose_receipt_sha256: str,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
    placement: PlacementRecord,
) -> bytes:
    """Project one published scene into the bytes a graph reader can serve without rebuilding.

    ``placement`` must already have been validated against ``pose_receipt`` and the point maps.
    The placement half of the payload is a transcription and nothing more; transcribing an
    unvalidated record would be laundering it.

    The cameras are NOT a transcription. ``recovered_camera_records`` parses the whole pose
    receipt and derives each 4x4 from a quaternion and a translation, and before this stage
    existed no ingest path called it at all: its only callers were in ``exulanica.graph``. So
    this is the first time the worker computes them, which is why the caller treats a raise
    here as a refusal of the projection alone rather than as a disagreement between records it
    has already checked.
    """
    _require_digest(pose_receipt_sha256, "pose receipt digest")
    _require_digest(placement_receipt_sha256, "placement receipt digest")
    _require_digest(gate_receipt_sha256, "gate receipt digest")
    if not scene_ref:
        raise ValueError("a projection needs the scene it answers for")
    if placement.scene_ref != scene_ref:
        raise ValueError("the placement names another scene")
    if placement.pose_receipt_sha256 != pose_receipt_sha256:
        raise ValueError("the placement was not built from this pose receipt")
    members = tuple(member_capture_refs)
    if not members or len(set(members)) != len(members):
        raise ValueError("scene members must be non-empty and duplicate free")
    if tuple(placement.member_capture_refs) != members:
        raise ValueError("the placement member list differs from the scene member list")

    cameras = recovered_camera_records(pose_receipt)
    payload = {
        "profile": SCENE_PROJECTION_PROFILE,
        "scene_ref": scene_ref,
        "bindings": {
            "pose_receipt_sha256": pose_receipt_sha256,
            "placement_receipt_sha256": placement_receipt_sha256,
            "gate_receipt_sha256": gate_receipt_sha256,
            "member_capture_refs": list(members),
            "point_map_inputs": [
                {"capture_ref": capture, "artifact_ref": artifact, "content_sha256": digest}
                for capture, artifact, digest in projection_point_map_inputs(placement)
            ],
        },
        "placed": [
            {
                "capture_ref": member.capture_ref,
                "point_map_artifact_ref": member.point_map_artifact_ref,
                "point_map_content_sha256": member.point_map_content_sha256,
                "scene_from_opm_row_major": [
                    _finite(value, "placement transform") for value in member.scene_from_opm
                ],
                "local_units_to_scene_units": _finite(
                    member.local_units_to_scene_units, "placement scale"
                ),
                "scale_status": member.scale_status,
            }
            for member in placement.placed
        ],
        "excluded": [
            {
                "capture_ref": member.capture_ref,
                "registered": member.registered,
                "reason": member.reason,
            }
            for member in placement.excluded
        ],
        "recovered_cameras": _camera_payload(cameras),
    }
    envelope = {
        "profile": SCENE_PROJECTION_ENVELOPE,
        "payload_sha256": _digest(_canonical(payload)),
        "projection": payload,
    }
    return _canonical(envelope) + b"\n"


#: Exactly what `SceneRecoveredCameraRow` and `SceneRecoveredCalibrationRow` in
#: `exulanica/graph/payload.py` accept, and both forbid an extra key. Spelled here so a projection
#: that would make the graph raise on construction is refused at publication instead.
CAMERA_FIELDS: Final = ("scene_from_camera_row_major", "calibration", "projection")
CALIBRATION_FIELDS: Final = ("model", "width", "height", "fx", "fy", "cx", "cy", "parameters")
CAMERA_PROJECTIONS: Final = ("pinhole", "pinhole-approximation")


def _camera_payload(cameras: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Transcribe the recovered cameras, refusing anything the graph row would not accept.

    Every number is checked finite, because `json.dumps` would otherwise write `NaN` and no
    reader may accept that. `width` and `height` are carried through as the integers they are:
    `SceneRecoveredCalibrationRow` declares them `int`, and rounding them to float here would put
    `"width":160.0` in a durable artifact whose response only came out byte-identical because
    pydantic happened to coerce it back. A non-integral value would have been a 500 instead.
    """
    projected: dict[str, Any] = {}
    for capture_ref, camera in cameras.items():
        if tuple(sorted(camera)) != tuple(sorted(CAMERA_FIELDS)):
            raise ValueError("a recovered camera does not carry exactly the fields the graph emits")
        calibration = camera["calibration"]
        if not isinstance(calibration, dict) or tuple(sorted(calibration)) != tuple(
            sorted(CALIBRATION_FIELDS)
        ):
            raise ValueError("a recovered camera calibration is malformed")
        if camera["projection"] not in CAMERA_PROJECTIONS:
            raise ValueError("a recovered camera names an unsupported projection")
        matrix = camera["scene_from_camera_row_major"]
        if not isinstance(matrix, list) or len(matrix) != 16:
            raise ValueError("a recovered camera transform is not a 4x4 matrix")
        parameters = calibration["parameters"]
        if not isinstance(parameters, list):
            raise ValueError("a recovered camera parameter list is malformed")
        projected[capture_ref] = {
            "scene_from_camera_row_major": [
                _finite(value, "recovered camera transform") for value in matrix
            ],
            "calibration": {
                "model": str(calibration["model"]),
                "width": _whole(calibration["width"], "calibration width"),
                "height": _whole(calibration["height"], "calibration height"),
                **{
                    key: _finite(calibration[key], f"calibration {key}")
                    for key in ("fx", "fy", "cx", "cy")
                },
                "parameters": [_finite(value, "calibration parameter") for value in parameters],
            },
            "projection": camera["projection"],
        }
    return projected


def _whole(value: object, field: str) -> int:
    """An integer, kept an integer. See `_camera_payload` for why this is not `_finite`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def validate_scene_projection(
    data: bytes,
    *,
    expected_scene_ref: str,
    pose_receipt_sha256: str,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
    point_map_inputs: Sequence[tuple[str, str, str]],
) -> SceneProjection:
    """Refuse a projection that is malformed or bound to anything but these exact inputs.

    Every failure raises ``ValueError``. The worker uses this to check its own bytes before it
    publishes them, and the backfill uses it to check what it wrote. The graph reader does the
    same checks in its own module because it may not import this one.
    """
    try:
        envelope = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("the scene projection is not JSON") from error
    if not isinstance(envelope, dict) or envelope.get("profile") != SCENE_PROJECTION_ENVELOPE:
        raise ValueError("the scene projection envelope version is unsupported")
    payload = envelope.get("projection")
    payload_digest = envelope.get("payload_sha256")
    if not isinstance(payload_digest, str) or _digest(_canonical(payload)) != payload_digest:
        raise ValueError("the scene projection payload disagrees with its digest")
    if not isinstance(payload, dict) or payload.get("profile") != SCENE_PROJECTION_PROFILE:
        raise ValueError("the scene projection format version is unsupported")
    if payload.get("scene_ref") != expected_scene_ref:
        raise ValueError("the scene projection names another scene")

    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("the scene projection bindings are malformed")
    for field, expected in (
        ("pose_receipt_sha256", pose_receipt_sha256),
        ("placement_receipt_sha256", placement_receipt_sha256),
        ("gate_receipt_sha256", gate_receipt_sha256),
    ):
        if bindings.get(field) != expected:
            raise ValueError(f"the scene projection is bound to another {field}")
    if bindings.get("member_capture_refs") != list(member_capture_refs):
        raise ValueError("the scene projection is bound to another member list")
    bound_inputs = bindings.get("point_map_inputs")
    if not isinstance(bound_inputs, list):
        raise ValueError("the scene projection point-map bindings are malformed")
    if [
        (item.get("capture_ref"), item.get("artifact_ref"), item.get("content_sha256"))
        if isinstance(item, dict)
        else None
        for item in bound_inputs
    ] != [tuple(item) for item in point_map_inputs]:
        raise ValueError("the scene projection is bound to other point maps")

    placed = tuple(_placed(item) for item in _list(payload.get("placed"), "placed"))
    excluded = tuple(_excluded(item) for item in _list(payload.get("excluded"), "excluded"))
    outcomes = [member.capture_ref for member in placed] + [
        member.capture_ref for member in excluded
    ]
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(member_capture_refs):
        raise ValueError("every scene member needs exactly one projected outcome")
    cameras = payload.get("recovered_cameras")
    if not isinstance(cameras, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict) for key, value in cameras.items()
    ):
        raise ValueError("the scene projection recovered cameras are malformed")
    return SceneProjection(
        scene_ref=expected_scene_ref,
        pose_receipt_sha256=pose_receipt_sha256,
        placement_receipt_sha256=placement_receipt_sha256,
        gate_receipt_sha256=gate_receipt_sha256,
        member_capture_refs=tuple(member_capture_refs),
        point_map_inputs=tuple(tuple(item) for item in point_map_inputs),  # type: ignore[misc]
        placed=placed,
        excluded=excluded,
        recovered_cameras=cameras,
    )


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"the scene projection {field} list is malformed")
    return value


def _placed(raw: object) -> ProjectedPlacement:
    if not isinstance(raw, dict):
        raise ValueError("a projected placement is malformed")
    matrix = raw.get("scene_from_opm_row_major")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise ValueError("a projected placement transform is not a 4x4 matrix")
    return ProjectedPlacement(
        capture_ref=str(raw.get("capture_ref", "")),
        point_map_artifact_ref=str(raw.get("point_map_artifact_ref", "")),
        point_map_content_sha256=str(raw.get("point_map_content_sha256", "")),
        scene_from_opm_row_major=tuple(
            _finite(value, "projected placement transform") for value in matrix
        ),
        local_units_to_scene_units=_finite(
            raw.get("local_units_to_scene_units"), "projected placement scale"
        ),
        scale_status=str(raw.get("scale_status", "")),
    )


def _excluded(raw: object) -> ProjectedExclusion:
    if not isinstance(raw, dict) or raw.get("registered") not in (True, False):
        raise ValueError("a projected exclusion is malformed")
    return ProjectedExclusion(
        capture_ref=str(raw.get("capture_ref", "")),
        registered=raw["registered"],
        reason=str(raw.get("reason", "")),
    )
