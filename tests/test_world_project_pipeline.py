"""The whole project pipeline offline: a fake World API, a fake GitHub, synthetic content only.

Two runs of a world are recorded into one project as two sessions; a private repository is
created through its review, the project is linked to it, and the saved checkpoints are published
as one rolling pull request, each checkpoint its own commit.
"""

import json
from copy import deepcopy

import pytest
from exulanica.world_package.projects import github
from exulanica.world_package.projects.__main__ import main
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError
from exulanica.world_package.projects.repository import Project

from test_world_project_capture import TOKEN, VERSION, WORLD, event, record, world  # noqa: F401
from test_world_project_github import Repository

WHO = ["--author-name", "Synthetic Student", "--author-email", "student@example.invalid"]


class Account(Repository):
    """The fake repository, plus the signed-in account that may or may not hold it yet."""

    def __init__(self):
        super().__init__()
        self.exists = False
        self.rest_calls = []

    def request(self, query, variables, **_):
        if "viewer { login repository" in query:
            return {
                "viewer": {
                    "login": "learner",
                    "repository": {"nameWithOwner": "learner/world"} if self.exists else None,
                }
            }
        return super().request(query, variables)

    def rest(self, method, path, body):
        self.rest_calls.append((method, path, body))
        self.exists = True
        return {"full_name": f"learner/{body['name']}", "private": True, "default_branch": "main"}


def run(arguments, capsys):
    code = main(arguments)
    out = capsys.readouterr().out
    return code, json.loads(out)


def record_run(world, tmp_path, folder, session, capsys, *extra):  # noqa: F811
    token = tmp_path / "token"
    token.write_text(TOKEN, encoding="utf-8")
    arguments = ["record-world", str(folder), "--api", world.url, "--token-file", str(token)]
    arguments += ["--world", WORLD, "--version", VERSION, "--thing", "knight:1"]
    arguments += ["--session", session, *extra, *WHO]
    return run(arguments, capsys)


