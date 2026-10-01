"""A remembered answer about a world's people keeps what it cited, across a reload (gap N-G3).

The society is a real one: an authored starter with a market stall, the saved-world engine, and
simulated minutes stepped through the API until it has recorded events. The answer is posted as
the browser posts one, read back, corrected, and refused when what it cites stands on a deleted
source. A project item naming the same event resolves it through the society's own authorization.
"""

from __future__ import annotations

import re
import uuid

import pytest
from exulanica.selection.society_question import SIMULATED_PLACEHOLDER
from exulanica.world.companion_memory import SIMULATED_LABEL
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID

import project_context_support as support

pytestmark = pytest.mark.postgres

SAVED_WORLD_SOCIETY = "exulanica-society/v2"
#: How many simulated minutes a test may step before it must have an event to cite.
MINUTES = 30


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from support.projects_api(tmp_path, repository, spine_schema)


@pytest.fixture
def society(api):
    saved = support.starter(api)
    support.place(api, saved, "cc0.market-stall", "stall", "stall")
    saved = support.entry(api, saved["entry_id"])
    w, v = saved["world_id"], saved["authored_version_id"]
    api.ok(
        api.call(
            "POST",
            f"/world/versions/{v}/society",
            world=w,
            json={"region_id": AUTHORED_STARTER_REGION_ID, "profile": SAVED_WORLD_SOCIETY},
        ),
        200,
        201,
    )
    events: list = []
    for _ in range(MINUTES):
        snapshot = api.ok(api.call("GET", f"/world/versions/{v}/society", world=w), 200)
        api.ok(
            api.call(
                "POST",
                f"/world/versions/{v}/society/steps",
                world=w,
                json={
                    "base_tick": snapshot["current_tick"],
                    "base_state_sha256": snapshot["state_sha256"],
                },
            ),
            200,
        )
        events = api.ok(api.call("GET", f"/world/versions/{v}/society/events", world=w), 200)[
            "events"
        ]
        if events:
            break
    assert events, f"no event in {MINUTES} simulated minutes"
    return {"saved": saved, "world_id": w, "version_id": v, "event": events[0]}


def _answer_body(society, **over):
    event = society["event"]
    body = {
        "question": "Why is this person at the stall?",
        "answer_text": "[inhabitant A] went to [spot A].",
        "prompt_version": "society-1",
        "latency_ms": 3,
        "composed": "none",
        "used_fallback": False,
        "unanswered_attempts": 0,
        "unanswered_cost_unknown": False,
        "world_id": society["world_id"],
        "simulation_citations": [
            {
                "ordinal": 0,
                "result_kind": "simulation_event",
                "version_id": society["version_id"],
                "inhabitant_id": event["subject_id"],
                "event_id": event["event_id"],
                "tick": event["tick"],
                "input_seq": event["document"].get("input_seq"),
            },
            {
                "ordinal": 1,
                "result_kind": "synthetic_inhabitant",
                "version_id": society["version_id"],
                "inhabitant_id": event["subject_id"],
                "tick": event["tick"],
            },
        ],
        "inhabitants": {
            "[inhabitant A]": {
                "version_id": society["version_id"],
                "inhabitant_id": event["subject_id"],
            }
        },
        "spots": {"[spot A]": "authored:stall:visit"},
    }
    return {**body, **over}


def test_a_remembered_answer_keeps_its_simulation_citations_across_a_reload(api, society):
    saved = api.ok(
        api.call("POST", "/companion/memory/answers", world=None, json=_answer_body(society)),
        201,
    )
    recent = api.ok(api.call("GET", "/companion/memory/recent", world=None), 200)
    answer = next(a for a in recent["answers"] if a["answer_id"] == saved["answer_id"])
    assert answer["world_id"] == society["world_id"]
    assert [c["result_kind"] for c in answer["simulation_citations"]] == [
        "simulation_event",
        "synthetic_inhabitant",
    ]
    cited = answer["simulation_citations"][0]
    assert cited["truth_class"] == "simulation"
    assert cited["event_id"] == society["event"]["event_id"]
    assert cited["tick"] == society["event"]["tick"]
    assert (
        answer["inhabitants"]["[inhabitant A]"]["inhabitant_id"] == (society["event"]["subject_id"])
    )
    assert answer["spots"] == {"[spot A]": "authored:stall:visit"}
    assert answer["citations"] == [] and answer["names"] == {}

    corrected = api.ok(
        api.call(
            "POST",
            f"/companion/memory/answers/{saved['answer_id']}/corrections",
            world=None,
            json={"answer_text": "[inhabitant A] was buying food at [spot A]."},
        ),
        201,
    )
    assert corrected["simulation_citations"] == answer["simulation_citations"]
    assert corrected["inhabitants"] == answer["inhabitants"]
    assert corrected["spots"] == answer["spots"]


