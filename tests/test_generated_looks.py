"""A world's own look: the derived style pack version passed generated pieces make.

The base is a library pack as the host's library serves it, so the derived look's base reference
is checked against the library's own listing; every manifest is also read by the style pack reader
under the real family catalog. The shared case of a generated pack drawn on a base, which the
browser's reader reads too, is pinned to what the builder writes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.generation import looks
from exulanica.world import style_packs
from exulanica.world.style_pack_library import style_pack_library

ROOT = Path(__file__).resolve().parents[1]
CASES: dict[str, Any] = json.loads(
    (ROOT / "assets/style-packs/manifest-cases.v1.json").read_text(encoding="utf-8")
)
CONTEXT = style_packs.load_context(ROOT)
COZY = "exulanica.cozy-town"


def _cozy() -> dict[str, Any]:
    raw = (ROOT / "assets/style-packs/packs" / COZY / "manifest.json").read_text(encoding="utf-8")
    return style_packs.read_manifest(json.loads(raw), CONTEXT)


def _piece(n: int, *, size: tuple[int, int, int] = (1200, 1200, 1500)) -> looks.GeneratedVariant:
    return looks.GeneratedVariant(
        piece_sha256=f"{n:064x}",
        piece_bytes=1000 + n,
        size_mm=size,
        receipt_sha256=f"{n + 0xF00:064x}",
    )


ROLES = {"fixture.well": [_piece(1), _piece(2)], "vehicle.sedan": [_piece(3)]}


def _build(chain: list[dict[str, Any]], roles: Any = None, version: int = 1) -> looks.DerivedLook:
    built = looks.build_derived_look(
        chain=chain,
        version=version,
        roles=ROLES if roles is None else roles,
        authors=["TRELLIS-image-large"],
        context=CONTEXT,
    )
    assert built is not None
    return built


def _drawn_on(base: dict[str, Any], pack_id: str) -> dict[str, Any]:
    """An authored pack drawn on ``base`` that restates nothing: a link of a longer chain."""
    manifest = copy.deepcopy(base)
    manifest.update(
        pack_id=pack_id,
        version=1,
        base={
            "pack_id": base["pack_id"],
            "version": base["version"],
            "manifest_sha256": style_packs.manifest_sha256(base),
        },
        light=None,
        shading=None,
        edge=None,
        palette={"encoding": style_packs.COLOUR_ENCODING, "swatches": []},
        surfaces={},
        modules={},
        files=[],
        preview=None,
    )
    return style_packs.read_manifest(manifest, CONTEXT)


def test_a_derived_look_is_drawn_on_the_library_pack_and_states_only_its_new_pieces() -> None:
    served = style_pack_library().pack(COZY)
    assert served is not None
    built = _build([_cozy()])
    manifest = built.manifest
    assert manifest["base"] == {
        "pack_id": COZY,
        "version": served.version,
        "manifest_sha256": served.manifest_sha256,
    }
    assert manifest["pack_id"] == "generated.cozy-town"
    assert (manifest["origin"], manifest["provenance"]["kind"]) == ("generated", "generated")
    assert manifest["licence"] == {"id": "CC0-1.0", "attribution": None}
    assert (manifest["light"], manifest["shading"], manifest["edge"]) == (None, None, None)
    assert (manifest["palette"]["swatches"], manifest["surfaces"]) == ([], {})
    assert sorted(manifest["modules"]) == ["fixture.well", "vehicle.sedan"]
    assert [v["file"] for v in manifest["modules"]["fixture.well"]["variants"]] == [
        f"generated/{1:064x}.glb",
        f"generated/{2:064x}.glb",
    ]
    assert manifest["modules"]["vehicle.sedan"]["variants"][0] == {
        "file": f"generated/{3:064x}.glb",
        "lod1": None,
        "size_mm": [1200, 1200, 1500],
        "stretch_mm": [None, None, None],
    }
    assert manifest["provenance"]["receipts"] == [f"{n + 0xF00:064x}" for n in (1, 2, 3)]
    assert manifest["title"] == "Cozy town, with new pieces"
    assert built.sha256 == style_packs.manifest_sha256(json.loads(built.canonical))


def test_the_same_pieces_on_the_same_base_are_the_same_look_whatever_the_order() -> None:
    first = _build([_cozy()])
    reordered = {"vehicle.sedan": ROLES["vehicle.sedan"], "fixture.well": ROLES["fixture.well"]}
    again = _build([_cozy()], reordered)
    assert (again.canonical, again.sha256) == (first.canonical, first.sha256)
    other_version = _build([_cozy()], version=2)
    assert other_version.content_sha256 == first.content_sha256
    assert other_version.sha256 != first.sha256
    swapped = {"fixture.well": [_piece(2), _piece(1)], "vehicle.sedan": [_piece(3)]}
    assert _build([_cozy()], swapped).content_sha256 != first.content_sha256
    on_another_base = _build([_drawn_on(_cozy(), "exulanica.case-two"), _cozy()])
    assert on_another_base.content_sha256 != first.content_sha256


def test_taking_back_every_piece_leaves_the_base_and_taking_back_one_kind_keeps_the_rest() -> None:
    assert (
        looks.build_derived_look(
            chain=[_cozy()], version=1, roles={"fixture.well": []}, authors=["m"], context=CONTEXT
        )
        is None
    )
    kept = _build([_cozy()], {"fixture.well": ROLES["fixture.well"], "vehicle.sedan": []})
    assert sorted(kept.manifest["modules"]) == ["fixture.well"]
    assert [f["path"] for f in kept.manifest["files"]] == [
        f"generated/{1:064x}.glb",
        f"generated/{2:064x}.glb",
    ]


def test_one_piece_dressing_two_roles_is_listed_once() -> None:
    built = _build([_cozy()], {"fixture.well": [_piece(1)], "vehicle.sedan": [_piece(1)]})
    assert [f["path"] for f in built.manifest["files"]] == [f"generated/{1:064x}.glb"]
    with pytest.raises(looks.DerivedLookRefused) as refused:
        _build(
            [_cozy()],
            {
                "fixture.well": [_piece(1)],
                "vehicle.sedan": [looks.GeneratedVariant(f"{1:064x}", 7, (10, 10, 10), "0" * 64)],
            },
        )
    assert refused.value.code == "piece_size_differs"


def test_a_chain_of_three_takes_a_derived_look_and_a_chain_of_four_does_not() -> None:
    cozy = _cozy()
    two = _drawn_on(cozy, "exulanica.case-two")
    three = _drawn_on(two, "exulanica.case-three")
    built = _build([three, two, cozy])
    assert built.manifest["base"]["pack_id"] == "exulanica.case-three"
    four = _drawn_on(three, "exulanica.case-four")
    with pytest.raises(looks.DerivedLookRefused) as refused:
        _build([four, three, two, cozy])
    assert refused.value.code == "look_chain_full"


@pytest.mark.parametrize(
    ("chain", "code"),
    [
        ([], "chain_incomplete"),
        ("missing-bottom", "chain_incomplete"),
        ("wrong-link", "chain_broken"),
        ("same-number-other-bytes", "chain_broken"),
        ("generated-base", "base_is_generated"),
    ],
)
def test_a_chain_that_is_not_one_library_pack_and_its_bases_is_refused(
    chain: Any, code: str
) -> None:
    cozy = _cozy()
    two = _drawn_on(cozy, "exulanica.case-two")
    if chain == "missing-bottom":
        chain = [two]
    elif chain == "wrong-link":
        other = copy.deepcopy(cozy)
        other["version"] = cozy["version"] + 1
        chain = [two, other]
    elif chain == "same-number-other-bytes":
        # The base edited without a new number: its id and version match, its digest does not.
        other = copy.deepcopy(cozy)
        other["title"] = "Cozy town edited"
        chain = [two, other]
    elif chain == "generated-base":
        chain = [_build([cozy]).manifest, cozy]
    with pytest.raises(looks.DerivedLookRefused) as refused:
        _build(chain)
    assert refused.value.code == code


def test_a_module_holds_at_most_eight_pieces_and_the_caller_chooses_them() -> None:
    eight = [_piece(n) for n in range(1, 9)]
    assert len(_build([_cozy()], {"fixture.well": eight}).manifest["files"]) == 8
    with pytest.raises(looks.DerivedLookRefused) as refused:
        _build([_cozy()], {"fixture.well": [*eight, _piece(9)]})
    assert refused.value.code == "too_many_variants"


def test_a_role_the_family_catalog_does_not_dress_with_pieces_is_refused_by_the_reader() -> None:
    with pytest.raises(looks.DerivedLookRefused) as refused:
        _build([_cozy()], {"wall.brick": [_piece(1)]})
    assert refused.value.code == "refused_by_reader"
    assert "modules.wall.brick" in refused.value.detail


def test_a_derived_id_is_its_library_base_s_in_the_generated_namespace() -> None:
    assert looks.derived_pack_id("exulanica.cozy-town") == "generated.cozy-town"
    assert looks.derived_pack_id("exulanica.a.b.c") == "generated.a.b.c"
    with pytest.raises(looks.DerivedLookRefused) as refused:
        looks.derived_pack_id("creator.own-town")
    assert refused.value.code == "base_not_library"


def test_the_shared_generated_case_is_what_the_builder_writes_on_its_base() -> None:
    by_name = {case["name"]: case for case in CASES["cases"]}
    base = by_name["a complete pack with no base"]["manifest"]
    case = by_name["a generated pack drawn on a base, stating only its new pieces"]
    families = {
        key: style_packs.LookFamily(**value) for key, value in CASES["context"]["families"].items()
    }
    context = style_packs.StylePackContext(
        families=families, texture_sets=frozenset(CASES["context"]["texture_sets"])
    )
    built = looks.build_derived_look(
        chain=[style_packs.read_manifest(base, context)],
        version=1,
        roles={
            "fixture.well": [_piece(1), _piece(2)],
            "vehicle.car": [_piece(3, size=(1900, 4600, 1600))],
        },
        authors=["TRELLIS-image-large"],
        context=context,
    )
    assert built is not None
    assert built.manifest == case["manifest"]
    assert built.sha256 == case["expect"]["sha256"]
