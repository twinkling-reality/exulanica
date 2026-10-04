"""Generated assets: the colour table, the mesh steps, the writer and the records.

Expected values come from outside the code under test: the published sRGB value of 128 (0.2158605
linear), hand-worked rotations and fits, and a container read back with struct rather than through
the writer.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from exulanica_appearance.assets import colour
from exulanica_appearance.assets.dryrun import STUB_PACK, dry_run, stub_mesh
from exulanica_appearance.assets.glb import write_glb
from exulanica_appearance.assets.mesh import (
    Mesh,
    cluster_simplify,
    fit,
    flat_palette,
    orient,
    simplify_to,
)
from exulanica_appearance.assets.postprocess import make_piece
from exulanica_appearance.assets.records import (
    REGENERATION,
    build_job,
    build_request,
    cache_scope,
    read_job,
    read_receipt,
    read_request,
    seed_for,
)
from exulanica_appearance.canonical import Refused, canonical_bytes, sha256_hex

BENCH = {"look_role": "prop.bench", "slot_mm": {"width": 1800, "height": 900, "depth": 700}}


def _box(extent: tuple[float, float, float]) -> Mesh:
    x, y, z = extent
    v = np.array([[a, b, c] for a in (0, x) for b in (0, y) for c in (0, z)], dtype=np.float64)
    f = np.array(
        [
            [0, 1, 3],
            [0, 3, 2],
            [4, 6, 7],
            [4, 7, 5],
            [0, 4, 5],
            [0, 5, 1],
            [2, 3, 7],
            [2, 7, 6],
            [0, 2, 6],
            [0, 6, 4],
            [1, 5, 7],
            [1, 7, 3],
        ]
    )
    return Mesh(v, f, np.tile(np.array([[200, 40, 40]], dtype=np.uint8), (8, 1)))


# ---- colour ------------------------------------------------------------------------------------


def test_the_table_holds_published_srgb_values() -> None:
    table = colour.linear16_table()
    assert table[0] == 0
    assert table[255] == 65535
    # sRGB 128 is 0.2158605 linear (IEC 61966-2-1); 0.2158605 * 65535 = 14146.4.
    assert table[128] == 14146
    # Byte 1 is on the linear segment: 1 / 255 / 12.92 * 65535 = 19.89.
    assert table[1] == 20
    assert all(b > a for a, b in itertools.pairwise(table)), "strictly increasing, so invertible"


def test_the_committed_table_is_the_rule_and_a_changed_value_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    values, digest = colour.read_table(repository)
    assert values == colour.linear16_table()
    assert digest == hashlib.sha256((repository / colour.TABLE_PATH).read_bytes()).hexdigest()
    document = json.loads((repository / colour.TABLE_PATH).read_bytes())
    document["values"][200] += 1
    changed = tmp_path / colour.TABLE_PATH
    changed.parent.mkdir(parents=True)
    changed.write_bytes(canonical_bytes(document) + b"\n")
    with pytest.raises(Refused):
        colour.read_table(tmp_path)


def test_a_colour_snaps_to_the_swatch_a_person_would_pick() -> None:
    palette = [[20, 20, 20], [200, 40, 40], [40, 160, 60]]
    picks = colour.nearest_swatch(np.array([[190, 60, 50], [10, 10, 30], [60, 150, 70]]), palette)
    assert picks.tolist() == [1, 0, 2]


# ---- mesh steps --------------------------------------------------------------------------------


def test_orient_takes_up_to_plus_y_and_front_to_plus_z_by_a_rotation() -> None:
    point = Mesh(
        np.array([[1.0, 2.0, 3.0], [0, 0, 0], [0, 0, 1]]),
        np.array([[0, 1, 2]]),
        np.zeros((3, 3), np.uint8),
    )
    out, record = orient(point, "+Z", "-Y")
    # Raw up +Z becomes y; raw front -Y becomes z, so raw y = 2 goes to z = -2; glTF x is up
    # cross front = Z x -Y = +X, so x stays 1.
    assert out.positions[0].tolist() == [1.0, 3.0, -2.0]
    assert record == {"front": "-Y", "step": "orient", "up": "+Z"}
    with pytest.raises(Refused):
        orient(point, "+Z", "-Z")


def test_contain_scales_uniformly_and_stands_the_base_centre_on_the_origin() -> None:
    out, record = fit(
        _box((1.0, 3.0, 2.0)), "contain", {"width": 500, "height": 1200, "depth": 800}
    )
    # Height limits: 1.2 / 3 = 0.4, so 400 x 1200 x 800, 100 mm spare in width.
    assert record["size_mm"] == {"width": 400, "height": 1200, "depth": 800}
    assert record["gap_mm"] == {"width": 100, "height": 0, "depth": 0}
    assert record["scale_per_million"] == 400_000
    assert out.positions[:, 1].min() == 0
    assert np.allclose(out.positions[:, [0, 2]].min(axis=0), -out.positions[:, [0, 2]].max(axis=0))


def test_fill_refuses_a_piece_the_page_could_not_stretch_to_its_slot() -> None:
    # A cube in a door slot: contained at 300 mm, the page would stretch width 4x.
    with pytest.raises(Refused, match="proportions"):
        fit(_box((1.0, 1.0, 1.0)), "fill", {"width": 1200, "height": 2400, "depth": 300})
    _, record = fit(_box((1.1, 2.3, 0.25)), "fill", {"width": 1200, "height": 2400, "depth": 300})
    assert all(800 <= value <= 1250 for value in record["stretch_per_mille"].values())


def test_simplify_reaches_the_budget_and_records_both_counts() -> None:
    tree = stub_mesh("plant.tree")
    assert len(tree.triangles) > 3000
    out, record = simplify_to(tree, 3000, cluster_simplify)
    assert len(out.triangles) <= 3000
    assert record["triangles_before"] == len(tree.triangles)
    assert record["parameters"]["simplifier"] == "cluster-stand-in/v1"


def test_the_written_colours_are_exactly_the_table_values_of_the_swatches(repository: Path) -> None:
    table, _ = colour.read_table(repository)
    palette = [[10, 10, 10], [200, 40, 40]]
    mesh, swatch, _ = flat_palette(_box((1.0, 1.0, 1.0)), palette)
    glb = write_glb(mesh, swatch, palette, table)
    magic, version, total = struct.unpack_from("<III", glb, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(glb))
    json_length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + json_length])
    accessor = document["accessors"][
        document["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"]
    ]
    assert (accessor["type"], accessor["componentType"], accessor["normalized"]) == (
        "VEC4",
        5123,
        True,
    )
    view = document["bufferViews"][accessor["bufferView"]]
    binary = glb[20 + json_length + 8 :]
    values = np.frombuffer(
        binary, dtype="<u2", count=accessor["count"] * 4, offset=view["byteOffset"]
    ).reshape(-1, 4)
    red = (table[200], table[40], table[40], 65535)
    assert {tuple(int(x) for x in row) for row in values} == {red}
    assert "extensionsUsed" not in document and "images" not in document


# ---- records -----------------------------------------------------------------------------------


def _request(**changes: object) -> dict:
    spec = {**BENCH, **changes}
    return read_request(build_request(pack=STUB_PACK, variants=2, route="S", **spec))


def test_a_request_takes_the_pack_format_s_budget_and_refuses_another() -> None:
    request = _request()
    assert request["budget"]["triangles"] == 1500 and request["budget"]["glb_bytes"] == 160_000
    tampered = dict(request, budget=dict(request["budget"], triangles=9000))
    with pytest.raises(Refused, match="budget"):
        read_request(canonical_bytes(tampered))


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"look_role": "character.baker"}, "does not make"),
        ({"look_role": "ground.cobbles"}, "does not make"),
        ({"look_role": "Prop.bench"}, "family.leaf"),
        ({"description": "x" * 81}, "plain words"),
        ({"description": "a bench\nwith a newline"}, "plain words"),
        ({"tile_module_mm": 1000}, "only a tiled piece"),
        ({"look_role": "boundary.fence"}, "module length"),
    ],
)
def test_a_request_refuses(changes: dict, match: str) -> None:
    with pytest.raises(Refused, match=match):
        _request(**changes)


def test_a_palette_with_two_alike_swatches_is_refused() -> None:
    pack = dict(STUB_PACK, palette=[[1, 2, 3], [1, 2, 3]])
    with pytest.raises(Refused, match="alike"):
        build_request(pack=pack, variants=1, route="S", **BENCH)


def test_a_request_with_a_description_is_cached_in_its_workspace_only() -> None:
    assert cache_scope(_request()) == "catalog"
    assert cache_scope(_request(description="a park bench with a curved back")) == "workspace"


def test_seeds_come_from_the_request_digest_under_a_prefix() -> None:
    digest = "ab" * 32
    expected = (
        int.from_bytes(
            hashlib.sha256(
                b"exulanica.generated-asset-seed/v1\x00"
                + bytes.fromhex(digest)
                + (1).to_bytes(4, "big")
            ).digest()[:8],
            "big",
        )
        >> 1
    )
    assert seed_for(digest, 1) == expected
    assert seed_for(digest, 0) != seed_for(digest, 1)


def test_a_job_refuses_a_changed_seed_and_a_stub_container_on_a_real_route() -> None:
    raw = build_request(pack=STUB_PACK, variants=2, route="S", **BENCH)
    job = json.loads(
        build_job(
            route="S",
            components_sha256="1" * 64,
            requests=[raw],
            code_sha256="2" * 64,
            container="stub",
            estimate_seconds=10,
        )
    )
    assert [item["variant"] for item in job["items"]] == [0, 1]
    assert job["stop"] == {"estimate_seconds": 10, "stop_at_seconds": 15}
    job["items"][1]["seed"] += 1
    with pytest.raises(Refused, match="seed"):
        read_job(canonical_bytes(job))
    real = build_request(pack=STUB_PACK, variants=1, route="A", **BENCH)
    with pytest.raises(Refused, match="stub"):
        build_job(
            route="A",
            components_sha256="1" * 64,
            requests=[real],
            code_sha256="2" * 64,
            container="stub",
            estimate_seconds=10,
        )


def test_a_piece_over_budget_says_which_measure_and_a_receipt_cannot_hide_it(
    repository: Path, tmp_path: Path
) -> None:
    table, _ = colour.read_table(repository)
    request = _request()
    tight = dict(request, budget=dict(request["budget"], glb_bytes=100))
    piece = make_piece(
        stub_mesh("prop.bench"),
        up="+Z",
        front="-Y",
        request=tight,
        simplifier=cluster_simplify,
        table=table,
    )
    assert piece.verdict == {"over": ["glb_bytes"], "within": False}

    run = dry_run(repository, tmp_path)
    receipts = sorted(tmp_path.glob("receipt-*.json"))
    requests = {
        sha256_hex(p.read_bytes()): read_request(p.read_bytes())
        for p in tmp_path.glob("request-*.json")
    }
    document = json.loads(receipts[0].read_bytes())
    request_of = requests[document["request_sha256"]]
    read_receipt(receipts[0].read_bytes(), request_of)
    assert document["regeneration"] == REGENERATION
    for change, match in (
        (
            {
                "verdict": {"over": [], "within": True},
                "measured": dict(document["measured"], triangles=10**6),
            },
            "verdict",
        ),
        ({"origin": "authored"}, "origin generated"),
        (
            {
                "postprocess": dict(
                    document["postprocess"], steps=document["postprocess"]["steps"][::-1]
                )
            },
            "in that order",
        ),
    ):
        with pytest.raises(Refused, match=match):
            read_receipt(canonical_bytes(dict(document, **change)), request_of)
    assert all(piece["within"] for piece in run["pieces"])
    assert len(run["pieces"]) == 5