def test_simulation_and_photographs_are_never_cited_together(api, society):
    both = api.call(
        "POST",
        "/companion/memory/answers",
        world=None,
        json=_answer_body(
            society,
            citations=[
                {"span_id": str(uuid.uuid4()), "capture_id": str(uuid.uuid4()), "ordinal": 0}
            ],
        ),
    )
    assert both.status_code == 422, both.text
    unnamed = api.call(
        "POST", "/companion/memory/answers", world=None, json=_answer_body(society, world_id=None)
    )
    assert unnamed.status_code == 422
    label = api.call(
        "POST",
        "/companion/memory/answers",
        world=None,
        json=_answer_body(society, spots={"[inhabitant B]": "authored:x"}),
    )
    assert label.status_code == 422
    # A label stands for what a simulated record cited; with no citation it stands for nothing.
    uncited = api.call(
        "POST",
        "/companion/memory/answers",
        world=None,
        json=_answer_body(society, simulation_citations=[]),
    )
    assert uncited.status_code == 422, uncited.text
    unlabelled_world = api.call(
        "POST",
        "/companion/memory/answers",
        world=None,
        json=_answer_body(society, simulation_citations=[], inhabitants={}, spots={}),
    )
    assert unlabelled_world.status_code == 422, unlabelled_world.text


def test_a_citation_of_a_record_not_in_this_world_is_an_unknown_reference(api, society):
    body = _answer_body(society)
    body["simulation_citations"][0]["event_id"] = str(uuid.uuid4())
    unknown = api.call("POST", "/companion/memory/answers", world=None, json=body)
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_reference"
    other, _version = support.other_world(api)
    elsewhere = api.call(
        "POST", "/companion/memory/answers", world=None, json=_answer_body(society, world_id=other)
    )
    assert elsewhere.status_code == 404


def test_a_citation_of_a_deleted_source_is_not_kept(api, society):
    support.invalidate(api, society["world_id"], society["version_id"])
    refused = api.call("POST", "/companion/memory/answers", world=None, json=_answer_body(society))
    assert refused.status_code == 424 and refused.json()["code"] == "unavailable_society_input"


def test_a_project_event_names_the_simulated_event_and_resolves_it(api, society):
    made = support.project(api, society["world_id"], society["version_id"])
    event = society["event"]
    item = support.add(
        api,
        society["world_id"],
        made,
        {
            "base_revision": made["revision"],
            "kind": "event",
            "basis": "simulated_event",
            "text": "Someone came to the stall",
            "references": [
                {
                    "kind": "society_event",
                    "world_id": society["world_id"],
                    "version_id": society["version_id"],
                    "event_id": event["event_id"],
                    "tick": event["tick"],
                    "input_seq": event["document"].get("input_seq"),
                    "object_id": None,
                    "edit_seq": None,
                    "edit_id": None,
                }
            ],
        },
    )
    read = api.ok(
        api.call("GET", f"/world/projects/{made['project_id']}/items", world=society["world_id"]),
        200,
    )
    [kept] = [i for i in read if i["item_id"] == item["item_id"]]
    assert kept["references"][0]["state"] == "available", kept
    assert kept["basis"] == "simulated_event"


def test_the_label_pattern_is_the_one_the_answer_route_writes():
    assert SIMULATED_LABEL.pattern == SIMULATED_PLACEHOLDER.pattern.removeprefix("(").removesuffix(
        ")"
    )
    for label in ("[inhabitant A]", "[spot AB]", "[person A]", "[inhabitant a]", "[spot  A]"):
        assert bool(SIMULATED_LABEL.fullmatch(label)) == bool(
            re.fullmatch(SIMULATED_PLACEHOLDER.pattern, label)
        )
