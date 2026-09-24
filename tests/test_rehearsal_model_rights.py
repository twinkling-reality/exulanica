"""The rehearsal's in-app model-rights step holds the drawer and the server to the server's words.

``grant-model-rights-in-app`` ticks the vision, search and Companion rights in the photo drawer and
checks what the page drew and what the server recorded. Its decisions are the exported functions of
``scripts/rehearsal/handlers.mjs`` (``compareOffers``, ``rightsPerPhoto``, ``rightsRecorded`` and
``roleTerms``), and these tests run them in Node on the offers the server itself states
(``model_right_offers()``), with a page and a grant built to match. The first test is the positive
control: everything as the drawer and the server should leave it holds. Every other test changes one
thing a real defect would change and expects the step to see it.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from exulanica.ingest.personal_admission import model_right_offers

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "scripts" / "rehearsal" / "handlers.mjs"
STEP = next(
    step
    for step in json.loads((ROOT / "scripts" / "rehearsal" / "steps.json").read_text())["steps"]
    if step["id"] == "grant-model-rights-in-app"
)
ROLES: list[str] = STEP["parameters"]["roles"]
STATED = [offer.as_record() for offer in model_right_offers()]
CAPTURES = [{"capture_id": f"00000000-0000-4000-8000-00000000000{index}"} for index in (1, 2, 3)]
GRANTED_UNTIL = "2026-09-25T12:00:00.000000Z"

# One Node process per case: import the handlers, run the step's decisions on the case, print them.
EVALUATE = """
import { readFileSync } from 'node:fs';
const { compareOffers, rightsPerPhoto, rightsRecorded, roleTerms } = await import(process.argv[1]);
const c = JSON.parse(readFileSync(0, 'utf8'));
const { offers, mismatches, unoffered } = compareOffers(c.roles, c.stated, c.drawn);
const perPhoto = rightsPerPhoto(c.roles, offers, c.captures, c.posted.request_body,
  c.posted.response_body.receipts, c.sources);
