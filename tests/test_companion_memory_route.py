"""The /companion/memory surface, through the real HTTP route.

`tests/test_api.py` already sweeps these five routes for authentication and for the never-403
rule, because every route in the application is swept. What is here is what the sweep cannot ask:
that the surface round-trips a memory, that a correction changes what a session opens with, that a
deletion is a deletion, and that a withdrawal of the photographs reaches the answers about them
without anything in the browser having to notice.
"""

from __future__ import annotations

import uuid

import pytest

from test_api import deployment as deployment

pytestmark = pytest.mark.postgres

_ANSWER = {
    "question": "When were these photographs taken?",
    "answer_text": "These photographs were taken on 2026-02-01.",
    "prompt_version": "selection-3",
    "latency_ms": 40208,
    "served_model": "nvidia/Nemotron-3_5-Lightning",
    "planned_by": "Qwen/Qwen3-235B-A22B-Instruct-2507",
}


def _record(deployment, **over):
    body = dict(_ANSWER)
    body.update(over)
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _capture_id(repository):
    return repository.connection.execute(
        "select capture_id from capture where workspace_id=%s and deleted_at is null",
        (repository.workspace_id,),
    ).fetchone()["capture_id"]


def test_an_answer_recorded_through_the_route_comes_back_on_the_next_read(deployment):
    """The whole point: a reload no longer starts from nothing."""
    recorded = _record(deployment)
    assert recorded["origin"] == "asked"
    assert recorded["served_model"] == "nvidia/Nemotron-3_5-Lightning"

    response = deployment.as_owner("GET", "/companion/memory/recent")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [answer["answer_id"] for answer in body["answers"]] == [recorded["answer_id"]]
    assert body["answers"][0]["answer_text"] == _ANSWER["answer_text"]
    assert body["escapes"] == []


def test_the_recent_read_starts_empty_rather_than_failing(deployment):
    """A person who has never asked anything has an empty memory, not an error."""
    response = deployment.as_owner("GET", "/companion/memory/recent")
    assert response.status_code == 200
    assert response.json() == {"answers": [], "escapes": []}


def test_an_escape_recorded_through_the_route_comes_back(deployment):
    response = deployment.as_owner(
        "POST",
        "/companion/memory/escapes",
        json={"escape": "skip", "intent": "confirm_continuity", "turn_id": "turn-1"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["escape"] == "skip"

    escapes = deployment.as_owner("GET", "/companion/memory/recent").json()["escapes"]
    assert len(escapes) == 1
    assert escapes[0]["intent"] == "confirm_continuity"
    assert escapes[0]["entity_id"] is None


def test_a_correction_replaces_what_a_session_opens_with_and_keeps_the_original(deployment):
    recorded = _record(deployment)
    response = deployment.as_owner(
        "POST",
        f"/companion/memory/answers/{recorded['answer_id']}/corrections",
        json={"answer_text": "No, the spring ones.", "correction_note": "Wrong roll."},
    )
    assert response.status_code == 201, response.text
    correction = response.json()
    assert correction["origin"] == "correction"
    assert correction["supersedes"] == recorded["answer_id"]
    # The person's sentence, so no model is named as having written it.
    assert correction["served_model"] is None
    assert correction["correction_note"] == "Wrong roll."

    answers = deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]
    assert [answer["answer_id"] for answer in answers] == [correction["answer_id"]]
    assert answers[0]["answer_text"] == "No, the spring ones."


def test_correcting_the_same_answer_twice_is_a_conflict_rather_than_a_fork(deployment):
    recorded = _record(deployment)
    path = f"/companion/memory/answers/{recorded['answer_id']}/corrections"
    assert deployment.as_owner("POST", path, json={"answer_text": "First."}).status_code == 201
    second = deployment.as_owner("POST", path, json={"answer_text": "Second."})
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "companion_memory_already_corrected"


def test_deleting_a_memory_removes_it_and_every_correction_of_it(deployment):
    recorded = _record(deployment)
    correction = deployment.as_owner(
        "POST",
        f"/companion/memory/answers/{recorded['answer_id']}/corrections",
        json={"answer_text": "No, the spring ones."},
    ).json()

    response = deployment.as_owner(
        "DELETE", f"/companion/memory/answers/{correction['answer_id']}"
    )
    assert response.status_code == 204, response.text
    assert response.content == b""

    assert deployment.as_owner("GET", "/companion/memory/recent").json()["answers"] == []
    # And it does not come back: deleting it again is a 404, not a second success.
    again = deployment.as_owner("DELETE", f"/companion/memory/answers/{recorded['answer_id']}")
    assert again.status_code == 404
    assert again.json()["code"] == "unknown_reference"


def test_a_memory_nobody_recorded_is_unknown_reference_rather_than_a_bare_detail(deployment):
    """`{code, detail}` rather than `{detail}`. A bare HTTPException loses the code the web
    client branches on, which `geometry.py` records as degrading `toApiError` to a synthetic
    `http_404`.
    """
    response = deployment.as_owner("DELETE", f"/companion/memory/answers/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json() == {
        "code": "unknown_reference",
        "detail": response.json()["detail"],
    }


def test_a_stranger_gets_the_same_404_as_for_a_memory_that_never_existed(deployment):
    """Not there and not yours are one code, so the surface is not an existence oracle."""
    recorded = _record(deployment)
    for method, path in (
        ("DELETE", f"/companion/memory/answers/{recorded['answer_id']}"),
        ("DELETE", f"/companion/memory/answers/{uuid.uuid4()}"),
    ):
        response = deployment.as_stranger(method, path)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["code"] == "unknown_reference"

    # The stranger's own memory is empty rather than refused, and the owner's is untouched.
    assert deployment.as_stranger("GET", "/companion/memory/recent").json()["answers"] == []
    assert len(deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]) == 1


