"""A project folder as a plain local git repository holding one selected checkpoint.

The folder holds `world-project.json`, decision evidence per session under `evidence/` and,
optionally, dependency bytes under `dependencies/` named by their SHA-256. Evidence files are
append-only: a saved record is never changed or removed. Saving commits only when the selected
content changed, so continuous world activity never becomes a commit per minute. No remote is
added, no hook runs, and git is always pointed at the project's own `.git` directory so it cannot
reach an enclosing checkout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica.world_package.projects.checkpoint import (
    MAX_BYTES,
    Conflict,
    ProjectError,
    checkpoint_digest,
    decode,
    digest,
    document,
    evidence_digest,
    evidence_document,
    evidence_warnings,
    fork,
    inspect,
    pretty,
    pretty_evidence,
)
from exulanica.world_package.projects.link import LINK_FILE, link_bytes, make_link, read_link
from exulanica.world_package.projects.schema import ModelBinding, binding_sha256
from exulanica.world_package.projects.summary import evidence_summary, report, subject

PROJECT_FILE = "world-project.json"
DEPENDENCY_DIR = "dependencies"
EVIDENCE_DIR = "evidence"
Sessions = dict[str, dict[str, Any]]
_TRAILER = re.compile(r"(?i)\b(co-authored-by|signed-off-by|generated[- ]with)\b")


@dataclass(frozen=True)
class Author:
    name: str
    email: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[^\x00-\x1f<>]{1,100}", self.name) or not re.fullmatch(
            r"[^\x00-\x1f<>\s]{1,200}", self.email
        ):
            raise ProjectError("author needs a one-line name and an email without spaces")


def check_message(message: str) -> str:
    """One line, at most 120 characters, no em dash and no attribution trailer."""
    if (
        not message.strip()
        or len(message) > 120
        or any(ord(c) < 32 for c in message)
        or "\u2014" in message
        or _TRAILER.search(message)
    ):
        raise ProjectError(
            "commit message must be one nonempty line of at most 120 characters, "
            "without an em dash or an attribution trailer"
        )
    return message.strip()


def _environment() -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # The user's global identity may apply; system configuration and prompts never do.
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return environment


class Project:
    """One local project folder. Every git call names this folder's `.git` explicitly."""

    def __init__(self, folder: Path, *, author: Author | None = None) -> None:
        self.folder = Path(os.path.abspath(folder))
        self.author = author

    @property
    def file(self) -> Path:
        return self.folder / PROJECT_FILE

    def git(self, *arguments: str, check: bool = True) -> str:
        options = [
            f"--git-dir={self.folder / '.git'}",
            f"--work-tree={self.folder}",
            "-c",
            # No file can exist below /dev/null, so no hook can run.
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.autocrlf=false",
        ]
        if self.author is not None:
            options += ["-c", f"user.name={self.author.name}"]
            options += ["-c", f"user.email={self.author.email}"]
        try:
            result = subprocess.run(
                ["git", *options, *arguments],
                cwd=self.folder,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProjectError("git did not complete in the project folder") from exc
        if check and result.returncode != 0:
            if "user.email" in result.stderr or "identity" in result.stderr:
                raise ProjectError("git needs an author; configure user.name and user.email")
            raise ProjectError("git refused the project operation")
        return result.stdout

    # Reading

    def _require(self) -> None:
        git_dir = self.folder / ".git"
        if self.folder.is_symlink() or not git_dir.is_dir() or git_dir.is_symlink():
            raise ProjectError("not a project folder: it has no .git directory of its own")
        if self.git("remote").strip():
            raise ProjectError("project folder has a remote; local projects have none")

    def head(self) -> str | None:
        self._require()
        value = self.git("rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False).strip()
        return value or None

    def _revision(self, revision: str) -> str:
        self._require()
        if not re.fullmatch(r"[0-9a-fA-F]{4,64}|HEAD(~[0-9]{1,6})?", revision):
            raise ProjectError("revision must be a commit identity or HEAD~N")
        return revision

    def at(self, revision: str) -> dict[str, Any]:
        """The checkpoint a commit holds."""
        data = self.git("show", f"{self._revision(revision)}:{PROJECT_FILE}").encode()
        return document(decode(data))

    def sessions_at(self, revision: str) -> Sessions:
        """The evidence files a commit holds, by file name."""
        listed = self.git(
            "ls-tree", "--name-only", f"{self._revision(revision)}", f"{EVIDENCE_DIR}/"
        )
        result = {}
        for path in listed.splitlines():
            name = path.removeprefix(f"{EVIDENCE_DIR}/")
            data = self.git("show", f"{revision}:{EVIDENCE_DIR}/{name}").encode()
            result[name] = evidence_document(decode(data))
        return result

    def published_files(self, revision: str) -> dict[str, bytes]:
        """The files publication sends for a commit: the world and its evidence, as bytes."""
        files = {PROJECT_FILE: pretty(self.at(revision))}
        files.update(
            {
                f"{EVIDENCE_DIR}/{name}": pretty_evidence(session)
                for name, session in self.sessions_at(revision).items()
            }
        )
        return files

    def working(self) -> dict[str, Any]:
        """The checkpoint as edited in the folder, which may be ahead of the last commit."""
        if self.file.is_symlink() or not self.file.is_file():
            raise ProjectError("world-project.json must be a regular file")
        with self.file.open("rb") as stream:
            return document(decode(stream.read(MAX_BYTES + 1)))

    def working_sessions(self) -> Sessions:
        folder = self.folder / EVIDENCE_DIR
        if folder.is_symlink():
            raise ProjectError("evidence folder must not be a symlink")
        if not folder.is_dir():
            return {}
        result = {}
        for path in sorted(folder.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise ProjectError("evidence files must be regular files")
            with path.open("rb") as stream:
                result[path.name] = evidence_document(decode(stream.read(MAX_BYTES + 1)))
        return result

    def history(self) -> list[dict[str, str]]:
        self._require()
        if self.head() is None:
            return []
        lines = self.git("log", "--format=%H%x09%s").splitlines()
        return [
            dict(zip(("commit", "message"), line.split("\t", 1), strict=True)) for line in lines
        ]

    def timeline(self, limit: int = 50) -> dict[str, Any]:
        """The read model for a history panel: pending changes, then checkpoints newest first.

        World changes (`summary`) and decision evidence (`evidence`) are reported separately.
        Lineage names the parent project of a fork; publication state belongs to the publisher.
        """
        self._require()
        if self.head() is None:
            raise ProjectError("project has no saved checkpoint")
        lines = self.git(
            "log", f"--max-count={max(1, min(limit, 500)) + 1}", "--format=%H%x09%ct%x09%s"
        ).splitlines()
        entries = [line.split("\t", 2) for line in lines]
        states = [(self.at(commit), self.sessions_at(commit)) for commit, _, _ in entries]
        checkpoints = []
        for index, (commit, seconds, message) in enumerate(entries[:limit]):
            older = states[index + 1] if index + 1 < len(states) else (None, {})
            world, sessions = states[index]
            checkpoints.append(
                {
                    "commit": commit,
                    "committed_at_unix": int(seconds),
                    "message": message,
                    "checkpoint_sha256": checkpoint_digest(world),
                    "summary": report(older[0], world)["summary"],
                    "evidence": evidence_summary(older[1], sessions),
                }
            )
        world, sessions = states[0]
        edited, edited_sessions = self.working(), self.working_sessions()
        return {
            "project_id": world["project_id"],
            "forked_from": world["forked_from"],
            "head": entries[0][0],
            "pending": [] if edited == world else report(world, edited)["summary"],
            "pending_evidence": evidence_summary(sessions, edited_sessions),
            "sessions": self._sessions_view(world, sessions),
            "link": read_link(self.folder),
            "checkpoints": checkpoints,
            "more": len(entries) > limit,
        }

    def _sessions_view(self, world: dict[str, Any], sessions: Sessions) -> list[dict[str, Any]]:
        warnings = {w["session"]: w["warning"] for w in evidence_warnings(world, sessions)}
        return [
            {
                "file": f"{EVIDENCE_DIR}/{name}",
                "session_id": session["session_id"],
                "records": len(session["decisions"]),
                "evidence_sha256": evidence_digest(session),
                "warning": warnings.get(name),
            }
            for name, session in sorted(sessions.items())
        ]

    def dependencies(self) -> dict[str, bytes]:
        folder = self.folder / DEPENDENCY_DIR
        result: dict[str, bytes] = {}
        if folder.is_symlink() or not folder.is_dir():
            return result
        for path in folder.iterdir():
            name_ok = re.fullmatch(r"[0-9a-f]{64}", path.name) is not None
            if name_ok and path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    result[path.name] = stream.read(MAX_BYTES + 1)
        return result

    # Writing

    def _write(
        self, checkpoint: Any, dependencies: dict[str, bytes], sessions: Sessions | None = None
    ) -> list[str]:
        if self.file.is_symlink():
            raise ProjectError("world-project.json must be a regular file")
        self.file.write_bytes(pretty(checkpoint))
        paths = [PROJECT_FILE]
        declared = {d["sha256"] for d in document(checkpoint)["dependencies"]}
        if dependencies:
            folder = self.folder / DEPENDENCY_DIR
            if folder.is_symlink():
                raise ProjectError("dependencies folder must not be a symlink")
            folder.mkdir(exist_ok=True)
            for sha, data in sorted(dependencies.items()):
                if sha not in declared or digest(data) != sha or len(data) > MAX_BYTES:
                    raise ProjectError("dependency bytes must be declared and match their digest")
                target = folder / sha
                if target.is_symlink():
                    raise ProjectError("dependency files must not be symlinks")
                target.write_bytes(data)
                paths.append(f"{DEPENDENCY_DIR}/{sha}")
        if sessions:
            folder = self.folder / EVIDENCE_DIR
            if folder.is_symlink():
                raise ProjectError("evidence folder must not be a symlink")
            folder.mkdir(exist_ok=True)
            for name, session in sorted(sessions.items()):
                target = folder / name
                if target.is_symlink():
                    raise ProjectError("evidence files must not be symlinks")
                target.write_bytes(pretty_evidence(session))
                paths.append(f"{EVIDENCE_DIR}/{name}")
        return paths

    def write_working(self, checkpoint: Any, evidence: Sequence[Any] = ()) -> None:
        """Show a pending selection and evidence in the folder without recording it."""
        self._require()
        self._write(checkpoint, {}, self._merge(self.working_sessions(), evidence))

    def _commit(self, paths: list[str], message: str) -> str:
        self.git("add", "--", *paths)
        self.git("commit", "--quiet", "--no-verify", "-m", check_message(message), "--", *paths)
        head = self.head()
        if head is None:
            raise ProjectError("git reported no commit after saving")
        return head

    @staticmethod
    def _merge(sessions: Sessions, evidence: Sequence[Any]) -> Sessions:
        result = dict(sessions)
        for value in evidence:
            session = evidence_document(value)
            result[session_file(session["session_id"])] = session
        return result

    def save(
        self,
        checkpoint: Any | None = None,
        *,
        evidence: Sequence[Any] = (),
        message: str | None = None,
        dependencies: dict[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Commit when the selection or its evidence differs from the last commit.

        Without a checkpoint argument the folder's edited files are saved. A session file passed
        in `evidence` replaces its working copy; saved records may only be added to, never
        changed or removed.
        """
        self._require()
        selected = document(self.working() if checkpoint is None else checkpoint)
        has_head = self.head() is not None
        last = self.at("HEAD") if has_head else None
        saved = self.sessions_at("HEAD") if has_head else {}
        if last is not None and last["project_id"] != selected["project_id"]:
            raise Conflict("this folder holds another project; fork into a new folder instead")
        base = self.working_sessions() if checkpoint is None else saved
        sessions = self._merge(base, evidence)
        append_only(saved, sessions)
        changed_sessions = {n: s for n, s in sessions.items() if saved.get(n) != s}
        present = self.dependencies()
        new_dependencies = {
            sha: data for sha, data in (dependencies or {}).items() if present.get(sha) != data
        }
        if last == selected and not changed_sessions and not new_dependencies:
            return {
                "committed": False,
                "reason": "unchanged",
                "commit": self.head(),
                "checkpoint_sha256": checkpoint_digest(selected),
                "summary": [],
                "evidence": [],
            }
        changed = report(last, selected)
        recorded = evidence_summary(saved, sessions)
        text = message or subject(last, selected, recorded) or "Add dependency files"
        paths = self._write(selected, new_dependencies, changed_sessions)
        return {
            "committed": True,
            "commit": self._commit(paths, text),
            "message": check_message(text),
            "checkpoint_sha256": checkpoint_digest(selected),
            **changed,
            "evidence": recorded,
        }

    def link(self, repository: str, base: str, branch: str) -> dict[str, Any]:
        """Record where this project publishes. A local, committed file; nothing is contacted."""
        self._require()
        if self.head() is None:
            raise ProjectError("project has no saved checkpoint")
        data = link_bytes(make_link(repository, base, branch))
        path = self.folder / LINK_FILE
        if path.is_symlink():
            raise ProjectError("project-link.json must be a regular file")
        if path.is_file() and path.read_bytes() == data:
            return {"committed": False, "reason": "unchanged", "link": read_link(self.folder)}
        path.write_bytes(data)
        text = f"Link project to {repository} (base {base}, branch {branch})"
        return {
            "committed": True,
            "commit": self._commit([LINK_FILE], text),
            "message": text,
            "link": read_link(self.folder),
        }

    # Comparing, reopening and forking

    def compare(self, before: str, after: str = "HEAD") -> dict[str, Any]:
        return {
            **report(self.at(before), self.at(after)),
            "evidence": evidence_summary(self.sessions_at(before), self.sessions_at(after)),
        }

    def reopen(self) -> dict[str, Any]:
        """Validate a checkout offline and report what it lacks. Nothing is installed anywhere."""
        self._require()
        if self.head() is None:
            raise ProjectError("project has no saved checkpoint")
        committed, sessions = self.at("HEAD"), self.sessions_at("HEAD")
        edited = self.working()
        result = inspect(committed, dependencies=self.dependencies())
        pending = [] if edited == committed else report(committed, edited)["summary"]
        return {
            **result,
            "project_id": committed["project_id"],
            "commit": self.head(),
            "uncommitted_edits": pending,
            "uncommitted_evidence": evidence_summary(sessions, self.working_sessions()),
            "sessions": self._sessions_view(committed, sessions),
            "link": read_link(self.folder),
            "installed": False,
        }


def session_file(session_id: str) -> str:
    """The evidence file name for a session identity."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", session_id) + ".json"


def _session_may_follow(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    """A living session's block may only close once, and grow its spending while open.

    A closed block never changes, not even when a later reconciliation settles an unknown cost:
    that is recorded as a new entry, never as an edit.
    """
    if old is None or old["state"] == "closed":
        return new == old
    if new is None or (new["session_id"], new["opened"]) != (old["session_id"], old["opened"]):
        return False
    return new["state"] in ("open", "closed")


def append_only(saved: Sessions, sessions: Sessions) -> None:
    for name, old in saved.items():
        new = sessions.get(name)
        if new is None:
            raise Conflict(f"evidence file {name} is saved and cannot be removed")
        records = {d["record_id"]: d for d in new["decisions"]}
        if (
            any(records.get(d["record_id"]) != d for d in old["decisions"])
            or any(model not in new["models"] for model in old["models"])
            or (old["project_id"], old["session_id"], old["source"])
            != (new["project_id"], new["session_id"], new["source"])
            or not _session_may_follow(old.get("living_session"), new.get("living_session"))
        ):
            raise Conflict(f"evidence file {name} is append-only; saved records cannot change")
    for name, session in sessions.items():
        if name != session_file(session["session_id"]):
            raise ProjectError(f"evidence file {name} does not match its session identity")


def create(
    folder: Path,
    checkpoint: Any,
    *,
    author: Author | None = None,
    message: str | None = None,
    dependencies: dict[str, bytes] | None = None,
    evidence: Sequence[Any] = (),
) -> dict[str, Any]:
    """Make a new project folder with its first checkpoint commit. The folder must be new."""
    folder = Path(os.path.abspath(folder))
    if folder.exists() or folder.is_symlink():
        raise Conflict("project folder exists; choose a new folder")
    selected = document(checkpoint)
    sessions = Project._merge({}, evidence)
    append_only({}, sessions)
    folder.mkdir(parents=True)
    project = Project(folder, author=author)
    try:
        # An empty template directory keeps git's sample hooks and templates out of the folder.
        with tempfile.TemporaryDirectory() as template:
            project.git("init", "--quiet", f"--template={template}", "--initial-branch=main")
        text = message or f"Start project {selected['project_id']}"
        paths = project._write(selected, dependencies or {}, sessions)
        commit = project._commit(paths, text)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {
        "committed": True,
        "commit": commit,
        "message": check_message(text),
        "checkpoint_sha256": checkpoint_digest(selected),
        **report(None, selected),
        "evidence": evidence_summary({}, sessions),
    }


def fork_project(
    source: Path,
    destination: Path,
    project_id: str,
    *,
    author: Author | None = None,
) -> dict[str, Any]:
    """A new folder and project identity whose checkpoint records its parent's lineage.

    The parent's evidence stays with the parent: it was recorded for that project, and the
    fork's lineage points back to it.
    """
    parent = Project(source, author=author)
    committed = parent.at("HEAD")
    child = fork(committed, project_id)
    return create(
        destination,
        child,
        author=author,
        message=f"Fork {committed['project_id']} as {project_id}",
        dependencies=parent.dependencies(),
    )


SESSION_LIMIT = 1024


def accumulate(saved: Sessions, captured: Any) -> list[dict[str, Any]]:
    """Merge a capture into the session's saved records, continuing in numbered files.

    A capture reads a window of recent records; the session keeps every record it has seen.
    Records already in a file stay in that file, so saved files only grow.
    """
    incoming = evidence_document(captured)
    base = incoming["session_id"]
    parts = [base, *(f"{base}:{n}" for n in range(2, 1000))]
    files = [saved[session_file(part)] for part in parts if session_file(part) in saved]
    seen = {d["record_id"] for session in files for d in session["decisions"]}
    fresh = [d for d in incoming["decisions"] if d["record_id"] not in seen]
    models = list(incoming["models"])
    result = []
    for index, part in enumerate(parts):
        old = files[index] if index < len(files) else None
        if old is None and not fresh:
            break
        decisions = list(old["decisions"]) if old else []
        room = SESSION_LIMIT - len(decisions)
        decisions += fresh[:room]
        fresh = fresh[room:]
        kept = list(old["models"]) if old else []
        bound = {d["binding_sha256"] for d in decisions}
        for model in models:
            if model not in kept and binding_sha256(ModelBinding.model_validate(model)) in bound:
                kept.append(model)
        result.append(
            evidence_document(
                {
                    **incoming,
                    "session_id": part,
                    "source": old["source"] if old else incoming["source"],
                    # A session was captured when its first file was written; later captures of
                    # the same session must not change that, or every poll would be a change.
                    "captured_at": old.get("captured_at") if old else incoming.get("captured_at"),
                    "models": kept,
                    "decisions": decisions,
                }
            )
        )
    return result


def published_part(files: dict[str, bytes]) -> dict[str, bytes]:
    """The project files among a branch's files; anything else on the branch is not ours."""
    return {
        path: data
        for path, data in files.items()
        if path == PROJECT_FILE or path.startswith(f"{EVIDENCE_DIR}/")
    }


def published_through(
    project: Project, remote: dict[str, bytes]
) -> tuple[list[dict[str, str]], int | None]:
    """Local history oldest first, and the index of the newest commit the remote files equal.

    -1 when the remote holds no project files (nothing published yet); None when the remote
    matches no local commit (someone else changed the branch).
    """
    published = published_part(remote)
    history = list(reversed(project.history()))
    if not published:
        return history, -1
    for index in range(len(history) - 1, -1, -1):
        if project.published_files(history[index]["commit"]) == published:
            return history, index
    return history, None
