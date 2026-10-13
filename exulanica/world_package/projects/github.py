"""Explicit GitHub checkpoint transport using gh and atomic expected-head publication.

Only world-project.json is read or written. No checkout discovery, directory traversal, git
staging, hooks, force updates or repository creation is part of this adapter.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.world_package.projects.checkpoint import (
    MAX_BYTES,
    Conflict,
    ProjectError,
    changes,
    checkpoint_digest,
    decode,
    digest,
    document,
    evidence_digest,
    evidence_document,
    pretty,
    pretty_evidence,
)
from exulanica.world_package.projects.repository import append_only, check_message
from exulanica.world_package.projects.summary import evidence_summary, summarize

PROJECT_PATH = "world-project.json"
_QUERY = """query($owner:String!, $name:String!, $ref:String!) {
  viewer { login }
  repository(owner:$owner, name:$name) {
    nameWithOwner viewerPermission isArchived isDisabled owner { login }
    ref(qualifiedName:$ref) {
      target { ... on Commit { oid file(path:"world-project.json") {
        mode object { ... on Blob { text byteSize isTruncated } }
      } } }
    }
  }
}"""
_MUTATION = """mutation($input:CreateCommitOnBranchInput!) {
  createCommitOnBranch(input:$input) { commit { oid } }
}"""


@dataclass(frozen=True)
class Target:
    repository: str
    branch: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9-]{1,100}/[A-Za-z0-9_.-]{1,100}", self.repository) is None:
            raise ProjectError("repository must explicitly name owner/repository")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}", self.branch) is None
            or any(
                part.startswith(".") or part.endswith((".", ".lock")) or not part
                for part in self.branch.split("/")
            )
            or ".." in self.branch
            or self.branch.startswith("refs/")
        ):
            raise ProjectError("branch must explicitly name a supported short branch name")


@dataclass(frozen=True)
class Snapshot:
    head: str
    checkpoint: dict[str, Any] | None
    writable_owned: bool


def gh_graphql(
    query: str, variables: dict[str, Any], *, tolerate_not_found: bool = False
) -> dict[str, Any]:
    """Use the user's CLI credential store; never return CLI stderr or retry a write.

    With `tolerate_not_found`, a response whose only errors are NOT_FOUND returns its data:
    asking whether a repository exists is answered by GitHub as such an error.
    """
    environment = dict(os.environ)
    for name in ("GH_DEBUG", "GH_HOST", "GH_REPO"):
        environment.pop(name, None)
    environment["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "--hostname", "github.com", "--input", "-"],
            input=json.dumps({"query": query, "variables": variables}),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(
            "GitHub request did not complete; a publication may have succeeded. "
            "Read the branch before preparing another review."
        ) from exc
    if tolerate_not_found:
        try:
            response = json.loads(result.stdout)
            errors = response.get("errors") or []
            if isinstance(response.get("data"), dict) and all(
                isinstance(e, dict) and e.get("type") == "NOT_FOUND" for e in errors
            ):
                return response["data"]
        except (ValueError, AttributeError):
            pass
    if result.returncode != 0:
        raise ProjectError(
            "GitHub refused or failed the request. Check CLI access and branch state; "
            "a publication outcome may be unknown. No automatic retry was made."
        )
    try:
        response = json.loads(result.stdout)
        if response.get("errors") or not isinstance(response.get("data"), dict):
            raise ValueError("GraphQL failure")
        return response["data"]
    except (ValueError, AttributeError) as exc:
        raise ProjectError(
            "GitHub returned an unsuccessful response; inspect branch state"
        ) from exc


class GitHubProjects:
    def __init__(
        self,
        request: Callable[[str, dict[str, Any]], dict[str, Any]] = gh_graphql,
    ) -> None:
        self.request = request

    def read(self, target: Target) -> Snapshot:
        owner, name = target.repository.split("/")
        data = self.request(
            _QUERY,
            {
                "owner": owner,
                "name": name,
                "ref": f"refs/heads/{target.branch}",
            },
        )
        try:
            repo = data["repository"]
            if repo is None or repo["nameWithOwner"].lower() != target.repository.lower():
                raise ProjectError("repository missing or redirected; select the exact destination")
            if repo["ref"] is None:
                raise ProjectError("branch must already exist and contain a commit")
            commit = repo["ref"]["target"]
            head = commit["oid"]
            if re.fullmatch(r"[0-9a-f]{40}", head) is None:
                raise ProjectError("GitHub did not return a commit identity")
            entry = commit["file"]
            checkpoint = None
            if entry is not None:
                blob = entry["object"]
                if (
                    entry["mode"] != 0o100644
                    or blob.get("isTruncated") is not False
                    or type(blob.get("byteSize")) is not int
                    or blob["byteSize"] > MAX_BYTES
                    or not isinstance(blob.get("text"), str)
                ):
                    raise ProjectError("remote checkpoint must be a bounded regular text file")
                checkpoint = document(decode(blob["text"].encode()))
            writable = (
                repo["owner"]["login"].lower() == data["viewer"]["login"].lower()
                and repo["viewerPermission"] in ("ADMIN", "MAINTAIN", "WRITE")
                and not repo["isArchived"]
                and not repo["isDisabled"]
            )
            return Snapshot(head, checkpoint, writable)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProjectError("GitHub returned incomplete repository metadata") from exc

    def review(self, target: Target, candidate: Any, message: str) -> dict[str, Any]:
        selected = document(candidate)
        if not message.strip() or len(message) > 120 or any(ord(c) < 32 for c in message):
            raise ProjectError("commit subject must be one nonempty line of at most 120 characters")
        if "\u2014" in message:
            raise ProjectError("commit subject must not contain an em dash")
        snapshot = self.read(target)
        if not snapshot.writable_owned:
            raise ProjectError("publication requires a writable repository owned by the CLI user")
        if snapshot.checkpoint is not None and (
            selected["project_id"] != snapshot.checkpoint["project_id"]
            or selected["source"]["world_id"] != snapshot.checkpoint["source"]["world_id"]
        ):
            raise Conflict("remote path belongs to another project or source world")
        review = {
            "target": asdict(target),
            "path": PROJECT_PATH,
            "expected_head": snapshot.head,
            "base_checkpoint_sha256": None
            if snapshot.checkpoint is None
            else checkpoint_digest(snapshot.checkpoint),
            "checkpoint_sha256": checkpoint_digest(selected),
            "message": message,
            "diff": changes(snapshot.checkpoint, selected),
            "publication": "Only the selected checkpoint will be published. Review all values "
            "and rights first; published copies cannot be recalled.",
        }
        return {**review, "review_sha256": digest(canonical_json(review))}

    def publish(
        self,
        target: Target,
        candidate: Any,
        message: str,
        *,
        reviewed_sha256: str,
        allow_publication: bool = False,
    ) -> dict[str, Any]:
        if not allow_publication:
            raise ProjectError(
                "publication requires explicit authorization separate from local save"
            )
        # Hold the validated copy whose bytes are reviewed, even if the caller mutates its input.
        selected = document(candidate)
        review = self.review(target, selected, message)
        if review["review_sha256"] != reviewed_sha256:
            raise Conflict("destination, head, checkpoint or subject changed; review again")
        if not review["diff"]:
            return {"published": False, "reason": "unchanged", "head": review["expected_head"]}
        data = self.request(
            _MUTATION,
            {
                "input": {
                    "branch": {
                        "repositoryNameWithOwner": target.repository,
                        "refName": target.branch,
                    },
                    "expectedHeadOid": review["expected_head"],
                    "message": {"headline": message},
                    "fileChanges": {
                        "additions": [
                            {
                                "path": PROJECT_PATH,
                                "contents": base64.b64encode(pretty(selected)).decode("ascii"),
                            }
                        ]
                    },
                }
            },
        )
        try:
            head = data["createCommitOnBranch"]["commit"]["oid"]
            if re.fullmatch(r"[0-9a-f]{40}", head) is None:
                raise ValueError("missing commit")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(
                "publication outcome unknown; read branch before another review"
            ) from exc
        return {
            "published": True,
            "head": head,
            "checkpoint_sha256": review["checkpoint_sha256"],
            "commit_url": f"https://github.com/{target.repository}/commit/{head}",
            "diff_url": f"https://github.com/{target.repository}/compare/"
            f"{review['expected_head']}...{head}",
        }


# Rolling pull request: a project branch whose saved checkpoints accumulate in one open pull
# request against a base branch, the way dependency bots group their updates.

EVIDENCE_PATH = "evidence"
# Unpublished checkpoints beyond this many are published as one commit of the last saved state.
MAX_REPLAYED = 50
_FILES = """
  file(path:"world-project.json") { mode object { ... on Blob { text byteSize isTruncated } } }
  evidence: file(path:"evidence") { mode object { ... on Tree { entries {
    name mode object { ... on Blob { text byteSize isTruncated } } } } } }