console.log(JSON.stringify({
  offered: [...offers.keys()], mismatches, unoffered, perPhoto,
  recorded: rightsRecorded(c.roles, offers, c.captures, c.posted, perPhoto),
  terms: roleTerms(c.roles, offers, perPhoto),
}));
"""


def _offer(role: str) -> dict[str, Any]:
    return next(o for o in STATED if o["role"] == role and o["offered_with"] == "detect")


def _right(capture: str, role: str, model: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "right_id": f"{capture}:{model['model_id']}",
        "capture_id": capture,
        "model": model,
        "destination": _offer(role)["destination"],
        "valid_until": GRANTED_UNTIL,
        "withdrawn": False,
        "state": "current",
        "notice_current": True,
    } | changes


def _case() -> dict[str, Any]:
    """The page and the grant exactly as the drawer and the server should leave them."""
    detect = [o for o in STATED if o["offered_with"] == "detect"]
    rights = {
        c["capture_id"]: [
            _right(c["capture_id"], role, model)
            for role in ROLES
            for model in _offer(role)["models"]
        ]
        for c in CAPTURES
    }
    return {
        "roles": ROLES,
        "stated": STATED,
        "drawn": [
            {
                "role": o["role"],
                "label": o["label"],
                "choice": o["label"],
                "checked": False,
                "notice": o["notice"],
            }
            for o in detect
        ],
        "captures": CAPTURES,
        "posted": {
            "status": 202,
            "request_body": {
                "members": [{"capture_id": c["capture_id"]} for c in CAPTURES],
                "model_rights": [
                    {"role": role, "valid_until": GRANTED_UNTIL, "notice": _offer(role)["notice"]}
                    for role in ROLES
                ],
            },
            "response_body": {
                "receipts": [
                    {"capture_id": capture, "model_rights": listed}
                    for capture, listed in rights.items()
                ]
            },
        },
        "sources": [
            {"capture_id": capture, "model_rights": listed} for capture, listed in rights.items()
        ],
    }


def _decide(case: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    completed = subprocess.run(
        [node, "--input-type=module", "-e", EVALUATE, str(HANDLERS)],
        input=json.dumps(case),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(completed.stdout)


def _changed(change) -> dict[str, Any]:
    case = copy.deepcopy(_case())
    change(case)
    return _decide(case)


def test_the_step_asks_for_roles_the_server_offers_with_detection_and_chains_with_a_fallback():
    detect = {o["role"] for o in STATED if o["offered_with"] == "detect"}
    assert ROLES and set(ROLES) <= detect
    # The chain rule is exercised only if some role reaches more than one model.
    assert any(len(_offer(role)["models"]) > 1 for role in ROLES)


def test_the_drawer_and_the_server_as_they_should_be_hold():
    decided = _decide(_case())
    assert decided["offered"] == ROLES
    assert decided["mismatches"] == []
    assert decided["unoffered"] == []
    assert decided["recorded"] is True
    assert all(
        p["receipt_covers"] == ROLES and p["listed_current_with_these_words"] == ROLES
        for p in decided["perPhoto"]
    )
    assert decided["terms"] == {
        c["capture_id"]: dict.fromkeys(ROLES, GRANTED_UNTIL) for c in CAPTURES
    }


def test_a_notice_drawn_or_sent_with_other_words_is_seen():
    last = len(ROLES) - 1

    def drawn_other(case):
        box = next(d for d in case["drawn"] if d["role"] == ROLES[0])
        box["notice"] = box["notice"][:-1]

    decided = _changed(drawn_other)
    assert decided["mismatches"] == [
        f"{ROLES[0]}: the notice beside it is not the offer's word for word"
    ]

    def sent_other(case):
        case["posted"]["request_body"]["model_rights"][last]["notice"] += " "

    assert _changed(sent_other)["recorded"] is False


def test_a_box_ticked_before_the_person_or_labelled_otherwise_is_seen():
    def ticked(case):
        case["drawn"][0]["checked"] = True

    assert _changed(ticked)["mismatches"] == [f"{ROLES[0]}: the box is not unticked"]

    def relabelled(case):
        case["drawn"][0]["choice"] = "Allow"

    assert _changed(relabelled)["mismatches"] == [f"{ROLES[0]}: the label is not the offer's"]


def test_a_missing_box_or_one_the_server_does_not_offer_with_detection_is_seen():
    def missing(case):
        case["drawn"] = [d for d in case["drawn"] if d["role"] != ROLES[1]]

    assert _changed(missing)["mismatches"] == [f"{ROLES[1]}: no box is drawn"]
    review_only = next(o for o in STATED if o["offered_with"] != "detect")

    def extra(case):
        case["drawn"].append(
            {
                "role": review_only["role"],
                "label": review_only["label"],
                "choice": review_only["label"],
                "checked": False,
                "notice": review_only["notice"],
            }
        )

    assert _changed(extra)["unoffered"] == [review_only["role"]]


def test_a_role_whose_fallback_model_has_no_right_is_not_recorded():
    chained = next(role for role in ROLES if len(_offer(role)["models"]) > 1)
    fallback = _offer(chained)["models"][-1]["model_id"]

    def without_fallback(case):
        for source in case["sources"]:
            source["model_rights"] = [
                r for r in source["model_rights"] if r["model"]["model_id"] != fallback
            ]

    decided = _changed(without_fallback)
    assert decided["recorded"] is False
    assert all(chained not in p["listed_current_with_these_words"] for p in decided["perPhoto"])
    assert all(terms[chained] is None for terms in decided["terms"].values())


def test_a_right_granted_against_other_words_or_ended_is_not_recorded():
    def other_words(case):
        case["sources"][0]["model_rights"][0]["notice_current"] = False

    assert _changed(other_words)["recorded"] is False

    def ended(case):
        case["sources"][1]["model_rights"][0]["state"] = "ended"

    assert _changed(ended)["recorded"] is False

    def withdrawn_in_receipt(case):
        case["posted"]["response_body"]["receipts"][2]["model_rights"][0]["withdrawn"] = True

    assert _changed(withdrawn_in_receipt)["recorded"] is False


def test_a_grant_for_other_photographs_or_roles_or_one_refused_is_not_recorded():
    def one_photo_short(case):
        case["posted"]["request_body"]["members"].pop()

    assert _changed(one_photo_short)["recorded"] is False

    def one_photo_more(case):
        case["posted"]["request_body"]["members"].append(
            {"capture_id": "00000000-0000-4000-8000-000000000009"}
        )

    assert _changed(one_photo_more)["recorded"] is False

    def one_role_short(case):
        case["posted"]["request_body"]["model_rights"].pop()

    assert _changed(one_role_short)["recorded"] is False

    def refused(case):
        case["posted"]["status"] = 409

    assert _changed(refused)["recorded"] is False


def test_a_roles_term_is_the_earliest_over_its_chain_of_the_latest_right_per_model():
    chained = next(role for role in ROLES if len(_offer(role)["models"]) > 1)
    primary, fallback = (m["model_id"] for m in _offer(chained)["models"][:2])
    capture = CAPTURES[0]["capture_id"]

    def terms(case):
        rights = case["sources"][0]["model_rights"]
        for right in rights:
            if right["model"]["model_id"] == fallback:
                right["valid_until"] = "2026-09-25T09:00:00.000000Z"
        latest = next(r for r in rights if r["model"]["model_id"] == primary)
        rights.append(latest | {"right_id": "later", "valid_until": "2026-09-26T12:00:00.000000Z"})

    assert _changed(terms)["terms"][capture][chained] == "2026-09-25T09:00:00.000000Z"
