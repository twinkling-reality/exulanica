"""Automatic publication: a followed project's rolling pull request follows it where its owner
linked it so, to a private repository only, at most so many times a day, pausing on any doubt.

Strict fake GitHub servers and synthetic projects only; nothing is published anywhere.
"""

import json
from copy import deepcopy

import pytest
from exulanica.world_package.projects import github
from exulanica.world_package.projects.__main__ import main
from exulanica.world_package.projects.link import read_link
from exulanica.world_package.projects.publish import (
    DAY_SECONDS,
    PUBLISH_FILE,
    publish_automatically,
    read_state,
    resume,
)

from test_world_project_github import Repository, local_project

NOW = 1_760_400_000.0  # 2025-10-14T00:00:00Z, a fixed clock


def linked(tmp_path, publish="automatic"):
    local, world, _ = local_project(tmp_path)
    local.link("learner/world", "main", "exulanica/world", publish)
    return local, world


def moved(local, world, x_mm):
    changed = deepcopy(world)
    changed["things"][0]["transform"]["x_mm"] = x_mm
    local.save(changed)
    return changed


def automatic(local, remote, now=NOW, per_day=24):
    return publish_automatically(
        local, read_link(local.folder), request=remote.request, now=now, per_day=per_day
    )


class Counting(Repository):
    """The fake repository, counting every request it answers."""

    def __init__(self):
        super().__init__()
        self.requests = 0

    def request(self, query, variables):
        self.requests += 1
        return super().request(query, variables)


def test_a_project_linked_by_hand_is_never_published_on_its_own(tmp_path):
    local, _ = linked(tmp_path, publish=None)
    remote = Counting()
    assert automatic(local, remote) is None
    assert remote.requests == 0 and remote.writes == []
    assert "publish" not in read_link(local.folder)


def test_a_linked_project_is_published_and_then_only_when_it_changes(tmp_path):
    local, world = linked(tmp_path)
    remote = Counting()
    said = automatic(local, remote)
    assert said == {
        "state": "published",
        "actions": ["create-branch", "commit", "open-pull-request"],
    }
    [pull] = remote.pulls
    assert pull["title"] == "Changes to this world" and pull["open"]
    assert read_state(local.folder)["attempts"] == ["2025-10-14T00:00:00Z"]
    # Nothing new: a review, no write, no attempt.
    writes = len(remote.writes)
    assert automatic(local, remote, now=NOW + 60) is None
    assert len(remote.writes) == writes
    assert len(read_state(local.folder)["attempts"]) == 1
    moved(local, world, 2000)
    assert automatic(local, remote, now=NOW + 120)["state"] == "published"
    held = json.loads(remote.branches["exulanica/world"]["files"]["world-project.json"])
    assert held["things"][0]["transform"]["x_mm"] == 2000
    # The state is never committed and never published.
    assert PUBLISH_FILE not in local.git("ls-files")
    assert all(PUBLISH_FILE not in branch["files"] for branch in remote.branches.values())


def test_a_repository_made_public_after_linking_is_never_published_to(tmp_path):
    # Fail first: a follower that trusted the visibility it read when linking would publish here.
    local, world = linked(tmp_path)
    remote = Counting()
    remote.visibility = "PUBLIC"
    said = automatic(local, remote)
    assert said["state"] == "paused"
    assert "no longer private" in said["error"]
    assert remote.writes == []
    assert read_state(local.folder)["paused"]["reason"] == said["error"]
    # Paused: not even read again, whatever the repository says now.
    remote.visibility = "PRIVATE"
    moved(local, world, 2000)
    requests = remote.requests
    assert automatic(local, remote, now=NOW + 60)["state"] == "paused"
    assert remote.requests == requests and remote.writes == []


class Failing(Counting):
    """A repository whose first commit write fails after it was sent: its outcome is unknown."""

    def __init__(self, error):
        super().__init__()
        self.error = error

    def request(self, query, variables):
        if "createCommitOnBranch" in query and self.error is not None:
            error, self.error = self.error, None
            self.requests += 1
            raise error
        return super().request(query, variables)