"""
_BRANCH_QUERY = (
    """query($owner:String!, $name:String!, $base:String!, $head:String!, $branch:String!) {
  viewer { login }
  repository(owner:$owner, name:$name) {
    id nameWithOwner viewerPermission isArchived isDisabled owner { login }
    base: ref(qualifiedName:$base) { target { ... on Commit { oid """
    + _FILES
    + """ } } }
    head: ref(qualifiedName:$head) { target { ... on Commit { oid """
    + _FILES
    + """ } } }
    pullRequests(headRefName:$branch, states:OPEN, first:2) {
      nodes { id number url baseRefName title body }
    }
  }
}"""
)
_CREATE_REF = """mutation($input:CreateRefInput!) { createRef(input:$input) { ref { name } } }"""
_CREATE_PR = """mutation($input:CreatePullRequestInput!) {
  createPullRequest(input:$input) { pullRequest { number url } }
}"""
_UPDATE_PR = """mutation($input:UpdatePullRequestInput!) {
  updatePullRequest(input:$input) { pullRequest { number url } }
}"""
_CLOSE_PR = """mutation($input:ClosePullRequestInput!) {
  closePullRequest(input:$input) { pullRequest { number url } }
}"""


@dataclass(frozen=True)
class BranchTarget:
    """A personal repository, the base branch to merge into and the project branch."""

    repository: str
    base: str
    branch: str

    def __post_init__(self) -> None:
        Target(self.repository, self.base)
        Target(self.repository, self.branch)
        if self.base == self.branch:
            raise ProjectError("the project branch must differ from the base branch")


@dataclass(frozen=True)
class Remote:
    repository_id: str
    writable_owned: bool
    base_head: str
    branch_head: str | None
    base_files: dict[str, bytes]
    branch_files: dict[str, bytes] | None
    pull_request: dict[str, Any] | None


def _blob(entry: dict[str, Any] | None) -> bytes | None:
    if entry is None:
        return None
    blob = entry["object"]
    if (
        entry["mode"] != 0o100644
        or blob.get("isTruncated") is not False
        or type(blob.get("byteSize")) is not int
        or blob["byteSize"] > MAX_BYTES
        or not isinstance(blob.get("text"), str)
    ):
        raise ProjectError("remote project files must be bounded regular text files")
    return blob["text"].encode()


def _files(commit: dict[str, Any]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    world = _blob(commit.get("file"))
    if world is not None:
        files[PROJECT_PATH] = world
    tree = commit.get("evidence")
    if tree is not None:
        entries = (tree.get("object") or {}).get("entries")
        if not isinstance(entries, list):
            raise ProjectError("remote evidence must be a folder of files")
        for entry in entries:
            name = entry["name"]
            if re.fullmatch(r"[A-Za-z0-9._-]{1,200}\.json", name) is None:
                raise ProjectError("remote evidence holds an unsupported file name")
            data = _blob(entry)
            if data is not None:
                files[f"{EVIDENCE_PATH}/{name}"] = data
    return files


def _sessions(files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    return {
        path.removeprefix(f"{EVIDENCE_PATH}/"): evidence_document(decode(data))
        for path, data in files.items()
        if path.startswith(f"{EVIDENCE_PATH}/")
    }


def _world(files: dict[str, bytes]) -> dict[str, Any] | None:
    data = files.get(PROJECT_PATH)
    return None if data is None else document(decode(data))


class RollingPullRequests:
    """Publish a local project's saved checkpoints to one rolling pull request.

    Only the last saved commit's `world-project.json` and evidence files are published, never
    pending edits or dependency bytes. Every write is reviewed first, is bound to the branch
    heads the review saw, and is never retried after an uncertain outcome.
    """

    def __init__(
        self,
        request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.request = request or gh_graphql

    def read(self, target: BranchTarget) -> Remote:
        owner, name = target.repository.split("/")
        data = self.request(
            _BRANCH_QUERY,
            {
                "owner": owner,
                "name": name,
                "base": f"refs/heads/{target.base}",
                "head": f"refs/heads/{target.branch}",
                "branch": target.branch,
            },
        )
        try:
            repo = data["repository"]
            if repo is None or repo["nameWithOwner"].lower() != target.repository.lower():
                raise ProjectError("repository missing or redirected; select the exact destination")
            if repo["base"] is None:
                raise ProjectError("base branch must already exist and contain a commit")
            base = repo["base"]["target"]
            head = None if repo["head"] is None else repo["head"]["target"]
            for commit in (base, head):
                if commit is not None and re.fullmatch(r"[0-9a-f]{40}", commit["oid"]) is None:
                    raise ProjectError("GitHub did not return a commit identity")
            requests = [
                pr for pr in repo["pullRequests"]["nodes"] if pr["baseRefName"] == target.base
            ]
            if len(requests) > 1:
                raise ProjectError("more than one open pull request uses this project branch")
            writable = (
                repo["owner"]["login"].lower() == data["viewer"]["login"].lower()
                and repo["viewerPermission"] in ("ADMIN", "MAINTAIN", "WRITE")
                and not repo["isArchived"]
                and not repo["isDisabled"]
            )
            return Remote(
                repository_id=repo["id"],
                writable_owned=writable,
                base_head=base["oid"],
                branch_head=None if head is None else head["oid"],
                base_files=_files(base),
                branch_files=None if head is None else _files(head),
                pull_request=requests[0] if requests else None,
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProjectError("GitHub returned incomplete repository metadata") from exc

    def review(
        self, target: BranchTarget, project: Any, message: str | None = None
    ) -> dict[str, Any]:
        """What publication would do, bound to what the remote holds now. Writes nothing."""
        return self._prepare(target, project, message)[0]

    @staticmethod
    def _snapshot(project: Any, revision: str) -> dict[str, bytes]:
        files = {PROJECT_PATH: pretty(project.at(revision))}
        files.update(
            {
                f"{EVIDENCE_PATH}/{name}": pretty_evidence(session)
                for name, session in project.sessions_at(revision).items()
            }
        )
        return files

    def _steps(
        self, project: Any, current: dict[str, bytes], message: str | None
    ) -> list[tuple[str, dict[str, bytes]]]:
        """Each unpublished local checkpoint as its own commit, with its own message.

        The remote branch is matched to the newest local checkpoint whose files it holds; the
        checkpoints after it are replayed in order. A branch matching no local checkpoint, or a
        long backlog, is published as one commit of the last saved state.
        """
        published = {
            path: data
            for path, data in current.items()
            if path == PROJECT_PATH or path.startswith(f"{EVIDENCE_PATH}/")
        }
        history = list(reversed(project.history()))
        start: int | None = -1 if not published else None
        for index in range(len(history) - 1, -1, -1):
            if start is not None:
                break
            if self._snapshot(project, history[index]["commit"]) == published:
                start = index
        pending = [] if start is None else history[start + 1 :]
        if start is None or len(pending) > MAX_REPLAYED:
            text = message or history[-1]["message"]
            pending = [{"commit": history[-1]["commit"], "message": text}]
        steps, state = [], dict(published)
        for entry in pending:
            files = self._snapshot(project, entry["commit"])
            changed = {path: data for path, data in files.items() if state.get(path) != data}
            if changed:
                steps.append((check_message(entry["message"]), changed))
                state.update(changed)
        return steps

    def _prepare(
        self, target: BranchTarget, project: Any, message: str | None
    ) -> tuple[dict[str, Any], list[tuple[str, dict[str, bytes]]], Remote]:
        if message is not None:
            check_message(message)
        world = project.at("HEAD")
        sessions = project.sessions_at("HEAD")
        local = self._snapshot(project, "HEAD")
        remote = self.read(target)
        if not remote.writable_owned:
            raise ProjectError("publication requires a writable repository owned by the CLI user")
        current = remote.branch_files if remote.branch_files is not None else remote.base_files
        for files in (remote.base_files, current):
            other = _world(files)
            if other is not None and (
                other["project_id"] != world["project_id"]
                or other["source"]["world_id"] != world["source"]["world_id"]
            ):
                raise Conflict("remote branch belongs to another project or source world")
        append_only(_sessions(current), sessions)
        steps = self._steps(project, current, message)
        base_world = _world(remote.base_files)
        words = summarize(base_world, world)
        evidence = evidence_summary(_sessions(remote.base_files), sessions)
        net_zero = all(remote.base_files.get(path) == data for path, data in local.items())
        if net_zero:
            actions = ["close-pull-request"] if remote.pull_request else []
        else:
            actions = [
                *(["create-branch"] if remote.branch_head is None else []),
                *(["commit"] * len(steps)),
                *(["open-pull-request"] if remote.pull_request is None else []),
            ]
        title = f"World changes for {world['project_id']}"
        body = "\n".join(
            [
                "Changes to the world:",
                *(f"- {line}" for line in words or ["none"]),
                "",
                "Decision evidence (what happened while models played; not part of the world):",
                *(f"- {line}" for line in evidence or ["none"]),
                "",
                "Recorded from a local Exulanica project. Review every value before merging.",
            ]
        )
        if (
            not net_zero
            and remote.pull_request is not None
            and (remote.pull_request.get("title"), remote.pull_request.get("body")) != (title, body)
        ):
            actions.append("update-pull-request")
        review = {
            "target": asdict(target),
            "base_head": remote.base_head,
            "branch_head": remote.branch_head,
            "pull_request": None if remote.pull_request is None else remote.pull_request["number"],
            "commits": [
                {
                    "message": text,
                    "files": {path: digest(data) for path, data in sorted(files.items())},
                }
                for text, files in steps
            ],
            "title": title,
            "body": body,
            "actions": actions,
            "checkpoint_sha256": checkpoint_digest(world),
            "evidence_sha256": {name: evidence_digest(s) for name, s in sorted(sessions.items())},
            "publication": "Only saved checkpoints and their evidence are published. Review all "
            "values and rights first; published copies cannot be recalled.",
        }
        return {**review, "review_sha256": digest(canonical_json(review))}, steps, remote

    def publish(
        self,
        target: BranchTarget,
        project: Any,
        message: str | None = None,
        *,
        reviewed_sha256: str,
        allow_publication: bool = False,
    ) -> dict[str, Any]:
        if not allow_publication:
            raise ProjectError(
                "publication requires explicit authorization separate from local save"
            )
        review, steps, remote = self._prepare(target, project, message)
        if review["review_sha256"] != reviewed_sha256:
            raise Conflict("destination, heads, content or message changed; review again")
        pull_request = remote.pull_request or {}
        done: list[str] = []
        head = review["branch_head"] or review["base_head"]
        pending = list(steps)
        try:
            for action in review["actions"]:
                if action == "create-branch":
                    self.request(
                        _CREATE_REF,
                        {
                            "input": {
                                "repositoryId": remote.repository_id,
                                "name": f"refs/heads/{target.branch}",
                                "oid": review["base_head"],
                            }
                        },
                    )
                elif action == "commit":
                    text, files = pending.pop(0)
                    data = self.request(
                        _MUTATION,
                        {
                            "input": {
                                "branch": {
                                    "repositoryNameWithOwner": target.repository,
                                    "refName": target.branch,
                                },
                                "expectedHeadOid": head,
                                "message": {"headline": text},
                                "fileChanges": {
                                    "additions": [
                                        {
                                            "path": path,
                                            "contents": base64.b64encode(files[path]).decode(),
                                        }
                                        for path in sorted(files)
                                    ]
                                },
                            }
                        },
                    )
                    head = data["createCommitOnBranch"]["commit"]["oid"]
                    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
                        raise ValueError("missing commit")
                elif action == "open-pull-request":
                    self.request(
                        _CREATE_PR,
                        {
                            "input": {
                                "repositoryId": remote.repository_id,
                                "baseRefName": target.base,
                                "headRefName": target.branch,
                                "title": review["title"],
                                "body": review["body"],
                            }
                        },
                    )
                elif action == "update-pull-request":
                    self.request(
                        _UPDATE_PR,
                        {
                            "input": {
                                "pullRequestId": pull_request["id"],
                                "title": review["title"],
                                "body": review["body"],
                            }
                        },
                    )
                elif action == "close-pull-request":
                    self.request(_CLOSE_PR, {"input": {"pullRequestId": pull_request["id"]}})
                done.append(action)
        except (ProjectError, KeyError, TypeError, ValueError) as exc:
            raise ProjectError(
                f"publication stopped after {done or 'no step'}; its last step's outcome may be "
                "unknown. Read the branch and pull request before another review."
            ) from exc
        return {
            "published": bool(done),
            "actions": done,
            "branch_url": f"https://github.com/{target.repository}/tree/{target.branch}",
            "compare_url": f"https://github.com/{target.repository}/compare/"
            f"{target.base}...{target.branch}",
        }


# Creating a repository: a reviewed operation like publication. GraphQL's createRepository cannot
# add a first commit, so creation uses REST with a README, which gives the base branch a commit.

_VIEWER_REPOSITORY = """query($name:String!) {
  viewer { login repository(name:$name) { nameWithOwner } }
}"""


def gh_rest(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """One REST call through the user's CLI credential store; no stderr echo and no retry."""
    environment = dict(os.environ)
    for name in ("GH_DEBUG", "GH_HOST", "GH_REPO"):
        environment.pop(name, None)
    environment["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--method", method, path, "--input", "-"],
            input=json.dumps(body),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(
            "GitHub request did not complete; the repository may exist. Review again first."
        ) from exc
    if result.returncode != 0:
        raise ProjectError(
            "GitHub refused or failed the request; its outcome may be unknown. "
            "No automatic retry was made."
        )
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict):
            raise ValueError("not an object")
        return response
    except ValueError as exc:
        raise ProjectError("GitHub returned an unsuccessful response") from exc


