"""Where a world is kept on GitHub: the state its project's follower writes beside the project and
the server reads from one configured directory. Synthetic folders and a strict fake repository;
nothing is published anywhere."""

import json
import os

import pytest
from exulanica.world.project_status import (
    MAX_STATUS_BYTES,
    STATUS_FILE,
    StatusRefused,
    projects_directory,
    read_statuses,
    status_document,
    write_status,
)

WORLD = "world:synthetic"


def status(world_id=WORLD, written_at="2026-10-15T01:00:00Z", **changes):
    return {
        "profile": "exulanica.world-project-status/v1",
        "world_id": world_id,
        "version_id": "version-fixture",
        "written_at": written_at,
        "checkpoints": 3,
        "last_checkpoint_at": "2026-10-15T00:50:00Z",
        "pending": False,
        "link": {"repository": "learner/world", "publish": "by hand"},
        "github": {
            "read_at": "2026-10-15T00:51:00Z",
            "visibility": "PRIVATE",
            "not_sent": 1,
            "pull_request": {"number": 3, "title": "Changes to Terraces on the bay"},
            "paused": None,
            "reached": True,
        },
        **changes,
    }


def folder(directory, name, document=None):
    path = directory / name
    path.mkdir(parents=True)
    if document is not None:
        write_status(path, document)
    return path


def test_the_state_is_closed_and_holds_no_path_or_credential():
    assert status_document(status())["github"]["not_sent"] == 1
    for broken in (
        {**status(), "folder": "/Users/someone/projects/world"},
        {
            **status(),
            "link": {"repository": "https://x:token@github.com/a/b", "publish": "by hand"},
        },
        {**status(), "checkpoints": -1},
        {**status(), "written_at": "yesterday"},
    ):
        with pytest.raises(StatusRefused):
            status_document(broken)


def test_only_the_configured_directory_s_own_folders_are_read(tmp_path):
    projects = tmp_path / "projects"
    folder(projects, "older", status(written_at="2026-10-15T00:00:00Z"))
    folder(projects, "newer", status(written_at="2026-10-15T02:00:00Z"))
    folder(projects, "another-world", status(world_id="world:another"))
    folder(projects, ".hidden", status())
    folder(projects, "empty")
    broken = folder(projects, "broken")
    (broken / STATUS_FILE).write_text("{not json", encoding="utf-8")
    large = folder(projects, "large")
    (large / STATUS_FILE).write_bytes(b" " * (MAX_STATUS_BYTES + 1))
    # A link, as a folder or as the file, is never followed.
    elsewhere = folder(tmp_path / "elsewhere", "kept", status())
    os.symlink(elsewhere, projects / "linked-folder")
    linked = folder(projects, "linked-file")
    os.symlink(elsewhere / STATUS_FILE, linked / STATUS_FILE)
    found = read_statuses(projects, WORLD)
    assert [s["written_at"] for s in found] == ["2026-10-15T02:00:00Z", "2026-10-15T00:00:00Z"]
    assert read_statuses(None, WORLD) == [] and read_statuses(tmp_path / "absent", WORLD) == []


def test_a_crafted_world_id_never_reaches_outside_the_configured_directory(tmp_path):
    # Fail first: a reader that joined the asked world id to the directory would read this file.
    projects = tmp_path / "projects"
    projects.mkdir()
    outside = folder(tmp_path, "outside", status(world_id="../outside"))
    assert (outside / STATUS_FILE).is_file()
    for crafted in ("../outside", "../outside/", "/" + str(outside).lstrip("/"), "..", "."):
        assert read_statuses(projects, crafted) == []


def test_the_directory_is_the_one_the_instance_is_configured_with(tmp_path):
    assert projects_directory({}) is None
    assert projects_directory({"EXULANICA_PROJECTS_DIRECTORY": str(tmp_path)}) == tmp_path


@pytest.fixture
def written(tmp_path):
    path = folder(tmp_path, "project")
    write_status(path, status())
    return path


def test_writing_replaces_the_whole_file_and_leaves_no_partial_one(written):
    write_status(written, status(written_at="2026-10-15T03:00:00Z"))
    assert json.loads((written / STATUS_FILE).read_text())["written_at"] == "2026-10-15T03:00:00Z"
    assert sorted(p.name for p in written.iterdir()) == [STATUS_FILE]
    with pytest.raises(StatusRefused):
        write_status(written, {**status(), "pending": "no"})
    assert json.loads((written / STATUS_FILE).read_text())["written_at"] == "2026-10-15T03:00:00Z"
