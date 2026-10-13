"""GitHub boundary tests with a synthetic server; no account or repository is contacted."""

import base64
import json
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, document, pretty
from exulanica.world_package.projects.github import GitHubProjects, Target, gh_graphql

from test_world_project import sample

TARGET = Target("learner/world", "main")


class Server:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint
        self.head = "a" * 40
        self.owner = "learner"
        self.writes = []
        self.move_during_write = False

    def request(self, query, variables):
        if query.startswith("query"):
            assert variables == {"owner": "learner", "name": "world", "ref": "refs/heads/main"}
            return {
                "viewer": {"login": "learner"},
                "repository": {
                    "nameWithOwner": "learner/world",
                    "owner": {"login": self.owner},
                    "viewerPermission": "ADMIN",
                    "isArchived": False,
                    "isDisabled": False,
                    "ref": {
                        "target": {
                            "oid": self.head,
                            "file": None
                            if self.checkpoint is None
                            else {
                                "mode": 0o100644,
                                "object": {
                                    "text": pretty(self.checkpoint).decode(),
                                    "byteSize": len(pretty(self.checkpoint)),
                                    "isTruncated": False,
                                },
                            },
                        }
                    },
                },
            }
        values = variables["input"]
        if self.move_during_write:
            self.head = "c" * 40
        if self.head != values["expectedHeadOid"]:
            raise Conflict("server atomically refused stale head")
        self.writes.append(deepcopy(values))
        [entry] = values["fileChanges"]["additions"]
        assert entry["path"] == "world-project.json"
        self.checkpoint = json.loads(base64.b64decode(entry["contents"]))
        self.head = "b" * 40
        return {"createCommitOnBranch": {"commit": {"oid": self.head}}}


def test_first_publication_reopen_edit_review_update_and_noop():
    project, _ = sample()
    server = Server()
    client = GitHubProjects(server.request)
    review = client.review(TARGET, project, "Add synthetic world checkpoint")
    assert not server.writes
    assert '"thing_id": "knight:1"' in review["diff"]
    with pytest.raises(ProjectError, match="authorization"):
        client.publish(
            TARGET,
            project,
            "Add synthetic world checkpoint",
            reviewed_sha256=review["review_sha256"],
        )
    result = client.publish(
        TARGET,
        project,
        "Add synthetic world checkpoint",
        reviewed_sha256=review["review_sha256"],
        allow_publication=True,
    )
    assert result["published"]
    assert result["diff_url"].endswith(f"{'a' * 40}...{'b' * 40}")
    assert client.read(TARGET).checkpoint == document(project)
    edited = deepcopy(project)
    edited["things"][0]["transform"]["x_mm"] = 500
    review = client.review(TARGET, edited, "Move the knight")
    assert '-        "x_mm": 0' in review["diff"]
    client.publish(
        TARGET,
        edited,
        "Move the knight",
        reviewed_sha256=review["review_sha256"],
        allow_publication=True,
    )
    assert len(server.writes) == 2
    assert server.writes[-1]["expectedHeadOid"] == "b" * 40
    assert server.writes[-1]["message"] == {"headline": "Move the knight"}
    review = client.review(TARGET, edited, "Move the knight")
    result = client.publish(
        TARGET,
        edited,
        "Move the knight",
        reviewed_sha256=review["review_sha256"],
        allow_publication=True,
    )
    assert not result["published"]
    assert len(server.writes) == 2


@pytest.mark.parametrize("change", ["head", "content", "message", "race"])
def test_review_binding_and_atomic_head_race(change):
    project, _ = sample()
    server = Server()
    client = GitHubProjects(server.request)
    review = client.review(TARGET, project, "Save world")
    message = "Save world"
    if change == "head":
        server.head = "d" * 40
    elif change == "content":
        project["things"][0]["transform"]["x_mm"] = 1000
    elif change == "message":
        message = "Different subject"
    else:
        server.move_during_write = True
    with pytest.raises(Conflict):
        client.publish(
            TARGET,
            project,
            message,
            reviewed_sha256=review["review_sha256"],
            allow_publication=True,
        )
    assert not server.writes


