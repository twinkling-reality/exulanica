"""The piece formats the product reads: the colour table, look roles and budgets, and the request,
job and seed records. Plain Python with no numpy, as the product installs it.

Expected values come from outside the code under test: the published sRGB value of 128 (0.2158605
linear), the pack format's budget table, and a seed recomputed here with hashlib.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import pytest
from exulanica_pieces import colour
from exulanica_pieces.canonical import Refused, canonical_bytes
from exulanica_pieces.records import (
    build_job,
    build_request,
    cache_scope,
    read_job,
    read_request,
    seed_for,
)

PACK = {
    "id": "test.toon-town",
    "palette": [[46, 42, 40], [120, 78, 48], [176, 120, 72], [70, 132, 64], [214, 72, 58]],
    "sha256": "0" * 64,
    "style": "toon style, flat colours, chunky simple shapes",
    "version": 1,
}
BENCH = {"look_role": "prop.bench", "slot_mm": {"width": 1800, "height": 900, "depth": 700}}
ROOT = Path(__file__).resolve().parents[1]


def test_the_table_holds_published_srgb_values() -> None:
    table = colour.linear16_table()
    assert table[0] == 0
    assert table[255] == 65535
    # sRGB 128 is 0.2158605 linear (IEC 61966-2-1); 0.2158605 * 65535 = 14146.4.
    assert table[128] == 14146
    # Byte 1 is on the linear segment: 1 / 255 / 12.92 * 65535 = 19.89.
    assert table[1] == 20
    assert all(b > a for a, b in itertools.pairwise(table)), "strictly increasing, so invertible"


def test_the_committed_table_is_the_rule_and_a_changed_value_is_refused(tmp_path: Path) -> None:
    repository = ROOT
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


def _request(**changes: object) -> dict:
    spec = {**BENCH, **changes}
    return read_request(build_request(pack=PACK, variants=2, route="S", **spec))


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
    pack = dict(PACK, palette=[[1, 2, 3], [1, 2, 3]])
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
    raw = build_request(pack=PACK, variants=2, route="S", **BENCH)
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
    real = build_request(pack=PACK, variants=1, route="A", **BENCH)
    with pytest.raises(Refused, match="stub"):
        build_job(
            route="A",
            components_sha256="1" * 64,
            requests=[real],
            code_sha256="2" * 64,
            container="stub",
            estimate_seconds=10,
        )
