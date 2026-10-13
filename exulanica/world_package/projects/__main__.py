"""Offline checkpoint commands and explicitly selected GitHub operations."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path

from exulanica.world_package.projects.capture import Capture, WorldReader, capture, read_token
from exulanica.world_package.projects.checkpoint import (
    MAX_BYTES,
    Conflict,
    ProjectError,
    changes,
    decode,
    evidence_digest,
    fork,
    inspect,
    playback,
    pretty_evidence,
    read,
    save,
)
from exulanica.world_package.projects.github import (
    BranchTarget,
    GitHubProjects,
    RepositoryCreation,
    RollingPullRequests,
    Target,
)
from exulanica.world_package.projects.link import resolve
from exulanica.world_package.projects.repository import (
    Author,
    Project,
    accumulate,
    create,
    fork_project,
)
from exulanica.world_package.projects.schema import Checkpoint, Evidence, Source
from exulanica.world_package.projects.watch import Policy, Watcher

PROJECT_COMMANDS = ("create", "record", "changes", "reopen", "fork-project", "history", "watch")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="print the editable checkpoint's closed JSON schema")
    for name in ("save", "inspect", "playback", "fork", "review", "publish"):
        command = commands.add_parser(name)
        command.add_argument("checkpoint", type=Path)
        if name in ("save", "fork"):
            command.add_argument("--output", type=Path, required=True)
        if name == "fork":
            command.add_argument("--project-id", required=True)
        if name == "inspect":
            command.add_argument("--dependencies", type=Path)
            command.add_argument("--expected-source", type=Path)
        if name in ("review", "publish"):
            command.add_argument("--repository", required=True)
            command.add_argument("--branch", required=True)
            command.add_argument("--message", required=True)
        if name == "publish":
            command.add_argument("--review-sha256", required=True)
            command.add_argument("--allow-publication", action="store_true")
    command = commands.add_parser("diff")
    command.add_argument("before", type=Path)
    command.add_argument("after", type=Path)
    command = commands.add_parser("fetch")
    command.add_argument("--repository", required=True)
    command.add_argument("--branch", required=True)
    command.add_argument("--output", type=Path, required=True)
    commands.add_parser("evidence-schema", help="print the session evidence file's JSON schema")

    # Project folders: plain local git repositories, no account and no remote.
    for name in PROJECT_COMMANDS:
        command = commands.add_parser(name)
        command.add_argument("folder", type=Path)
        if name in ("create", "record", "fork-project", "watch"):
            command.add_argument("--author-name")
            command.add_argument("--author-email")
        if name in ("create", "record"):
            command.add_argument("--from", dest="source", type=Path, required=name == "create")
            command.add_argument("--evidence", type=Path, action="append", default=[])
            command.add_argument("--dependencies", type=Path)
            command.add_argument("--message")
        if name == "changes":
            command.add_argument("--from", dest="before", default="HEAD~1")
            command.add_argument("--to", dest="after", default="HEAD")
        if name == "fork-project":
            command.add_argument("--to", dest="destination", type=Path, required=True)
            command.add_argument("--project-id", required=True)
        if name == "history":
            command.add_argument("--limit", type=int, default=50)
        if name == "watch":
            _world_arguments(command)
            command.add_argument("--poll-seconds", type=float, default=15.0)
            command.add_argument("--settle-seconds", type=float, default=120.0)
            command.add_argument("--max-pending-seconds", type=float, default=1800.0)
            command.add_argument("--daily-cap", type=int, default=48)
    for name in ("review-branch", "publish-branch"):
        command = commands.add_parser(name, help="one rolling pull request for a project folder")
        command.add_argument("folder", type=Path)
        command.add_argument("--repository", help="defaults to the project's link")
        command.add_argument("--base", help="defaults to the project's link")
        command.add_argument("--branch", help="defaults to the project's link")
        command.add_argument(
            "--message", help="only when the branch matches no saved checkpoint and is squashed"
        )
        if name == "publish-branch":
            command.add_argument("--review-sha256", required=True)
            command.add_argument("--allow-publication", action="store_true")
    for name in ("review-repository", "create-repository"):
        command = commands.add_parser(name, help="a private repository under the signed-in account")
        command.add_argument("name")
        command.add_argument("--description", default="")
        if name == "create-repository":
            command.add_argument("--review-sha256", required=True)
            command.add_argument("--allow-publication", action="store_true")
    command = commands.add_parser("link", help="record where a project folder publishes")
    command.add_argument("folder", type=Path)
    command.add_argument("--repository", required=True)
    command.add_argument("--base", required=True)
    command.add_argument("--branch", required=True)
    command.add_argument("--author-name")
    command.add_argument("--author-email")
    command = commands.add_parser(
        "record-world", help="capture a running world (GET) into a project folder as a checkpoint"
    )
    command.add_argument("folder", type=Path)
    _world_arguments(command)
    command.add_argument("--session", required=True)
    command.add_argument("--project-id", help="required when the folder does not exist yet")
    command.add_argument("--message")
    command.add_argument("--author-name")
    command.add_argument("--author-email")
    command = commands.add_parser("capture", help="read a selection from a running world (GET)")
    _world_arguments(command)
    command.add_argument("--project-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--session")
    command.add_argument("--evidence-output", type=Path)
    command.add_argument("--dependencies-output", type=Path)
    return root


def _world_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--api", required=True, help="http://localhost:PORT or an https origin")
    command.add_argument("--token-file", type=Path, required=True)
    command.add_argument("--world", required=True)
    command.add_argument("--version", required=True)
    command.add_argument("--thing", action="append", required=True)
    command.add_argument("--readable", action="store_true")


def _author(args: argparse.Namespace) -> Author | None:
    if args.author_name is None and args.author_email is None:
        return None  # The user's own git identity applies.
    return Author(args.author_name or "", args.author_email or "")


def _json_file(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ProjectError("input must be a regular file")
    with path.open("rb") as stream:
        return decode(stream.read(MAX_BYTES + 1))


def _local_dependencies(folder: Path | None) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    if folder is None:
        return found
    for path in folder.iterdir():
        if len(path.name) == 64 and path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                found[path.name] = stream.read(MAX_BYTES + 1)
    return found


def _reader(args: argparse.Namespace) -> WorldReader:
    return WorldReader(args.api, read_token(args.token_file), args.world)


def _capture(
    args: argparse.Namespace, reader: WorldReader, project_id: str, session: str | None
) -> Capture:
    return capture(
        reader,
        version_id=args.version,
        project_id=project_id,
        thing_ids=args.thing,
        readable=args.readable,
        session_id=session,
    )


def project_command(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "capture":
        with _reader(args) as reader:
            result = _capture(args, reader, args.project_id, args.session)
        saved = {"checkpoint_sha256": save(args.output, result.checkpoint)}
        if result.evidence is not None:
            if args.evidence_output is None:
                raise ProjectError("a session capture needs --evidence-output")
            descriptor = os.open(args.evidence_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(pretty_evidence(result.evidence))
            saved["evidence_sha256"] = evidence_digest(result.evidence)
        if args.dependencies_output is not None:
            args.dependencies_output.mkdir(mode=0o700, exist_ok=True)
            for sha, data in result.dependencies.items():
                (args.dependencies_output / sha).write_bytes(data)
        return {**saved, "report": result.report, "published": False}
    if args.command == "link":
        return Project(args.folder, author=_author(args)).link(
            args.repository, args.base, args.branch
        )
    if args.command == "record-world":
        return record_world(args)
    if args.command == "create":
        return create(
            args.folder,
            _json_file(args.source),
            author=_author(args),
            message=args.message,
            dependencies=_local_dependencies(args.dependencies),
            evidence=[_json_file(path) for path in args.evidence],
        )
    project = Project(args.folder, author=_author(args) if "author_name" in args else None)
    if args.command == "record":
        return project.save(
            None if args.source is None else _json_file(args.source),
            evidence=[_json_file(path) for path in args.evidence],
            message=args.message,
            dependencies=_local_dependencies(args.dependencies),
        )
    if args.command == "changes":
        return project.compare(args.before, args.after)
    if args.command == "reopen":
        return project.reopen()
    if args.command == "history":
        return project.timeline(args.limit)
    if args.command == "fork-project":
        return fork_project(args.folder, args.destination, args.project_id, author=_author(args))
    # watch: a session per run, recorded locally only.
    policy = Policy(
        poll_seconds=args.poll_seconds,
        settle_seconds=args.settle_seconds,
        max_pending_seconds=args.max_pending_seconds,
        daily_cap=args.daily_cap,
    )
    project_id = project.at("HEAD")["project_id"]
    session = "session:" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    with _reader(args) as reader:
        watcher = Watcher(project, lambda: _capture(args, reader, project_id, session), policy)
        final = watcher.run(stop, lambda outcome: print(json.dumps(_brief(outcome)), flush=True))
    return {"session_id": session, "final": _brief(final)}


def record_world(args: argparse.Namespace) -> dict[str, object]:
    """Capture a running world into a project folder: one checkpoint, one session's evidence."""
    exists = args.folder.exists()
    project = Project(args.folder, author=_author(args))
    project_id = project.at("HEAD")["project_id"] if exists else args.project_id
    if project_id is None:
        raise ProjectError("a new project folder needs --project-id")
    with _reader(args) as reader:
        captured = _capture(args, reader, project_id, args.session)
    if not exists:
        return {
            **create(
                args.folder,
                captured.checkpoint,
                author=_author(args),
                message=args.message,
                dependencies=captured.dependencies,
                evidence=[captured.evidence] if captured.evidence else [],
            ),
            "report": captured.report,
        }
    evidence = []
    if captured.evidence:
        # A later run's world may still hold an earlier run's records; each is kept once. A
        # request identity derives from the being and the minute, so two runs from one start
        # reuse identities for different decisions: the source record's digest tells them apart.
        sessions = project.working_sessions()
        own = {
            name
            for name, held in sessions.items()
            if held["session_id"] == args.session
            or held["session_id"].startswith(f"{args.session}:")
        }
        held = {
            d["source_record_sha256"]
            for name, session in sessions.items()
            if name not in own
            for d in session["decisions"]
        }
        fresh = [d for d in captured.evidence["decisions"] if d["source_record_sha256"] not in held]
        if fresh:
            evidence = accumulate(sessions, {**captured.evidence, "decisions": fresh})
    return {
        **project.save(
            captured.checkpoint,
            evidence=evidence,
            message=args.message,
            dependencies=captured.dependencies,
        ),
        "report": captured.report,
    }


