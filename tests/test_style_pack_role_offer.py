"""What a look offers a look role before any slot's fit, in the page's order: the leaf, then the
family's default, else the engine's primitive. Asked of the committed library packs, read from
their files, and of a look of generated pieces drawn on one, whose base's modules still answer for
every role it does not state itself."""

from __future__ import annotations

import json
from pathlib import Path

from exulanica.generation.looks import GeneratedVariant, build_derived_look
from exulanica.world.style_packs import load_context, read_manifest, role_offer

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "assets/style-packs/packs"
CONTEXT = load_context(ROOT)


def _pack(pack_id: str) -> dict:
    return read_manifest(json.loads((PACKS / pack_id / "manifest.json").read_text()), CONTEXT)


def test_a_role_is_offered_its_leaf_then_its_family_s_default_then_nothing() -> None:
    cozy = _pack("exulanica.cozy-town")
    assert "plant.default" in cozy["modules"] and "plant.oak" not in cozy["modules"]
    assert role_offer([cozy], "plant.default", CONTEXT) == "leaf"
    assert role_offer([cozy], "plant.oak", CONTEXT) == "default"
    assert role_offer([cozy], "vehicle.sedan", CONTEXT) == "leaf"
    # A fixture family the cozy town dresses with no piece at all: the engine's box.
    assert not any(name.startswith("fixture.") for name in cozy["modules"])
    assert role_offer([cozy], "fixture.well", CONTEXT) is None
    # A family no catalog knows, and one only surfaces dress, offer no piece either.
    assert role_offer([cozy], "nothing.well", CONTEXT) is None
    assert role_offer([cozy], "character.default", CONTEXT) is None


def test_a_look_of_generated_pieces_answers_with_its_own_modules_then_its_base_s() -> None:
    cozy = _pack("exulanica.cozy-town")
    well = GeneratedVariant("1" * 64, 1000, (1200, 1200, 1500), "2" * 64)
    derived = build_derived_look(
        chain=[cozy], version=1, roles={"fixture.well": [well]}, authors=["a"], context=CONTEXT
    )
    assert derived is not None
    chain = [derived.manifest, cozy]
    assert role_offer(chain, "fixture.well", CONTEXT) == "leaf"
    assert role_offer(chain, "fixture.gate", CONTEXT) is None
    assert role_offer(chain, "plant.oak", CONTEXT) == "default"
