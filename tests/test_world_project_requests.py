"""A request to keep a world in a project: written by the server into the projects directory's
requests folder, under a name the server makes, and never anywhere else.

Synthetic directories only; nothing reads a world or reaches GitHub.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from exulanica.world import project_requests
from exulanica.world.project_requests import (
    REQUESTS_FOLDER,
    RequestConflict,
    RequestRefused,
    confirm_publication,
    read_publications,
    read_requests,
    refuse_request,
    remove_request,
    request_project,
    request_publication,
    review_publication,
    start_publication,
    withdraw_request,
)

WORLD = "world:synthetic"
WORKSPACE = "0b0e0c1d-0000-4000-8000-0000000000aa"
STRANGER = "0b0e0c1d-0000-4000-8000-0000000000bb"
VERSION = "0b0e0c1d-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)


def ask(directory, world_id=WORLD, workspace_id=WORKSPACE, **changes):
    return request_project(
        directory,
        **{
            "workspace_id": workspace_id,
            "world_id": world_id,
            "version_id": VERSION,
            "readable": False,
            "now": NOW,
            **changes,
        },
    )


def everything(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_a_request_is_written_in_the_requests_folder_under_a_name_the_server_makes(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    request = ask(projects, readable=True)
    assert request["profile"] == "exulanica.world-project-request/v1"
    assert (request["world_id"], request["version_id"], request["readable"]) == (
        WORLD,
        VERSION,
        True,
    )
    assert request["requested_at"] == "2026-10-15T07:00:00Z" and request["refused"] is None
    assert everything(projects) == [
        REQUESTS_FOLDER,
        f"{REQUESTS_FOLDER}/{project_requests.LOCK_FILE}",
        f"{REQUESTS_FOLDER}/{request['request_id']}.json",
    ]
    assert len(request["request_id"]) == 32 and int(request["request_id"], 16) >= 0
    assert read_requests(projects, (WORKSPACE, WORLD)) == [request]
    assert read_requests(projects, (WORKSPACE, "world:another")) == []


def test_a_world_has_one_request_at_a_time_and_a_refused_one_is_replaced(tmp_path):
    first = ask(tmp_path)
    assert ask(tmp_path, readable=True) == first  # still waiting: answered as it is
    other = ask(tmp_path, world_id="world:another")
    refuse_request(tmp_path, first["request_id"], "world_unreadable", NOW)
    [refused] = read_requests(tmp_path, (WORKSPACE, WORLD))
    assert refused["refused"] == {"code": "world_unreadable", "at": "2026-10-15T07:00:00Z"}
    again = ask(tmp_path)
    assert again["request_id"] != first["request_id"]
    assert read_requests(tmp_path) == sorted(
        [other, again], key=lambda r: (r["requested_at"], r["request_id"])
    )
    remove_request(tmp_path, again["request_id"])
    assert read_requests(tmp_path, (WORKSPACE, WORLD)) == []


def test_no_request_reaches_outside_the_requests_folder(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ("a" * 32 + ".json")).write_text("{}")
    request = ask(projects)
    # Fail first: a store that joined the asked identity to the folder would remove these.
    for crafted in ("../outside/" + "a" * 32, "..", "A" * 32, "a" * 31, "a" * 33, "/" + "a" * 32):
        with pytest.raises(RequestRefused):
            withdraw_request(projects, crafted, (WORKSPACE, WORLD))
    assert (outside / ("a" * 32 + ".json")).exists()
    # Another world's request is not this world's to take back.
    assert withdraw_request(projects, request["request_id"], (WORKSPACE, "world:another")) is False
    assert withdraw_request(projects, request["request_id"], (WORKSPACE, WORLD)) is True
    assert read_requests(projects) == []


def test_a_requests_folder_that_is_a_link_is_never_written_or_read(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, projects / REQUESTS_FOLDER)
    with pytest.raises(RequestRefused, match="link"):
        ask(projects)
    assert everything(elsewhere) == []
    assert read_requests(projects) == []
    # A link to a folder that is not there yet is not made into one either.
    (projects / REQUESTS_FOLDER).unlink()
    os.symlink(tmp_path / "not-yet", projects / REQUESTS_FOLDER)
    with pytest.raises(RequestRefused, match="link"):
        ask(projects)
    assert not (tmp_path / "not-yet").exists()


def test_only_well_formed_request_files_are_read(tmp_path):
    request = ask(tmp_path)
    folder = tmp_path / REQUESTS_FOLDER
    elsewhere = tmp_path / "kept.json"
    elsewhere.write_text(json.dumps({**request, "request_id": "b" * 32}))
    os.symlink(elsewhere, folder / ("b" * 32 + ".json"))  # a link: passed over
    (folder / ("c" * 32 + ".json")).write_text(json.dumps(request))  # names another request
    (folder / ("d" * 32 + ".json")).write_text("{not json")
    (folder / ("e" * 32 + ".json")).write_bytes(b" " * (project_requests.MAX_REQUEST_BYTES + 1))
    (folder / "notes.json").write_text(json.dumps(request))  # not a request's name
    assert read_requests(tmp_path) == [request]


def test_requests_are_bounded_and_need_a_projects_directory(tmp_path, monkeypatch):
    with pytest.raises(RequestRefused, match="no projects directory"):
        ask(None)
    with pytest.raises(RequestRefused, match="no projects directory"):
        ask(tmp_path / "absent")
    monkeypatch.setattr(project_requests, "MAX_REQUESTS", 2)
    ask(tmp_path, world_id="world:one")
    ask(tmp_path, world_id="world:two")
    with pytest.raises(RequestRefused, match="too many"):
        ask(tmp_path, world_id="world:three")


def test_one_world_id_in_two_workspaces_keeps_two_requests_apart(tmp_path):
    # One install may hold worlds of several workspaces under one id: a request is its own
    # workspace's, to read and to take back.
    mine, theirs = ask(tmp_path), ask(tmp_path, workspace_id=STRANGER)
    assert mine["request_id"] != theirs["request_id"]
    assert read_requests(tmp_path, (WORKSPACE, WORLD)) == [mine]
    assert withdraw_request(tmp_path, mine["request_id"], (STRANGER, WORLD)) is False
    assert withdraw_request(tmp_path, theirs["request_id"], (STRANGER, WORLD)) is True
    assert read_requests(tmp_path) == [mine]


def test_a_request_is_written_while_the_requests_folder_s_lock_is_held(tmp_path, monkeypatch):
    # Two asks for one world at once (a double click) never both write: the read, the check and
    # the write happen under one lock, the follower's removals and refusals take it too.
    import fcntl

    written = project_requests._write
    seen = []

    def write_and_try_the_lock(folder, document):
        descriptor = os.open(folder / project_requests.LOCK_FILE, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            seen.append(document["request_id"])
        finally:
            os.close(descriptor)
        written(folder, document)

    monkeypatch.setattr(project_requests, "_write", write_and_try_the_lock)
    request = ask(tmp_path)
    refuse_request(tmp_path, request["request_id"], "failed", NOW)
    assert seen == [request["request_id"], request["request_id"]]


# -- putting a kept project on GitHub -------------------------------------------------------------

PROJECT = "project:demo"
REVIEW = {
    "owner": "learner",
    "repository": "learner/world",
    "readable": False,
    "checkpoints": 2,
    "publications_per_day": 24,
    "review_sha256": "a" * 64,
    "reviewed_at": "2026-10-15T07:00:00Z",
}


def publish(directory, name="world", project_id=PROJECT, workspace_id=WORKSPACE):
    return request_publication(
        directory,
        workspace_id=workspace_id,
        world_id=WORLD,
        version_id=VERSION,
        project_id=project_id,
        name=name,
        now=NOW,
    )


def test_requests_to_publish_and_to_keep_are_read_apart(tmp_path):
    kept, published = ask(tmp_path), publish(tmp_path)
    assert published["profile"] == "exulanica.world-project-publication-request/v1"
    assert (published["project_id"], published["name"], published["review"]) == (
        PROJECT,
        "world",
        None,
    )
    assert read_requests(tmp_path, (WORKSPACE, WORLD)) == [kept]
    assert read_publications(tmp_path, (WORKSPACE, WORLD)) == [published]
    assert read_publications(tmp_path, (STRANGER, WORLD)) == []
    # A request to keep the world is still answered as the one waiting, never the publication.
    assert ask(tmp_path) == kept


def test_a_repository_name_is_a_name_and_nothing_else(tmp_path):
    assert publish(tmp_path, name="my-world.v2_1")["name"] == "my-world.v2_1"
    assert publish(tmp_path, name=None)["name"] is None
    for broken in (".", "..", "learner/world", "", "a" * 101, "two words", "../world"):
        with pytest.raises(RequestRefused):
            publish(tmp_path, name=broken)


def test_a_project_has_one_publication_request_and_one_being_created_stays(tmp_path):
    first = publish(tmp_path)
    assert publish(tmp_path) == first  # waiting under the same name: answered as it is
    renamed = publish(tmp_path, name="harbour")
    assert renamed["request_id"] != first["request_id"]
    assert read_publications(tmp_path) == [renamed]
    other = publish(tmp_path, project_id="project:other")
    assert review_publication(tmp_path, renamed["request_id"], REVIEW)
    confirm_publication(tmp_path, renamed["request_id"], (WORKSPACE, WORLD), "a" * 64, NOW)
    assert start_publication(tmp_path, renamed["request_id"], NOW)["started_at"] is not None
    # Being created: neither asked again nor taken back; the other project's request is its own.
    for again in (lambda: publish(tmp_path), lambda: publish(tmp_path, name="another")):
        with pytest.raises(RequestConflict) as caught:
            again()
        assert caught.value.code == "publication_started"
    with pytest.raises(RequestConflict):
        withdraw_request(tmp_path, renamed["request_id"], (WORKSPACE, WORLD))
    assert withdraw_request(tmp_path, other["request_id"], (WORKSPACE, WORLD)) is True
    # Refused (the follower stopped while creating it), it is replaced by the next ask.
    refuse_request(tmp_path, renamed["request_id"], "failed", NOW)
    assert publish(tmp_path)["request_id"] not in (first["request_id"], renamed["request_id"])


def test_the_person_s_yes_is_bound_to_the_review_they_saw(tmp_path):
    request = publish(tmp_path)
    identity, world = request["request_id"], (WORKSPACE, WORLD)

    def refused_by(digest):
        with pytest.raises(RequestConflict) as caught:
            confirm_publication(tmp_path, identity, world, digest, NOW)
        return caught.value.code

    assert confirm_publication(tmp_path, "b" * 32, world, "a" * 64, NOW) is None
    assert confirm_publication(tmp_path, identity, (STRANGER, WORLD), "a" * 64, NOW) is None
    assert refused_by("a" * 64) == "publication_not_reviewed"
    assert start_publication(tmp_path, identity, NOW) is None  # nothing starts without a yes
    assert review_publication(tmp_path, identity, REVIEW)
    assert not review_publication(tmp_path, identity, {**REVIEW, "owner": "other"})
    assert refused_by("b" * 64) == "publication_review_changed"
    confirmed = confirm_publication(tmp_path, identity, world, "a" * 64, NOW)
    assert confirmed["confirmed"] == {"review_sha256": "a" * 64, "at": "2026-10-15T07:00:00Z"}
    assert confirm_publication(tmp_path, identity, world, "a" * 64, NOW) == confirmed
    started = start_publication(tmp_path, identity, NOW)
    assert started["started_at"] == "2026-10-15T07:00:00Z"
    assert start_publication(tmp_path, identity, NOW) is None  # started once
    refuse_request(tmp_path, identity, "name_taken", NOW)
    assert refused_by("a" * 64) == "publication_refused"
    [kept] = read_publications(tmp_path)
    assert kept["refused"] == {"code": "name_taken", "at": "2026-10-15T07:00:00Z"}


def test_publication_requests_count_toward_the_folder_s_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(project_requests, "MAX_REQUESTS", 2)
    ask(tmp_path)
    publish(tmp_path)
    with pytest.raises(RequestRefused, match="too many"):
        publish(tmp_path, project_id="project:other")
    with pytest.raises(RequestRefused, match="too many"):
        ask(tmp_path, world_id="world:another")
