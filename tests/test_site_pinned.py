"""Today's site worlds, pinned: the digests a world of each fixture kind is held to.

A site world regenerates from its receipt and is held to its plan digest and its output digest; its
people walk the place its records make; the page draws the drawing its receipt makes. A change to
the site grammar, the walking place or the drawing that is meant to leave every existing world as
it was (such as an optional field only a world that asks for it states) leaves these literals as
they are. A change meant to move them says so, and states the new values with its reason.

The kinds are the hand-written fixtures in ``tests/fixtures/world-kinds``; the land is written here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.world.composers.site_plan import compose_kind
from exulanica.world.kinds.document import read_kind
from exulanica.world.site_drawing import site_drawing, site_drawing_sha256

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"

#: A small land: rising north to a hill, a shore to the south, mountains on the horizon.
LAND = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 8000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
        {"id": "swell", "kind": "undulation", "amplitude_mm": 700, "wavelength_mm": 40000},
        {"id": "hill", "kind": "rise", "side": "north", "distance_mm": 30000, "height_mm": 20000},
        {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
        {"id": "skyline", "kind": "range", "side": "north", "distance_mm": 2000000,
         "band_mm": 800000, "height_mm": 300000},
    ],
}  # fmt: skip

#: Each world's plan, output, walking place and drawing digests, by fixture and ground.
PINNED: dict[tuple[str, str], dict[str, str]] = {
    ("farm", "level"): {
        "plan": "153718fb014e38e00721e6984459f96515b5baaa0914b1a309e63f0cb7e4648d",
        "output": "15038a3d47e0cd50e314fe276193e5fab37acdf869f917ddb7d16e64e788a9f3",
        "place": "77f91ea2412aa4c025388b4a0e5149d906cf0a84d22a3dde41b2130a5f760c30",
        "drawing": "2743b374b95f94ab4276f5286ed216a2af38ae5e9c5a5d00b9f8e1f1329dc057",
    },
    ("cafe", "level"): {
        "plan": "7babded1d2d4b6897dd3019ae8b271925db60254124b9ae1c4b754eb25fce913",
        "output": "ae31888d719eaaf4882cf9bc94254efd8e3911fa1db8ce80025cb85763f67196",
        "place": "ff6ec3cbda6e5a49ffa64ae5422396f7bbb198ab731095fe2dced309b57f84ce",
        "drawing": "0a14eb6d4754035a5e230880a0a92a018c4d882fb4f0e7c174f4efdf198fdcc5",
    },
    ("site", "level"): {
        "plan": "9d32eb168ac33646f636965b512cb711a3a0db9a04073e6265c93871e3f84c64",
        "output": "1c0a9ac86f5a650a7083cf522516e38995728a9d63f67d3f641f9d0e48362020",
        "place": "46447728e66cc269a2473d724436d17b458705fb56f0d9a42dd0c287c8ab5c16",
        "drawing": "e6604bee278a8a7245d8acb7fc17ba45d1a9de6c389922c320df7247bad9d929",
    },
    ("farm", "land"): {
        "plan": "153718fb014e38e00721e6984459f96515b5baaa0914b1a309e63f0cb7e4648d",
        "output": "90059b2af17ea92b31edf39f0927c9064c6f7462afc669f9fc4cb6f530ee9102",
        "place": "6a0bced1012db3290df2817f0132e458479bc0af31f3b0e452a900e7d60799b8",
        # Moved when new worlds came to name land rules 5, whose grading lists a retaining wall
        # where levels meet: the drawing names the receipt, which names the rules, and lists the
        # farm's walls where its terraces and paths meet at other levels; no land moved.
        "drawing": "58c782b57bd1854b51074c4bcc60648e3f76ed4dea099f1b093d1f40b52721da",
    },
    ("site", "land"): {
        "plan": "9d32eb168ac33646f636965b512cb711a3a0db9a04073e6265c93871e3f84c64",
        "output": "7feb099103fe9f3d14f1bd684b4ae766dbae0bc58332aeb75956d9b2e9891647",
        "place": "fd6c4c4930ce53df8f68f0d42c12a32a212f2efa655a392d56ec87a4d927530f",
        # Moved with land rules 5, as the farm's on land: the receipt the drawing names, and the
        # site's one wall.
        "drawing": "b576f3d2e498c8eacc7a8b23d66688a6b071229ae3b19405912fcd90bbc69ed0",
    },
}

WORLDS = [
    ("farm", "level"),
    ("cafe", "level"),
    ("site", "level"),
    ("farm", "land"),
    ("site", "land"),
]


def _digests(name: str, ground: str) -> dict[str, str]:
    document = json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))
    kind = read_kind(document)
    world_id = f"world:generated:pinned-{name}-{ground}"
    world = compose_kind(
        kind,
        kind.values(kind.presets[0][0]),
        world_id,
        place_id="place:pinned",
        land=LAND if ground == "land" else None,
    )
    drawing = site_drawing(
        world_id=world_id,
        receipt=world.receipt,
        receipt_sha256=world.receipt_sha256,
        records=world.records,
    )
    place: Any = world.place
    return {
        "plan": world.receipt["plan_sha256"],
        "output": world.receipt["output_digest"],
        "place": sha256_of_canonical(place).hex(),
        "drawing": site_drawing_sha256(drawing),
    }


@pytest.mark.parametrize(("name", "ground"), WORLDS)
def test_a_fixture_world_is_made_drawn_and_walked_as_pinned(name: str, ground: str) -> None:
    assert _digests(name, ground) == PINNED[(name, ground)]
