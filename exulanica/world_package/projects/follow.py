"""Follow a world on its own: project folders kept current with nobody running a command.

A project folder that holds `project-follow.json` (profile `exulanica.world-project-follow/v1`)
follows the world and version it names: which of the version's placed things (`"every"` one a
checkpoint can hold, or a list), whether readable text is kept, the instant from which the
world's living sessions are recorded (`sessions.since`, or null for none), and, optionally, the
watcher's limits, each absent one at the watcher's own default. The file holds no origin,
credential or path. It is committed in the folder like the link and never published.

The follower keeps every followed folder of one projects directory current with the watcher
(:mod:`exulanica.world_package.projects.watch`). It reads each world through the World API by GET
alone, with one bearer it holds in memory, and records a checkpoint once the world has settled.
Each poll captures at most one living session as its own evidence file: one the project holds as
open until it is held closed (a closed session is recorded at once), else the oldest one opened
since `sessions.since` that the project does not hold, so a session that opened and closed
between two polls, or while no follower ran, is still recorded. A closed session that leaves no
evidence of a followed thing is passed over. A world with no society is followed for its edits
alone, a world made from a world kind with nothing placed for its made parts alone, and a version
with neither waits. It writes only the project folders, never the world, and a remote only where
the project's link says to publish on its own: after each checkpoint it records, such a project's
rolling pull request follows it
(:mod:`exulanica.world_package.projects.publish`, at most `limits.publications_per_day` attempts a
day). One follower holds a projects directory at a time; one project's fault never stops the
others. A person may also ask through the server for a world to be kept
(:mod:`exulanica.world.project_requests`): the follower takes one such request a scan, makes and
names the folder itself, starts the project as following a world does, and removes the request,
or leaves it refused by a code where the project cannot start. When it stops, each project with
pending changes records them once, and nothing more is published.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, ValidationError, model_validator

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError
from exulanica.world.project_requests import read_requests, refuse_request, remove_request
from exulanica.world.project_status import (
    PROFILE as STATUS_PROFILE,
)
from exulanica.world.project_status import (
    STATUS_FILE,
    StatusRefused,
    status_document,
    write_status,
)
from exulanica.world_package.projects.capture import (
    Capture,
    NothingSelectable,
    WorldReader,
    capture,
    check_origin,
    segment,
    sessions_listing,
)
from exulanica.world_package.projects.checkpoint import MAX_BYTES, Conflict, ProjectError, decode
from exulanica.world_package.projects.link import read_link
from exulanica.world_package.projects.publish import (
    PUBLICATIONS_PER_DAY,
    github_view,
    publish_automatically,
)
from exulanica.world_package.projects.repository import (
    EVIDENCE_DIR,
    PROJECT_FILE,
    Author,
    Project,
    create,
)
from exulanica.world_package.projects.schema import Closed, Instant, Name, scan_values, unique
from exulanica.world_package.projects.watch import Policy, Watcher

PROFILE: Final = "exulanica.world-project-follow/v1"
FOLLOW_FILE: Final = "project-follow.json"
#: The one follower of a projects directory holds an exclusive lock on this file in it.
LOCK_FILE: Final = ".project-follower.lock"
FOLLOW_MESSAGE: Final = "Follow the world as it changes"
UNFOLLOW_MESSAGE: Final = "Stop following the world"
#: How many folders one follower follows, unless its host states another number.
MAXIMUM: Final = 64
#: How long stopping may spend recording pending changes, unless its host states another.
FINISH_SECONDS: Final = 60.0
#: How soon a folder that gains, changes or loses its follow file is seen, at most.
RESCAN_SECONDS: Final = 5.0
#: What a poll that last saw pending changes left: recorded once more when the follower stops.
_PENDING: Final = ("settling", "capped")


class Limits(Closed):
    """The watcher's limits, in whole seconds and checkpoints a day; absent is its default."""

    poll_seconds: int | None = None
    settle_seconds: int | None = None
    max_pending_seconds: int | None = None
    daily_cap: int | None = None
    #: Automatic publications a day, where the project's link publishes on its own.
    publications_per_day: Annotated[int, Field(ge=1, le=1_000)] | None = None


