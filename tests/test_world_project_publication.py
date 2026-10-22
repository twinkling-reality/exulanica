"""Putting a kept project on the person's own GitHub from a request: the follower reviews with the
person's GitHub CLI and creates nothing until the person said yes to that review, then creates a
private repository, links the project and publishes it. A fake World API and a fake GitHub only;
nothing reaches GitHub, and the GitHub CLI itself is a stand-in script.
"""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime

import pytest
from exulanica.world.project_requests import (
    confirm_publication,
    read_publications,
    request_publication,
    start_publication,
)
from exulanica.world.project_status import STATUS_FILE
from exulanica.world_package.projects import publication
from exulanica.world_package.projects.checkpoint import Conflict
from exulanica.world_package.projects.follow import Follower, read_follow
from exulanica.world_package.projects.link import read_link
from exulanica.world_package.projects.repository import Project

from test_world_project_capture import TOKEN, VERSION, WORLD
from test_world_project_follow import WORKSPACE, Clock, follow, token, world  # noqa: F401
from test_world_project_pipeline import Account

PROJECT = "project:demo"
NOW = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)


class Person(Account):
    """The person's GitHub as their CLI sees it: an account, the repository it may make, and
    whether the CLI is there and signed in."""

    def __init__(self):
        super().__init__()
        self.login = "learner"
        self.state: str | None = None

    def request(self, query, variables, **_):
        answer = super().request(query, variables)
        if "viewer { login repository" in query:
            answer["viewer"]["login"] = self.login
        return answer

    def ready(self):
        return self.state


@pytest.fixture
def kept(world, token, tmp_path):  # noqa: F811
    """A project the follower follows, as a request to keep the world would have started it."""
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo", "--no-sessions")
    person = Person()
    follower = Follower(
        projects,
        base_url=world.url,
        token=TOKEN,
        clock=Clock(),
        github=person.request,
        github_rest=person.rest,
        github_ready=person.ready,
    )
    assert {"project": "demo", "state": "following"} in follower.scan()
    yield projects, folder, person, follower
    follower.close()


def ask(projects, name="world", project_id=PROJECT):
    return request_publication(
        projects,
        workspace_id=WORKSPACE,
        world_id=WORLD,
        version_id=VERSION,
        project_id=project_id,
        name=name,
        now=NOW,
    )


def say_yes(projects, request_id):
    [request] = [r for r in read_publications(projects) if r["request_id"] == request_id]
    digest = request["review"]["review_sha256"]
    return confirm_publication(projects, request_id, (WORKSPACE, WORLD), digest, NOW)


def told_about(follower, project="demo"):
    return [t for t in follower.scan() if t["project"] in (project, None)]


def test_a_review_writes_nothing_on_github_and_a_yes_makes_a_linked_private_project(kept):
    projects, folder, person, follower = kept
    request = ask(projects)

    assert told_about(follower) == [{"project": "demo", "state": "reviewed"}]
    [reviewed] = read_publications(projects)
    review = reviewed["review"]
    assert (review["owner"], review["repository"], review["readable"]) == (
        "learner",
        "learner/world",
        False,
    )
    assert review["checkpoints"] == 1 and len(review["review_sha256"]) == 64
    # The follower's own daily bound, which the card states and the yes binds.
    assert review["publications_per_day"] == 24
    # Only reads so far: no repository made, nothing written, and nothing more until a yes.
    assert person.rest_calls == [] and person.writes == []
    assert told_about(follower) == [] and person.rest_calls == []

    say_yes(projects, request["request_id"])
    told = told_about(follower)

    assert told[0] == {"project": "demo", "state": "linked"}
    assert told[1]["state"] == "published"
    assert person.rest_calls == [
        (
            "POST",
            "/user/repos",
            {"name": "world", "description": "", "private": True, "auto_init": True},
        )
    ]
    link = read_link(folder)
    assert (link["repository"], link["base"], link["branch"], link["publish"]) == (
        "learner/world",
        "main",
        publication.BRANCH,
        "automatic",
    )
    [pull] = person.pulls
    assert pull["open"] and pull["headRefName"] == publication.BRANCH
    status = json.loads((folder / STATUS_FILE).read_text())
    assert status["project_id"] == PROJECT
    assert status["link"] == {"repository": "learner/world", "publish": "automatic"}
    assert status["github"]["visibility"] == "PRIVATE" and status["github"]["not_sent"] == 0
    assert read_publications(projects) == []


def refused(projects):
    [request] = read_publications(projects)
    return request["refused"]["code"]


def test_the_yes_binds_the_daily_bound_the_review_states(kept):
    _projects, folder, person, _follower = kept
    settings = read_follow(folder)
    access = publication.Access(person.request, person.rest, person.ready)
    asked = {"name": "world"}
    usual = publication.review(Project(folder), settings, asked, access, NOW)
    fewer = {**settings, "limits": {**(settings.get("limits") or {}), "publications_per_day": 4}}
    rarer = publication.review(Project(folder), fewer, asked, access, NOW)
    assert (usual["publications_per_day"], rarer["publications_per_day"]) == (24, 4)
    assert usual["review_sha256"] != rarer["review_sha256"]


