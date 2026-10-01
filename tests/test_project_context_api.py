"""World projects over HTTP, as a deployment serves them.

Every test runs the application as a provisioned runtime role with no model client, so each
refusal and each isolation here is the deployment's, and everything shown is what a no-model
installation serves. `docs/project-context.md` is the contract these hold.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

import project_context_support as support
from project_context_support import OWNER, PEER, READER, STRANGER

pytestmark = pytest.mark.postgres


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from support.projects_api(tmp_path, repository, spine_schema)


@pytest.fixture
def world(api):
    """The owner's starter with a market stall and a bench applied, and a project on it."""
    saved = support.starter(api)
    support.place(api, saved, "cc0.market-stall", "stall", "stall")
    saved = support.entry(api, saved["entry_id"])
    version = support.place(api, saved, "cc0.bench", "bench", "bench")
    saved = support.entry(api, saved["entry_id"])
    made = support.project(api, saved["world_id"], saved["authored_version_id"])
    return {"saved": saved, "version": version, "project": made, "world_id": saved["world_id"]}


def _items(api, world, token=OWNER, **params):
    return api.call(
        "GET",
        f"/world/projects/{world['project']['project_id']}/items",
        token=token,
        world=world["world_id"],
        params=params,
    )


def _context(api, world, token=OWNER, **params):
    return api.call(
        "GET",
        f"/world/projects/{world['project']['project_id']}/context",
        token=token,
        world=world["world_id"],
        params=params,
    )


def test_a_project_is_kept_corrected_and_reopened_by_an_independent_client(api, world):
    """Create, read, correct and delete through one client; reopen through another and find the
    same accepted operation, by edit id and result digest, resolved against its authority."""
    w, project_id = world["world_id"], world["project"]["project_id"]
    bench = support.edit_reference(world["version"], "bench")
    base = world["project"]["revision"]
    goal = support.add(
        api,
        w,
        world["project"],
        {"base_revision": base, "kind": "goal", "basis": "user_statement", "text": "Rest spots"},
    )
    preference = support.add(
        api,
        w,
        world["project"],
        {
            "base_revision": goal["project_revision"],
            "kind": "preference",
            "basis": "user_statement",
            "text": "Benches face the stall",
        },
    )
    question = support.add(
        api,
        w,
        world["project"],
        {
            "base_revision": preference["project_revision"],
            "kind": "question",
            "basis": "user_statement",
            "text": "Will anyone sit there?",
        },
    )
    decision = support.add(
        api,
        w,
        world["project"],
        {
            "base_revision": question["project_revision"],
            "kind": "decision",
            "basis": "recorded_outcome",
            "text": "Kept the bench by the stall",
            "references": [bench],
        },
    )
    assert decision["references"][0]["state"] == "available"
    corrected = api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/items/{goal['item_id']}/corrections",
            world=w,
            json={
                "base_revision": decision["project_revision"],
                "text": "Two rest spots",
                "note": "one was not enough",
            },
        ),
        201,
    )
    assert (corrected["revision"], corrected["text"], corrected["basis"]) == (
        2,
        "Two rest spots",
        "user_statement",
    )
    history = api.ok(
        api.call("GET", f"/world/projects/{project_id}/items/{goal['item_id']}/history", world=w),
        200,
    )
    assert [r["text"] for r in history] == ["Rest spots", "Two rest spots"]
    assert (
        api.ok(
            api.call(
                "DELETE", f"/world/projects/{project_id}/items/{preference['item_id']}", world=w
            ),
            200,
        )["project_revision"]
        == corrected["project_revision"] + 1
    )

    # Another client, sharing nothing with the first but the token: the application's own
    # state is all it reads.
    with support.build_app(
        support.services_for(api.scratch, api.grants, api.client.app.state.services.store)
    ) as fresh:
        reopened = support.Api(
            fresh,
            api.repository,
            api.scratch,
            api.workspace_id,
            api.stranger_workspace,
            api.owner,
            api.peer,
            api.grants,
            api.database,
        )
        listed = reopened.ok(reopened.call("GET", "/world/projects", world=w), 200)
        assert [p["project_id"] for p in listed] == [project_id]
        items = reopened.ok(
            reopened.call("GET", f"/world/projects/{project_id}/items", world=w), 200
        )
        assert {i["kind"]: i["text"] for i in items} == {
            "goal": "Two rest spots",
            "question": "Will anyone sit there?",
            "decision": "Kept the bench by the stall",
        }
        kept = next(i for i in items if i["kind"] == "decision")["references"][0]
        assert kept["reference"] == bench
        assert kept["state"] == "available"
        version = reopened.ok(
            reopened.call("GET", f"/world/versions/{bench['version_id']}", world=w),
            200,
        )
        edit = next(e for e in version["edits"] if e["edit_id"] == bench["edit_id"])
        assert edit["result_state_sha256"] == bench["result_state_sha256"]
        project = reopened.ok(reopened.call("GET", f"/world/projects/{project_id}", world=w), 200)
        assert project["binding"]["state"] == "available"
        assert project["binding"]["entry_id"] == world["saved"]["entry_id"]
        assert project["counts"]["goal"] == 1 and project["counts"]["preference"] == 0


