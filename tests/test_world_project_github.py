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