@pytest.mark.parametrize("code", ["gh_missing", "not_signed_in"])
def test_without_the_cli_signed_in_nothing_is_asked_of_github(kept, code):
    projects, _folder, person, follower = kept
    person.state = code
    ask(projects)
    assert told_about(follower) == [{"project": "demo", "state": "refused", "error": code}]
    assert refused(projects) == code and person.rest_calls == [] and person.writes == []


def test_a_name_already_used_is_refused_before_anything_is_made(kept):
    projects, _folder, person, follower = kept
    person.exists = True
    ask(projects)
    told_about(follower)
    assert refused(projects) == "name_taken" and person.rest_calls == []


def test_an_account_changed_since_the_review_makes_nothing(kept):
    projects, folder, person, follower = kept
    request = ask(projects)
    told_about(follower)
    say_yes(projects, request["request_id"])
    person.login = "someone-else"
    assert told_about(follower) == [{"project": "demo", "state": "refused", "error": "changed"}]
    assert person.rest_calls == [] and read_link(folder) is None


def test_a_repository_that_does_not_read_private_is_never_linked(kept):
    projects, folder, person, follower = kept
    request = ask(projects)
    told_about(follower)
    say_yes(projects, request["request_id"])
    person.visibility = "PUBLIC"
    told_about(follower)
    assert refused(projects) == "not_private"
    assert read_link(folder) is None and person.writes == []


def test_files_whose_rights_cannot_be_read_refuse_the_review(kept, monkeypatch):
    projects, _folder, person, follower = kept

    def refuse(files, visibility, kinds):
        raise Conflict("a made thing whose rights cannot be read")

    monkeypatch.setattr(publication, "check_rights", refuse)
    ask(projects)
    told_about(follower)
    assert refused(projects) == "rights_refused" and person.rest_calls == []


def test_a_review_that_raises_names_its_class_in_the_follower_s_event_alone(kept, monkeypatch):
    projects, _folder, person, follower = kept

    def broken(*_args):
        raise RuntimeError("an answer nobody planned for, with a path /tmp/secret in it")

    monkeypatch.setattr(publication, "review", broken)
    ask(projects)
    told = {"project": "demo", "state": "refused", "error": "failed", "exception": "RuntimeError"}
    assert told_about(follower) == [told]
    assert refused(projects) == "failed" and person.rest_calls == []


def test_a_creation_a_stopped_follower_began_is_never_tried_again(kept):
    projects, folder, person, follower = kept
    request = ask(projects)
    told_about(follower)
    say_yes(projects, request["request_id"])
    # A follower marked it started, then stopped before it said how it ended.
    assert start_publication(projects, request["request_id"], NOW) is not None
    assert told_about(follower) == [{"project": None, "state": "refused", "error": "failed"}]
    assert refused(projects) == "failed" and person.rest_calls == [] and read_link(folder) is None


def test_a_world_erased_after_the_yes_gets_no_repository(kept, world):  # noqa: F811
    projects, folder, person, follower = kept
    request = ask(projects)
    told_about(follower)
    say_yes(projects, request["request_id"])
    # Erased between the person's yes and the follower's next scan (AUDIT S1).
    world.refusals[f"/world/versions/{VERSION}"] = (410, {"code": "world_removed"})
    assert told_about(follower) == [{"project": "demo", "state": "gone"}]
    assert read_publications(projects) == [] and read_link(folder) is None
    assert person.rest_calls == [] and person.writes == []


def test_a_request_for_a_project_this_follower_does_not_follow_leaves(kept):
    projects, _folder, person, follower = kept
    ask(projects, project_id="project:another")
    assert told_about(follower) == [{"project": None, "state": "gone"}]
    assert read_publications(projects) == [] and person.rest_calls == []


class Head:
    """A project whose last checkpoint is `checkpoint`."""

    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    def at(self, revision):
        return self.checkpoint


def test_a_proposed_name_holds_the_title_only_where_written_words_are_kept():
    titled = Head({"project_id": PROJECT, "title": "Terraces on the bay, Café 2"})
    assert (
        publication.proposed_name(titled, readable=True) == "exulanica-terraces-on-the-bay-cafe-2"
    )
    plain = publication.proposed_name(titled, readable=False)
    assert plain.startswith("exulanica-world-") and len(plain) == len("exulanica-world-") + 12
    assert "terraces" not in plain
    untitled = Head({"project_id": PROJECT, "title": "東京"})
    assert publication.proposed_name(untitled, readable=True) == plain


def test_the_cli_is_asked_only_whether_it_is_signed_in(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    asked = tmp_path / "asked"
    monkeypatch.setenv("PATH", str(bin_dir))
    assert publication.gh_ready() == "gh_missing"
    cli = bin_dir / "gh"
    for code, expected in ((1, "not_signed_in"), (0, None)):
        cli.write_text(f'#!/bin/sh\necho "$@" > "{asked}"\nexit {code}\n')
        cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
        assert publication.gh_ready() == expected
        assert asked.read_text().split() == ["auth", "status", "--hostname", "github.com"]
