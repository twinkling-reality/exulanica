"""The rehearsal's personal path holds the drawer's offer and review to the server's own answers.

``review-photographs-in-app``, ``wait-for-depth-and-grouping``, ``make-world-from-photographs`` and
``made-world-refuses-new-photograph`` decide with exported functions of
``scripts/rehearsal/handlers.mjs``: ``offerMismatches`` (the offer a person reads against
GET /worlds/personal-source), ``reviewMismatches`` (the review the drawer posted against the
stand-in the step list states) and ``sceneWorkWaiting`` (what GET /operations/reconstruction-scenes
leaves for a scene worker). These tests run them in Node. Each group starts with a positive control,
the page and the server as they should be, and then changes one thing a real defect would change.
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
STAND_IN = STEPS["stand_ins"]["human-review"]
REVIEW = next(s for s in STEPS["steps"] if s["id"] == "review-photographs-in-app")
BUTTONS: dict[str, str] = REVIEW["parameters"]["buttons"]
CHOICE: str = REVIEW["parameters"]["review_choice"]
CAPTURES = [{"capture_id": f"00000000-0000-4000-8000-00000000000{index}"} for index in (1, 2, 3)]

EVALUATE = """
import { readFileSync } from 'node:fs';
const { offerMismatches, reviewMismatches, sceneWorkWaiting } = await import(process.argv[1]);
const c = JSON.parse(readFileSync(0, 'utf8'));
const out = {};
if (c.offer) out.offer = offerMismatches(c.offer.server, c.offer.seen, c.offer.buttons);
const r = c.review;
if (r) out.review = reviewMismatches(r.standIn, r.choice, r.captures, r.posted);
if (c.scenes !== undefined) out.scenes = sceneWorkWaiting(c.scenes);
console.log(JSON.stringify(out));
"""


def _decide(case: dict[str, Any]) -> dict[str, Any]:
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


def _offered() -> dict[str, Any]:
    server = {
        "action": "create_world",
        "refusal": None,
        "photographs": {"reviewed": 3, "composed": 3, "outside_scene_groups": 0},
        "regions": 3,
        "topology_digest": "a" * 64,
    }
    seen = {
        "state": "create_world",
        "status": None,
        "counts": "3 reviewed photographs in 3 places.",
        "button": BUTTONS["create_world"],
        "enabled": True,
        "failure": None,
    }
    return {"server": server, "seen": seen, "buttons": BUTTONS}


def _refused() -> dict[str, Any]:
    detail = "None of your photographs has a current review from you."
    server = {
        "action": None,
        "refusal": {"code": "no_reviewed_personal_sources", "detail": detail},
        "photographs": {"reviewed": 0, "composed": 0, "outside_scene_groups": 0},
        "regions": 0,
    }
    seen = {"state": "refused", "status": detail, "counts": None, "button": None, "enabled": False}
    return {"server": server, "seen": seen, "buttons": BUTTONS}


def _posted() -> dict[str, Any]:
    return {
        "status": 202,
        "request_body": {
            "operation": "review",
            "reviewed_by_name": STAND_IN["reviewer_name"],
            "purpose": STAND_IN["purpose"],
            "authority": {"account_authority_basis": STAND_IN["authority_basis"]},
            "attestation": "I personally inspected every exact photograph in this inventory",
            "members": [{"capture_id": c["capture_id"], "review": CHOICE} for c in CAPTURES],
        },
        "response_body": {
            "receipts": [
                {"capture_id": c["capture_id"], "eligibility_state": "eligible"} for c in CAPTURES
            ]
        },
    }


def _review(posted: dict[str, Any]) -> dict[str, Any]:
    return {
        "review": {"standIn": STAND_IN, "choice": CHOICE, "captures": CAPTURES, "posted": posted}
    }


def test_an_offer_and_a_refusal_shown_as_the_server_gives_them_hold():
    assert _decide({"offer": _offered()})["offer"] == []
    assert _decide({"offer": _refused()})["offer"] == []


@pytest.mark.parametrize(
    ("case", "change", "expected"),
    [
        (
            _refused,
            lambda o: o["seen"].update(status="Review your photographs."),
            "not shown in the server's words",
        ),
        (
            _refused,
            lambda o: o["seen"].update(button=BUTTONS["create_world"]),
            "a button is offered beside a refusal",
        ),
        (
            _offered,
            lambda o: o["seen"].update(button="Make a world"),
            'the button is not "Make a world from my photographs"',
        ),
        (_offered, lambda o: o["seen"].update(enabled=False), "the button is not enabled"),
        (
            _offered,
            lambda o: o["seen"].update(counts="2 reviewed photographs in 3 places."),
            "composed photographs",
        ),
        (_offered, lambda o: o["server"].update(regions=1), "the server's places"),
        (
            _offered,
            lambda o: o["server"].update(action="rebuild_world"),
            "names no button for rebuild_world",
        ),
    ],
)
def test_an_offer_that_departs_from_the_server_is_seen(case, change, expected):
    offer = copy.deepcopy(case())
    change(offer)
    found = _decide({"offer": offer})["offer"]
    assert any(expected in mismatch for mismatch in found), found


def test_a_review_posted_as_the_stand_in_states_holds():
    assert _decide(_review(_posted()))["review"] == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda p: p["request_body"].update(reviewed_by_name="Synthetic Reviewer"),
            "not named as the stand-in",
        ),
        (
            lambda p: p["request_body"].update(purpose="Make a world"),
            "purpose is not the stand-in's",
        ),
        (
            lambda p: p["request_body"]["authority"].update(account_authority_basis="I own them"),
            "authority basis",
        ),
        (lambda p: p["request_body"].update(attestation=None), "no attestation was sent"),
        (lambda p: p["request_body"].update(operation="detect"), "the request is not a review"),
        (lambda p: p["request_body"]["members"].pop(), "does not name every photograph"),
        (
            lambda p: p["request_body"]["members"][0].update(review="confirmed-regions"),
            "does not name every photograph",
        ),
        (
            lambda p: p["response_body"]["receipts"][0].update(eligibility_state="blocked"),
            "a receipt is not eligible",
        ),
        (lambda p: p.update(status=409), "not 202"),
    ],
)
def test_a_review_that_departs_from_the_stand_in_or_the_photographs_is_seen(change, expected):
    posted = _posted()
    change(posted)
    found = _decide(_review(posted))["review"]
    assert any(expected in mismatch for mismatch in found), found


def _scenes(**queue: int) -> dict[str, Any]:
    """GET /operations/reconstruction-scenes as reconstruction_scene_metrics shapes it."""
    return {
        "coordination": {"state": "idle", "reasons": []},
        "dependency_queue": {"queued": 0, "running": 0},
        "depth": {"queued": 0, "running": 0, "retryable": 0, "waiting_for_point_maps": 0} | queue,
    }


def test_scene_work_is_counted_from_the_fields_the_operations_read_states():
    from exulanica.ingest import operations

    source = Path(operations.__file__).read_text()
    for field in ("queued", "running", "retryable", "waiting_for_point_maps"):
        assert f'"{field}"' in source, field
    assert _decide({"scenes": _scenes()})["scenes"] == 0
    for field in ("queued", "running", "retryable", "waiting_for_point_maps"):
        assert _decide({"scenes": _scenes(**{field: 1})})["scenes"] == 1, field
    # A read that does not state the queue is not nothing waiting.
    assert _decide({"scenes": {"coordination": {"state": "idle"}}})["scenes"] is None
    assert _decide({"scenes": None})["scenes"] is None