def test_withdrawing_the_photographs_removes_the_answers_about_them(deployment, repository):
    """End to end, and the browser is told nothing: the next read simply does not carry it."""
    capture_id = _capture_id(repository)
    recorded = _record(
        deployment,
        citations=[
            {
                "span_id": str(deployment.span_id),
                "capture_id": str(capture_id),
                "ordinal": 0,
            }
        ],
    )
    assert len(recorded["citations"]) == 1

    before = deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]
    assert [answer["answer_id"] for answer in before] == [recorded["answer_id"]]

    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )

    after = deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]
    assert after == []


def test_an_answer_citing_evidence_already_withdrawn_is_refused_rather_than_stored(
    deployment, repository
):
    capture_id = _capture_id(repository)
    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )
    response = deployment.as_owner(
        "POST",
        "/companion/memory/answers",
        json={
            **_ANSWER,
            "citations": [
                {"span_id": str(deployment.span_id), "capture_id": str(capture_id), "ordinal": 0}
            ],
        },
    )
    assert response.status_code >= 400, response.text
    assert deployment.as_owner("GET", "/companion/memory/recent").json()["answers"] == []


def test_the_body_may_not_carry_a_workspace_or_an_actor(deployment):
    """Every model in this package sets `extra="forbid"`, and the rule that no request model may
    carry a workspace id or an actor is stated in `authorisation.py` and `person_consent.py`.
    This is that rule for this surface, held rather than assumed.
    """
    for field in ("workspace_id", "actor_id", "actor"):
        response = deployment.as_owner(
            "POST", "/companion/memory/answers", json={**_ANSWER, field: str(uuid.uuid4())}
        )
        assert response.status_code == 422, (field, response.text)


def test_an_invented_abstention_code_is_refused_by_the_schema(deployment):
    """The four codes stay four. Merging them "lets a system that always says 'I don't know'
    score perfectly", which is the M3 argument for keeping them distinct in the first place.
    """
    response = deployment.as_owner(
        "POST",
        "/companion/memory/answers",
        json={**_ANSWER, "abstained": "UNANSWERABLE_BECAUSE_I_SAID_SO"},
    )
    assert response.status_code == 422, response.text


def test_the_recent_read_is_bounded(deployment):
    assert deployment.as_owner("GET", "/companion/memory/recent?limit=0").status_code == 422
    assert deployment.as_owner("GET", "/companion/memory/recent?limit=9999").status_code == 422
    assert deployment.as_owner("GET", "/companion/memory/recent?limit=1").status_code == 200