def test_other_owner_other_project_and_unsafe_remote_file_refused():
    project, _ = sample()
    server = Server(project)
    client = GitHubProjects(server.request)
    server.owner = "another-person"
    with pytest.raises(ProjectError, match="owned"):
        client.review(TARGET, project, "Save world")
    server.owner = "learner"
    candidate = deepcopy(project)
    candidate["project_id"] = "project:different"
    with pytest.raises(Conflict, match="another project"):
        client.review(TARGET, candidate, "Save world")

    def symlink(query, variables):
        result = server.request(query, variables)
        result["repository"]["ref"]["target"]["file"]["mode"] = 0o120000
        return result

    with pytest.raises(ProjectError, match="regular text"):
        GitHubProjects(symlink).read(TARGET)
    assert not server.writes


@pytest.mark.parametrize(
    "repo,branch",
    [
        ("https://github.com/learner/world", "main"),
        ("learner/world", "../main"),
        ("learner/world", "main..next"),
        ("learner/world", "refs/heads/main"),
        ("learner/world", "main.lock"),
        ("learner/world", "-unsafe"),
    ],
)
def test_explicit_destination_validation(repo, branch):
    with pytest.raises(ProjectError):
        Target(repo, branch)


def test_gh_uses_structured_input_pinned_host_timeout_and_redacted_failure(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_DEBUG", "api")
    monkeypatch.setenv("GH_HOST", "unexpected.invalid")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"ok": True}}))

    monkeypatch.setattr(subprocess, "run", run)
    assert gh_graphql("query{}", {"name": "literal $(no shell)"}) == {"ok": True}
    command, kwargs = calls[0]
    assert command == ["gh", "api", "graphql", "--hostname", "github.com", "--input", "-"]
    assert kwargs["timeout"] == 45
    assert "GH_DEBUG" not in kwargs["env"]
    assert "GH_HOST" not in kwargs["env"]
    assert json.loads(kwargs["input"])["variables"]["name"] == "literal $(no shell)"

    def fail(command, **kwargs):
        return SimpleNamespace(returncode=1, stderr="PRIVATE-SECRET", stdout="PRIVATE-SECRET")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ProjectError) as error:
        gh_graphql("mutation{}", {})
    assert "PRIVATE-SECRET" not in str(error.value)


def test_unknown_outcome_never_retries(monkeypatch):
    calls = []

    def timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="PRIVATE-SECRET")

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ProjectError, match="may have succeeded"):
        gh_graphql("mutation{}", {})
    assert len(calls) == 1


# -- rolling pull request ------------------------------------------------------------------


