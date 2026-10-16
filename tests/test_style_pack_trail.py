"""Plants that hang over a ground's edge (a pack's ``trail``).

The rule's refusals are shared cases in ``assets/style-packs/manifest-cases.v1.json``, which both
readers run. Here, what only the server holds: a pack that states no trail keeps its bytes, and one
that states a rule keeps exactly the figures it states; a pack drawn on a base may name its base's
plants, while one with no base names its own; and the admission holds every piece a trail rule
names to a textured piece, since trailing plants are drawn instanced.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import style_packs
from exulanica.world.style_pack_admission import StylePackAdmissionRefused, admit
from exulanica_pieces.budgets import read_budgets

from static_glb_builder import UNSIGNED_SHORT, Gltf, png
from style_pack_upload_support import Upload, upload

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = read_budgets(ROOT)
CASES: dict[str, Any] = json.loads(
    (ROOT / "assets/style-packs/manifest-cases.v1.json").read_text(encoding="utf-8")
)
BY_NAME = {case["name"]: case for case in CASES["cases"]}
#: A pack with plant modules and no trail, and the same pack with two trail rules, one stating
#: every optional figure and one stating none.
LAWNS = BY_NAME["a pack growing grass and flowers on its lawns in a wind"]
TRAILS = BY_NAME[
    "a pack hanging plants over its grounds' edges, one rule stating every figure and one none"
]
RULE = {"pieces": ["plant.ivy"], "share_permille": 300, "hang_permille": [200, 600], "seed": 5}


def _context() -> style_packs.StylePackContext:
    families = {
        key: style_packs.LookFamily(**value) for key, value in CASES["context"]["families"].items()
    }
    return style_packs.StylePackContext(
        families=families, texture_sets=frozenset(CASES["context"]["texture_sets"])
    )


def test_a_pack_stating_no_trail_keeps_its_bytes_and_a_rule_keeps_only_the_figures_it_states():
    untouched = style_packs.read_manifest(LAWNS["manifest"], _context())
    assert "trail" not in untouched
    assert style_packs.manifest_sha256(untouched) == LAWNS["expect"]["sha256"]
    read = style_packs.read_manifest(TRAILS["manifest"], _context())
    # No figure the rule leaves out is written in: the page's defaults stay the page's.
    assert read["trail"]["ground.default"] == {
        "pieces": ["plant.grass_tuft"],
        "share_permille": 250,
        "hang_permille": [500, 500],
        "seed": 0,
    }
    assert read["trail"]["ground.lawn"] == TRAILS["manifest"]["trail"]["ground.lawn"]


def test_a_pack_on_a_base_may_name_its_bases_plants_and_one_with_no_base_names_its_own():
    drafted = copy.deepcopy(BY_NAME["a pack drafted on a base, stating only what it changes"])
    on_base = {**drafted["manifest"], "trail": {"ground.lawn": RULE}}
    assert on_base["base"] is not None and "plant.ivy" not in on_base["modules"]
    assert style_packs.read_manifest(on_base, _context())["trail"] == {"ground.lawn": RULE}
    no_base = {**TRAILS["manifest"], "trail": {"ground.lawn": RULE}}
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(no_base, _context())
    assert (refused.value.reason, refused.value.path) == (
        "reference",
        "trail.ground.lawn.pieces[0]",
    )


def _textured_plant() -> bytes:
    """A 1 by 1.5 m leafy quad hanging down from its edge, drawn in a picture: a textured piece."""
    gltf = Gltf()
    quad = [(-0.5, 0.0, 0.05), (-0.5, 1.5, 0.05), (0.5, 1.5, 0.05), (0.5, 0.0, 0.05)]
    primitive = {
        "attributes": {
            "POSITION": gltf.positions(quad),
            "NORMAL": gltf.vectors([(0.0, 0.0, 1.0)] * 4, "VEC3"),
            "TEXCOORD_0": gltf.vectors([(0, 0), (0, 1), (1, 1), (1, 0)], "VEC2"),
        },
        "indices": gltf.indices([0, 1, 2, 0, 2, 3], UNSIGNED_SHORT),
        "material": 0,
        "mode": 4,
    }
    colour = gltf.texture(gltf.image(png(64, 64), "image/png"))
    gltf.material(
        pbrMetallicRoughness={"baseColorTexture": {"index": colour}},
        alphaMode="MASK",
        alphaCutoff=0.5,
        doubleSided=True,
    )
    gltf.mesh(primitive)
    gltf.scene(gltf.node(mesh=0))
    return gltf.build()


def _no_base(_base: Any) -> str:
    raise StylePackAdmissionRefused("style_pack_base_unavailable", "no base here", path="base")


def _admit(made: Upload) -> Any:
    return admit(
        made.declaration_bytes(),
        made.manifest_bytes,
        made.files,
        context=style_packs.load_context(ROOT),
        budgets=BUDGETS.families,
        lod1_share_permille=BUDGETS.lod1_share_permille,
        resolve_base=_no_base,
    )


def _trailing(made: Upload) -> Upload:
    made.manifest["trail"] = {"ground.default": {**RULE, "pieces": ["plant.default"]}}
    return made


def test_a_trailing_piece_is_admitted_textured_and_refused_by_name_as_a_palette_piece():
    textured = upload()
    textured.files["pieces/tree.glb"] = _textured_plant()
    textured = _trailing(textured.relist())
    assert _admit(textured).manifest_canonical == textured.manifest_bytes
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(_trailing(upload()))
    assert (refused.value.code, refused.value.path, str(refused.value)) == (
        "style_pack_piece_refused",
        "pieces/tree.glb",
        "pieces/tree.glb: a trailing piece is a textured piece: trail is drawn instanced",
    )
