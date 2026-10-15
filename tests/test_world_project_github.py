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
from test_world_project_apply import fields_used

TARGET = Target("learner/world", "main")

#: The mutation input fields this adapter may send, each confirmed against GitHub's GraphQL schema
#: by introspection on 13 October 2026. The fakes refuse any other field, so a misspelled input
#: (the adapter once sent CommittableBranch.refName) fails here instead of on GitHub.
INPUTS = {
    "createCommitOnBranch": "CreateCommitOnBranchInput",
    "createRef": "CreateRefInput",
    "createPullRequest": "CreatePullRequestInput",
    "updatePullRequest": "UpdatePullRequestInput",
    "closePullRequest": "ClosePullRequestInput",
}
FIELDS = {
    "CreateCommitOnBranchInput": {
        "branch": "CommittableBranch",
        "fileChanges": "FileChanges",
        "message": "CommitMessage",
        "expectedHeadOid": None,
    },
    "CommittableBranch": {"id": None, "repositoryNameWithOwner": None, "branchName": None},
    "FileChanges": {"additions": "FileAddition"},
    "FileAddition": {"path": None, "contents": None},
    "CommitMessage": {"headline": None},
    "CreateRefInput": {"repositoryId": None, "name": None, "oid": None},
    "CreatePullRequestInput": {
        "repositoryId": None,
        "baseRefName": None,
        "headRefName": None,
        "title": None,
        "body": None,
    },
    "UpdatePullRequestInput": {"pullRequestId": None, "title": None, "body": None},
    "ClosePullRequestInput": {"pullRequestId": None},
}


def conforms(type_name, value):
    """Refuse any input field the schema type does not declare, at every depth."""
    fields = FIELDS[type_name]
    unknown = set(value) - set(fields)
    assert not unknown, f"{type_name} has no input field {sorted(unknown)}"
    for key, child in value.items():
        nested = fields[key]
        if nested is None:
            continue
        for item in child if isinstance(child, list) else [child]:
            conforms(nested, item)


def mutation(query, variables):
    """The mutation's name, after checking its input against the pinned schema."""
    name = next(n for n in INPUTS if f"{n}(input:" in query)
    assert f"$input:{INPUTS[name]}!" in query
    conforms(INPUTS[name], variables["input"])
    return name


class Server:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint
        self.head = "a" * 40
        self.owner = "learner"
        self.writes = []
        self.move_during_write = False
        #: Repository.visibility, as the rolling branch read's fake states it.
        self.visibility = "PRIVATE"

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
                    "visibility": self.visibility,
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
        assert mutation(query, variables) == "createCommitOnBranch"
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


#: Fields the rolling branch read names. Repository.visibility (PUBLIC, PRIVATE or INTERNAL) and
#: isPrivate were confirmed by introspection on 14 October 2026; the rest were confirmed on 13
#: October or have been read from GitHub by this query.
BRANCH_QUERY_FIELDS = {
    "viewer",
    "login",
    "repository",
    "id",
    "nameWithOwner",
    "viewerPermission",
    "isArchived",
    "isDisabled",
    "isPrivate",
    "visibility",
    "owner",
    "ref",
    "target",
    "oid",
    "file",
    "mode",
    "object",
    "text",
    "byteSize",
    "isTruncated",
    "entries",
    "name",
    "pullRequests",
    "nodes",
    "number",
    "url",
    "baseRefName",
    "title",
    "body",
}