@pytest.mark.parametrize("error", [ValueError("connection reset"), RuntimeError("socket closed")])
def test_an_unknown_outcome_pauses_and_is_never_retried(tmp_path, error):
    # Fail first: a follower that retried here would send the commit a second time.
    local, world = linked(tmp_path)
    remote = Failing(error)
    said = automatic(local, remote)
    assert said["state"] == "paused"
    assert "unknown" in said["error"]
    assert "createCommitOnBranch" not in remote.writes  # the failed one is not on record
    requests = remote.requests
    for step in range(1, 4):
        moved(local, world, 1000 * step)
        assert automatic(local, remote, now=NOW + 60 * step)["state"] == "paused"
    assert remote.requests == requests
    # A person looks, publishes by hand, and that lifts the pause.
    assert resume(local.folder) is True
    assert resume(local.folder) is False
    assert automatic(local, remote, now=NOW + 600)["state"] == "published"


def test_a_day_holds_at_most_its_number_of_attempts_across_a_restart(tmp_path):
    local, world = linked(tmp_path)
    remote = Counting()
    for step in range(2):
        moved(local, world, 1000 * (step + 1))
        assert automatic(local, remote, now=NOW + step, per_day=2)["state"] == "published"
    moved(local, world, 5000)
    held = automatic(local, remote, now=NOW + 10, per_day=2)
    assert held == {"state": "held", "error": "at most 2 automatic publications a day"}
    # The attempts are kept in the folder, so a new follower process holds the same bound.
    assert len(json.loads((local.folder / PUBLISH_FILE).read_text())["attempts"]) == 2
    assert automatic(local, remote, now=NOW + 20, per_day=2)["state"] == "held"
    assert automatic(local, remote, now=NOW + DAY_SECONDS, per_day=2)["state"] == "published"
    # Only the attempts of the last day are kept: the first has aged out.
    assert read_state(local.folder)["attempts"] == ["2025-10-14T00:00:01Z", "2025-10-15T00:00:00Z"]


def test_written_words_pause_automatic_publication_to_any_repository_not_private(tmp_path):
    from test_world_project_insight import session

    local, _ = linked(tmp_path)
    world, evidence = session(count=2, readable=True)
    local.save(world, evidence=[{**evidence, "session_id": "session:labelled"}])
    remote = Counting()
    remote.visibility = "INTERNAL"
    said = automatic(local, remote)
    assert said["state"] == "paused" and "written words" in said["error"]
    assert remote.writes == []


def run(argv, capsys):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_linking_to_publish_on_its_own_needs_a_private_repository(tmp_path, monkeypatch, capsys):
    local, _, _ = local_project(tmp_path)
    remote = Counting()
    monkeypatch.setattr(github, "gh_graphql", remote.request)
    link = [
        "link",
        str(local.folder),
        "--repository",
        "learner/world",
        "--base",
        "main",
        "--branch",
        "exulanica/world",
    ]
    remote.visibility = "PUBLIC"
    code, said = run([*link, "--publish", "automatic"], capsys)
    assert code == 1 and "private repository" in said["error"]
    assert read_link(local.folder) is None
    remote.visibility = "PRIVATE"
    code, said = run([*link, "--publish", "automatic"], capsys)
    assert code == 0 and read_link(local.folder)["publish"] == "automatic"
    assert said["message"].endswith(", published automatically")
    code, _ = run(link, capsys)  # by hand again: the link holds no publish field
    assert code == 0 and "publish" not in read_link(local.folder)
    assert remote.writes == []


def test_a_person_s_own_publication_lifts_a_pause(tmp_path, monkeypatch, capsys):
    local, _ = linked(tmp_path)
    remote = Counting()
    remote.visibility = "PUBLIC"
    assert automatic(local, remote)["state"] == "paused"
    remote.visibility = "PRIVATE"
    monkeypatch.setattr(github, "gh_graphql", remote.request)
    code, review = run(["review-branch", str(local.folder)], capsys)
    assert code == 0
    code, published = run(
        [
            "publish-branch",
            str(local.folder),
            "--review-sha256",
            review["review_sha256"],
            "--allow-publication",
        ],
        capsys,
    )
    assert code == 0 and published["published"]
    assert published["automatic_publication_resumed"] is True
    assert read_state(local.folder)["paused"] is None