class Repository:
    """A fake personal repository with branches of files and pull requests."""

    def __init__(self):
        self.count = 0
        self.branches = {"main": {"oid": self.oid(), "files": {"README.md": b"hello"}}}
        self.pulls = []
        self.writes = []
        self.owner = "learner"
        self.move = None

    def oid(self):
        self.count += 1
        return f"{self.count:040x}"

    @staticmethod
    def blob(data):
        text = data.decode()
        return {
            "mode": 0o100644,
            "object": {"text": text, "byteSize": len(data), "isTruncated": False},
        }

    def ref(self, name):
        branch = self.branches.get(name.removeprefix("refs/heads/"))
        if branch is None:
            return None
        files = branch["files"]
        evidence = sorted(p for p in files if p.startswith("evidence/"))
        return {
            "target": {
                "oid": branch["oid"],
                "file": self.blob(files["world-project.json"])
                if "world-project.json" in files
                else None,
                "evidence": {
                    "mode": 0o040000,
                    "object": {
                        "entries": [
                            {"name": p.removeprefix("evidence/"), **self.blob(files[p])}
                            for p in evidence
                        ]
                    },
                }
                if evidence
                else None,
            }
        }

    def request(self, query, variables):
        if query.startswith("query"):
            if self.move:
                self.move()
                self.move = None
            return {
                "viewer": {"login": "learner"},
                "repository": {
                    "id": "R_1",
                    "nameWithOwner": "learner/world",
                    "owner": {"login": self.owner},
                    "viewerPermission": "ADMIN",
                    "isArchived": False,
                    "isDisabled": False,
                    "base": self.ref(variables["base"]),
                    "head": self.ref(variables["head"]),
                    "pullRequests": {
                        "nodes": [
                            pr
                            for pr in self.pulls
                            if pr["open"] and pr["headRefName"] == variables["branch"]
                        ]
                    },
                },
            }
        values = variables["input"]
        self.writes.append(query.split("(")[0].split()[-1] if "mutation" in query else query)
        if "createRef" in query:
            name = values["name"].removeprefix("refs/heads/")
            source = next(b for b in self.branches.values() if b["oid"] == values["oid"])
            self.branches[name] = {"oid": values["oid"], "files": dict(source["files"])}
            return {"createRef": {"ref": {"name": name}}}
        if "createCommitOnBranch" in query:
            branch = self.branches[values["branch"]["refName"]]
            if branch["oid"] != values["expectedHeadOid"]:
                raise Conflict("server atomically refused stale head")
            for entry in values["fileChanges"]["additions"]:
                branch["files"][entry["path"]] = base64.b64decode(entry["contents"])
            branch["oid"] = self.oid()
            return {"createCommitOnBranch": {"commit": {"oid": branch["oid"]}}}
        if "createPullRequest" in query:
            pr = {
                "id": f"PR_{len(self.pulls) + 1}",
                "number": len(self.pulls) + 1,
                "url": "https://example.invalid/pr",
                "baseRefName": values["baseRefName"],
                "headRefName": values["headRefName"],
                "title": values["title"],
                "body": values["body"],
                "open": True,
            }
            self.pulls.append(pr)
            return {"createPullRequest": {"pullRequest": {"number": pr["number"]}}}
        pr = next(p for p in self.pulls if p["id"] == values["pullRequestId"])
        if "updatePullRequest" in query:
            pr.update(title=values["title"], body=values["body"])
            return {"updatePullRequest": {"pullRequest": {"number": pr["number"]}}}
        pr["open"] = False
        return {"closePullRequest": {"pullRequest": {"number": pr["number"]}}}


def local_project(tmp_path):
    from exulanica.world_package.projects.repository import Author, Project, create

    from test_world_project_repository import evidence_from

    project, _ = sample()
    world, evidence = evidence_from(project)
    folder = tmp_path / "project"
    author = Author("Synthetic Student", "student@example.invalid")
    create(folder, world, author=author, evidence=[evidence])
    return Project(folder, author=author), world, evidence


def publish(client, target, local, message):
    review = client.review(target, local, message)
    return review, client.publish(
        target, local, message, reviewed_sha256=review["review_sha256"], allow_publication=True
    )


