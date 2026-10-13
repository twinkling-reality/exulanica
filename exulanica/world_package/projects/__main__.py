"""Offline checkpoint commands and explicitly selected GitHub operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exulanica.world_package.projects.checkpoint import (
    MAX_BYTES,
    Conflict,
    ProjectError,
    changes,
    decode,
    fork,
    inspect,
    playback,
    read,
    save,
)
from exulanica.world_package.projects.github import GitHubProjects, Target
from exulanica.world_package.projects.schema import Checkpoint, Source


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
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "schema":
            print(json.dumps(Checkpoint.model_json_schema(), indent=2, sort_keys=True))
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