def test_another_person_of_the_workspace_reads_only_what_is_shared(api, world):
    w, made = world["world_id"], world["project"]
    project_id = made["project_id"]
    answer = support.remembered_answer(api)
    private = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "preference",
            "basis": "user_statement",
            "text": "Quiet mornings for me",
            "references": [{"kind": "companion_answer", "answer_id": answer}],
        },
    )
    shared = support.add(
        api,
        w,
        made,
        {
            "base_revision": private["project_revision"],
            "kind": "goal",
            "basis": "user_statement",
            "text": "A square people use",
        },
    )
    # Nothing is shared yet: the project is another person's private record.
    assert api.ok(api.call("GET", "/world/projects", token=PEER, world=w), 200) == []
    unknown = api.call("GET", f"/world/projects/{project_id}", token=PEER, world=w)
    invented = api.call("GET", f"/world/projects/{uuid.uuid4()}", token=PEER, world=w)
    assert (unknown.status_code, unknown.json()) == (invented.status_code, invented.json())
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_reference"

    shares = api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/shares",
            world=w,
            json={
                "base_revision": shared["project_revision"],
                "project": True,
                "item_ids": [shared["item_id"], private["item_id"]],
            },
        ),
        200,
    )
    seen = api.ok(_items(api, world, token=PEER), 200)
    assert {i["item_id"] for i in seen} == {shared["item_id"], private["item_id"]}
    for item in seen:
        assert item["owner_is_reader"] is False and item["source_answer_ids"] == []
    hidden = next(i for i in seen if i["item_id"] == private["item_id"])
    assert hidden["references"] == [] and hidden["hidden_references"] == 1
    # The words that stand are shared; why the owner corrected them is not.
    api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/items/{shared['item_id']}/corrections",
            world=w,
            json={
                "base_revision": shares["project_revision"],
                "text": "A square people use daily",
                "note": "my own reason",
            },
        ),
        201,
    )
    again = {i["item_id"]: i for i in api.ok(_items(api, world, token=PEER), 200)}
    assert again[shared["item_id"]]["text"] == "A square people use daily"
    assert again[shared["item_id"]]["note"] is None
    assert "my own reason" not in json.dumps(api.ok(_context(api, world, token=PEER), 200))

    for method, path, body in (
        (
            "POST",
            f"/world/projects/{project_id}/items",
            {"base_revision": 1, "kind": "goal", "basis": "user_statement", "text": "x"},
        ),
        ("POST", f"/world/projects/{project_id}/shares", {"base_revision": 1, "project": True}),
        ("DELETE", f"/world/projects/{project_id}/items/{shared['item_id']}", None),
        ("GET", f"/world/projects/{project_id}/items/{shared['item_id']}/history", None),
        ("GET", f"/world/projects/{project_id}/audit", None),
    ):
        refused = api.call(method, path, token=PEER, world=w, json=body)
        assert refused.status_code == 403, (path, refused.text)
        assert refused.json()["code"] == "not_project_owner"

    item_share = next(s for s in shares["shares"] if s["item_id"] == private["item_id"])
    api.ok(
        api.call(
            "DELETE", f"/world/projects/{project_id}/shares/{item_share['share_id']}", world=w
        ),
        200,
    )
    assert [i["item_id"] for i in api.ok(_items(api, world, token=PEER), 200)] == [
        shared["item_id"]
    ]
    project_share = next(s for s in shares["shares"] if s["item_id"] is None)
    api.ok(
        api.call(
            "DELETE", f"/world/projects/{project_id}/shares/{project_share['share_id']}", world=w
        ),
        200,
    )
    assert api.call("GET", f"/world/projects/{project_id}", token=PEER, world=w).status_code == 404
    assert api.ok(api.call("GET", "/world/projects", token=PEER, world=w), 200) == []


