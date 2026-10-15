"""Plants that climb a building's walls (a pack's ``climb``).

The reader takes the optional field keyed by a structure look role and refuses it by reason and
path elsewhere; a pack that states none keeps its bytes; and the admission holds every piece a
climb rule names to a textured piece, since climbing plants are drawn instanced. The browser's
reader is held to the same refusals by ``web/packages/atlas-core/test/style-pack.test.ts``.
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
#: The shared cases' complete pack, whose plants are not its modules: a car and a window only.
BASE = CASES["cases"][0]
RULE = {
    "pieces": ["vehicle.car"],
    "walls": ["back", "left", "right"],
    "sun_within_mdeg": 100_000,
    "share_permille": 400,
    "height_permille": [300, 700],
    "seed": 7,
}


def _context() -> style_packs.StylePackContext:
    families = {
        key: style_packs.LookFamily(**value) for key, value in CASES["context"]["families"].items()
    }
    families["structure"] = style_packs.LookFamily("contain", "both", 0, 0)
    return style_packs.StylePackContext(
        families=families, texture_sets=frozenset(CASES["context"]["texture_sets"])
    )


def _with_plant(rule: dict[str, Any], role: str = "structure.default") -> dict[str, Any]:
    """The base pack with a plant module (its car's piece stands in) and ``rule`` on ``role``."""
    manifest = copy.deepcopy(BASE["manifest"])
    manifest["modules"]["plant.ivy"] = copy.deepcopy(manifest["modules"]["vehicle.car"])
    manifest["climb"] = {role: {**rule, "pieces": ["plant.ivy"]}}
    return manifest


def test_a_pack_may_grow_plants_on_a_structures_walls_and_one_stating_none_reads_as_it_did():
    read = style_packs.read_manifest(_with_plant(RULE), _context())
    assert read["climb"]["structure.default"]["walls"] == ["back", "left", "right"]
    assert '"climb":{"structure.default":' in style_packs.canonical_json(read)
    # The sun test is optional.
    plain = {key: value for key, value in RULE.items() if key != "sun_within_mdeg"}
    assert (
        "sun_within_mdeg"
        not in style_packs.read_manifest(_with_plant(plain), _context())["climb"][
            "structure.default"
        ]
    )
    untouched = style_packs.read_manifest(BASE["manifest"], _context())
    assert "climb" not in untouched
    assert style_packs.manifest_sha256(untouched) == BASE["expect"]["sha256"]


@pytest.mark.parametrize(
    ("manifest", "reason", "path"),
    [
        (_with_plant(RULE, "fixture.bench"), "reference", "climb.fixture.bench"),
        (
            {**_with_plant(RULE), "climb": {"structure.default": RULE}},
            "reference",
            "climb.structure.default.pieces[0]",
        ),
        (
            _with_plant({**RULE, "walls": ["back", "back"]}),
            "duplicate",
            "climb.structure.default.walls",
        ),
        (_with_plant({**RULE, "walls": ["roof"]}), "range", "climb.structure.default.walls[0]"),
        (_with_plant({**RULE, "walls": []}), "range", "climb.structure.default.walls"),
        (
            _with_plant({**RULE, "height_permille": [800, 200]}),
            "range",
            "climb.structure.default.height_permille",
        ),
        (
            _with_plant({**RULE, "sun_within_mdeg": 180_001}),
            "range",
            "climb.structure.default.sun_within_mdeg",
        ),
        (
            _with_plant({**RULE, "share_permille": 0}),
            "range",
            "climb.structure.default.share_permille",
        ),
        (_with_plant({**RULE, "spread": 3}), "shape", "climb.structure.default"),
    ],
    ids=[
        "not a structure",
        "a piece that is no plant",
        "a wall twice",
        "an unknown wall",
        "no wall",
        "height out of order",
        "sun past half a turn",
        "no share",
        "an unknown key",
    ],
)
def test_a_climb_rule_is_refused_by_reason_and_path(manifest, reason, path):
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(manifest, _context())
    assert (refused.value.reason, refused.value.path) == (reason, path)


def _textured_plant() -> bytes:
    """A 1 by 2 m leafy quad against its wall, drawn in a picture: a textured piece."""
    gltf = Gltf()
    quad = [(-0.5, 0.0, 0.05), (-0.5, 2.0, 0.05), (0.5, 2.0, 0.05), (0.5, 0.0, 0.05)]
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


def _climbing(made: Upload) -> Upload:
    made.manifest["climb"] = {"structure.default": {**RULE, "pieces": ["plant.default"]}}
    return made


def test_a_climbing_piece_is_admitted_textured_and_refused_by_name_as_a_palette_piece():
    textured = upload()
    textured.files["pieces/tree.glb"] = _textured_plant()
    textured = _climbing(textured.relist())
    assert _admit(textured).manifest_canonical == textured.manifest_bytes
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(_climbing(upload()))
    assert (refused.value.code, refused.value.path, str(refused.value)) == (
        "style_pack_piece_refused",
        "pieces/tree.glb",
        "pieces/tree.glb: a climbing piece is a textured piece: climb is drawn instanced",
    )