def test_one_rolling_pull_request_collects_saved_checkpoints(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    remote = Repository()
    client = RollingPullRequests(remote.request)
    local, world, _ = local_project(tmp_path)
    review = client.review(target, local, "Start the world project")
    assert review["actions"] == ["create-branch", "commit", "open-pull-request"]
    assert remote.writes == []
    with pytest.raises(ProjectError, match="authorization"):
        client.publish(target, local, "Start the world project", reviewed_sha256="0" * 64)
    _, result = publish(client, target, local, "Start the world project")
    assert result["actions"] == ["create-branch", "commit", "open-pull-request"]
    files = remote.branches["exulanica/world"]["files"]
    assert sorted(files) == ["README.md", "evidence/session-one.json", "world-project.json"]
    assert remote.branches["main"]["files"] == {"README.md": b"hello"}
    [pr] = remote.pulls
    assert "not part of the world" in pr["body"]
    assert "recorded 1 decision record from session session:one" in pr["body"]
    assert "Co-authored" not in pr["body"] and "Generated" not in pr["body"]

    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    local.save(moved)
    review, result = publish(client, target, local, "Move the knight")
    # The commit carries its own sentence; the request's text against main is unchanged.
    assert result["actions"] == ["commit"]
    assert list(review["files"]) == ["world-project.json"]
    assert len(remote.pulls) == 1 and "moved the knight 2 m east" not in pr["body"]
    assert "- started project" in pr["body"]  # Against the base branch, which has no project.

    # Nothing new saved: no write at all.
    review = client.review(target, local, "Move the knight")
    assert review["actions"] == []
    writes = list(remote.writes)
    assert client.publish(
        target,
        local,
        "Move the knight",
        reviewed_sha256=review["review_sha256"],
        allow_publication=True,
    ) == {**result, "published": False, "actions": []}
    assert remote.writes == writes


def test_a_pull_request_whose_changes_cancel_out_is_closed(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    remote = Repository()
    client = RollingPullRequests(remote.request)
    local, world, _ = local_project(tmp_path)
    publish(client, target, local, "Start the world project")
    # The owner merged it; main now holds the project.
    remote.branches["main"]["files"] = dict(remote.branches["exulanica/world"]["files"])
    remote.pulls[0]["open"] = False
    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    local.save(moved)
    _, result = publish(client, target, local, "Move the knight")
    assert result["actions"] == ["commit", "open-pull-request"]
    assert "- moved the knight 2 m east" in remote.pulls[1]["body"]
    local.save(world)  # Moved back: nothing differs from main any more.
    review, result = publish(client, target, local, "Move the knight back")
    assert review["actions"] == ["close-pull-request"]
    assert remote.pulls[1]["open"] is False


def test_rolling_publication_refuses_races_foreign_content_and_shared_repositories(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    remote = Repository()
    client = RollingPullRequests(remote.request)
    local, world, _ = local_project(tmp_path)
    publish(client, target, local, "Start the world project")
    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    local.save(moved)
    review = client.review(target, local, "Move the knight")

    def someone_pushes():
        remote.branches["exulanica/world"]["oid"] = remote.oid()

    remote.move = someone_pushes
    with pytest.raises(Conflict, match="review again"):
        client.publish(
            target,
            local,
            "Move the knight",
            reviewed_sha256=review["review_sha256"],
            allow_publication=True,
        )
    remote.branches["exulanica/world"]["files"]["evidence/other.json"] = remote.branches[
        "exulanica/world"
    ]["files"]["evidence/session-one.json"]
    with pytest.raises(Conflict):  # Remote evidence the local project does not hold.
        client.review(target, local, "Move the knight")
    del remote.branches["exulanica/world"]["files"]["evidence/other.json"]
    remote.owner = "an-organization"
    with pytest.raises(ProjectError, match="owned by the CLI user"):
        client.review(target, local, "Move the knight")
    with pytest.raises(ProjectError):
        BranchTarget("learner/world", "main", "main")
    with pytest.raises(ProjectError):
        client.review(target, local, "Move the knight \u2014 east")


def test_publish_branch_command_needs_explicit_authorization_before_any_request(
    tmp_path, monkeypatch, capsys
):
    from exulanica.world_package.projects.__main__ import main

    local, _, _ = local_project(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("GitHub must not be contacted")

    monkeypatch.setattr(subprocess, "run", no_network)
    arguments = [
        "publish-branch",
        str(local.folder),
        "--repository",
        "learner/world",
        "--base",
        "main",
        "--branch",
        "exulanica/world",
        "--message",
        "Start the world project",
        "--review-sha256",
        "0" * 64,
    ]
    assert main(arguments) == 1
    assert "authorization" in capsys.readouterr().out