def test_another_workspace_is_answered_as_an_invented_id_is(api, world):
    w, made = world["world_id"], world["project"]
    item = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "task",
            "basis": "user_statement",
            "text": "Add shade",
        },
    )
    project_id = made["project_id"]
    for method, path in (
        ("GET", f"/world/projects/{project_id}"),
        ("GET", f"/world/projects/{project_id}/items"),
        ("GET", f"/world/projects/{project_id}/context"),
        ("GET", f"/world/projects/{project_id}/audit"),
        ("GET", f"/world/projects/{project_id}/items/{item['item_id']}/history"),
        ("DELETE", f"/world/projects/{project_id}/items/{item['item_id']}"),
        ("DELETE", f"/world/projects/{project_id}"),
    ):
        foreign = api.call(method, path, token=STRANGER, world=w)
        invented = api.call(
            method, path.replace(project_id, str(uuid.uuid4())), token=STRANGER, world=w
        )
        assert foreign.status_code == invented.status_code == 404, (path, foreign.text)
        assert foreign.json() == invented.json()
    assert api.ok(api.call("GET", f"/world/projects/{project_id}", world=w), 200)


def test_a_read_only_token_reads_and_writes_nothing(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    assert api.ok(api.call("GET", f"/world/projects/{project_id}", token=READER, world=w), 200)
    create = api.call(
        "POST",
        "/world/projects",
        token=READER,
        world=w,
        json={"title": "x", "version_id": world["saved"]["authored_version_id"]},
    )
    assert create.status_code == 403
    add = api.call(
        "POST",
        f"/world/projects/{project_id}/items",
        token=READER,
        world=w,
        json={"base_revision": 1, "kind": "goal", "basis": "user_statement", "text": "x"},
    )
    assert add.status_code == 404 and add.json()["code"] == "unknown_reference"


def test_stale_and_conflicting_clients_are_refused_by_name(api, world):
    w, made = world["world_id"], world["project"]
    body = {"base_revision": made["revision"], "kind": "goal", "basis": "user_statement"}
    results: list = [None, None]

    def write(index: int) -> None:
        results[index] = api.call(
            "POST",
            f"/world/projects/{made['project_id']}/items",
            world=w,
            json={**body, "text": f"goal {index}"},
        )

    threads = [threading.Thread(target=write, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 409], [r.text for r in results]
    refused = next(r for r in results if r.status_code == 409)
    assert refused.json()["code"] == "stale_project_context"
    rename = api.call(
        "PUT",
        f"/world/projects/{made['project_id']}",
        world=w,
        json={
            "base_revision": made["revision"],
            "title": "Renamed",
            "version_id": made["binding"]["version_id"],
        },
    )
    assert rename.status_code == 409 and rename.json()["code"] == "stale_project_context"


def test_an_exact_retry_returns_the_first_item_and_a_reused_key_is_refused(api, world):
    w, made = world["world_id"], world["project"]
    key = str(uuid.uuid4())
    body = {
        "base_revision": made["revision"],
        "kind": "task",
        "basis": "user_statement",
        "text": "Paint the stall",
        "idempotency_key": key,
    }
    first = support.add(api, w, made, body)
    again = support.add(api, w, made, body, status=(200,))
    assert again["item_id"] == first["item_id"]
    reused = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={**body, "text": "Paint the bench"},
    )
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key_reused"
    project_key = str(uuid.uuid4())
    body = {
        "title": "Keyed",
        "version_id": made["binding"]["version_id"],
        "idempotency_key": project_key,
    }
    created = api.call("POST", "/world/projects", world=w, json=body)
    retried = api.call("POST", "/world/projects", world=w, json=body)
    assert (created.status_code, retried.status_code) == (201, 200)
    assert created.json()["project_id"] == retried.json()["project_id"]


def test_missing_versions_and_records_are_unknown_and_disagreeing_ids_refused(api, world):
    w, made = world["world_id"], world["project"]
    missing = api.call(
        "POST", "/world/projects", world=w, json={"title": "x", "version_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 404 and missing.json()["code"] == "unknown_reference"
    bench = support.edit_reference(world["version"], "bench")
    decision = {"base_revision": made["revision"], "kind": "decision", "basis": "recorded_outcome"}
    unknown = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={**decision, "references": [{**bench, "edit_id": str(uuid.uuid4())}]},
    )
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_reference"
    mismatch = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={**decision, "references": [{**bench, "result_state_sha256": "0" * 64}]},
    )
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "reference_mismatch"
    wrong_kind = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={
            **decision,
            "references": [
                {"kind": "style_preview", "world_id": w, "preview_id": str(uuid.uuid4())}
            ],
        },
    )
    assert wrong_kind.status_code == 422
    placeholder = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={
            "base_revision": made["revision"],
            "kind": "goal",
            "basis": "user_statement",
            "text": "Ask [person A] about it",
        },
    )
    assert placeholder.status_code == 422
    assert placeholder.json()["code"] == "invalid_project_context"
    assert "[person A]" not in placeholder.json()["detail"]