#: The limits the watcher itself takes.
_WATCHER_LIMITS: Final = ("poll_seconds", "settle_seconds", "max_pending_seconds", "daily_cap")
#: What each outcome of an automatic publication is called in an event.
_PUBLICATION_EVENTS: Final = {
    "published": "published",
    "paused": "publication_paused",
    "held": "publication_held",
    "refused": "publication_refused",
}


class Sessions(Closed):
    #: Living sessions opened from this instant on are recorded; earlier ones are history.
    since: Instant


class FollowSettings(Closed):
    profile: Literal["exulanica.world-project-follow/v1"]
    world_id: Name
    version_id: Name
    things: Literal["every"] | Annotated[list[Name], Field(min_length=1, max_length=256)]
    readable: bool
    sessions: Sessions | None
    limits: Limits | None = None

    @model_validator(mode="after")
    def checked(self) -> Self:
        if isinstance(self.things, list):
            unique(self.things, "thing")
        policy_of(self.model_dump())
        scan_values(self.model_dump())
        return self


def _held_status(folder: Path) -> dict[str, Any] | None:
    """The state the follower last wrote beside a project, or None."""
    try:
        path = folder / STATUS_FILE
        if path.is_file() and not path.is_symlink():
            return status_document(json.loads(path.read_bytes()))
    except (OSError, ValueError, StatusRefused):
        return None
    return None


def _stamp(seconds: float) -> str:
    """An instant in the project files' one spelling."""
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_of(settings: Mapping[str, Any]) -> Policy:
    """The watcher's policy a follow file states: its own limits, the watcher's defaults else."""
    limits = settings.get("limits") or {}
    return Policy(
        **{
            key: value
            for key, value in limits.items()
            if value is not None and key in _WATCHER_LIMITS
        }
    )


def follow_document(value: Any) -> dict[str, Any]:
    """The settings in their one form: absent limits left out, so two spellings never differ."""
    try:
        document = FollowSettings.model_validate(value).model_dump()
        limits = {k: v for k, v in (document.pop("limits") or {}).items() if v is not None}
        if limits:
            document["limits"] = limits
        canonical_json(document)
        return document
    except (ValidationError, ValueError, ExulanicaError) as exc:
        # Validation errors carry the input; never echo a value.
        raise ProjectError("follow settings violate their closed schema or limits") from exc


def follow_bytes(value: Any) -> bytes:
    return (json.dumps(follow_document(value), indent=2, sort_keys=True) + "\n").encode()


def read_follow(folder: Path) -> dict[str, Any] | None:
    """The folder's follow settings, or None where it follows nothing."""
    path = folder / FOLLOW_FILE
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProjectError("project-follow.json must be a regular file")
    with path.open("rb") as stream:
        return follow_document(decode(stream.read(MAX_BYTES + 1)))


def write_follow(project: Project, settings: Any) -> dict[str, Any]:
    """Record what the folder follows as one local commit; the same settings commit nothing."""
    project._require()
    if project.head() is None:
        raise ProjectError("project has no saved checkpoint")
    document = follow_document(settings)
    if document["world_id"] != project.at("HEAD")["source"]["world_id"]:
        raise Conflict("this project belongs to another world; follow that world in a new folder")
    path = project.folder / FOLLOW_FILE
    if path.is_symlink():
        raise ProjectError("project-follow.json must be a regular file")
    data = follow_bytes(document)
    if path.is_file() and path.read_bytes() == data:
        return {"committed": False, "reason": "unchanged", "follow": document}
    path.write_bytes(data)
    return {
        "committed": True,
        "commit": project._commit([FOLLOW_FILE], FOLLOW_MESSAGE),
        "message": FOLLOW_MESSAGE,
        "follow": document,
    }


def stop_following(project: Project) -> dict[str, Any]:
    """Remove the follow file as one local commit; the project and its history stay."""
    project._require()
    path = project.folder / FOLLOW_FILE
    if path.is_symlink():
        raise ProjectError("project-follow.json must be a regular file")
    if not path.is_file():
        return {"committed": False, "reason": "not followed"}
    path.unlink()
    return {
        "committed": True,
        "commit": project._commit([FOLLOW_FILE], UNFOLLOW_MESSAGE),
        "message": UNFOLLOW_MESSAGE,
    }


