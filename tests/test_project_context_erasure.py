"""Deleted project context is gone from every read and from the rows, on every deletion path.

Each path is driven the way the product drives it (a person's deletion, a rejected suggestion, a
deleted or renamed project, a deleted Companion answer, a deleted source item and the copies of its
copies, a workspace tombstone), and each is followed by a check of the rows themselves, as the
schema owner, so the claim is about what the database holds and not about what a route chooses to
show: no revision keeps its words, notes or references, no request digest survives, and no row of
any project table still spells the deleted sentence. What stays is the residue the audit read
serves. A capture tombstone reaching an item through a photograph's answer is checked in
``tests/test_restore_replay_project_context.py``, at the source and again after a restore.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.guards import TOMBSTONE_REFUSAL
from exulanica.db.session import set_workspace

import project_context_support as support
from project_context_support import OWNER

pytestmark = pytest.mark.postgres

#: Every table migration 0127 adds and every text-bearing column a search could find words in.
_PROJECT_TABLES = (
    "world_project",
    "world_project_binding",
    "world_project_item",
    "world_project_item_revision",
    "world_project_item_source",
    "world_project_share",
)


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from support.projects_api(tmp_path, repository, spine_schema)


@pytest.fixture
def world(api):
    saved = support.starter(api)
    made = support.project(api, saved["world_id"], saved["authored_version_id"])
    return {"saved": saved, "project": made, "world_id": saved["world_id"]}


def _spelled(api, phrase: str) -> list[str]:
    """Every project-table row whose text anywhere spells ``phrase``, read as the schema owner."""
    connection = api.repository.connection
    found = []
    for table in _PROJECT_TABLES:
        rows = connection.execute(
            f"select to_jsonb(t)::text as row from {table} t where to_jsonb(t)::text like %s",
            (f"%{phrase}%",),
        ).fetchall()
        found.extend(f"{table}: {row['row']}" for row in rows)
    return found


def _erased(api, item_id: str) -> None:
    """The item's rows as the database holds them: withdrawn, every revision cleared."""
    connection = api.repository.connection
    item = connection.execute(
        "select status::text as status, request_sha256, withdrawn_at from world_project_item "
        "where item_id=%s",
        (item_id,),
    ).fetchone()
    assert item["status"] == "withdrawn" and item["withdrawn_at"] is not None
    assert item["request_sha256"] is None
    revisions = connection.execute(
        "select text, note, refs, erased_at, basis::text as basis, recorded_at "
        "from world_project_item_revision where item_id=%s order by revision",
        (item_id,),
    ).fetchall()
    assert revisions, "the residue keeps each revision's basis and instant"
    for revision in revisions:
        assert (revision["text"], revision["note"], revision["refs"]) == (None, None, None)
        assert revision["erased_at"] is not None
        assert revision["basis"] and revision["recorded_at"]


def _secret(label: str) -> str:
    return f"secret {label} {uuid.uuid4().hex[:8]}"


def _add(api, world, *, text, kind="goal", basis="user_statement", references=(), **extra):
    base = support.revision(api, world["world_id"], world["project"]["project_id"])
    return support.add(
        api,
        world["world_id"],
        world["project"],
        {
            "base_revision": base,
            "kind": kind,
            "basis": basis,
            "text": text,
            "references": list(references),
            **extra,
        },
    )


def test_a_deleted_item_is_gone_from_a_later_assembly_and_every_read(api, world):
    """Assemble first, so a cached assembly would have something to hand back; there is none."""
    w, project_id = world["world_id"], world["project"]["project_id"]
    phrase = _secret("goal")
    item = _add(api, world, text=phrase, idempotency_key=str(uuid.uuid4()))
    api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/items/{item['item_id']}/corrections",
            world=w,
            json={
                "base_revision": item["project_revision"],
                "text": phrase + " corrected",
                "note": phrase + " because",
            },
        ),
        201,
    )
    before = api.ok(api.call("GET", f"/world/projects/{project_id}/context", world=w), 200)
    assert [e["item_id"] for e in before["entries"]] == [item["item_id"]]
    api.ok(
        api.call("DELETE", f"/world/projects/{project_id}/items/{item['item_id']}", world=w), 200
    )
    after = api.ok(api.call("GET", f"/world/projects/{project_id}/context", world=w), 200)
    assert after["entries"] == [] and after["assembly_sha256"] != before["assembly_sha256"]
    assert api.ok(api.call("GET", f"/world/projects/{project_id}/items", world=w), 200) == []
    history = api.call(
        "GET", f"/world/projects/{project_id}/items/{item['item_id']}/history", world=w
    )
    assert history.status_code == 404
    audit = api.ok(api.call("GET", f"/world/projects/{project_id}/audit", world=w), 200)
    residue = audit["items"][0]
    assert (residue["status"], residue["withdrawn_reason"], len(residue["revisions"])) == (
        "withdrawn",
        "deleted",
        2,
    )
    assert phrase in str(before)
    assert phrase not in str(after) and phrase not in str(audit)
    _erased(api, item["item_id"])
    assert _spelled(api, phrase) == []


