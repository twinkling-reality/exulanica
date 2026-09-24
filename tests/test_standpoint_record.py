"""The standpoint record's reader refuses what it cannot present without guessing.

Each test tampers one field of a valid record and asserts the refusal, and the first test holds the
untampered record readable, so every refusal below is a refusal of the tampering and not of a
fixture that never parsed.
"""

from __future__ import annotations

import json
import math

import pytest
from exulanica.reconstruction.standpoint_record import (
    DECLARED,
    ArrangedMember,
    Arrangement,
    MemberIntrinsics,
    MemberReading,
    StandpointMember,
    StandpointPair,
    StandpointRecord,
    StandpointRecordError,
    member_refusal,
    parse_standpoint_record,
    scene_from_opm_row_major,
)

SCENE = "00000000-0000-4000-8000-00000000000a"
IDENTITY_PPB = (1_000_000_000, 0, 0, 0, 1_000_000_000, 0, 0, 0, 1_000_000_000)
#: A quarter turn about +Y, written the way the producer writes it.
QUARTER_TURN_PPB = (0, 0, 1_000_000_000, 0, 1_000_000_000, 0, -1_000_000_000, 0, 0)


def _member(ordinal: int, outcome: str = "joined") -> StandpointMember:
    read = outcome in ("joined", "not_joined")
    return StandpointMember(
        ordinal=ordinal,
        member_ref=f"00000000-0000-4000-8000-{ordinal:012d}",
        outcome=outcome,  # type: ignore[arg-type]
        point_map_artifact_ref=(
            None if outcome == "not_permitted" else f"00000000-0000-4000-9000-{ordinal:012d}"
        ),
        point_map_sha256=None if outcome == "not_permitted" else f"{ordinal:x}" * 64,
        reading=(
            MemberReading(
                image_sha256="e" * 64,
                source_size=(4032, 3024),
                model_size=(512, 384),
                intrinsics=MemberIntrinsics(
                    source="exif-35mm-equivalent",
                    stated_focal_micropixels=3_030_000_000,
                    focal_micropixels=3_000_000_000,
                    depth_model_focal_micropixels=3_150_000_000,
                ),
                features=2000,
            )
            if read
            else None
        ),
    )


def _pair(a: int, b: int, outcome: str) -> StandpointPair:
    joined = outcome == "joined"
    return StandpointPair(
        a=a,
        b=b,
        outcome=outcome,  # type: ignore[arg-type]
        matches=300,
        inliers=250 if joined else 3,
        inlier_cells=8 if joined else 1,
        rotation_ppb=IDENTITY_PPB if joined else None,
        residual_millidegrees={"max": 400, "p50": 100, "p90": 200} if joined else None,
        standpoint_residual_millidegrees={"max": 500, "p50": 110, "p90": 220} if joined else None,
        translation_mm=(10, 0, -5) if joined else None,
        translation_sigma_mm=4 if joined else None,
        depth_ratio_ppm=1_010_000 if joined else None,
        changed_ppm=1_000 if joined else None,
    )


def _record() -> StandpointRecord:
    members = (_member(0), _member(1), _member(2, "not_joined"), _member(3, "not_permitted"))
    record = StandpointRecord(
        scene_ref=SCENE,
        policy_sha256="d" * 64,
        stage_version=1,
        feature_extractor={"contract": "pycolmap-sift", "pycolmap": "4.2.0"},
        members=members,
        pairs=(
            _pair(0, 1, "joined"),
            _pair(0, 2, "insufficient_overlap"),
            _pair(1, 2, "moved_between_photographs"),
        ),
        components=((0, 1), (2,), (3,)),
        arrangement=Arrangement(
            reference=0,
            members=(
                ArrangedMember(0, IDENTITY_PPB, 1_000_000, 952_381),
                ArrangedMember(1, QUARTER_TURN_PPB, 1_010_000, 952_381),
            ),
            up={"method": "camera-horizontal-axes", "implied_roll_millidegrees": {"max": 900}},
            rotation_solve={"edges": [], "max_residual_millidegrees": 0},
            scale_solve={"edges": [], "max_residual_ppm": 0, "gauge": "g"},
        ),
        refusal=None,
    )
    return record


