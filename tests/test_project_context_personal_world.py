"""A world project and a remembered answer keep the version they name when photographs are added.

Adding photographs to a made personal world opens a new version whose parent is the old one and
moves the saved entry to it (``docs/saved-world-entry.md``). Three tables of the project-context
plane name a version, and ``VERSION_TABLES`` in ``exulanica/world/personal_composition.py`` says
what an addition does with each: a project stays bound to the version it was bound to, each of its
bindings stays as recorded, and a remembered answer about the world's people keeps citing the
version it read, where the society it read stays. This drives a real addition through the
application, as provisioned runtime roles, and holds each of those rows unchanged by it; the
project's read then names both versions, and only its owner's write binds it to the new one.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.canonical import sha256_of_canonical

from personal_world_support import (
    compose,
    group,
    make_world,
    personal_world_api,
    photograph,
    place_object,
    source_media,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from personal_world_api(tmp_path, repository, spine_schema)


def _away_society(api, entry: dict) -> str:
    """A society on the saved version whose one inhabitant is away, so the addition may proceed;
    planted, because no product path gives a personal-source world inhabitants. Returns the
    inhabitant's id."""
    connection = api.repository.connection
    place, inhabitant = uuid.uuid4(), str(uuid.uuid4())
    connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (api.repository.workspace_id, place),
    )
    state = {"inhabitants": [{"id": inhabitant}], "presence": {"status": "away"}}
    connection.execute(
        "insert into world_society(workspace_id,world_id,version_id,place_id,region_id,"
        "engine_version,seed,population_size,tick_seconds,state,state_sha256,created_by) "
        "values(%s,%s,%s,%s,%s,%s,%s,1,60,%s,%s,%s)",
        (
            api.repository.workspace_id,
            entry["world_id"],
            entry["authored_version_id"],
            place,
            "region:society",
            "exulanica-society/v2",
            "ab" * 32,
            json.dumps(state),
            sha256_of_canonical(state).hex(),
            api.actor,
        ),
    )
    connection.commit()
    return inhabitant


def _rows(api, project_id: str, answer_id: str) -> dict[str, list]:
    """Every row of the three version-naming tables this project and answer hold, as the owner."""
    connection = api.repository.connection
    return {
        table: connection.execute(
            f"select * from {table} where {key}=%s {order}", (value,)
        ).fetchall()
        for table, key, value, order in (
            ("world_project", "project_id", project_id, ""),
            ("world_project_binding", "project_id", project_id, "order by binding_seq"),
            ("companion_answer_simulation_citation", "answer_id", answer_id, "order by ordinal"),
            ("companion_answer_simulation_label", "answer_id", answer_id, "order by label"),
        )
    }


def test_a_project_and_a_remembered_answer_stay_with_the_version_they_name(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry = place_object(api, entry, region)
    world, made = entry["world_id"], entry["authored_version_id"]
    [edit] = api.version(entry)["edits"]
    inhabitant = _away_society(api, entry)

    answer = api.post(
        "/companion/memory/answers",
        {
            "question": "Who rests by the lantern?",
            "answer_text": "[inhabitant A] rested by the lantern.",
            "prompt_version": "society-1",
            "latency_ms": 3,
            "composed": "none",
            "used_fallback": False,
            "unanswered_attempts": 0,
            "unanswered_cost_unknown": False,
            "world_id": world,
            "simulation_citations": [
                {
                    "ordinal": 0,
                    "result_kind": "synthetic_inhabitant",
                    "version_id": made,
                    "inhabitant_id": inhabitant,
                    "tick": 0,
                }
            ],
            "inhabitants": {"[inhabitant A]": {"version_id": made, "inhabitant_id": inhabitant}},
        },
    )
    assert answer.status_code == 201, answer.text
    answer_id = answer.json()["answer_id"]
    created = api.post(
        f"/world/projects?world_id={world}", {"title": "Evening rest", "version_id": made}
    )
    assert created.status_code == 201, created.text
    project = created.json()
    decision = api.post(
        f"/world/projects/{project['project_id']}/items?world_id={world}",
        {
            "base_revision": project["revision"],
            "kind": "decision",
            "basis": "recorded_outcome",
            "text": "Kept the lantern",
            "references": [
                {
                    "kind": "world_edit",
                    "operation": "POST /world/versions/{version_id}/objects",
                    "world_id": world,
                    "version_id": made,
                    "edit_id": edit["edit_id"],
                    "edit_seq": edit["edit_seq"],
                    "result_state_sha256": edit["result_state_sha256"],
                }
            ],
        },
    )
    assert decision.status_code == 201, decision.text
    before = _rows(api, project["project_id"], answer_id)
    assert before["companion_answer_simulation_citation"]
    assert before["companion_answer_simulation_label"]

    photograph(api, minute=3)
    group(api)
    read = api.read()
    assert read["action"] == "add_photographs", read
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    moved = api.entry(entry["entry_id"])
    opened = moved["authored_version_id"]
    assert opened != made and api.version(moved)["parent_version_id"] == made

    # Each row naming the made version is exactly as it was: nothing moved or carried it.
    assert _rows(api, project["project_id"], answer_id) == before
    read_back = api.get(f"/world/projects/{project['project_id']}?world_id={world}")
    assert read_back.status_code == 200, read_back.text
    binding = read_back.json()["binding"]
    assert (binding["version_id"], binding["state"], binding["entry_version_id"]) == (
        made,
        "available",
        opened,
    )
    items = api.get(f"/world/projects/{project['project_id']}/items?world_id={world}").json()
    assert [[r["state"] for r in item["references"]] for item in items] == [["available"]]
    recent = api.get("/companion/memory/recent").json()["answers"]
    [remembered] = [a for a in recent if a["answer_id"] == answer_id]
    assert [c["version_id"] for c in remembered["simulation_citations"]] == [made]
    assert remembered["inhabitants"]["[inhabitant A]"]["version_id"] == made

    # Only the owner's own write binds the project to the version the saved world opens now; the
    # first binding stays as it was recorded, and the decision still names the made version's edit.
    rebound = api.put(
        f"/world/projects/{project['project_id']}?world_id={world}",
        {
            "base_revision": read_back.json()["revision"],
            "title": "Evening rest",
            "version_id": opened,
        },
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["binding"]["version_id"] == opened
    after = _rows(api, project["project_id"], answer_id)["world_project_binding"]
    assert after[0] == before["world_project_binding"][0]
    assert [(row["binding_seq"], str(row["version_id"])) for row in after] == [
        (1, made),
        (2, opened),
    ]
    items = api.get(f"/world/projects/{project['project_id']}/items?world_id={world}").json()
    assert [[r["state"] for r in item["references"]] for item in items] == [["available"]]