class RepositoryCreation:
    """Create a private repository under the signed-in account, after a bound review."""

    def __init__(
        self,
        request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        rest: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.request = request or (
            lambda query, variables: gh_graphql(query, variables, tolerate_not_found=True)
        )
        self.rest = rest or gh_rest

    def review(self, name: str, description: str = "") -> dict[str, Any]:
        """What creation would do. Reads the signed-in login and whether the name is free."""
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) is None or name in (".", ".."):
            raise ProjectError("repository name must be letters, digits, '-', '_' or '.'")
        if len(description) > 200 or any(ord(c) < 32 for c in description):
            raise ProjectError("description must be one line of at most 200 characters")
        data = self.request(_VIEWER_REPOSITORY, {"name": name})
        try:
            login = data["viewer"]["login"]
            existing = data["viewer"]["repository"]
        except (KeyError, TypeError) as exc:
            raise ProjectError("GitHub returned incomplete account metadata") from exc
        if not isinstance(login, str) or re.fullmatch(r"[A-Za-z0-9-]{1,100}", login) is None:
            raise ProjectError("GitHub did not return the signed-in login")
        if existing is not None:
            raise Conflict(
                "a repository with this name exists; link the project to it instead of creating"
            )
        review = {
            "repository": f"{login}/{name}",
            "owner": login,
            "visibility": "private",
            "first_commit": "README on the default branch",
            "description": description,
            "creation": "Creates an empty private repository with a README under the signed-in "
            "account. Nothing from the project is published by this step.",
        }
        return {**review, "review_sha256": digest(canonical_json(review))}

    def create(
        self,
        name: str,
        description: str = "",
        *,
        reviewed_sha256: str,
        allow_publication: bool = False,
    ) -> dict[str, Any]:
        if not allow_publication:
            raise ProjectError("creating a repository requires explicit authorization")
        review = self.review(name, description)
        if review["review_sha256"] != reviewed_sha256:
            raise Conflict("account, name or description changed; review again")
        made = self.rest(
            "POST",
            "/user/repos",
            {"name": name, "description": description, "private": True, "auto_init": True},
        )
        try:
            ok = (
                made["full_name"].lower() == review["repository"].lower()
                and made["private"] is True
                and isinstance(made["default_branch"], str)
            )
        except (KeyError, TypeError, AttributeError):
            ok = False
        if not ok:
            raise ProjectError(
                "GitHub's reply did not confirm a private repository; inspect it before linking"
            )
        return {
            "created": True,
            "repository": made["full_name"],
            "private": True,
            "default_branch": made["default_branch"],
            "url": f"https://github.com/{made['full_name']}",
        }