def test_a_withdrawn_source_makes_the_binding_and_its_records_unavailable(api, world):
    """The structural plane's invalidation, as a deletion of the version's source writes it."""
    w, made = world["world_id"], world["project"]
    bench = support.edit_reference(world["version"], "bench")
    decision = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "decision",
            "basis": "recorded_outcome",
            "references": [bench],
        },
    )
    support.invalidate(api, w, bench["version_id"])
    read = api.ok(api.call("GET", f"/world/projects/{made['project_id']}", world=w), 200)
    assert (read["binding"]["state"], read["binding"]["code"]) == (
        "unavailable",
        "invalidated_source_version",
    )
    item = api.ok(_items(api, world), 200)[0]
    assert item["item_id"] == decision["item_id"]
    assert (item["references"][0]["state"], item["references"][0]["code"]) == (
        "unavailable",
        "invalidated_source_version",
    )
    context = api.ok(_context(api, world), 200)
    assert context["entries"] == [] and context["omitted"]["reference_unavailable"] == 1
    refused = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={
            "base_revision": decision["project_revision"],
            "kind": "decision",
            "basis": "recorded_outcome",
            "references": [bench],
        },
    )
    assert refused.status_code == 409 and refused.json()["code"] == "invalidated_source_version"
    again = api.call(
        "POST", "/world/projects", world=w, json={"title": "x", "version_id": bench["version_id"]}
    )
    assert again.status_code == 409 and again.json()["code"] == "invalidated_source_version"


def test_a_suggestion_waits_for_review_and_the_context_holds_only_accepted_items(api, world):
    w, made = world["world_id"], world["project"]
    answer = support.remembered_answer(api)
    suggestion = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "preference",
            "basis": "inferred_suggestion",
            "text": "Prefers shaded seats",
            "references": [{"kind": "companion_answer", "answer_id": answer}],
        },
    )
    assert (suggestion["status"], suggestion["origin"]) == ("proposed", "companion")
    unsourced = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={
            "base_revision": suggestion["project_revision"],
            "kind": "goal",
            "basis": "inferred_suggestion",
            "text": "An inference with no source",
        },
    )
    assert unsourced.status_code == 422
    # The Companion's words about the person reach nobody else before the person accepts them.
    unshared = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/shares",
        world=w,
        json={
            "base_revision": suggestion["project_revision"],
            "project": False,
            "item_ids": [suggestion["item_id"]],
        },
    )
    assert (unshared.status_code, unshared.json()["code"]) == (409, "project_item_not_current")
    context = api.ok(_context(api, world), 200)
    assert context["entries"] == [] and context["omitted"]["pending_review"] == 1
    accepted = api.ok(
        api.call(
            "POST",
            f"/world/projects/{made['project_id']}/items/{suggestion['item_id']}/review",
            world=w,
            json={"base_revision": suggestion["project_revision"], "decision": "accept"},
        ),
        200,
    )
    assert accepted["item"]["status"] == "active"
    context = api.ok(_context(api, world), 200)
    assert [e["item_id"] for e in context["entries"]] == [suggestion["item_id"]]
    assert context["entries"][0]["basis"] == "inferred_suggestion"
    assert context["entries"][0]["origin"] == "companion"