def held_sessions(project: Project) -> dict[str, str]:
    """Each living session the project holds, saved or pending, and its state there."""
    held: dict[str, str] = {}
    for sessions in (project.sessions_at("HEAD"), project.working_sessions()):
        for session in sessions.values():
            block = session.get("living_session")
            if block is not None:
                held[block["session_id"]] = block["state"]
    return held


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def due_session(
    listing: Sequence[Mapping[str, Any]],
    held: Mapping[str, str],
    since: str,
    *,
    passed: Collection[str] = frozenset(),
) -> str | None:
    """The one living session a poll captures, of the society's list (newest first).

    A session the project holds as open comes first, until it is held closed; then the oldest one
    opened since `since` that the project neither holds nor passed over. None when none is due.
    """
    oldest_first = list(reversed(listing))
    for one in oldest_first:
        if held.get(one["session_id"]) == "open":
            return one["session_id"]
    start = _instant(since)
    for one in oldest_first:
        session_id = one["session_id"]
        if session_id in held or session_id in passed:
            continue
        if _instant(one["opened"]["opened_at"]) >= start:
            return session_id
    return None


def read_world(
    reader: WorldReader,
    settings: Mapping[str, Any],
    project_id: str,
    *,
    project: Project | None = None,
    passed: set[str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Capture:
    """One poll's capture of a followed world, with the living session due, if any.

    Without `project` it is the first capture of a new project: the world alone.
    """
    version = settings["version_id"]
    listing = sessions_listing(reader, version)
    session = None
    revisions: dict[tuple[str, str, str], str] = {}
    parts_known: dict[str, Any] | None = None
    if project is not None:
        # The revision the project knows last: pending in the folder, else its last commit.
        try:
            world = project.working()
        except ProjectError:
            world = project.at("HEAD")
        revisions = {
            (m["thing_id"], m["provider"], m["model_id"]): m["revision"] for m in world["models"]
        }
        # A made world's parts change only with its version: read again only when it changed.
        if world.get("parts") is not None:
            parts_known = {"state_sha256": world["source"]["state_sha256"], "parts": world["parts"]}
        if listing is not None and settings["sessions"] is not None:
            try:
                session = due_session(
                    listing,
                    held_sessions(project),
                    settings["sessions"]["since"],
                    passed=passed or set(),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError("world API returned a malformed living session list") from exc
    captured = capture(
        reader,
        version_id=version,
        project_id=project_id,
        thing_ids=None if settings["things"] == "every" else list(settings["things"]),
        # A version with no society yet has no model assignments to read.
        include_models=listing is not None,
        include_decisions=session is not None,
        readable=settings["readable"],
        living_session=session,
        revisions=revisions,
        parts_known=parts_known,
        now=now,
    )
    if session is not None and captured.evidence is None and passed is not None:
        state = next(
            (one.get("state") for one in listing or [] if one["session_id"] == session), None
        )
        if state == "closed":
            # Closed with nothing of a followed thing to keep: never due again in this process.
            passed.add(session)
    return captured


def _hold(directory: Path) -> int:
    """The directory's lock, held until closed: one follower writes its folders at a time."""
    try:
        descriptor = os.open(directory / LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ProjectError("the projects directory's lock file could not be opened") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        raise ProjectError("another follower holds this projects directory") from exc
    return descriptor


class _Followed:
    """One followed folder: its settings, project, reader and watcher, and what it last said."""

    def __init__(
        self,
        name: str,
        project: Project,
        settings: dict[str, Any],
        digest: str,
        reader: WorldReader,
        clock: Callable[[], float],
    ) -> None:
        self.name = name
        self.project = project
        self.settings = settings
        self.digest = digest
        self.reader = reader
        self.project_id = project.at("HEAD")["project_id"]
        self.passed: set[str] = set()
        self.state: str | None = None
        self.error: str | None = None
        #: What its last automatic publication said, so a pause is told once.
        self.published: tuple[str, str | None] | None = None
        self.due = clock()
        self.watcher = Watcher(
            project,
            lambda: read_world(
                reader,
                settings,
                self.project_id,
                project=project,
                passed=self.passed,
                now=lambda: datetime.fromtimestamp(clock(), UTC),
            ),
            policy_of(settings),
            clock,
        )


class Follower:
    """Keeps every followed folder of one projects directory current, round after round."""

    def __init__(
        self,
        directory: Path,
        *,
        base_url: str,
        token: str,
        clock: Callable[[], float] = time.time,
        maximum: int = MAXIMUM,
        finish_seconds: float = FINISH_SECONDS,
        author: Author | None = None,
        github: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.directory = Path(os.path.abspath(directory))
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ProjectError("the projects directory must be a directory, not a link")
        if type(maximum) is not int or not 1 <= maximum <= 1_000:
            raise ProjectError("a follower follows between 1 and 1000 folders")
        if not 1 <= finish_seconds <= 3_600:
            raise ProjectError("stopping may spend between 1 second and an hour recording")
        self.base_url = check_origin(base_url)
        self._token = token
        self.clock = clock
        self.maximum = maximum
        self.finish_seconds = finish_seconds
        self.author = author
        #: GitHub's GraphQL, for a project linked to publish on its own (the gh CLI when None).
        self.github = github
        self._items: dict[str, _Followed] = {}
        self._refused: dict[str, str] = {}
        self._unreadable = False
        self._lock: int | None = _hold(self.directory)

    def followed(self) -> list[str]:
        return sorted(self._items)

    def _start(self, name: str, folder: Path, settings: dict[str, Any], digest: str) -> _Followed:
        project = Project(folder, author=self.author)
        project._require()
        if project.head() is None:
            raise ProjectError("this folder has no saved checkpoint; follow a world into it first")
        if project.at("HEAD")["source"]["world_id"] != settings["world_id"]:
            raise ProjectError("the follow file names another world than this project's")
        reader = WorldReader(self.base_url, self._token, settings["world_id"])
        try:
            return _Followed(name, project, settings, digest, reader, self.clock)
        except BaseException:
            reader.close()
            raise

    def _drop(self, name: str) -> None:
        item = self._items.pop(name, None)
        if item is not None:
            item.reader.close()

    def _refuse(self, name: str, reason: str) -> list[dict[str, Any]]:
        self._drop(name)
        if self._refused.get(name) == reason:
            return []
        self._refused[name] = reason
        return [{"project": name, "state": "refused", "error": reason}]

    def take_request(self) -> list[dict[str, Any]]:
        """Start the project a person asked for through the server (the projects directory's
        requests, :mod:`exulanica.world.project_requests`), one a scan, oldest first.

        The folder is named here, from the request's own identity, which the server made; the
        project starts as following a world does (every thing, sessions from now, readable text
        as asked). Taken, the request leaves; a start that cannot be made leaves it refused by a
        code, and the folder is not made. A world this follower already follows at that version
        needs no new folder: its request just leaves."""
        for request in read_requests(self.directory):
            if request["refused"] is not None:
                continue
            request_id, world_id = request["request_id"], request["world_id"]
            now = datetime.fromtimestamp(self.clock(), UTC)
            if any(
                (item.settings["world_id"], item.settings["version_id"])
                == (world_id, request["version_id"])
                for item in self._items.values()
            ):
                remove_request(self.directory, request_id)
                return [{"project": None, "state": "already followed"}]
            if len(self._items) >= self.maximum:
                refuse_request(self.directory, request_id, "too_many_projects", now)
                return [{"project": None, "state": "refused", "error": "too_many_projects"}]
            name = f"world-{request_id[:12]}"
            settings = follow_document(
                {
                    "profile": PROFILE,
                    "world_id": world_id,
                    "version_id": request["version_id"],
                    "things": "every",
                    "readable": request["readable"],
                    "sessions": {"since": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                }
            )
            try:
                with WorldReader(self.base_url, self._token, world_id) as reader:
                    # Only a version this follower's own workspace holds is ever started: the
                    # server made the request's version id and took it only from the workspace
                    # that holds it. Another workspace's request, or one for a world erased
                    # since, can never start here, so it leaves rather than waiting refused.
                    if not reader.holds(
                        "GET version", f"/world/versions/{segment(request['version_id'])}"
                    ):
                        remove_request(self.directory, request_id)
                        return [{"project": None, "state": "gone"}]
                    captured = read_world(reader, settings, f"project:{request_id[:12]}")
                create(
                    self.directory / name,
                    captured.checkpoint,
                    author=self.author,
                    message="Start the project",
                    dependencies=captured.dependencies,
                )
                write_follow(Project(self.directory / name, author=self.author), settings)
            except NothingSelectable:
                code = "nothing_to_keep"
            except (ProjectError, OSError):
                code = "world_unreadable"
            except Exception:
                # Its class names it in the follower's own events; the request says only "failed".
                code = "failed"
            else:
                remove_request(self.directory, request_id)
                return [{"project": name, "state": "started"}]
            refuse_request(self.directory, request_id, code, now)
            return [{"project": None, "state": "refused", "error": code}]
        return []

    def scan(self) -> list[dict[str, Any]]:
        """Start a project a person asked for, then follow the folders that gained a follow file,
        by the settings they now state, and leave the ones that lost theirs."""
        told: list[dict[str, Any]] = self.take_request()
        try:
            entries = sorted(self.directory.iterdir())
        except OSError:
            # The folders already followed go on being followed; the fault is said once.
            if self._unreadable:
                return told
            self._unreadable = True
            return [
                *told,
                {
                    "project": None,
                    "state": "unreadable",
                    "error": "the projects directory could not be read",
                },
            ]
        self._unreadable = False
        present: dict[str, Path] = {}
        for entry in entries:
            follows = entry / FOLLOW_FILE
            if entry.name.startswith(".") or entry.is_symlink() or not entry.is_dir():
                continue
            if follows.exists() or follows.is_symlink():
                present[entry.name] = entry
        for name in sorted(set(self._items) - set(present)):
            self._drop(name)
            told.append({"project": name, "state": "left"})
        for name in set(self._refused) - set(present):
            del self._refused[name]
        for index, (name, folder) in enumerate(sorted(present.items())):
            if index >= self.maximum:
                folders = "folder" if self.maximum == 1 else "folders"
                told += self._refuse(
                    name, f"this follower follows at most {self.maximum} {folders}"
                )
                continue
            try:
                settings = read_follow(folder)
                if settings is None:
                    continue
                digest = hashlib.sha256(canonical_json(settings)).hexdigest()
                held = self._items.get(name)
                if held is not None and held.digest == digest:
                    continue
                self._drop(name)
                self._items[name] = self._start(name, folder, settings, digest)
            except ProjectError as exc:
                told += self._refuse(name, str(exc))
                continue
            except OSError:
                told += self._refuse(name, "this folder could not be read")
                continue
            self._refused.pop(name, None)
            told.append({"project": name, "state": "following"})
        return told

    @staticmethod
    def _attempt(step: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return step()
        except NothingSelectable as exc:
            return {"state": "waiting", "error": str(exc)}
        except ProjectError as exc:
            return {"state": "unreachable", "error": str(exc)}
        except Exception as exc:
            # One project's fault never stops the others; its class names it, never a value.
            return {"state": "failed", "error": type(exc).__name__}

    @staticmethod
    def _told(item: _Followed, outcome: Mapping[str, Any]) -> list[dict[str, Any]]:
        """What a poll says: only a new state or error, and every checkpoint."""
        brief = {
            key: outcome[key]
            for key in ("state", "pending", "pending_evidence", "message", "commit", "error")
            if key in outcome
        }
        state, error = brief["state"], brief.get("error")
        if (state, error) == (item.state, item.error) and state != "checkpointed":
            return []
        item.state, item.error = state, error
        return [{"project": item.name, **brief}]

    def round(self, stop: threading.Event | None = None) -> list[dict[str, Any]]:
        """Scan the directory, then poll every followed world that is due, once."""
        told = self.scan()
        now = self.clock()
        for name in sorted(self._items):
            if stop is not None and stop.is_set():
                break
            item = self._items[name]
            if now < item.due:
                continue
            item.due = now + item.watcher.policy.poll_seconds
            outcome = self._attempt(item.watcher.step)
            said = self._told(item, outcome)
            told += said
            if outcome.get("state") == "checkpointed":
                told += self._publish(item)
            elif said:
                self._report(item)
        return told

    def _report(self, item: _Followed, github: Mapping[str, Any] | None = None) -> None:
        """Write the project's state beside it, where the server reads it
        (:mod:`exulanica.world.project_status`): its checkpoints, whether changes wait, its link
        and what GitHub last said, kept from the last write unless `github` is new. Never
        committed, never published; a state that cannot be written stops nothing."""
        folder = Path(item.project.folder)
        previous = _held_status(folder)
        try:
            saved = item.project.git(
                "log", "--format=%ct", "--", PROJECT_FILE, EVIDENCE_DIR
            ).split()
            link = read_link(folder)
            held = None if previous is None else previous["github"]
            document = {
                "profile": STATUS_PROFILE,
                "world_id": item.settings["world_id"],
                "version_id": item.settings["version_id"],
                "written_at": _stamp(self.clock()),
                "checkpoints": len(saved),
                "last_checkpoint_at": _stamp(float(saved[0])) if saved else None,
                "pending": item.state in _PENDING,
                "settle_seconds": round(item.watcher.policy.settle_seconds),
                "link": None
                if link is None
                else {
                    "repository": link["repository"],
                    "publish": "automatic" if link.get("publish") == "automatic" else "by hand",
                },
                "github": None if link is None else (github if github is not None else held),
            }
            if previous is not None and {**previous, "written_at": ""} == {
                **status_document(document),
                "written_at": "",
            }:
                return
            write_status(folder, document)
        except (ProjectError, OSError, ValueError, StatusRefused):
            return

    def _publish(self, item: _Followed) -> list[dict[str, Any]]:
        """After a checkpoint, publish the project on its own where its link says so, then read
        once what its repository holds of it, for the server's read of the project's state. A
        pause or hold is told once; every publication is told."""
        link = None
        try:
            link = read_link(item.project.folder)
            if link is None:
                self._report(item)
                return []
            limits = item.settings.get("limits") or {}
            outcome = publish_automatically(
                item.project,
                link,
                request=self.github,
                now=self.clock(),
                per_day=limits.get("publications_per_day") or PUBLICATIONS_PER_DAY,
            )
        except ProjectError as exc:
            outcome = {"state": "refused", "error": str(exc)}
        except Exception as exc:
            outcome = {"state": "refused", "error": type(exc).__name__}
        if link is not None:
            held = _held_status(Path(item.project.folder))
            try:
                view = github_view(
                    item.project,
                    link,
                    request=self.github,
                    now=self.clock(),
                    previous=None if held is None else held["github"],
                )
            except Exception:
                view = None
            self._report(item, view)
        if outcome is None:
            return []
        said = (outcome["state"], outcome.get("error"))
        if said == item.published and outcome["state"] != "published":
            return []
        item.published = said
        event = {"project": item.name, "state": _PUBLICATION_EVENTS[outcome["state"]]}
        for key in ("actions", "error"):
            if key in outcome:
                event[key] = outcome[key]
        return [event]

    def _pause(self) -> float:
        now = self.clock()
        due = min((item.due for item in self._items.values()), default=now + RESCAN_SECONDS)
        return max(0.0, min(due - now, RESCAN_SECONDS))

    def run(
        self,
        stop: threading.Event,
        tell: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Follow until `stop` is set, then record what is pending once and close."""
        say = tell or (lambda _: None)
        try:
            while not stop.is_set():
                for outcome in self.round(stop):
                    say(outcome)
                if not stop.is_set():
                    stop.wait(self._pause())
            return self.finish(say)
        finally:
            self.close()

    def finish(self, tell: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        """Record each project's pending changes once, within the finish deadline."""
        say = tell or (lambda _: None)
        deadline = time.monotonic() + self.finish_seconds
        recorded = left = 0
        for name in sorted(self._items):
            item = self._items[name]
            if item.state not in _PENDING:
                continue
            if time.monotonic() >= deadline:
                left += 1
                say({"project": name, "state": "left_pending"})
                continue
            outcome = self._attempt(item.watcher.finish)
            if outcome["state"] == "checkpointed":
                recorded += 1
            elif outcome["state"] != "clean":
                left += 1
            for told in self._told(item, outcome):
                say(told)
        return {"recorded": recorded, "left_pending": left}

    def close(self) -> None:
        for name in list(self._items):
            self._drop(name)
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    def __enter__(self) -> Follower:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
