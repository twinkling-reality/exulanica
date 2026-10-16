"""Putting a kept project on the person's own GitHub, when they asked for it through the server.

The server writes the person's request (:mod:`exulanica.world.project_requests`) and never runs
the GitHub CLI. The follower (:mod:`exulanica.world_package.projects.follow`), which runs as the
person on their own computer, acts on it here with their own GitHub CLI, which keeps their
sign-in: nothing here sees, stores or passes a token. It takes the two steps a person takes by
hand (``review-repository``, ``create-repository``, ``link --publish automatic``):

1. **Review, writing nothing on GitHub.** The CLI must be installed and signed in. The account it
   is signed in as and whether the name is free are read
   (:class:`~exulanica.world_package.projects.github.RepositoryCreation`), and the files the first
   publication would send are checked as for a private repository
   (:mod:`exulanica.world_package.projects.rights`). The review's digest binds the account, the
   repository, the project, whether written words would go and how many publications a day
   follow.
2. **Create, bound to that review, once the person said yes to it.** The review is made again and
   must give the same digest. The private repository is created (with a README, so its default
   branch has a commit), read again and required to say ``PRIVATE``, and the project is linked to
   it to publish on its own, so the follower publishes this and each later checkpoint
   (:mod:`exulanica.world_package.projects.publish`: private only, a daily bound, a pause on any
   doubt).

Anything refused or uncertain is said by a code (:data:`~exulanica.world.project_requests.
PUBLICATION_REFUSALS`) and nothing is retried: a creation whose outcome cannot be read is
``failed``, and the person looks on GitHub before asking again.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, digest
from exulanica.world_package.projects.github import (
    BranchTarget,
    RepositoryCreation,
    RollingPullRequests,
)
from exulanica.world_package.projects.link import read_link
from exulanica.world_package.projects.publish import PUBLICATIONS_PER_DAY
from exulanica.world_package.projects.repository import EVIDENCE_DIR, PROJECT_FILE, Project
from exulanica.world_package.projects.rights import PRIVATE
from exulanica.world_package.projects.rights import check as check_rights

#: The project branch a project put on GitHub from History publishes from.
BRANCH: Final = "exulanica/world"
#: How long asking the GitHub CLI whether it is signed in may take.
READY_SECONDS: Final = 20


class Refused(Exception):
    """Putting the project on GitHub stopped, for the reason its code names."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Access:
    """How the follower reaches the person's GitHub: their own GitHub CLI, unless a test gives
    stand-ins (GraphQL, REST, and whether the CLI is there and signed in)."""

    graphql: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    rest: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None
    ready: Callable[[], str | None] | None = None


def gh_ready() -> str | None:
    """None where the GitHub CLI is installed and signed in to github.com; otherwise the code
    that says which (``gh_missing``, ``not_signed_in``). What the CLI prints is never kept."""
    if shutil.which("gh") is None:
        return "gh_missing"
    environment = dict(os.environ)
    for name in ("GH_DEBUG", "GH_HOST", "GH_REPO"):
        environment.pop(name, None)
    environment["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com"],
            capture_output=True,
            timeout=READY_SECONDS,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not_signed_in"
    return None if result.returncode == 0 else "not_signed_in"


def proposed_name(project: Project, readable: bool) -> str:
    """The repository name proposed when the person names none: the world's title as words where
    the project keeps written words (``exulanica-terraces-on-the-bay``), else words that say
    nothing of it (``exulanica-world-`` and 12 hexadecimal characters of the project's identity)."""
    world = project.at("HEAD")
    title = world.get("title") if readable else None
    if isinstance(title, str):
        plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
        words = "-".join(re.findall(r"[a-z0-9]+", plain))[:60].strip("-")
        if words:
            return f"exulanica-{words}"
    hashed = hashlib.sha256(str(world["project_id"]).encode()).hexdigest()
    return f"exulanica-world-{hashed[:12]}"


def _ready(access: Access) -> None:
    code = (access.ready or gh_ready)()
    if code is not None:
        raise Refused(code)


def per_day(settings: Mapping[str, Any]) -> int:
    """The most automatic publications a day the follower makes for the project: its follow file's
    limit, else the default."""
    return (settings.get("limits") or {}).get("publications_per_day") or PUBLICATIONS_PER_DAY


def _bound(creation: Mapping[str, Any], project: Project, settings: Mapping[str, Any]) -> str:
    """The review's digest: the account and repository (RepositoryCreation's own review), the
    project, whether written words go and the daily bound. The person's yes names it."""
    project_id = project.at("HEAD")["project_id"]
    return digest(
        canonical_json(
            {
                "creation_sha256": creation["review_sha256"],
                "project_id": project_id,
                "readable": bool(settings["readable"]),
                "publications_per_day": per_day(settings),
            }
        )
    )


def _rights(project: Project) -> None:
    """The files the first publication sends, checked as for a private repository."""
    try:
        check_rights(project.published_files("HEAD"), PRIVATE, project.dependencies())
    except Conflict as exc:
        raise Refused("rights_refused") from exc


def _review_name(creation: RepositoryCreation, name: str) -> dict[str, Any]:
    try:
        return creation.review(name)
    except Conflict as exc:
        raise Refused("name_taken") from exc


def review(
    project: Project,
    settings: Mapping[str, Any],
    request: Mapping[str, Any],
    access: Access,
    now: datetime,
) -> dict[str, Any]:
    """What creating the repository would do, read with the person's GitHub CLI; nothing is
    written on GitHub. Refused by a code where it could not be made."""
    if read_link(project.folder) is not None:
        raise Refused("failed")  # linked by hand meanwhile: there is nothing to create
    _ready(access)
    readable = bool(settings["readable"])
    creation = RepositoryCreation(access.graphql, access.rest)
    made = _review_name(creation, request["name"] or proposed_name(project, readable))
    _rights(project)
    saved = project.git("log", "--format=%H", "--", PROJECT_FILE, EVIDENCE_DIR).split()
    return {
        "owner": made["owner"],
        "repository": made["repository"],
        "readable": readable,
        "checkpoints": len(saved),
        "publications_per_day": per_day(settings),
        "review_sha256": _bound(made, project, settings),
        "reviewed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def create(
    project: Project,
    settings: Mapping[str, Any],
    request: Mapping[str, Any],
    access: Access,
) -> dict[str, Any]:
    """Create the repository the person said yes to, and link the project to it to publish on
    its own; answers the link. The review is made again first and must give the digest the
    person's yes names; the repository must read ``PRIVATE`` before the project is linked.
    Nothing is retried: an outcome that cannot be read is ``failed``."""
    if read_link(project.folder) is not None:
        raise Refused("failed")
    _ready(access)
    creation = RepositoryCreation(access.graphql, access.rest)
    name = request["review"]["repository"].split("/")[1]
    fresh = _review_name(creation, name)
    if _bound(fresh, project, settings) != request["confirmed"]["review_sha256"]:
        raise Refused("changed")
    _rights(project)
    try:
        made = creation.create(name, reviewed_sha256=fresh["review_sha256"], allow_publication=True)
    except Conflict as exc:
        raise Refused("changed") from exc
    except ProjectError as exc:
        raise Refused("failed") from exc
    target = BranchTarget(made["repository"], made["default_branch"], BRANCH)
    try:
        remote = RollingPullRequests(access.graphql).read(target)
    except ProjectError as exc:
        raise Refused("failed") from exc
    if remote.visibility != PRIVATE:
        raise Refused("not_private")
    project.link(made["repository"], made["default_branch"], BRANCH, "automatic")
    link = read_link(project.folder)
    if link is None:
        raise Refused("failed")
    return link
