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
    pretty,
)

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


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Use the user's CLI credential store; never return CLI stderr or retry a write."""
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