def test_a_resolved_question_leaves_the_context_and_stays_readable(api, world):
    w, made = world["world_id"], world["project"]
    question = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "question",
            "basis": "user_statement",
            "text": "Where does the queue form?",
        },
    )
    resolved = api.ok(
        api.call(
            "POST",
            f"/world/projects/{made['project_id']}/items/{question['item_id']}/resolve",
            world=w,
            json={"base_revision": question["project_revision"]},
        ),
        200,
    )
    assert resolved["status"] == "resolved"
    context = api.ok(_context(api, world), 200)
    assert context["entries"] == [] and context["omitted"]["resolved"] == 1
    listed = api.ok(_items(api, world, status=["resolved"]), 200)
    assert [i["text"] for i in listed] == ["Where does the queue form?"]
    preference = support.add(
        api,
        w,
        made,
        {
            "base_revision": resolved["project_revision"],
            "kind": "preference",
            "basis": "user_statement",
            "text": "Wide paths",
        },
    )
    refused = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items/{preference['item_id']}/resolve",
        world=w,
        json={"base_revision": preference["project_revision"]},
    )
    assert refused.status_code == 422


def test_cross_world_reuse_copies_the_owners_item_and_follows_its_deletion(api, world):
    w, made = world["world_id"], world["project"]
    source = support.add(
        api,
        w,
        made,
        {
            "base_revision": made["revision"],
            "kind": "preference",
            "basis": "user_statement",
            "text": "Benches in the shade",
        },
    )
    other, version = support.other_world(api)
    elsewhere = support.project(api, other, version, title="Another place")
    copy = api.ok(
        api.call(
            "POST",
            f"/world/projects/{elsewhere['project_id']}/items",
            world=other,
            json={
                "base_revision": elsewhere["revision"],
                "reuse": {
                    "world_id": w,
                    "project_id": made["project_id"],
                    "item_id": source["item_id"],
                },
            },
        ),
        201,
    )
    assert copy["text"] == "Benches in the shade"
    assert copy["reused_from"] == {
        "world_id": w,
        "project_id": made["project_id"],
        "item_id": source["item_id"],
    }
    within = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        world=w,
        json={
            "base_revision": source["project_revision"],
            "reuse": {
                "world_id": w,
                "project_id": made["project_id"],
                "item_id": source["item_id"],
            },
        },
    )
    assert (within.status_code, within.json()["code"]) == (422, "invalid_project_context")
    # Another person's shared item is never copied, so stopping a share leaves no copy behind.
    api.ok(
        api.call(
            "POST",
            f"/world/projects/{made['project_id']}/shares",
            world=w,
            json={
                "base_revision": source["project_revision"],
                "project": True,
                "item_ids": [source["item_id"]],
            },
        ),
        200,
    )
    theirs = support.project(api, other, version, title="Theirs")
    refused = api.call(
        "POST",
        f"/world/projects/{theirs['project_id']}/items",
        token=PEER,
        world=other,
        json={
            "base_revision": theirs["revision"],
            "reuse": {
                "world_id": w,
                "project_id": made["project_id"],
                "item_id": source["item_id"],
            },
        },
    )
    assert refused.status_code in (403, 404)
    api.ok(
        api.call(
            "DELETE", f"/world/projects/{made['project_id']}/items/{source['item_id']}", world=w
        ),
        200,
    )
    copies = api.ok(
        api.call("GET", f"/world/projects/{elsewhere['project_id']}/items", world=other), 200
    )
    assert copies == []


def test_every_operation_answers_with_no_model_configured(api, world):
    """The fixture's application has no model client; every read and write above ran on it."""
    assert api.client.app.state.services.model_client is None
    context = api.ok(_context(api, world, max_entries=1, max_bytes=1024), 200)
    assert context["budget"] == {
        "max_entries": 1,
        "max_bytes": 1024,
        "used_entries": 0,
        "used_bytes": 0,
    }
    too_small = _context(api, world, max_bytes=100)
    assert too_small.status_code == 422


def test_a_token_removed_at_restart_is_refused(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    grants = {k: v for k, v in api.grants.items() if k != OWNER}
    with support.build_app(
        support.services_for(api.scratch, grants, api.client.app.state.services.store)
    ) as restarted:
        refused = restarted.get(
            f"/world/projects/{project_id}",
            params={"world_id": w},
            headers={"Authorization": f"Bearer {OWNER}"},
        )
        assert refused.status_code == 401
