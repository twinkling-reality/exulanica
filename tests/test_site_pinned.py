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
# Every place and drawing below moved when doors came to stand clear (society-policy v5): a new
# world's door stands 340 mm before its threshold, which moves the walking place, and the drawing
# names the receipt, which names the policy. No plan or output moved.
PINNED: dict[tuple[str, str], dict[str, str]] = {
    ("farm", "level"): {
        "plan": "153718fb014e38e00721e6984459f96515b5baaa0914b1a309e63f0cb7e4648d",
        "output": "15038a3d47e0cd50e314fe276193e5fab37acdf869f917ddb7d16e64e788a9f3",
        "place": "5a033163bae2a0a6176f0c7f439b4c78afb57ffa90f152bd1b1f2e5b01bf0f31",
        "drawing": "534f39b141d0e8335a77a4b65d8c4ba67f20f97a278a549e28c3129df9ddbd39",
    },
    ("cafe", "level"): {
        "plan": "7babded1d2d4b6897dd3019ae8b271925db60254124b9ae1c4b754eb25fce913",
        "output": "ae31888d719eaaf4882cf9bc94254efd8e3911fa1db8ce80025cb85763f67196",
        "place": "b246dc42d99f4c16a168f62e443eb25d5ee145ce5cb7997ef0f27f6728ffd3d4",
        "drawing": "1a5de9197dd2e486505776060015c937e42c6215ffc382c438ac9104fecc8e6f",
    },
    ("site", "level"): {
        "plan": "9d32eb168ac33646f636965b512cb711a3a0db9a04073e6265c93871e3f84c64",
        "output": "1c0a9ac86f5a650a7083cf522516e38995728a9d63f67d3f641f9d0e48362020",
        "place": "9a6a3c954ede399b56641799d482baffd034e7a562599f83508f6a8731922a68",
        "drawing": "c6fca4326a591019f0563d291a6a0da03526db3b05ee602b4afafa3f0ea49e50",
    },
    ("farm", "land"): {
        "plan": "153718fb014e38e00721e6984459f96515b5baaa0914b1a309e63f0cb7e4648d",
        "output": "90059b2af17ea92b31edf39f0927c9064c6f7462afc669f9fc4cb6f530ee9102",
        "place": "97a3a85280c50d6208e1f6c178b3c1e462871669cb221d2e9c7d4cbc653f08e4",
        # Moved when new worlds came to name land rules 6, which grade by the grading catalog: the
        # drawing names the receipt, which names the rules; no land moved (the farm's terraces
        # stand within the bound, so none is held in a wall). Its walls are rules 5's.
        "drawing": "6c971c8c1b423e35e04526d2628b73353386b278e8f418984a4ddaed4e3e54f1",
    },
    ("site", "land"): {
        "plan": "9d32eb168ac33646f636965b512cb711a3a0db9a04073e6265c93871e3f84c64",
        "output": "7feb099103fe9f3d14f1bd684b4ae766dbae0bc58332aeb75956d9b2e9891647",
        "place": "feece6870dce65752bc39afe58df1434eb060d50db9cf6c6c4c4ee62f016122c",
        # Moved with land rules 6, as the farm's on land: the receipt the drawing names.
        "drawing": "47f2bcf8af0a8ba878eb56916bd5af20fc71c167d31d9f11bee25b5dd17a7f79",
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