class Repository:
    """A fake personal repository with branches of files and pull requests."""

    def __init__(self):
        self.count = 0
        self.branches = {"main": {"oid": self.oid(), "files": {"README.md": b"hello"}}}
        self.pulls = []
        self.writes = []
        self.owner = "learner"
        self.move = None
        self.visibility = "PRIVATE"

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
            if "pullRequests(headRefName:$branch, states:OPEN" in query:
                unknown = fields_used(query) - BRANCH_QUERY_FIELDS
                assert not unknown, f"GitHub declares no field {sorted(unknown)}"
            if self.move:
                self.move()
                self.move = None
            return {
                "viewer": {"login": "learner"},
                "repository": {
                    "id": "R_1",
                    "visibility": self.visibility,
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
        self.writes.append(mutation(query, variables))
        if "createRef" in query:
            name = values["name"].removeprefix("refs/heads/")
            source = next(b for b in self.branches.values() if b["oid"] == values["oid"])
            self.branches[name] = {"oid": values["oid"], "files": dict(source["files"])}
            return {"createRef": {"ref": {"name": name}}}
        if "createCommitOnBranch" in query:
            branch = self.branches[values["branch"]["branchName"]]
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
    assert "Kept beside the world, not part of it" in pr["body"]
    # The fixture's record keeps no receipt, so what became of it is said to be unrecorded.
    assert (
        "- The knight, with synthetic-model: 1 decision; what the world did with it" in (pr["body"])
    )
    assert "Co-authored" not in pr["body"] and "Generated" not in pr["body"]

    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    local.save(moved)
    review, result = publish(client, target, local, "Move the knight")
    # The commit carries its own sentence; the request's text names the committed files'
    # digests, so it is rewritten to stay in step with them.
    assert result["actions"] == ["commit", "update-pull-request"]
    assert [list(c["files"]) for c in review["commits"]] == [["world-project.json"]]
    assert review["commits"][0]["message"] == "Moved the knight 2 m east"
    assert len(remote.pulls) == 1 and "Moved the knight 2 m east" not in pr["body"]
    # Against the base branch, which has no project.
    assert "- Started the project with 1 thing" in pr["body"]

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
    assert "- Moved the knight 2 m east" in remote.pulls[1]["body"]
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


def test_each_unpublished_checkpoint_becomes_its_own_commit(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    remote = Repository()
    client = RollingPullRequests(remote.request)
    local, world, _ = local_project(tmp_path)
    for x_mm in (1000, 3000):
        moved = deepcopy(world)
        moved["things"][0]["transform"]["x_mm"] = x_mm
        local.save(moved)
    review, result = publish(client, target, local, None)
    assert [c["message"] for c in review["commits"]] == [
        "Started the project",
        "Moved the knight 1 m east",
        "Moved the knight 2 m east",
    ]
    assert result["actions"] == ["create-branch", "commit", "commit", "commit", "open-pull-request"]
    # Someone else's commit makes the branch match no local checkpoint: one commit, given words.
    branch = remote.branches["exulanica/world"]
    branch["files"]["world-project.json"] = branch["files"]["world-project.json"].replace(
        b'"x_mm": 3000', b'"x_mm": 3500'
    )
    branch["oid"] = remote.oid()
    review = client.review(target, local, "Put the knight back where it was saved")
    assert [c["message"] for c in review["commits"]] == ["Put the knight back where it was saved"]


def answering(body, code=1):
    return lambda *a, **k: SimpleNamespace(returncode=code, stdout=json.dumps(body), stderr="")


def test_a_free_repository_name_is_a_not_found_answer_and_nothing_else(monkeypatch):
    from exulanica.world_package.projects.github import RepositoryCreation, gh_graphql

    free = {
        "data": {"viewer": {"login": "learner", "repository": None}},
        "errors": [
            {"type": "NOT_FOUND", "path": ["viewer", "repository"], "message": "not resolved"}
        ],
    }
    monkeypatch.setattr(subprocess, "run", answering(free))
    assert RepositoryCreation().review("world")["repository"] == "learner/world"
    with pytest.raises(ProjectError):  # The default reading excuses file lookups only.
        gh_graphql("q", {})
    for body in (
        {"data": None, "errors": [{"type": "FORBIDDEN"}]},
        {**free, "errors": [{**free["errors"][0], "type": "FORBIDDEN"}]},
        {"data": {"viewer": {"login": "learner", "repository": None}}},
    ):
        monkeypatch.setattr(subprocess, "run", answering(body))
        with pytest.raises(ProjectError):
            RepositoryCreation().review("world")


def fresh_base(errors):
    """GitHub's reply for a repository whose main holds only a README and no project branch."""
    return {
        "data": {
            "viewer": {"login": "learner"},
            "repository": {
                "id": "R_1",
                "nameWithOwner": "learner/world",
                "owner": {"login": "learner"},
                "viewerPermission": "ADMIN",
                "isArchived": False,
                "isDisabled": False,
                "base": {"target": {"oid": "a" * 40, "file": None, "evidence": None}},
                "head": None,
                "pullRequests": {"nodes": []},
            },
        },
        "errors": errors,
    }


MISSING = [
    {"type": "NOT_FOUND", "path": ["repository", "base", "target", "file"], "message": "no file"},
    {"type": "NOT_FOUND", "path": ["repository", "base", "target", "evidence"], "message": "no"},
]


def test_a_fresh_base_branch_without_project_files_reads_as_empty(monkeypatch):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    monkeypatch.setattr(subprocess, "run", answering(fresh_base(MISSING)))
    remote = RollingPullRequests().read(target)
    assert remote.base_files == {} and remote.branch_head is None
    refusals = [
        [{**MISSING[0], "type": "FORBIDDEN"}],
        [{**MISSING[0], "path": ["repository", "pullRequests"]}],
        [{**MISSING[0], "path": ["viewer", "repository"]}],
    ]
    for errors in refusals:
        monkeypatch.setattr(subprocess, "run", answering(fresh_base(errors)))
        with pytest.raises(ProjectError):
            RollingPullRequests().read(target)
    present = fresh_base(MISSING[:1])
    present["data"]["repository"]["base"]["target"]["file"] = {"mode": 33188}
    monkeypatch.setattr(subprocess, "run", answering(present))
    with pytest.raises(ProjectError):  # A NOT_FOUND for a value GitHub nevertheless returned.
        RollingPullRequests().read(target)


def test_the_pinned_schema_refuses_a_misspelled_input():
    with pytest.raises(AssertionError, match="no input field"):
        conforms("CommittableBranch", {"repositoryNameWithOwner": "a/b", "refName": "x"})
    with pytest.raises(AssertionError, match="no input field"):
        conforms(
            "CreateCommitOnBranchInput",
            {"fileChanges": {"additions": [{"path": "p", "body": "x"}]}},
        )


def test_publication_resumes_on_a_branch_created_before_a_failed_commit(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    target = BranchTarget("learner/world", "main", "exulanica/world")
    remote = Repository()
    client = RollingPullRequests(remote.request)
    local, _, _ = local_project(tmp_path)
    # A first attempt created the branch at main's commit and stopped before committing.
    remote.branches["exulanica/world"] = deepcopy(remote.branches["main"])
    review, result = publish(client, target, local, None)
    assert review["actions"] == ["commit", "open-pull-request"]
    assert result["actions"] == ["commit", "open-pull-request"]
    assert client.review(target, local)["actions"] == []


def test_visibility_decides_whether_the_request_reads_labels_or_codes(tmp_path):
    from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests

    from test_world_project_insight import session

    target = BranchTarget("learner/world", "main", "exulanica/world")
    reviews = {}
    for readable in (True, False):
        local, _, _ = local_project(tmp_path / str(readable))
        world, evidence = session(count=2, readable=readable)
        local.save(world, evidence=[{**evidence, "session_id": "session:labelled"}])
        reviews[readable] = local
    remote = Repository()
    client = RollingPullRequests(remote.request)
    private = client.review(target, reviews[True])
    assert private["text"] == "readable"
    assert "\u201crest by the well\u201d" in private["body"]
    assert "## What the characters did" in private["body"]
    remote.visibility = "PUBLIC"
    # A project holding written words reaches no public repository at all
    # (test_world_project_rights); one without them is told in codes.
    with pytest.raises(Conflict, match="written words"):
        client.review(target, reviews[True])
    public = client.review(target, reviews[False])
    assert public["text"] == "codes"
    assert "chose one of 2 choices" in public["body"]
    assert "rest by the well" not in public["body"]
    assert public["review_sha256"] != private["review_sha256"]
    remote.visibility = "INTERNAL"
    assert client.review(target, reviews[False])["text"] == "codes"
    assert remote.writes == []
