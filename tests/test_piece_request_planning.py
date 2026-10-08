"""Planning piece requests: from an ask (thing kinds and a look) to request documents and an
estimate.

Expected values come from elsewhere than the planner: the requests warm session 1 actually ran
(``ml/appearance/evidence/generated-assets-session-1/requests``, built by its own script), the kind
documents under ``assets/catalogs/things/kinds``, the committed pack manifests, and figures worked
by hand from the compute catalog's rate.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    PieceAskRefused,
    assert_catalog_words,
    estimate,
    generation_catalogs,
    plan_requests,
)
from exulanica.world.style_pack_library import style_pack_library
from exulanica_pieces.canonical import sha256_hex
from exulanica_pieces.styles import PieceStyles

ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = ROOT / "ml/appearance/evidence/generated-assets-session-1/requests"
LIBRARY = style_pack_library()


def _ran() -> dict[str, bytes]:
    """Session 1's requests by look role, as its builder wrote them."""
    found = {}
    for path in SESSION_1.glob("*.json"):
        raw = path.read_bytes()
        found[json.loads(raw)["look_role"]] = raw
    return found


def _cozy_as_session_1_saw_it() -> LookReference:
    pack = json.loads(next(iter(_ran().values())))["pack"]
    return LookReference(pack["id"], pack["version"], pack["sha256"])


def test_kinds_with_no_recipe_entry_plan_the_requests_session_1_ran() -> None:
    ran = _ran()
    planned = plan_requests(
        [("lantern", 1), ("sword", 3), ("planter_tree", 1)],
        _cozy_as_session_1_saw_it(),
        library=LIBRARY,
    )
    for plan in planned:
        assert plan.request == ran[plan.look_role], plan.look_role
        assert plan.request_sha256 == sha256_hex(ran[plan.look_role])
        assert plan.cache_scope == "catalog" and plan.variants == 4


def test_a_kind_with_a_newer_recipe_entry_carries_its_words_and_version() -> None:
    (gate,) = plan_requests([("gate", 1)], _cozy_as_session_1_saw_it(), library=LIBRARY)
    document = json.loads(gate.request)
    box = json.loads((ROOT / "assets/catalogs/things/kinds/gate.v1.json").read_text())["body"]
    assert document["slot_mm"] == box["box_mm"]
    assert document["look_role"] == "fixture.gate"
    assert document["description"] == (
        "a wide flat wooden village gate: two thin posts and a wide open arch, flat"
    )
    assert document["recipe"]["catalog_version"] == 2
    # Session 1 asked by the bare key; this is a different request, so it is made anew.
    assert gate.request != _ran()["fixture.gate"]


def test_the_look_s_palette_and_style_words_are_the_pack_s() -> None:
    pack = LIBRARY.pack("exulanica.toon-town")
    assert pack is not None
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    (well,) = plan_requests([("well", 1)], look, library=LIBRARY)
    document = json.loads(well.request)["pack"]
    manifest = json.loads(
        (ROOT / "assets/style-packs/packs/exulanica.toon-town/manifest.json").read_text()
    )
    assert document["palette"] == [swatch["srgb8"] for swatch in manifest["palette"]["swatches"]]
    assert document["style"] == (
        "bright flat toon colours, dark ink outlines, white frames, blue glass, "
        "round toy-like shapes"
    )
    assert (document["id"], document["version"], document["sha256"]) == (
        pack.pack_id,
        pack.version,
        pack.manifest_sha256,
    )


def test_the_estimate_is_worked_from_the_rate() -> None:
    planned = plan_requests(
        [("well", 1), ("gate", 1), ("lantern", 1)], _cozy_as_session_1_saw_it(), library=LIBRARY
    )
    worked = estimate(planned, generation_catalogs().compute.for_provider(GPU_PROVIDER))
    # 3 kinds of 4 variants; 8 s typical, 30 s bound, USD 1.80 an hour (0.05 cents a second).
    assert worked.items == 12
    assert (worked.first_seconds_warm, worked.all_seconds_warm) == (24, 96)
    assert worked.usd_typical == Decimal("0.048")
    assert worked.usd_worst_case == Decimal("0.18")
    assert worked.cold_start_seconds == 680
    assert worked.provider == "nebius_ai_cloud_gpu"


@pytest.mark.parametrize(
    ("kinds", "code"),
    [
        ([("knight", 1)], "kind_without_piece"),
        ([("well", 9)], "kind_unknown"),
        ([("well", 1), ("well", 1)], "kind_repeated"),
        ([("well", 1)] * 0, "too_many_kinds"),
        ([(f"kind_{n}", 1) for n in range(17)], "too_many_kinds"),
    ],
)
def test_an_ask_that_cannot_be_built_is_refused_whole(
    kinds: list[tuple[str, int]], code: str
) -> None:
    with pytest.raises(PieceAskRefused) as refused:
        plan_requests(kinds, _cozy_as_session_1_saw_it(), library=LIBRARY)
    assert refused.value.code == code


def test_a_look_this_server_does_not_serve_is_refused() -> None:
    look = _cozy_as_session_1_saw_it()
    with pytest.raises(PieceAskRefused) as refused:
        plan_requests(
            [("well", 1)], dataclasses.replace(look, manifest_sha256="0" * 64), library=LIBRARY
        )
    assert refused.value.code == "look_not_served"


def test_a_pack_without_style_words_has_no_generated_pieces() -> None:
    catalogs = generation_catalogs()
    without = dataclasses.replace(
        catalogs, styles=PieceStyles(catalog_version=1, sha256="0" * 64, words={})
    )
    with pytest.raises(PieceAskRefused) as refused:
        plan_requests([("well", 1)], _cozy_as_session_1_saw_it(), library=LIBRARY, catalogs=without)
    assert refused.value.code == "look_without_style_words"


def _document(plan) -> dict:
    return json.loads(plan.request)


def test_every_planned_request_s_words_are_the_catalogs_own() -> None:
    catalogs = generation_catalogs()
    kinds = [("well", 1), ("gate", 1), ("lantern", 1), ("bench", 1), ("planter_tree", 1)]
    for pack in LIBRARY.packs:
        look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
        for plan in plan_requests(kinds, look, library=LIBRARY):
            assert_catalog_words(_document(plan), catalogs)


@pytest.mark.parametrize(
    "forge",
    [
        # A person's own words in place of the recipe's.
        lambda d: {**d, "description": "the blue bench my grandmother sat on"},
        # The recipe's words, claimed under a catalog version that has no such entry.
        lambda d: {**d, "recipe": {**d["recipe"], "catalog_version": 1}},
        # Words with no recipe named at all.
        lambda d: {k: v for k, v in d.items() if k != "recipe"},
        # Style words that are not the pack's.
        lambda d: {**d, "pack": {**d["pack"], "style": "in the style of my own drawings"}},
    ],
    ids=["free-words", "wrong-version", "no-recipe", "free-style"],
)
def test_a_request_holding_words_no_catalog_states_is_refused(forge) -> None:
    (gate,) = plan_requests([("gate", 1)], _cozy_as_session_1_saw_it(), library=LIBRARY)
    document = _document(gate)
    assert_catalog_words(document, generation_catalogs())  # the positive control
    with pytest.raises(PieceAskRefused) as refused:
        assert_catalog_words(forge(document), generation_catalogs())
    assert refused.value.code == "words_not_from_catalog"
