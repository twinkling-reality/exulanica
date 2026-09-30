"""The world style client waits for a request as long as the page waits for any ordinary read.

``WORLD_STYLE_REQUEST_TIMEOUT_MS`` in ``web/packages/app/src/world-style-api.ts`` bounds each
world style request, so a held style row or a request that never comes back ends in a failure
the page can say. It is the page's allowance for an ordinary read, which
``PACKET_TIMEOUT_MS`` in ``web/packages/app/src/companion-ask-api.ts`` states: one fact written
in two files, held equal here.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "web/packages/app/src"


def _milliseconds(source: str, name: str) -> int:
    found = re.search(rf"^const {name} = ([0-9_]+);$", (APP / source).read_text(), re.MULTILINE)
    assert found is not None, f"{source} states no {name}"
    return int(found.group(1).replace("_", ""))


def test_a_world_style_request_waits_the_page_s_allowance_for_an_ordinary_read():
    style = _milliseconds("world-style-api.ts", "WORLD_STYLE_REQUEST_TIMEOUT_MS")
    assert style > 0
    assert style == _milliseconds("companion-ask-api.ts", "PACKET_TIMEOUT_MS")
