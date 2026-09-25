"""The rehearsal holds the made world's addition offer to the server's own preview.

``made-world-takes-new-photograph`` reads the drawer's offer with ``offerMismatches`` from
``scripts/rehearsal/handlers.mjs``, run here in Node. When GET /worlds/personal-source previews an
addition, the offer's line is the preview's first sentence as the server wrote it, beside the
button the step names for ``add_photographs``; the counts of composed photographs and places are
the line only when the server previews nothing. Each case starts from the offer as it should be
and changes one thing a real defect would change.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "scripts" / "rehearsal" / "handlers.mjs"
STEPS = json.loads((ROOT / "scripts" / "rehearsal" / "steps.json").read_text())
ADDITION = next(s for s in STEPS["steps"] if s["id"] == "made-world-takes-new-photograph")
BUTTONS: dict[str, str] = ADDITION["parameters"]["buttons"]

EVALUATE = """
import { readFileSync } from 'node:fs';
const { offerMismatches } = await import(process.argv[1]);
const c = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(offerMismatches(c.server, c.seen, c.buttons)));
"""

SENTENCES = [
    "1 new photograph is added to this world.",
    "It joins a place already in the world.",
]


def _mismatches(case: dict[str, Any]) -> list[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    completed = subprocess.run(
        [node, "--input-type=module", "-e", EVALUATE, HANDLERS.as_uri()],
        input=json.dumps(case),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(completed.stdout)


def _addition() -> dict[str, Any]:
    server = {
        "action": "add_photographs",
        "refusal": None,
        "photographs": {"reviewed": 4, "composed": 4, "outside_scene_groups": 0},
        "regions": 3,
        "topology_digest": "b" * 64,
        "current_topology_digest": "a" * 64,
        "preview": {"preview_sha256": "c" * 64, "sentences": SENTENCES, "counts": {}},
    }
    seen = {
        "state": "add_photographs",
        "status": None,
        "counts": SENTENCES[0],
        "button": BUTTONS["add_photographs"],
        "enabled": True,
        "failure": None,
    }
    return {"server": server, "seen": seen, "buttons": BUTTONS}


def test_the_addition_offer_reads_the_preview_first_sentence_beside_its_button():
    assert _mismatches(_addition()) == []


def test_an_addition_offer_showing_other_words_or_another_button_is_a_mismatch():
    counted = _addition()
    # The counts a composition states are not what the offer says when the server previews.
    counted["seen"]["counts"] = "4 reviewed photographs in 3 places."
    assert _mismatches(counted) == ["the offer's line is not the preview's first sentence"]
    later = _addition()
    later["seen"]["counts"] = SENTENCES[1]
    assert _mismatches(later) == ["the offer's line is not the preview's first sentence"]
    button = _addition()
    button["seen"]["button"] = BUTTONS["create_world"]
    assert _mismatches(button) == [f'the button is not "{BUTTONS["add_photographs"]}"']
    disabled = _addition()
    disabled["seen"]["enabled"] = False
    assert _mismatches(disabled) == ["the button is not enabled"]


def test_without_a_preview_the_offer_still_states_the_composed_counts():
    composing = copy.deepcopy(_addition())
    composing["server"] |= {"action": "create_world", "preview": None}
    composing["seen"] |= {
        "button": BUTTONS["create_world"],
        "counts": "4 reviewed photographs in 3 places.",
    }
    assert _mismatches(composing) == []
    composing["seen"]["counts"] = SENTENCES[0]
    assert "the counts do not state the server's composed photographs" in _mismatches(composing)