def _brief(outcome: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in outcome.items() if k != "diff"}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "schema":
            print(json.dumps(Checkpoint.model_json_schema(), indent=2, sort_keys=True))
            return 0
        if args.command == "evidence-schema":
            print(json.dumps(Evidence.model_json_schema(), indent=2, sort_keys=True))
            return 0
        if args.command in ("review-repository", "create-repository"):
            creation = RepositoryCreation()
            if args.command == "review-repository":
                result = creation.review(args.name, args.description)
            else:
                result = creation.create(
                    args.name,
                    args.description,
                    reviewed_sha256=args.review_sha256,
                    allow_publication=args.allow_publication,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command in ("review-branch", "publish-branch"):
            linked = resolve(args.folder, args.repository, args.base, args.branch)
            target = BranchTarget(linked["repository"], linked["base"], linked["branch"])
            client, project = RollingPullRequests(), Project(args.folder)
            if args.command == "review-branch":
                result = client.review(target, project, args.message)
            else:
                result = client.publish(
                    target,
                    project,
                    args.message,
                    reviewed_sha256=args.review_sha256,
                    allow_publication=args.allow_publication,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command in (*PROJECT_COMMANDS, "capture", "link", "record-world"):
            print(json.dumps(project_command(args), indent=2, sort_keys=True))
            return 0
        if args.command == "diff":
            print(changes(read(args.before), read(args.after)), end="")
            return 0
        if args.command == "fetch":
            snapshot = GitHubProjects().read(Target(args.repository, args.branch))
            if snapshot.checkpoint is None:
                raise ProjectError("branch has no world-project.json checkpoint")
            result = {
                "saved_locally": True,
                "head": snapshot.head,
                "checkpoint_sha256": save(args.output, snapshot.checkpoint),
            }
        else:
            checkpoint = read(args.checkpoint)
            if args.command in ("save", "fork"):
                value = fork(checkpoint, args.project_id) if args.command == "fork" else checkpoint
                result = {
                    "saved_locally": True,
                    "published": False,
                    "checkpoint_sha256": save(args.output, value),
                }
            elif args.command == "inspect":
                dependencies = {}
                if args.dependencies:
                    for dependency in checkpoint["dependencies"]:
                        path = args.dependencies / dependency["sha256"]
                        if path.is_file() and not path.is_symlink():
                            with path.open("rb") as stream:
                                dependencies[dependency["sha256"]] = stream.read(MAX_BYTES + 1)
                expected = None
                if args.expected_source:
                    with args.expected_source.open("rb") as stream:
                        expected = Source.model_validate(decode(stream.read(MAX_BYTES + 1)))
                result = inspect(checkpoint, dependencies=dependencies, expected_source=expected)
            elif args.command == "playback":
                result = playback(checkpoint)
            else:
                client = GitHubProjects()
                target = Target(args.repository, args.branch)
                if args.command == "review":
                    result = client.review(target, checkpoint, args.message)
                else:
                    result = client.publish(
                        target,
                        checkpoint,
                        args.message,
                        reviewed_sha256=args.review_sha256,
                        allow_publication=args.allow_publication,
                    )
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.command == "inspect" and not result["dependencies_ready"]:
            return 2
        return 0
    except ProjectError as exc:
        print(json.dumps({"error": str(exc), "conflict": isinstance(exc, Conflict)}))
        return 1
    except (OSError, ValueError):
        # Input validation may contain selected private values. Keep CLI failures value-free.
        print(
            json.dumps(
                {
                    "error": "project operation refused; check format, dependencies, "
                    "review/base identity and destination access"
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