def test_two_runs_a_new_private_repository_a_link_and_one_rolling_pull_request(
    world,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    account = Account()
    monkeypatch.setattr(github, "gh_graphql", account.request)
    monkeypatch.setattr(github, "gh_rest", account.rest)
    folder = tmp_path / "knight-project"

    # Run 1 creates the project; its decisions become session run-1's evidence.
    code, first = record_run(
        world, tmp_path, folder, "session:run-1", capsys, "--project-id", "project:knight"
    )
    assert code == 0 and first["committed"]
    assert first["evidence"] == ["Recorded 3 decisions"]

    # Run 2: the knight was moved and decided once more.
    view = world.routes[f"/world/versions/{VERSION}"]
    view["things"][0]["transform"]["x_mm"] = 2000
    world.records["r5"] = record("r5", world.knight, 9, "bench, 3 m away")
    world.routes[("events", None)]["events"].insert(
        0, event("r5", world.knight, 9, "applied", seq=5)
    )
    code, second = record_run(world, tmp_path, folder, "session:run-2", capsys)
    assert code == 0
    assert second["summary"] == ["Moved the knight 2 m east"]
    # The new session keeps only what run 1 did not already record; run 1's file is untouched.
    assert second["evidence"] == ["Recorded 1 decision"]

    # A third run from the same start reuses a request identity for a different decision: kept.
    world.records["r5"] = record("r5", world.knight, 9, "wait here a minute")
    world.records["r5"]["decision"]["document_sha256"] = "9" * 64
    code, third = record_run(world, tmp_path, folder, "session:run-3", capsys)
    assert third["evidence"] == ["Recorded 1 decision"]

    # Recording the same run again changes nothing.
    code, again = record_run(world, tmp_path, folder, "session:run-3", capsys)
    assert again["committed"] is False

    # Creating the repository: review, then refusal without authorization, then creation.
    code, review = run(["review-repository", "world", "--description", "A world project"], capsys)
    assert review["repository"] == "learner/world" and review["visibility"] == "private"
    assert account.rest_calls == []
    code, refused = run(
        ["create-repository", "world", "--review-sha256", review["review_sha256"]], capsys
    )
    assert code == 1 and "authorization" in refused["error"] and account.rest_calls == []
    code, made = run(
        [
            "create-repository",
            "world",
            "--description",
            "A world project",
            "--review-sha256",
            review["review_sha256"],
            "--allow-publication",
        ],
        capsys,
    )
    assert made["created"] and made["private"]
    assert account.rest_calls == [
        (
            "POST",
            "/user/repos",
            {"name": "world", "description": "A world project", "private": True, "auto_init": True},
        )
    ]
    code, refused = run(["review-repository", "world"], capsys)
    assert code == 1 and "link the project" in refused["error"]

    # Link, then publish from the link alone.
    code, linked = run(
        [
            "link",
            str(folder),
            "--repository",
            "learner/world",
            "--base",
            "main",
            "--branch",
            "exulanica/knight",
            *WHO,
        ],
        capsys,
    )
    assert linked["message"] == "Link project to learner/world (base main, branch exulanica/knight)"
    assert Project(folder).timeline()["link"]["branch"] == "exulanica/knight"
    code, refused = run(["review-branch", str(folder), "--branch", "elsewhere"], capsys)
    assert code == 1 and "differs from the project's link" in refused["error"]
    code, branch_review = run(["review-branch", str(folder)], capsys)
    assert [c["message"] for c in branch_review["commits"]] == [
        "Started the project",
        "Moved the knight 2 m east, recorded 1 decision",
        "Recorded 1 decision",
    ]
    assert account.writes == []
    code, published = run(
        [
            "publish-branch",
            str(folder),
            "--review-sha256",
            branch_review["review_sha256"],
            "--allow-publication",
        ],
        capsys,
    )
    assert published["actions"] == [
        "create-branch",
        "commit",
        "commit",
        "commit",
        "open-pull-request",
    ]
    files = account.branches["exulanica/knight"]["files"]
    assert sorted(files) == [
        "README.md",
        "evidence/session-run-1.json",
        "evidence/session-run-2.json",
        "evidence/session-run-3.json",
        "world-project.json",
    ]
    assert "project-link.json" not in files
    [pull] = account.pulls
    # Each recorded file has its own part, in plain words; none is named by its identity.
    assert pull["body"].count("### Decisions, minutes ") == 3
    assert "- The knight, with synthetic-model: 3 decisions" in pull["body"]
    assert "run-1" not in pull["body"].split("<!--")[0]


def test_a_long_login_and_name_link_in_a_commit_within_the_message_rule(
    world,  # noqa: F811
    tmp_path,
    capsys,
):
    # GitHub's longest login (39) and repository name (100): the full link line would pass 120
    # characters, so its commit says less and the committed project-link.json holds the rest.
    folder = tmp_path / "long-project"
    code, first = record_run(
        world, tmp_path, folder, "session:run-1", capsys, "--project-id", "project:knight"
    )
    assert code == 0 and first["committed"]
    repository = "o" * 39 + "/" + "n" * 100
    project = Project(folder)
    linked = project.link(repository, "main", "exulanica/world", "automatic")
    assert linked["committed"] and len(linked["message"]) <= 120
    assert linked["message"] == "Link project to its repository"
    assert project.git("status", "--porcelain") == ""
    assert project.timeline()["link"]["repository"] == repository


def test_the_link_is_closed_and_holds_no_credentials(tmp_path):
    from exulanica.world_package.projects.link import link_document, make_link, resolve

    with pytest.raises(ProjectError):
        make_link("https://user:pass@github.com/learner/world", "main", "x")
    with pytest.raises(ProjectError):
        make_link("learner/world", "main", "main")
    with pytest.raises(ProjectError):
        link_document({**make_link("learner/world", "main", "x"), "token": "secret"})
    with pytest.raises(ProjectError):
        make_link("learner/world", "main", "x", "whenever")
    # Publishing by hand writes no publish field, so a link written before it keeps its bytes.
    assert make_link("learner/world", "main", "x") == {
        "profile": "exulanica.world-project-link/v1",
        "repository": "learner/world",
        "base": "main",
        "branch": "x",
    }
    assert make_link("learner/world", "main", "x", "automatic")["publish"] == "automatic"
    with pytest.raises(ProjectError, match="no link"):
        resolve(tmp_path, "learner/world", None, None)
    assert resolve(tmp_path, "learner/world", "main", "x")["branch"] == "x"


def test_creation_refuses_an_unconfirmed_reply_and_a_bad_name():
    account = Account()
    creation = github.RepositoryCreation(account.request, lambda *_: {"full_name": "learner/world"})
    review = creation.review("world")
    with pytest.raises(ProjectError, match="did not confirm"):
        creation.create("world", reviewed_sha256=review["review_sha256"], allow_publication=True)
    for name in ("", "..", "a/b", "x" * 101):
        with pytest.raises(ProjectError):
            creation.review(name)
    account.exists = True
    with pytest.raises(Conflict):
        github.RepositoryCreation(account.request, account.rest).review("world")
    assert deepcopy(account.rest_calls) == []
