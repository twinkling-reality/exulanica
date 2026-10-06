"""The piece formats the product reads: the colour table, look roles and budgets, and the request,
job and seed records. Plain Python with no numpy, as the product installs it.

Expected values come from outside the code under test: the published sRGB value of 128 (0.2158605
linear), the pack format's budget table as its design states it (kilobytes of 1,024 bytes), the
style pack reader's own reading of the same file, and a seed recomputed here with hashlib.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import pytest
from exulanica.world import style_packs
from exulanica_pieces import budgets as piece_budgets
from exulanica_pieces import colour
from exulanica_pieces.canonical import Refused, canonical_bytes, parse_canonical, sha256_hex
from exulanica_pieces.records import (
    REQUEST_PROFILE_V1,
    build_job,
    build_request,
    cache_scope,
    prompt_for,
    read_job,
    read_receipt,
    read_request,
    seed_for,
    verdict,
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
BUDGETS = piece_budgets.read_budgets(ROOT)
KB = 1024


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


# --------------------------------------------------------------------------------------------
# The piece budgets file
# --------------------------------------------------------------------------------------------


def test_the_budgets_are_the_pack_format_s_table() -> None:
    # From the pack format's design table: LOD0 triangles / materials / texture side / bytes.
    table = {
        "window": (400, 2, 256, 64 * KB),
        "door": (1_500, 3, 512, 160 * KB),
        "roof": (2_000, 2, 512, 200 * KB),
        "fixture": (1_500, 2, 256, 160 * KB),
        "prop": (1_500, 2, 256, 160 * KB),
        "plant": (3_000, 2, 512, 300 * KB),
        "vehicle": (4_000, 3, 512, 400 * KB),
        "structure": (20_000, 4, 1024, 1536 * KB),
    }
    for family, (triangles, materials, side, size) in table.items():
        budget = BUDGETS.families[family]
        assert (budget.triangles, budget.materials, budget.texture_side_px, budget.glb_bytes) == (
            triangles,
            materials,
            side,
            size,
        ), family
    boundary = BUDGETS.families["boundary"]
    assert (boundary.triangles, boundary.triangles_per_metre) == (0, 200)
    assert BUDGETS.lod1_share_permille == 250  # "at most a quarter"
    path = ROOT / piece_budgets.BUDGETS_PATH
    assert BUDGETS.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_budgets_read_as_the_style_pack_reader_reads_them() -> None:
    theirs = style_packs.read_piece_budgets(ROOT)
    assert set(theirs) == set(BUDGETS.families)
    for family, budget in theirs.items():
        ours = BUDGETS.families[family]
        for field in ("triangles", "triangles_per_metre", "materials", "texture_side_px"):
            assert getattr(ours, field) == getattr(budget, field), (family, field)
        assert ours.glb_bytes == budget.glb_bytes, family
        for width_mm in (100, 1000, 4500):
            assert ours.triangle_limit(width_mm) == budget.triangle_limit(width_mm), family


def _write_budgets(tmp_path: Path, document: object, raw: bytes | None = None) -> Path:
    target = tmp_path / piece_budgets.BUDGETS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw if raw is not None else canonical_bytes(document) + b"\n")
    return tmp_path


def _budgets_document() -> dict:
    return json.loads((ROOT / piece_budgets.BUDGETS_PATH).read_bytes())


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d["families"]["prop"].update(triangles_per_metre=10), "exactly one"),
        (lambda d: d["families"]["boundary"].update(triangles_per_metre=0), "exactly one"),
        (lambda d: d["families"]["prop"].pop("materials"), "exactly"),
        (lambda d: d["families"]["prop"].update(materials=True), "whole number"),
        (lambda d: d["families"]["prop"].update(glb_bytes=0), "positive"),
        (lambda d: d["families"].update(spaceship=d["families"]["prop"]), "not a look family"),
        (lambda d: d.update(profile="exulanica.style-pack-piece-budgets/v2"), "is not"),
        (lambda d: d.update(lod1_share_permille=1001), "1 to 1,000"),
        (lambda d: d.update(extra=1), "exactly"),
    ],
)
def test_a_changed_budgets_file_is_refused(tmp_path: Path, change, match: str) -> None:
    document = _budgets_document()
    change(document)
    with pytest.raises(Refused, match=match):
        piece_budgets.read_budgets(_write_budgets(tmp_path, document))


def test_a_budgets_file_with_a_fraction_or_another_spelling_is_refused(tmp_path: Path) -> None:
    raw = (ROOT / piece_budgets.BUDGETS_PATH).read_bytes()
    fraction = raw.replace(b'"materials":2,', b'"materials":2.0,', 1)
    assert fraction != raw
    with pytest.raises(Refused, match="fraction"):
        piece_budgets.read_budgets(_write_budgets(tmp_path, None, fraction))
    spaced = json.dumps(_budgets_document(), indent=1, sort_keys=True).encode() + b"\n"
    with pytest.raises(Refused, match="canonical"):
        piece_budgets.read_budgets(_write_budgets(tmp_path, None, spaced))


# --------------------------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------------------------


def _request(**changes: object) -> dict:
    spec = {**BENCH, **changes}
    return read_request(
        build_request(pack=PACK, variants=2, route="S", budgets=BUDGETS, **spec), BUDGETS
    )


def test_a_request_takes_the_pack_format_s_budget_and_refuses_another() -> None:
    request = _request()
    assert request["profile"] == "exulanica.generated-asset-request/v2"
    assert request["budget"] == {
        "budgets_sha256": BUDGETS.sha256,
        "glb_bytes": 160 * KB,
        "materials": 2,
        "texture_side_px": 256,
        "triangles": 1500,
        "vertices": 4500,
    }
    tampered = dict(request, budget=dict(request["budget"], triangles=9000))
    with pytest.raises(Refused, match="budget"):
        read_request(canonical_bytes(tampered), BUDGETS)


def test_a_tiled_request_takes_triangles_per_metre_of_its_module() -> None:
    fence = _request(
        look_role="boundary.picket_fence",
        slot_mm={"width": 12000, "height": 1000, "depth": 200},
        tile_module_mm=2000,
    )
    assert (fence["budget"]["triangles"], fence["budget"]["vertices"]) == (400, 1200)


def test_a_v2_request_is_read_only_against_the_budgets_file_it_names(tmp_path: Path) -> None:
    raw = build_request(pack=PACK, variants=1, route="S", budgets=BUDGETS, **BENCH)
    with pytest.raises(Refused, match="file it names"):
        read_request(raw, None)
    document = _budgets_document()
    document["about"] += " Changed."
    other = piece_budgets.read_budgets(_write_budgets(tmp_path, document))
    assert other.families == BUDGETS.families and other.sha256 != BUDGETS.sha256
    with pytest.raises(Refused, match="not the file read"):
        read_request(raw, other)


def test_a_v1_request_still_reads_against_the_table_it_was_made_with() -> None:
    # A v1 request as the format wrote it before the pack format's file: kilobytes of 1,000 bytes
    # and the status sentence, with no budgets digest. Nothing here is computed by the reader.
    status = "provisional: the style pack format's numbers, until that format is approved"
    bench = {
        "budget": {
            "glb_bytes": 160_000,
            "materials": 2,
            "status": status,
            "texture_side_px": 256,
            "triangles": 1500,
            "vertices": 4500,
        },
        "fit": "contain",
        "look_role": "prop.bench",
        "pack": PACK,
        "profile": REQUEST_PROFILE_V1,
        "route": "S",
        "slot_mm": BENCH["slot_mm"],
        "variants": 1,
    }
    assert read_request(canonical_bytes(bench), None)["budget"]["glb_bytes"] == 160_000
    shrub_budget = {
        "glb_bytes": 300_000,
        "materials": 2,
        "status": status,
        "texture_side_px": 512,
        "triangles": 800,
        "vertices": 2400,
    }
    shrub = dict(bench, look_role="plant.shrub", budget=shrub_budget)
    assert read_request(canonical_bytes(shrub), BUDGETS)["budget"]["triangles"] == 800
    v2_numbers = dict(bench, budget=dict(bench["budget"], glb_bytes=160 * KB))
    with pytest.raises(Refused, match="budget"):
        read_request(canonical_bytes(v2_numbers), None)


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
        build_request(pack=pack, variants=1, route="S", budgets=BUDGETS, **BENCH)


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
    raw = build_request(pack=PACK, variants=2, route="S", budgets=BUDGETS, **BENCH)
    job = json.loads(
        build_job(
            budgets=BUDGETS,
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
    real = build_request(pack=PACK, variants=1, route="A", budgets=BUDGETS, **BENCH)
    with pytest.raises(Refused, match="stub"):
        build_job(
            budgets=BUDGETS,
            route="A",
            components_sha256="1" * 64,
            requests=[real],
            code_sha256="2" * 64,
            container="stub",
            estimate_seconds=10,
        )


# --------------------------------------------------------------------------------------------
# Held pieces, the prompt template and the job's version
# --------------------------------------------------------------------------------------------

SWORD = {"look_role": "prop.sword", "slot_mm": {"width": 120, "height": 1000, "depth": 40}}
#: The thing kind's grip (THINGS: 150 mm up its length, extending upward) and humanoid/v1's
#: grip_section_mm_maximum (60 mm), as THINGS states them on 2026-10-06.
SWORD_HOLD = {"axis": "+z", "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 150}, "section_mm_maximum": 60}


def _held(**hold_changes: object) -> dict:
    hold = {**SWORD_HOLD, **hold_changes}
    return read_request(
        build_request(pack=PACK, variants=1, route="S", budgets=BUDGETS, hold=hold, **SWORD),
        BUDGETS,
    )


def test_a_held_request_carries_its_grip_and_poses_its_picture() -> None:
    request = _held()
    assert request["hold"] == SWORD_HOLD
    pose = "standing upright, its handle at the bottom, whole object in frame"
    assert pose in prompt_for(request)
    assert "hanging from a ring or handle at its top" in prompt_for(_held(axis="-z"))


def test_a_request_without_a_grip_keeps_the_first_template_s_words() -> None:
    # The template's words before it had a version, typed here: a version names them, it does
    # not change them.
    assert prompt_for(_request()) == (
        "bench, a single prop for a game world, toon style, flat colours, chunky simple shapes, "
        "about 1800 mm wide, 900 mm tall and 700 mm deep, whole object in frame, three-quarter "
        "front view, plain light grey background, no text, no lettering, no logo"
    )


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"axis": "up"}, "hold.axis"),
        ({"grip": {"x_mm": 0, "y_mm": 0, "z_mm": 1001}}, "inside the slot"),
        ({"grip": {"x_mm": 61, "y_mm": 0, "z_mm": 150}}, "inside the slot"),
        ({"grip": {"x_mm": 0, "y_mm": 21, "z_mm": 150}}, "inside the slot"),
        ({"grip": {"x_mm": 0, "y_mm": 0, "z_mm": -1}}, "inside the slot"),
        ({"grip": {"x_mm": 0, "y_mm": 0}}, "exactly"),
        ({"grip": {"x_mm": 0.5, "y_mm": 0, "z_mm": 150}}, "fraction"),
        ({"grip": {"x_mm": "0", "y_mm": 0, "z_mm": 150}}, "whole millimetres"),
        ({"section_mm_maximum": 0}, "1 to 1,000"),
        ({"reach": 3}, "exactly"),
    ],
)
def test_a_held_request_refuses(changes: dict, match: str) -> None:
    with pytest.raises(Refused, match=match):
        _held(**changes)


def test_only_a_contained_piece_and_a_v2_request_hold_a_grip() -> None:
    door = {"look_role": "door.shop_door", "slot_mm": {"width": 1200, "height": 2400, "depth": 300}}
    with pytest.raises(Refused, match="contain"):
        build_request(pack=PACK, variants=1, route="S", budgets=BUDGETS, hold=SWORD_HOLD, **door)
    v1 = json.loads(build_request(pack=PACK, variants=1, route="S", budgets=BUDGETS, **SWORD))
    v1["profile"] = REQUEST_PROFILE_V1
    v1["hold"] = SWORD_HOLD
    with pytest.raises(Refused, match="v1 request holds no grip"):
        read_request(canonical_bytes(v1), BUDGETS)


def _measured(**hold: object) -> dict:
    budget = _held()["budget"]
    base = {key: 0 for key in ("glb_bytes", "materials", "texture_side_px", "triangles")}
    base["vertices"] = 0
    held = {"band_mm": 10, "fill_permille": 800, "grip_in_section": True}
    held["section_mm"] = {"x_mm": 60, "y_mm": 30}
    held.update(hold)
    return verdict({**base, "hold": held}, budget, SWORD_HOLD)


def test_a_held_piece_s_verdict_names_its_fill_and_its_grip() -> None:
    assert _measured() == {"over": [], "within": True}  # 800 per mille and 60 mm are allowed
    assert _measured(fill_permille=799)["over"] == ["hold_fill"]
    assert _measured(section_mm={"x_mm": 61, "y_mm": 30})["over"] == ["grip_section"]
    assert _measured(section_mm=None, grip_in_section=False)["over"] == ["grip_section"]
    assert _measured(grip_in_section=False)["over"] == ["grip_section"]


def test_a_job_names_its_prompt_template_and_a_v1_job_still_reads() -> None:
    raw = build_request(pack=PACK, variants=1, route="S", budgets=BUDGETS, **BENCH)
    job = json.loads(
        build_job(
            budgets=BUDGETS,
            route="S",
            components_sha256="1" * 64,
            requests=[raw],
            code_sha256="2" * 64,
            container="stub",
            estimate_seconds=10,
        )
    )
    assert job["profile"] == "exulanica.generated-asset-job/v2"
    assert job["prompt_version"] == "exulanica.generated-asset-prompt/v1"
    with pytest.raises(Refused, match="prompt template"):
        read_job(canonical_bytes(dict(job, prompt_version="exulanica.generated-asset-prompt/v0")))
    v1 = {key: value for key, value in job.items() if key != "prompt_version"}
    v1["profile"] = "exulanica.generated-asset-job/v1"
    assert read_job(canonical_bytes(v1))["route"] == "S"
    with pytest.raises(Refused, match="exactly"):
        read_job(canonical_bytes(dict(v1, prompt_version=job["prompt_version"])))


def test_the_shared_case_is_one_held_piece_s_records_read_strictly() -> None:
    """The case other readers test against (the origin record's) holds records these readers
    accept: a request, the job that made it and its receipt, tied together by digest."""
    path = ROOT / "tests/fixtures/generated-piece/sword-case.v1.json"
    case = parse_canonical(path.read_bytes().rstrip(b"\n"), "case")
    assert case["profile"] == "exulanica.generated-piece-case/v1"
    request = read_request(canonical_bytes(case["request"]), BUDGETS)
    job_raw = canonical_bytes(case["job"])
    job = read_job(job_raw)
    receipt = read_receipt(canonical_bytes(case["receipt"]), request)
    request_sha256 = sha256_hex(canonical_bytes(case["request"]))
    assert receipt["job_sha256"] == sha256_hex(job_raw)
    assert request_sha256 in {item["request_sha256"] for item in job["items"]}
    assert (request["look_role"], request["hold"]["axis"]) == ("prop.sword", "+z")
    assert (receipt["origin"], receipt["truth"], receipt["licence"]) == (
        "generated",
        "invented",
        "CC0-1.0",
    )
    assert receipt["verdict"] == {"over": [], "within": True}