def _tampered(mutate) -> bytes:
    payload = json.loads(_record().to_bytes())
    mutate(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_an_untampered_record_reads_back_exactly():
    data = _record().to_bytes()
    parsed = parse_standpoint_record(data, expected_scene_ref=SCENE)
    assert parsed.to_bytes() == data
    assert parsed.arrangement is not None and len(parsed.arrangement.members) == 2
    assert json.loads(data)["declared"] == dict(DECLARED)


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("profile", lambda p: p.update(profile="exulanica.standpoint-scene/v0")),
        ("declared", lambda p: p["declared"].update(promotes_rung=True)),
        ("stage", lambda p: p["stage"].update(key="scene_pose")),
        ("ordinals", lambda p: p["members"][1].update(ordinal=5)),
        (
            "reflection",
            lambda p: p["arrangement"]["members"][0].update(
                scene_from_camera_ppb=[
                    -1_000_000_000,
                    0,
                    0,
                    0,
                    1_000_000_000,
                    0,
                    0,
                    0,
                    1_000_000_000,
                ]
            ),
        ),
        (
            "not a rotation",
            lambda p: p["arrangement"]["members"][0].update(
                scene_from_camera_ppb=[
                    2_000_000_000,
                    0,
                    0,
                    0,
                    1_000_000_000,
                    0,
                    0,
                    0,
                    1_000_000_000,
                ]
            ),
        ),
        (
            "reading without read",
            lambda p: p["members"][3].update(reading=p["members"][0]["reading"]),
        ),
        ("read without reading", lambda p: p["members"][2].update(reading=None)),
        ("permitted-less map", lambda p: p["members"][3].update(point_map_sha256="a" * 64)),
        ("joined without rotation", lambda p: p["pairs"][0].update(rotation_ppb=None)),
        ("partition", lambda p: p.update(components=[[0, 1], [2]])),
        ("arrangement not a component", lambda p: p.update(components=[[0], [1], [2], [3]])),
        ("outcome disagrees", lambda p: p["members"][2].update(outcome="joined")),
        ("refusal beside arrangement", lambda p: p.update(refusal="nothing_joined")),
        ("unknown pair outcome", lambda p: p["pairs"][1].update(outcome="guessed")),
        ("duplicate pair", lambda p: p["pairs"].append(dict(p["pairs"][0]))),
    ],
)
def test_a_tampered_record_is_refused(name, mutate):
    with pytest.raises(StandpointRecordError):
        parse_standpoint_record(_tampered(mutate))


def test_bytes_that_are_not_the_canonical_encoding_are_refused():
    pretty = json.dumps(json.loads(_record().to_bytes()), indent=1).encode()
    with pytest.raises(StandpointRecordError):
        parse_standpoint_record(pretty)


def test_a_record_for_another_scene_or_other_point_maps_is_refused():
    data = _record().to_bytes()
    with pytest.raises(StandpointRecordError):
        parse_standpoint_record(data, expected_scene_ref="00000000-0000-4000-8000-0000000000ff")
    members = [
        (m.member_ref, m.point_map_artifact_ref, m.point_map_sha256) for m in _record().members
    ]
    assert parse_standpoint_record(data, expected_members=members)
    members[1] = (members[1][0], members[1][1], "f" * 64)
    with pytest.raises(StandpointRecordError):
        parse_standpoint_record(data, expected_members=members)


def test_a_photograph_that_states_no_focal_length_is_named_and_holds_no_reading():
    record = _record()
    unstated = StandpointMember(
        ordinal=4,
        member_ref="00000000-0000-4000-8000-000000000004",
        outcome="focal_length_unstated",
        point_map_artifact_ref="00000000-0000-4000-9000-000000000004",
        point_map_sha256="4" * 64,
    )
    widened = StandpointRecord(
        **{
            **{name: getattr(record, name) for name in StandpointRecord.__slots__},
            "members": (*record.members, unstated),
            "components": (*record.components, (4,)),
        }
    )
    parsed = parse_standpoint_record(widened.to_bytes())
    assert member_refusal(parsed, 4) == "focal_length_unstated"
    payload = json.loads(widened.to_bytes())
    payload["members"][4]["reading"] = payload["members"][0]["reading"]
    with pytest.raises(StandpointRecordError):
        parse_standpoint_record(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def test_a_member_apart_is_named_by_the_refusal_a_person_can_act_on():
    record = _record()
    assert member_refusal(record, 0) is None
    # Refused for overlap against one photograph and for having moved against another: moved is
    # the one a person can do something about, so it is the one named.
    assert member_refusal(record, 2) == "moved_between_photographs"
    assert member_refusal(record, 3) == "not_permitted"


def test_the_renderer_transform_is_the_rotation_after_both_scales():
    member = ArrangedMember(1, QUARTER_TURN_PPB, 2_000_000, 500_000)
    matrix = scene_from_opm_row_major(member)
    # A point one metre to the camera's right and one metre ahead.
    x, y, z = 1.0, 0.0, -1.0
    moved = [
        matrix[row * 4] * x
        + matrix[row * 4 + 1] * y
        + matrix[row * 4 + 2] * z
        + matrix[row * 4 + 3]
        for row in range(3)
    ]
    # Sideways by depth 2 times lateral 0.5, ahead by depth 2, then a quarter turn about +Y.
    assert moved == pytest.approx([-2.0, 0.0, -1.0])
    assert matrix[12:] == (0.0, 0.0, 0.0, 1.0)
    assert all(math.isfinite(value) for value in matrix)
