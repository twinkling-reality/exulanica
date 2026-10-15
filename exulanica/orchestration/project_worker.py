"""Keep the world projects of one projects directory current, in a process of its own.

    python -m exulanica.orchestration.project_worker --projects DIR \\
        --api http://localhost:PORT --token-file PATH

A project folder that holds a follow file follows its world (``follow FOLDER``,
:mod:`exulanica.world_package.projects.follow`). This process reads each followed world through
the World API by GET alone, with one bearer it reads from a file into memory and never prints,
and records each project's checkpoints and living sessions in its own folder under the limits
that folder states. It writes nothing to a world and nothing to a remote.

**Where it runs.** Beside an API, never inside one. The HTTP surface may not import the project
package (the backend's layering contract puts the package projection above it), and a follower is
a client of the API, not of its database: it needs the API's origin and a ``world.read`` bearer,
and no database URL, store or model key. Plain http reaches only ``localhost``, as for every
capture, so it runs on the computer that serves the API. Each setting may be given by its flag or
by ``EXULANICA_PROJECTS_DIRECTORY``, ``EXULANICA_PROJECT_API_URL`` and
``EXULANICA_PROJECT_TOKEN_FILE``. ``EXULANICA_PROJECTS_MAXIMUM`` bounds how many folders it
follows (64 unless stated) and ``EXULANICA_PROJECT_FINISH_SECONDS`` how long stopping may spend
recording (60 unless stated).

**Stopping.** SIGTERM or SIGINT: the round in hand finishes, each project with pending changes
records them once within the finish deadline, and the process exits 0. One follower holds a
projects directory at a time; a second one refuses to start. Each event is one line of JSON on
standard output, naming a project folder by its name alone, never by its path.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from exulanica.env import env_get
from exulanica.world_package.projects.capture import read_token
from exulanica.world_package.projects.checkpoint import ProjectError
from exulanica.world_package.projects.follow import FINISH_SECONDS, MAXIMUM, Follower

__all__ = ["main"]


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "project-worker", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _settings(argv: Sequence[str] | None, environ: Mapping[str, str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="exulanica-project-worker", description=__doc__)
    parser.add_argument("--projects", default=env_get("PROJECTS_DIRECTORY", environ))
    parser.add_argument("--api", default=env_get("PROJECT_API_URL", environ))
    parser.add_argument("--token-file", default=env_get("PROJECT_TOKEN_FILE", environ))
    parser.add_argument("--maximum", default=env_get("PROJECTS_MAXIMUM", environ, str(MAXIMUM)))
    parser.add_argument(
        "--finish-seconds",
        default=env_get("PROJECT_FINISH_SECONDS", environ, str(int(FINISH_SECONDS))),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if None in (args.projects, args.api, args.token_file):
        raise ProjectError(
            "name the projects directory, the API origin and the token file "
            "(--projects, --api and --token-file)"
        )
    try:
        args.maximum = int(args.maximum)
        args.finish_seconds = int(args.finish_seconds)
    except ValueError as exc:
        raise ProjectError("the maximum and the finish seconds are whole numbers") from exc
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ
    try:
        args = _settings(argv, environment)
        follower = Follower(
            Path(args.projects),
            base_url=args.api,
            token=read_token(Path(args.token_file)),
            maximum=args.maximum,
            finish_seconds=args.finish_seconds,
        )
    except ProjectError as exc:
        # A refusal names what is wrong and never a value: no path, origin or token.
        _emit(output, "startup_failed", failure_class=type(exc).__name__, message=str(exc))
        return 1
    except OSError as exc:
        _emit(
            output,
            "startup_failed",
            failure_class=type(exc).__name__,
            message="the projects directory or the token file could not be read",
        )
        return 1
    stop = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        stop.set()

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        _emit(output, "startup", maximum=args.maximum, finish_seconds=args.finish_seconds)
        final = follower.run(stop, lambda outcome: _emit(output, "project", **outcome))
    finally:
        follower.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    _emit(output, "stopped", **final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
