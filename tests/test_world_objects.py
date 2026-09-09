"""The authored delta with no database: canonical order, fixed point, and reviewed bounds.

Every test here has a negative control, because a guard that has only ever been shown accepting
valid input has not been shown to be a guard.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import re
import struct

import pytest
from exulanica.canonical import canonical_json
from exulanica.world import (
    MAX_SCALE_MILLI,
    MAX_YAW_MICRORADIANS,
    OBJECT_ID_PATTERN,
    AuthoredObject,
    ElementOverride,
    InvalidObjectData,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    canonical_delta_document,
    delta_sha256,
    reviewed_assets,
    validate_behaviour,
)
from exulanica.world.objects import validate_object, validate_object_id, validate_transform

#: The reviewed cube's content digest. Objects name an asset by its bytes, not by its key,
#: so this is what a request body and the digested object document both carry.
CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"

REGISTRY = {
    ("motion.bounded-path", 1): {
        "travel_mm": {"kind": "integer", "minimum": 100, "maximum": 10_000, "default": 1_000},
        "period_milliseconds": {
            "kind": "integer",
            "minimum": 500,
            "maximum": 60_000,
            "default": 4_000,
        },
        "axis": {"kind": "choice", "choices": ["x", "y", "z"], "default": "x"},
        "easing": {"kind": "choice", "choices": ["linear", "smooth"], "default": "smooth"},
    }
}
PARAMETERS = {
    "travel_mm": 2_000,
    "period_milliseconds": 4_000,
    "axis": "x",
    "easing": "smooth",
}


def transform(**overrides):
    values = {
        "x_mm": 1_200,
        "y_mm": 0,
        "z_mm": -450,
        "yaw_microradians": 785_398,
        "scale_milli": 1_000,
    }
    values.update(overrides)
    return Transform(**values)


def authored(object_id="object:lantern", **overrides):
    values = {
        "object_id": object_id,
        "asset_sha256": CUBE,
        "region_id": "region-a",
        "transform": transform(),
        "origin": ObjectOrigin("authored", "fictional"),
        "behaviour": None,
        "removed": False,
    }
    values.update(overrides)
    return AuthoredObject(**values)


# -- the object id contract --------------------------------------------------------------------


def test_the_object_id_contract_is_the_same_in_python_and_in_the_schema():
    """One regex, quoted in two languages, compared here.

    They were briefly different. Python accepted any 1-to-200-character string while the schema
    required lowercase and at least two characters, so "a" and "Object:Lantern" passed validation
    and then raised a CheckViolation, which the application answers with a 500 rather than the
    422 this surface promises."""
    migration = (
        pathlib.Path(__file__).resolve().parents[1]
        / "exulanica/migrations/0042_authored_world_objects.sql"
    ).read_text(encoding="utf-8")
    assert f"check (object_id ~ '{OBJECT_ID_PATTERN}')" in migration


@pytest.mark.parametrize("object_id", ["a", "7", "object:lantern", "a.b_c-d:e", "ab"])
def test_an_acceptable_object_id_is_accepted(object_id):
    assert validate_object_id(object_id) == object_id
    assert re.match(OBJECT_ID_PATTERN, object_id)


@pytest.mark.parametrize(
    "object_id",
    [
        "",
        "Object:Lantern",
        "object lantern",
        "-lead",
        "trail-",
        ":colon",
        "объект",
        "a" * 201,
        # Python's ``$`` matches before a trailing newline; PostgreSQL's does not.
        "object:lantern\n",
        "ab\n",
    ],
)
def test_an_object_id_the_schema_would_refuse_is_refused_first(object_id):
    """The negative control, and the one that matters: every id Python accepts must be an id the
    database accepts, or the refusal arrives as a 500."""
    with pytest.raises(InvalidObjectData):
        validate_object_id(object_id)


# -- the canonical delta -----------------------------------------------------------------------


def test_the_delta_digest_ignores_the_order_rows_arrive_in():
    a, b = authored("object:a"), authored("object:b")
    assert delta_sha256((a, b), ()) == delta_sha256((b, a), ())


def test_the_delta_digest_does_not_ignore_the_content():
    """The negative control for the test above: an order-insensitive digest that ignored
    everything would also pass it."""
    assert delta_sha256((authored("object:a"),), ()) != delta_sha256((authored("object:b"),), ())
    moved = authored("object:a", transform=transform(x_mm=1_201))
    assert delta_sha256((authored("object:a"),), ()) != delta_sha256((moved,), ())


def test_the_delta_document_sorts_objects_and_overrides():
    document = canonical_delta_document(
        (authored("object:c"), authored("object:a")),
        (ElementOverride("element:z", True), ElementOverride("element:a", True)),
    )
    assert [o["object_id"] for o in document["objects"]] == ["object:a", "object:c"]
    assert [o["element_id"] for o in document["element_overrides"]] == ["element:a", "element:z"]


def test_the_delta_document_is_canonically_encodable():
    canonical_json(canonical_delta_document((authored(),), (ElementOverride("element:a", True),)))


def test_a_float_coordinate_cannot_reach_a_digest():
    """The negative control for fixed point. A float must not merely digest differently, it must
    fail to digest at all, because that is the property that keeps every verifier agreeing."""
    with pytest.raises(InvalidObjectData):
        validate_transform(transform(x_mm=1_200.5))
    with pytest.raises(TypeError):
        canonical_json({"x_mm": 1_200.5})


def test_a_transform_carries_its_own_units():
    document = transform().document()
    assert document["coordinate_space"] == "region_local"
    assert document["coordinate_unit"] == "millimetre"


# -- fixed-point bounds ------------------------------------------------------------------------


def test_a_transform_inside_the_bounds_is_accepted():
    assert validate_transform(transform()) is not None
    assert validate_transform(transform(yaw_microradians=0)) is not None
    assert validate_transform(transform(yaw_microradians=MAX_YAW_MICRORADIANS)) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"yaw_microradians": -1},
        {"yaw_microradians": MAX_YAW_MICRORADIANS + 1},
        {"scale_milli": 0},
        {"scale_milli": MAX_SCALE_MILLI + 1},
        {"x_mm": 1_000_000_001},
        {"x_mm": -1_000_000_001},
    ],
)
def test_a_transform_outside_the_bounds_is_refused(overrides):
    with pytest.raises(InvalidObjectData):
        validate_transform(transform(**overrides))


def test_a_boolean_is_not_a_coordinate():
    """bool subclasses int in Python, so a bare isinstance check would let True through and it
    would digest as `true` rather than as `1`."""
    with pytest.raises(InvalidObjectData):
        validate_transform(transform(x_mm=True))


# -- origin ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["fictional", "personal"])
def test_the_person_chooses_either_role(role):
    validate_object(
        authored(origin=ObjectOrigin("authored", role)),
        region_ids=frozenset({"region-a"}),
        asset_digests=frozenset({CUBE}),
        registry=REGISTRY,
    )


def test_an_unchosen_or_invented_role_is_refused():
    for role in ("", "unknown", "real", "auto"):
        with pytest.raises(InvalidObjectData):
            validate_object(
                authored(origin=ObjectOrigin("authored", role)),
                region_ids=frozenset({"region-a"}),
                asset_digests=frozenset({CUBE}),
                registry=REGISTRY,
            )


def test_origin_kind_cannot_claim_anything_but_authored():
    with pytest.raises(InvalidObjectData):
        validate_object(
            authored(origin=ObjectOrigin("captured", "personal")),
            region_ids=frozenset({"region-a"}),
            asset_digests=frozenset({CUBE}),
            registry=REGISTRY,
        )


# -- unknown references ------------------------------------------------------------------------


def test_a_known_region_and_asset_are_accepted():
    validate_object(
        authored(),
        region_ids=frozenset({"region-a"}),
        asset_digests=frozenset({CUBE}),
        registry=REGISTRY,
    )


def test_an_unknown_region_is_refused():
    with pytest.raises(InvalidObjectData, match="region"):
        validate_object(
            authored(region_id="region-nowhere"),
            region_ids=frozenset({"region-a"}),
            asset_digests=frozenset({CUBE}),
            registry=REGISTRY,
        )


def test_an_unreviewed_asset_is_refused():
    with pytest.raises(InvalidObjectData, match="reviewed asset"):
        validate_object(
            authored(asset_sha256="0" * 64),
            region_ids=frozenset({"region-a"}),
            asset_digests=frozenset({CUBE}),
            registry=REGISTRY,
        )


# -- behaviour bounds --------------------------------------------------------------------------


def test_no_behaviour_is_a_valid_object():
    assert validate_behaviour(None, REGISTRY) is None


def test_a_behaviour_inside_every_bound_is_accepted():
    behaviour = ObjectBehaviour("motion.bounded-path", 1, PARAMETERS)
    assert validate_behaviour(behaviour, REGISTRY) is behaviour


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({**PARAMETERS, "travel_mm": 99}, "between"),
        ({**PARAMETERS, "travel_mm": 10_001}, "between"),
        ({**PARAMETERS, "period_milliseconds": 499}, "between"),
        ({**PARAMETERS, "axis": "w"}, "one of"),
        ({**PARAMETERS, "easing": "bouncy"}, "one of"),
        ({**PARAMETERS, "travel_mm": "1000"}, "integer"),
        ({**PARAMETERS, "travel_mm": True}, "integer"),
        ({**PARAMETERS, "extra": 1}, "unknown"),
        ({k: v for k, v in PARAMETERS.items() if k != "axis"}, "required"),
    ],
)
def test_an_out_of_contract_parameter_fails_closed(parameters, match):
    with pytest.raises(InvalidObjectData, match=match):
        validate_behaviour(ObjectBehaviour("motion.bounded-path", 1, parameters), REGISTRY)


def test_an_unsupported_behaviour_fails_visibly():
    """The first milestone names this as its own acceptance evidence."""
    for key, version in (("motion.teleport", 1), ("motion.bounded-path", 2)):
        with pytest.raises(InvalidObjectData, match="not reviewed"):
            validate_behaviour(ObjectBehaviour(key, version, PARAMETERS), REGISTRY)


# -- reviewed assets ---------------------------------------------------------------------------


def test_the_generated_assets_reproduce_the_digests_migration_0042_pinned():
    """If this fails, the migration is describing bytes this code no longer produces."""
    pinned = {
        "cc0.marker-cube": (
            "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9",
            780,
        ),
        "cc0.marker-pillar": (
            "b960af0f1c85f6c41a38ce09727cd19bc2bbc0e21bb8f3f111707af9b90b2737",
            784,
        ),
        "cc0.marker-plate": (
            "19425a058c19d4009392093e770c7f115a68d020b67e0bdce83abdad4b5a2f6e",
            684,
        ),
    }
    catalog = {asset.asset_key: asset for asset in reviewed_assets()}
    assert set(catalog) == set(pinned)
    for key, (digest, size) in pinned.items():
        assert catalog[key].content_sha256 == digest
        assert catalog[key].byte_size == size
    licences = {asset.licence_sha256 for asset in catalog.values()}
    assert licences == {"6f89ee797a8cb18ff880d0d38840884953b437230709a84dfa94cf2a5869ea6f"}


def test_generation_is_deterministic():
    assert [a.payload for a in reviewed_assets()] == [a.payload for a in reviewed_assets()]


@pytest.mark.parametrize("asset", reviewed_assets(), ids=lambda a: a.asset_key)
def test_every_reviewed_asset_is_a_readable_gltf_binary(asset):
    payload = asset.payload
    magic, version, total = struct.unpack_from("<III", payload, 0)
    assert magic == 0x46546C67
    assert version == 2
    assert total == len(payload)

    offset, chunks = 12, {}
    while offset < total:
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        # Every chunk four-byte aligned, or a conforming reader stops at the first one.
        assert length % 4 == 0
        chunks[kind] = payload[offset : offset + length]
        offset += length
    assert offset == total

    document = json.loads(chunks[0x4E4F534A].decode("utf-8"))
    binary = chunks[0x004E4942]
    assert document["asset"]["version"] == "2.0"
    positions, indices = document["accessors"]
    views = document["bufferViews"]

    position_view = views[positions["bufferView"]]
    assert position_view["byteLength"] == positions["count"] * 12
    vertices = [
        struct.unpack_from("<3f", binary, position_view["byteOffset"] + i * 12)
        for i in range(positions["count"])
    ]
    assert [min(v[axis] for v in vertices) for axis in range(3)] == positions["min"]
    assert [max(v[axis] for v in vertices) for axis in range(3)] == positions["max"]

    index_view = views[indices["bufferView"]]
    # An accessor's offset must be a multiple of its component size; four keeps both happy.
    assert index_view["byteOffset"] % 4 == 0
    values = [
        struct.unpack_from("<H", binary, index_view["byteOffset"] + i * 2)[0]
        for i in range(indices["count"])
    ]
    assert indices["count"] % 3 == 0
    assert max(values) < positions["count"]


def test_every_solid_face_is_wound_outward():
    """A reversed face renders inside out. The plate is excluded because it is flat: it has no
    inside, and it is wound both ways on purpose."""

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    for asset in reviewed_assets():
        if asset.asset_key == "cc0.marker-plate":
            continue
        payload = asset.payload
        offset, chunks = 12, {}
        while offset < len(payload):
            length, kind = struct.unpack_from("<II", payload, offset)
            offset += 8
            chunks[kind] = payload[offset : offset + length]
            offset += length
        document = json.loads(chunks[0x4E4F534A].decode("utf-8"))
        binary = chunks[0x004E4942]
        positions, indices = document["accessors"]
        views = document["bufferViews"]
        vertices = [
            struct.unpack_from("<3f", binary, views[0]["byteOffset"] + i * 12)
            for i in range(positions["count"])
        ]
        values = [
            struct.unpack_from("<H", binary, views[1]["byteOffset"] + i * 2)[0]
            for i in range(indices["count"])
        ]
        centre = tuple(sum(v[axis] for v in vertices) / len(vertices) for axis in range(3))
        for triangle in range(0, len(values), 3):
            a, b, c = (vertices[values[triangle + i]] for i in range(3))
            edge_one = tuple(b[i] - a[i] for i in range(3))
            edge_two = tuple(c[i] - a[i] for i in range(3))
            normal = cross(edge_one, edge_two)
            outward = tuple(a[i] - centre[i] for i in range(3))
            assert sum(normal[i] * outward[i] for i in range(3)) > 0, asset.asset_key


def test_the_runtime_role_cannot_write_the_reviewed_catalogs():
    """Migration 0042 revokes write on both registries, and that revoke is not sufficient alone.

    ``provision_runtime_role`` grants ``select, insert, update`` on every table in the schema and
    then revokes insert and update on ``READ_ONLY_TABLES``. A reviewed catalog absent from that
    tuple has its migration-time revoke handed straight back on the next deployment, which is how
    a table the contract calls read-only becomes writable from any workspace's runtime
    connection."""
    from exulanica.db.roles import READ_ONLY_TABLES

    assert "world_reviewed_asset" in READ_ONLY_TABLES
    assert "world_object_behaviour_registry" in READ_ONLY_TABLES


def test_the_licence_names_the_dedication_it_claims():
    for asset in reviewed_assets():
        assert asset.licence_id == "CC0-1.0"
        text = asset.licence_bytes.decode("utf-8")
        assert "CC0 1.0 Universal" in text
        assert "creativecommons.org/publicdomain/zero/1.0" in text


# -- the published renderer fixture -------------------------------------------------------------
#
# `web/packages/graph-client/test/fixtures/world-objects.json` is generated from a real
# `GET /world/versions/{id}` body and is stable once published: fields may be added, and no field
# in it may be renamed, retyped or removed. These tests are what makes that a rule rather than an
# intention, and they are here rather than in `web/` because the shape is the backend's to keep.


FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "web/packages/graph-client/test/fixtures/world-objects.json"
)


@pytest.fixture(scope="module")
def published_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_the_fixture_state_digest_recomputes_from_its_own_delta(published_fixture):
    """The one check that cannot be satisfied by editing the file to look right: the digest is
    over the objects and overrides the file itself carries."""
    objects = tuple(
        AuthoredObject(
            object_id=o["object_id"],
            asset_sha256=o["asset"]["content_sha256"],
            region_id=o["region_id"],
            transform=Transform(
                o["transform"]["x_mm"],
                o["transform"]["y_mm"],
                o["transform"]["z_mm"],
                o["transform"]["yaw_microradians"],
                o["transform"]["scale_milli"],
            ),
            origin=ObjectOrigin(o["origin"]["kind"], o["origin"]["role"]),
            behaviour=(
                None
                if o["behaviour"] is None
                else ObjectBehaviour(
                    o["behaviour"]["behaviour_key"],
                    o["behaviour"]["behaviour_version"],
                    o["behaviour"]["parameters"],
                )
            ),
            removed=o["removed"],
        )
        for o in published_fixture["objects"]
    )
    overrides = tuple(
        ElementOverride(
            element_id=o["element_id"],
            suppressed=o["suppressed"],
            transform=(
                None
                if o["transform"] is None
                else Transform(
                    o["transform"]["x_mm"],
                    o["transform"]["y_mm"],
                    o["transform"]["z_mm"],
                    o["transform"]["yaw_microradians"],
                    o["transform"]["scale_milli"],
                )
            ),
        )
        for o in published_fixture["element_overrides"]
    )
    assert delta_sha256(objects, overrides) == published_fixture["state_sha256"]


def test_the_fixture_carries_every_published_field(published_fixture):
    """The negative control for "stable once published": a removed or renamed field fails here
    rather than in whatever consumes the fixture next."""
    assert set(published_fixture) == {
        "schema_version",
        "version_id",
        "world_id",
        "source_snapshot_id",
        "parent_version_id",
        "title",
        "origin",
        "style_version_id",
        "state_sha256",
        "edit_seq",
        "source_invalidated",
        "created_by",
        "created_at",
        "objects",
        "element_overrides",
        "edits",
    }
    assert published_fixture["schema_version"] == 1
    assert published_fixture["origin"] == "authored"

    for obj in published_fixture["objects"]:
        assert set(obj) == {
            "object_id",
            "asset",
            "region_id",
            "transform",
            "origin",
            "behaviour",
            "removed",
        }
        assert set(obj["asset"]) == {
            "asset_key",
            "title",
            "summary",
            "media_type",
            "content_sha256",
            "byte_size",
            "licence_id",
            "licence_sha256",
            "availability",
        }
        assert set(obj["transform"]) == {
            "coordinate_space",
            "coordinate_unit",
            "x_mm",
            "y_mm",
            "z_mm",
            "yaw_microradians",
            "scale_milli",
        }
        assert set(obj["origin"]) == {"kind", "role"}
        if obj["behaviour"] is not None:
            assert set(obj["behaviour"]) == {
                "behaviour_key",
                "behaviour_version",
                "parameters",
            }

    for edit in published_fixture["edits"]:
        assert set(edit) == {
            "edit_id",
            "edit_seq",
            "kind",
            "object_id",
            "element_id",
            "undone_edit_id",
            "base_state_sha256",
            "result_state_sha256",
            "actor",
            "recorded_at",
        }


def test_the_fixture_carries_a_transform_a_reader_can_interpret_without_context(
    published_fixture,
):
    for obj in published_fixture["objects"]:
        assert obj["transform"]["coordinate_space"] == "region_local"
        assert obj["transform"]["coordinate_unit"] == "millimetre"
        for key in ("x_mm", "y_mm", "z_mm", "yaw_microradians", "scale_milli"):
            value = obj["transform"][key]
            assert isinstance(value, int) and not isinstance(value, bool), key


def test_the_fixture_names_assets_this_repository_actually_generates(published_fixture):
    catalog = {asset.asset_key: asset for asset in reviewed_assets()}
    for obj in published_fixture["objects"]:
        asset = obj["asset"]
        generated = catalog[asset["asset_key"]]
        assert asset["content_sha256"] == generated.content_sha256
        assert asset["byte_size"] == generated.byte_size
        assert asset["licence_sha256"] == generated.licence_sha256
        assert asset["licence_id"] == "CC0-1.0"


def test_the_fixture_shows_a_complete_edit_chain_ending_in_an_undo(published_fixture):
    """A fixture the renderer task can build an undo control against, not just a placed object."""
    edits = published_fixture["edits"]
    assert [e["kind"] for e in edits] == [
        "add_object",
        "add_object",
        "move_object",
        "remove_object",
        "undo",
    ]
    assert [e["edit_seq"] for e in edits] == [1, 2, 3, 4, 5]
    for earlier, later in itertools.pairwise(edits):
        assert earlier["result_state_sha256"] == later["base_state_sha256"]
    assert edits[-1]["result_state_sha256"] == published_fixture["state_sha256"]
    assert edits[-1]["undone_edit_id"] == edits[3]["edit_id"]
    # The undone removal is visibly back, which is the property the control has to show.
    restored = {o["object_id"]: o for o in published_fixture["objects"]}
    assert restored[edits[3]["object_id"]]["removed"] is False
    # Both origin roles and a behaviour-carrying and behaviour-free object are represented.
    assert {o["origin"]["role"] for o in published_fixture["objects"]} == {
        "fictional",
        "personal",
    }
    assert {o["behaviour"] is None for o in published_fixture["objects"]} == {True, False}
