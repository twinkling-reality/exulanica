"""The places the society turns, as the page's seating test reads them.

The page finds which place a person holds by carrying their recorded position back into the
object's frame (``web/packages/atlas-react/src/playcanvas/society/seating.ts``). Its test reads
``web/packages/atlas-react/test/fixtures/society-seating.json``: for each kind that states places,
an object turned to several yaws, the places this server turned for it with ``destination_places``
(outward rounding and all), and the ``use`` the registry reads serve for it. The fixture is written
from this server's own code and never by hand; this test fails when the code no longer writes the
same document. Rewrite it with ``EXULANICA_SEATING_FIXTURE=write``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from exulanica.api.world_version_document import object_use_view
from exulanica.world.assets import reviewed_assets
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.society_authored_ground import _UsableObject, destination_places
from exulanica.world.society_composition import REVIEWED_REACH_MM, reviewed_assignment
from exulanica.world.society_planner import CLEARANCE_MM

from test_society_saved_world_objects import FACING_THE_PERSON, STANDING, thing

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "web/packages/atlas-react/test/fixtures/society-seating.json"
)
#: The yaws each kind is turned to: none, the yaw at which a bench once lost its middle place to
#: rounding (tests/test_society_object_catalog.py SWEEP), a quarter turn, the half turn a person
#: faces, and two that fall between whole degrees.
YAWS = (0, 47_856, 1_570_796, FACING_THE_PERSON, 2_468_013, 5_555_555)
#: Where each object stands, off the origin and at an elevation, so neither can cancel out.
CENTRE_MM = (2_345, 120, -1_234)


def _document() -> dict[str, Any]:
    assets = {asset.asset_key: asset for asset in reviewed_assets()}
    cases = []
    for kind in world_object_catalog().kinds:
        if not kind.use.places:
            continue
        row = reviewed_assignment(kind, REVIEWED_REACH_MM)
        hx, hz = row["footprint_half_extents_mm"]
        for yaw in YAWS:
            x, y, z = CENTRE_MM
            obj = thing("object:it", assets[kind.asset_key], x, z, y_mm=y, yaw=yaw)
            usable = _UsableObject(obj, row, (x, z), (hx, hz))
            use = object_use_view(kind.asset_key)
            assert use is not None
            cases.append(
                {
                    "asset_key": kind.asset_key,
                    "transform": {
                        "x_mm": x,
                        "y_mm": y,
                        "z_mm": z,
                        "yaw_microradians": yaw,
                        "scale_milli": 1000,
                    },
                    "turned_places_mm": [
                        list(point) for point in destination_places(usable, STANDING, CLEARANCE_MM)
                    ],
                    "use": use.model_dump(),
                }
            )
    return {
        "profile": "exulanica.society-seating-fixture/v1",
        "written_by": "tests/test_society_seating_fixture.py",
        "cases": cases,
    }


def _text(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def test_the_page_s_seating_fixture_is_what_this_server_turns():
    document = _document()
    # Positive control: the fixture covers every kind that states places, at every yaw.
    kinds = {case["asset_key"] for case in document["cases"]}
    assert len(kinds) == 5 and len(document["cases"]) == 5 * len(YAWS)
    if os.environ.get("EXULANICA_SEATING_FIXTURE") == "write":
        FIXTURE.write_text(_text(document))
    assert FIXTURE.read_text() == _text(document)
