"""The reads a world's History page needs, against PostgreSQL through the routes a page reads with:
every character record of a version by when it was written, every model choice for its people by
when it was made, and where the world is kept on GitHub, as its project's follower last wrote it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from exulanica.world.project_requests import review_publication, start_publication
from exulanica.world.project_status import write_status

from personal_world_support import OWNER_TOKEN
from test_saved_world_holding_things_postgres import _query, _scope
from test_society_made_world import made as imported_made  # noqa: F401
from test_thing_characters_postgres import CHARACTER, _a_society_with_a_knight, _knight, _write

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def test_every_character_record_reads_newest_first_with_what_it_stated(made):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    first = _write(api, entry, "knight", None, CHARACTER).json()
    second = _write(api, entry, "knight", first["revision"], {"name": "Sir Pell"}).json()
    cleared = _write(api, entry, "knight", second["revision"], None).json()
    path = _scope(entry) + "/things/characters/history" + _query(entry)
    read = api.get(path)
    assert read.status_code == 200, read.text
    assert read.headers["cache-control"] == "private, no-store"
    body = read.json()
    assert body["profile"] == "exulanica.thing-character-history/v1" and body["more"] is False
    assert [(r["revision"], r["states_name"], r["states_about"]) for r in body["records"]] == [
        (cleared["revision"], False, False),
        (second["revision"], True, False),
        (first["revision"], True, True),
    ]
    # Never the words themselves: the newest read holds those.
    assert "Sir Pell" not in read.text and CHARACTER["about"] not in read.text
    limited = api.get(path + "&limit=2").json()
    assert len(limited["records"]) == 2 and limited["more"] is True
    absent = api.get(f"/world/versions/{uuid.uuid4()}/things/characters/history" + _query(entry))
    assert (absent.status_code, absent.json()["code"]) == (404, "unknown_reference")


def test_every_model_choice_for_the_people_reads_newest_first_and_never_who_chose(made):
    api = made
    entry, society = _a_society_with_a_knight(api)
    knight = _knight(society)["id"]
    models = _scope(entry) + "/society/models"
    for _ in range(2):
        chosen = api.post(
            models + _query(entry),
            {"idempotency_key": str(uuid.uuid4()), "people": [knight], "model": None},
        )
        assert chosen.status_code == 200, chosen.text
    read = api.get(models + "/history" + _query(entry))
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["profile"] == "exulanica.society-model-history/v1"
    seqs = [choice["choice_seq"] for choice in body["choices"]]
    assert seqs == sorted(seqs, reverse=True) and len(seqs) >= 2
    newest = body["choices"][0]
    assert newest["subjects"] == [knight] and newest["model"] is None
    assert newest["decider"] == {"kind": "routine"} and newest["recorded_at"]
    assert "chosen_by" not in read.text and str(api.actor) not in read.text
    older = api.get(models + f"/history{_query(entry)}&before={seqs[0]}").json()
    assert [c["choice_seq"] for c in older["choices"]] == seqs[1:]


def test_where_the_world_is_kept_on_github_reads_the_configured_directory_alone(
    made, tmp_path, monkeypatch
):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    path = "/world/github-projects" + _query(entry)
    assert api.get(path).json()["projects"] == []  # no directory configured
    projects = tmp_path / "projects"
    # The third is another workspace's project of a world under the same id: its version is not
    # one this workspace holds, so it is never answered here.
    for name, world_id, version_id in (
        ("kept", entry["world_id"], entry["authored_version_id"]),
        ("other", "world:another", entry["authored_version_id"]),
        ("elsewhere", entry["world_id"], str(uuid.uuid4())),
    ):
        folder = projects / name
        folder.mkdir(parents=True)
        write_status(
            folder,
            {
                "profile": "exulanica.world-project-status/v1",
                "world_id": world_id,
                "version_id": version_id,
                "written_at": "2026-10-15T01:00:00Z",
                "checkpoints": 2,
                "last_checkpoint_at": "2026-10-15T00:59:00Z",
                "pending": False,
                "link": {"repository": "learner/world", "publish": "automatic"},
                "github": None,
            },
        )
    monkeypatch.setenv("EXULANICA_PROJECTS_DIRECTORY", str(projects))
    read = api.get(path)
    assert read.status_code == 200, read.text
    [kept] = read.json()["projects"]
    assert (kept["world_id"], kept["version_id"]) == (
        entry["world_id"],
        entry["authored_version_id"],
    )
    assert kept["link"] == {"repository": "learner/world", "publish": "automatic"}
    assert str(projects) not in read.text  # no path is ever answered


def _delete(api, path):
    return api.client.delete(path, headers={"Authorization": f"Bearer {OWNER_TOKEN}"})


def test_a_person_asks_for_a_world_to_be_kept_and_takes_the_request_back(
    made, tmp_path, monkeypatch
):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    query = _query(entry)
    path = "/world/github-projects" + query
    body = {"version_id": entry["authored_version_id"], "readable": True}
    refused = api.post(path, body)
    assert refused.status_code == 409 and refused.json()["code"] == "projects_not_kept"
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("EXULANICA_PROJECTS_DIRECTORY", str(projects))
    asked = api.post(path, body)
    assert asked.status_code == 202, asked.text
    request = asked.json()
    assert (request["world_id"], request["version_id"], request["readable"]) == (
        entry["world_id"],
        entry["authored_version_id"],
        True,
    )
    assert str(projects) not in asked.text  # no path is ever answered
    # Asked again while it waits: the same request.
    assert api.post(path, body).json()["request_id"] == request["request_id"]
    assert [r["request_id"] for r in api.get(path).json()["requests"]] == [request["request_id"]]
    # Only a version this workspace holds, and nothing but the version and the setting.
    assert api.post(path, {"version_id": str(uuid.uuid4())}).status_code == 404
    assert api.post(path, {**body, "folder": "elsewhere"}).status_code == 422
    taken = f"/world/github-projects/requests/{request['request_id']}" + query
    assert _delete(api, taken).status_code == 204
    assert _delete(api, taken).status_code == 404
    # A crafted name never reaches a file: refused by its pattern, or, climbing out, by no route.
    for crafted in ("..", "A" * 32, "a" * 31, "%2E%2E%2Foutside"):
        answer = _delete(api, f"/world/github-projects/requests/{crafted}" + query)
        assert answer.status_code in (404, 405, 422), answer.text
    assert api.get(path).json()["requests"] == []
    assert sorted(entry.name for entry in projects.iterdir()) == [".requests"]


def test_a_person_asks_for_a_kept_project_on_github_and_says_yes_to_its_review(
    made, tmp_path, monkeypatch
):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    query = _query(entry)
    path = "/world/github-projects/publications" + query
    asked_for = {"project_id": "project:demo", "name": "world"}
    refused = api.post(path, asked_for)
    assert refused.status_code == 409 and refused.json()["code"] == "projects_not_kept"
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("EXULANICA_PROJECTS_DIRECTORY", str(projects))
    # No project of this world states that identity.
    assert api.post(path, asked_for).status_code == 404
    status = {
        "profile": "exulanica.world-project-status/v1",
        "world_id": entry["world_id"],
        "version_id": entry["authored_version_id"],
        "project_id": "project:demo",
        "written_at": "2026-10-15T01:00:00Z",
        "checkpoints": 2,
        "last_checkpoint_at": "2026-10-15T00:59:00Z",
        "pending": False,
        "link": None,
        "github": None,
    }
    (projects / "world-a").mkdir()
    write_status(projects / "world-a", status)
    # A project of a version this workspace does not hold is nobody's here.
    (projects / "world-b").mkdir()
    write_status(
        projects / "world-b",
        {**status, "project_id": "project:other", "version_id": str(uuid.uuid4())},
    )
    assert api.post(path, {"project_id": "project:other"}).status_code == 404
    asked = api.post(path, asked_for)
    assert asked.status_code == 202, asked.text
    request = asked.json()
    assert request["profile"] == "exulanica.world-project-publication-request/v1"
    assert (request["project_id"], request["name"], request["version_id"], request["review"]) == (
        "project:demo",
        "world",
        entry["authored_version_id"],
        None,
    )
    listed = api.get("/world/github-projects" + query).json()
    assert listed["publications"] == [request] and listed["requests"] == []
    # A name is a name: no owner, no path, nothing else in the body.
    for broken in ({**asked_for, "name": "learner/world"}, {**asked_for, "name": ".."}):
        assert api.post(path, broken).status_code == 422
    assert api.post(path, {**asked_for, "folder": "elsewhere"}).status_code == 422
    create = f"/world/github-projects/publications/{request['request_id']}/create" + query

    def yes(digest):
        return api.post(create, {"review_sha256": digest})

    assert yes("a" * 64).json()["code"] == "publication_not_reviewed"
    # The follower's review, as it writes it beside the request.
    review = {
        "owner": "learner",
        "repository": "learner/world",
        "readable": False,
        "checkpoints": 2,
        "publications_per_day": 24,
        "review_sha256": "a" * 64,
        "reviewed_at": "2026-10-15T01:01:00Z",
    }
    assert review_publication(projects, request["request_id"], review)
    changed = yes("b" * 64)
    assert (changed.status_code, changed.json()["code"]) == (409, "publication_review_changed")
    confirmed = yes("a" * 64)
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["confirmed"]["review_sha256"] == "a" * 64
    unknown = f"/world/github-projects/publications/{'c' * 32}/create" + query
    assert api.post(unknown, {"review_sha256": "a" * 64}).status_code == 404
    # Being created: neither taken back nor asked again.
    start_publication(projects, request["request_id"], datetime.now(UTC))
    taken = _delete(api, f"/world/github-projects/requests/{request['request_id']}" + query)
    assert (taken.status_code, taken.json()["code"]) == (409, "publication_started")
    assert api.post(path, asked_for).json()["code"] == "publication_started"
    # A project already linked to a repository has nothing to create.
    write_status(
        projects / "world-a",
        {**status, "link": {"repository": "learner/world", "publish": "by hand"}},
    )
    assert api.post(path, asked_for).json()["code"] == "project_linked"
    assert str(projects) not in asked.text + confirmed.text