def test_a_rejected_suggestion_keeps_nothing_it_said(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    answer = support.remembered_answer(api)
    phrase = _secret("suggestion")
    item = _add(
        api,
        world,
        text=phrase,
        kind="preference",
        basis="inferred_suggestion",
        references=[{"kind": "companion_answer", "answer_id": answer}],
    )
    rejected = api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/items/{item['item_id']}/review",
            world=w,
            json={"base_revision": item["project_revision"], "decision": "reject"},
        ),
        200,
    )
    assert rejected["item"] is None
    _erased(api, item["item_id"])
    reason = api.repository.connection.execute(
        "select withdrawn_reason::text as r from world_project_item where item_id=%s",
        (item["item_id"],),
    ).fetchone()["r"]
    assert reason == "rejected"
    assert _spelled(api, phrase) == []


def test_a_deleted_project_erases_its_title_items_and_shares(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    phrase = _secret("project")
    api.ok(
        api.call(
            "PUT",
            f"/world/projects/{project_id}",
            world=w,
            json={
                "base_revision": world["project"]["revision"],
                "title": phrase,
                "version_id": world["project"]["binding"]["version_id"],
            },
        ),
        200,
    )
    item = _add(api, world, text=phrase + " item")
    api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/shares",
            world=w,
            json={
                "base_revision": item["project_revision"],
                "project": True,
                "item_ids": [item["item_id"]],
            },
        ),
        200,
    )
    deleted = api.call("DELETE", f"/world/projects/{project_id}", world=w)
    assert deleted.status_code == 204
    assert api.call("GET", f"/world/projects/{project_id}", world=w).status_code == 404
    audit = api.ok(api.call("GET", f"/world/projects/{project_id}/audit", world=w), 200)
    assert audit["withdrawn_at"] is not None and audit["withdrawn_by_tombstone"] is False
    assert all(s["withdrawn_at"] is not None for s in audit["shares"])
    assert audit["items"][0]["withdrawn_reason"] == "project_deleted"
    connection = api.repository.connection
    row = connection.execute(
        "select title, request_sha256 from world_project where project_id=%s", (project_id,)
    ).fetchone()
    assert row == {"title": None, "request_sha256": None}
    _erased(api, item["item_id"])
    assert _spelled(api, phrase) == []


def _digest(api, project_id: str) -> str | None:
    return api.repository.connection.execute(
        "select request_sha256 from world_project where project_id=%s", (project_id,)
    ).fetchone()["request_sha256"]


def test_a_creation_digest_goes_with_the_title_it_covers(api, world):
    """A digest of a short title is the title to anyone who can guess it: a rename clears it, a
    deletion clears it, and the key that made the project no longer answers as that request."""
    w = world["world_id"]
    version = world["project"]["binding"]["version_id"]
    first, second = _secret("first title"), _secret("second title")
    key = str(uuid.uuid4())
    renamed = support.project(api, w, version, title=first, idempotency_key=key)
    assert _digest(api, renamed["project_id"]) is not None
    api.ok(
        api.call(
            "PUT",
            f"/world/projects/{renamed['project_id']}",
            world=w,
            json={"base_revision": renamed["revision"], "title": "Renamed", "version_id": version},
        ),
        200,
    )
    assert _digest(api, renamed["project_id"]) is None
    retried = api.call(
        "POST",
        "/world/projects",
        world=w,
        json={"title": first, "version_id": version, "idempotency_key": key},
    )
    assert (retried.status_code, retried.json()["code"]) == (409, "idempotency_key_reused")
    deleted = support.project(api, w, version, title=second, idempotency_key=str(uuid.uuid4()))
    assert _digest(api, deleted["project_id"]) is not None
    gone = api.call("DELETE", f"/world/projects/{deleted['project_id']}", world=w)
    assert gone.status_code == 204
    assert _digest(api, deleted["project_id"]) is None
    assert _spelled(api, first) == [] and _spelled(api, second) == []


