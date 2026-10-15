"""The reads a world's History page needs, against PostgreSQL through the routes a page reads with:
every character record of a version by when it was written, every model choice for its people by
when it was made, and where the world is kept on GitHub, as its project's follower last wrote it.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.project_status import write_status

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
    for name, world_id in (("kept", entry["world_id"]), ("other", "world:another")):
        folder = projects / name
        folder.mkdir(parents=True)
        write_status(
            folder,
            {
                "profile": "exulanica.world-project-status/v1",
                "world_id": world_id,
                "version_id": entry["authored_version_id"],
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
    assert kept["world_id"] == entry["world_id"]
    assert kept["link"] == {"repository": "learner/world", "publish": "automatic"}
    assert str(projects) not in read.text  # no path is ever answered