def test_deleting_an_item_closes_its_share_at_the_same_instant(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    phrase = _secret("shared")
    item = _add(api, world, text=phrase)
    shared = api.ok(
        api.call(
            "POST",
            f"/world/projects/{project_id}/shares",
            world=w,
            json={
                "base_revision": item["project_revision"],
                "project": False,
                "item_ids": [item["item_id"]],
            },
        ),
        200,
    )
    [share] = shared["shares"]
    api.ok(
        api.call("DELETE", f"/world/projects/{project_id}/items/{item['item_id']}", world=w), 200
    )
    connection = api.repository.connection
    closed = connection.execute(
        "select s.withdrawn_at as share_ended, i.withdrawn_at as item_ended "
        "from world_project_share s join world_project_item i using (workspace_id, item_id) "
        "where s.share_id=%s",
        (share["share_id"],),
    ).fetchone()
    assert closed["share_ended"] is not None and closed["share_ended"] == closed["item_ended"]
    _erased(api, item["item_id"])
    assert _spelled(api, phrase) == []


def test_deleting_a_companion_answer_deletes_what_was_drawn_from_it(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    answer = support.remembered_answer(api)
    phrase = _secret("drawn")
    item = _add(
        api,
        world,
        text=phrase,
        references=[{"kind": "companion_answer", "answer_id": answer}],
    )
    deleted = api.call("DELETE", f"/companion/memory/answers/{answer}", world=None)
    assert deleted.status_code == 204, deleted.text
    assert api.ok(api.call("GET", f"/world/projects/{project_id}/items", world=w), 200) == []
    _erased(api, item["item_id"])
    reason = api.repository.connection.execute(
        "select withdrawn_reason::text as r, withdrawn_by from world_project_item where item_id=%s",
        (item["item_id"],),
    ).fetchone()
    assert reason == {"r": "source_withdrawn", "withdrawn_by": None}
    assert _spelled(api, phrase) == []


def test_deleting_a_source_item_deletes_its_copies_in_other_worlds(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    phrase = _secret("copied")
    source = _add(api, world, text=phrase, kind="preference")
    other, version = support.other_world(api)
    elsewhere = support.project(api, other, version, title="Elsewhere")
    copy = api.ok(
        api.call(
            "POST",
            f"/world/projects/{elsewhere['project_id']}/items",
            world=other,
            json={
                "base_revision": elsewhere["revision"],
                "reuse": {"world_id": w, "project_id": project_id, "item_id": source["item_id"]},
            },
        ),
        201,
    )
    # A copy of the copy, back in the first world: a deletion reaches it through the copy.
    third = support.project(api, w, world["project"]["binding"]["version_id"], title="Third")
    copy_of_copy = api.ok(
        api.call(
            "POST",
            f"/world/projects/{third['project_id']}/items",
            world=w,
            json={
                "base_revision": third["revision"],
                "reuse": {
                    "world_id": other,
                    "project_id": elsewhere["project_id"],
                    "item_id": copy["item_id"],
                },
            },
        ),
        201,
    )
    api.ok(
        api.call("DELETE", f"/world/projects/{project_id}/items/{source['item_id']}", world=w), 200
    )
    for item in (source, copy, copy_of_copy):
        _erased(api, item["item_id"])
    reasons = {
        str(row["item_id"]): row["reason"]
        for row in api.repository.connection.execute(
            "select item_id, withdrawn_reason::text as reason from world_project_item "
            "where item_id = any(%s::uuid[])",
            ([source["item_id"], copy["item_id"], copy_of_copy["item_id"]],),
        ).fetchall()
    }
    assert reasons == {
        source["item_id"]: "deleted",
        copy["item_id"]: "source_withdrawn",
        copy_of_copy["item_id"]: "source_withdrawn",
    }
    assert _spelled(api, phrase) == []


def test_a_workspace_tombstone_deletes_every_project_and_takes_no_new_one(api, world):
    w, project_id = world["world_id"], world["project"]["project_id"]
    phrase = _secret("workspace")
    item = _add(api, world, text=phrase)
    connection = api.repository.connection
    set_workspace(connection, api.workspace_id)
    tombstone = connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'workspace', %s, 'test') returning tombstone_id, effective_at",
        (api.workspace_id, api.owner),
    ).fetchone()
    project = connection.execute(
        "select title, withdrawn_at, withdrawn_by from world_project where project_id=%s",
        (project_id,),
    ).fetchone()
    assert project == {
        "title": None,
        "withdrawn_at": tombstone["effective_at"],
        "withdrawn_by": tombstone["tombstone_id"],
    }
    _erased(api, item["item_id"])
    reason = connection.execute(
        "select withdrawn_reason::text as r, withdrawn_by from world_project_item where item_id=%s",
        (item["item_id"],),
    ).fetchone()
    assert reason == {"r": "workspace_deleted", "withdrawn_by": tombstone["tombstone_id"]}
    assert _spelled(api, phrase) == []
    # The deletion invalidated every version's source too, so the route answers that first; the
    # database's own guard is the wall behind it, for any path that reaches the table.
    refused = api.call(
        "POST",
        "/world/projects",
        token=OWNER,
        world=w,
        json={"title": "after", "version_id": world["project"]["binding"]["version_id"]},
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "invalidated_source_version")
    refusal = pytest.raises(psycopg.errors.IntegrityConstraintViolation, match=TOMBSTONE_REFUSAL)
    with refusal, connection.transaction():
        connection.execute(
            "insert into world_project (workspace_id, world_id, owner_actor_id, title, "
            "version_id) values (%s, %s, %s, 'after', %s)",
            (api.workspace_id, w, api.owner, world["project"]["binding"]["version_id"]),
        )
