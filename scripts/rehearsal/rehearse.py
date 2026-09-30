#!/usr/bin/env python3
"""Rehearse the first demonstration in the real application and write what every step showed.

    python3 scripts/rehearsal/rehearse.py --worktree PATH --slot N --out DIR [--model-env FILE]
        [--bound-usd USD] [--sessions ID,ID] [--timing-phase] [--reuse-database]
        [--launcher PATH] [--gpu-slot PATH]

The step list (``steps.json``), its gates (read from ``docs/product-direction.md``) and the drivers
all come from the tree this script is in. The application under test is the worktree ``--worktree``
names. In order, refusing at the first precondition that does not hold:

1.  Checks the step list is well formed, and refuses a run whose hosted-model steps are estimated
    above the step list's ``ask_before_usd``.
2.  Starts the acceptance runtime for that worktree on the slot with the acceptance launcher
    (``scripts/acceptance/launch.py`` in this tree by default; ``--launcher`` names another) and
    ``up --production``: the worktree's disposable test server, a fresh synthetic workspace with
    its own token, the API, and the application built for production with no development token in
    the build environment and served by ``vite preview`` on the slot's application port, proxying
    ``/api`` to the API. The launcher also gets the step list's ``runtime.society_playback``
    flags (``--society-playback``), so the API plays the run's own workspace at the host's
    declared pace and ``up`` refuses unless readiness reports it played. With ``--model-env``
    the launcher runs with ``--model``: a short child process reads the one variable
    ``NEBIUS_API_KEY`` from that file, puts it in its own
    environment with ``EXULANICA_EGRESS_ALLOWLIST`` set to the origins of the providers the
    worktree's model manifest binds a role to, as the worktree's own code derives them
    (``Manifest.bound_origins``), and replaces itself with the launcher, with the API's allocated
    bound as ``EXULANICA_BUDGET_USD`` so the API itself refuses a call past it. ``--bound-usd``
    lowers the total run cap and both process allocations. The key never enters this process, and
    nothing here prints, logs or writes it.
3.  Takes the launcher's record of that build (its script and index hashes, and the hash of the page
    the preview served) as this run's build, and checks the preview's ``/api`` proxy answers.
    The launcher starts the API with no derivative worker of its own (``--no-derivative-worker``);
    this script then starts each worker main runs in production that the step list's ``runtime``
    names by its command (the derivative worker), from that worktree's environment, over the run's workspace and database, with the
    environment the step list gives it (the derivative worker's depth model among it) and, for a
    worker that asks a model and with ``--model-env``, the key through the same child-process
    handoff. It waits for each worker's startup event and stops them before the launcher stops
    the API.
4.  Runs the sessions in step-list order. An orchestrator session is run here; a browser session is
    one ``node session.mjs`` process, one headless Chrome with one page, queued behind the
    machine's GPU slot (``.exulanica/bin/gpu-slot``) because browser work on this machine takes
    turns. A step that requires a step that did not pass is reported ``not_reachable`` with that
    reason; a hosted-model step is not started once reported spend reaches the step list's bound.
5.  With ``--timing-phase``, repeats the walker, host and menu timing observations after the
    functional sessions in a separate production-browser session. The caller takes gpu-slot,
    then quiet-slot; the timing driver refuses to start below 70 percent CPU idle over ten
    seconds and discards its measurements if the during-run mean is below 50 percent. It records
    its receipt and pictures separately from the loaded functional observations.
6.  Writes ``result.json`` (``result.schema.json``) and ``summary.txt``, checks that no file in the
    run directory or the production build holds the synthetic token, and stops everything it
    started, in every outcome.

Exit 0 when every step passed or is declared not available; 1 when a step failed or was not
reachable; 2 when a precondition refused the run; 3 when the token was found in the run directory
or the build.
Standard library only, like the launcher, so it imports nothing it measures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import resultdoc  # noqa: E402
import steplist  # noqa: E402

REHEARSAL_TREE = HERE.parents[1]
SESSION_DRIVER = HERE / "session.mjs"
PHOTOGRAPHS_DRIVER = HERE / "photographs.py"
#: Headless Chrome flags beyond the driver's own: draw WebGL on this Mac's GPU through Metal, as the
#: characters and world-scale runs did, rather than falling back to software rendering.
CHROME_GPU_FLAGS = ("--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist")
#: How long a browser session may wait for the machine's GPU slot before its budget starts. Another
#: lane's capture holds the slot for minutes, not hours (gpu-slot's own rule), so half an hour of
#: queueing means something is stuck and the run should say so rather than wait on.
GPU_SLOT_WAIT_SECONDS = 1800
#: Environment prefixes the launcher also drops, so nothing in the operator's shell can redirect a
#: build, a preview or a client to another database, model or token.
SCRUBBED_PREFIXES = ("EXULANICA_", "PG", "NEBIUS_", "VITE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_")

#: Reads exactly one variable from the operator's environment file, in its own process, and
#: replaces itself with the launcher. Every other line is skipped unparsed.
KEY_HANDOFF = r"""
import os, sys
path, allowlist, separator, *command = sys.argv[1:]
if separator != "--" or not command:
    raise SystemExit("usage: KEY_HANDOFF FILE ALLOWLIST -- COMMAND...")
name = "NEBIUS_API_KEY"
key = None
with open(path, encoding="utf-8") as handle:
    for line in handle:
        text = line.strip()
        if text.startswith("export "):
            text = text[len("export "):].lstrip()
        if not text.startswith(name + "="):
            continue
        value = text[len(name) + 1:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        key = value or None
        break
if key is None:
    raise SystemExit(name + " is absent from the model environment file")
environment = dict(os.environ)
environment[name] = key
environment["EXULANICA_EGRESS_ALLOWLIST"] = allowlist
os.execvpe(command[0], command, environment)
"""


class Refused(Exception):
    """A precondition of the run does not hold; the message says which."""


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def clean_environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(SCRUBBED_PREFIXES)}


def scrub(text: str) -> str:
    return text.replace(str(Path.home()), "<home>")


def git(tree: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tree), *arguments], capture_output=True, text=True, check=True
    ).stdout.strip()


def tree_identity(tree: Path) -> dict[str, str]:
    diff = subprocess.run(
        ["git", "-C", str(tree), "diff", "HEAD", "--binary"], capture_output=True, check=True
    ).stdout
    return {
        "head": git(tree, "rev-parse", "HEAD"),
        "diff_head_sha256": hashlib.sha256(diff).hexdigest(),
    }


def main_checkout(tree: Path) -> Path:
    """The main checkout, found from git: the parent of the tree's common git directory."""
    return Path(git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent


def browser_slot_command(gpu: Path | None, quiet: Path | None, command: list[str]) -> list[str]:
    """Acquire GPU before quiet for every browser capture, including functional steps."""
    if gpu is None or quiet is None:
        raise Refused("browser capture requires both GPU and quiet slots")
    return [str(gpu), str(quiet), *command]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Refused(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http(
    url: str,
    token: str | None = None,
    method: str = "GET",
    body: object = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as refused:
        raw, status = refused.read(), refused.code
    text = raw.decode(errors="replace")
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


def wait_http(url: str, seconds: float) -> tuple[int, Any]:
    deadline = time.monotonic() + seconds
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            return http(url, timeout=5)
        except OSError as error:
            last = str(error)
        time.sleep(0.5)
    raise Refused(f"{url} did not answer within {seconds:.0f} s ({last})")


def worker_events(log: Path) -> list[dict[str, Any]]:
    """The JSON events a worker command wrote to its log; other lines (library output) skipped."""
    if not log.exists():
        return []
    events = []
    for line in log.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "event" in event:
            events.append(event)
    return events


def run_bounds(steps: Mapping[str, Any], requested: str | None) -> tuple[Decimal, Decimal, Decimal]:
    """Total, API and worker money ceilings; an override reduces both process ceilings."""
    spend = steps["spend"]
    ceiling = Decimal(spend["total_cap_usd"])
    api = Decimal(spend["bound_usd"])
    worker = Decimal(spend["worker_bound_usd"])
    if requested is None:
        return ceiling, api, worker
    try:
        bound = Decimal(requested)
    except (InvalidOperation, TypeError):
        bound = None
    if bound is None or not bound.is_finite() or not Decimal(0) < bound <= ceiling:
        raise Refused(
            f"--bound-usd {requested!r} must be a decimal above 0 and at most the step list's "
            f"total cap of {ceiling} USD"
        )
    api = min(api * bound / ceiling, bound)
    worker = min(worker * bound / ceiling, bound - api)
    return bound, api, worker


def page_deadlines(worktree: Path, source: Mapping[str, Any]) -> dict[str, int]:
    """The page's own deadlines, in milliseconds, read from the application's source.

    ``source`` names the file and the constants (``runtime.answer_deadlines`` in the step list).
    A constant that is missing or not a plain integer refuses the run, so the driver never waits
    on a number that is not the one the page it drives was built with.
    """
    text = (worktree / source["file"]).read_text(encoding="utf-8")
    found: dict[str, int] = {}
    for name in source["constants"]:
        match = re.search(rf"^const {re.escape(name)} = ([0-9_]+);$", text, re.MULTILINE)
        if match is None:
            raise Refused(f"{source['file']} states no plain integer {name}")
        found[name] = int(match.group(1).replace("_", ""))
    return found


#: What the worktree's own interpreter prints for ``model_allowlist``: the manifest's one derivation.
_BOUND_ORIGINS = (
    "import json; from exulanica.models.manifest import load_manifest; "
    "print(json.dumps(sorted(load_manifest().bound_origins())))"
)


def model_allowlist(worktree: Path) -> str:
    """The egress allowlist the API needs: the origins of the providers its bound roles use.

    Asked of the worktree's own interpreter, so this process still imports nothing it measures,
    and the origins are the manifest's one derivation (``Manifest.bound_origins``) rather than a
    second reading of its JSON. The child is given no variable of this process's environment but
    where to find its interpreter and its home.
    """
    python = worktree / ".venv" / "bin" / "python"
    with subprocess.Popen(
        [str(python), "-c", _BOUND_ORIGINS],
        cwd=worktree,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as child:
        out, err = child.communicate(timeout=120)
    if child.returncode != 0:
        raise Refused(f"the worktree could not name its model origins: {err.strip()[-300:]}")
    origins = json.loads(out)
    if not isinstance(origins, list) or not origins:
        raise Refused("the worktree's manifest names no model origin")
    return json.dumps(origins)


class Run:
    """One rehearsal run: its runtime, its outcomes and everything it must stop."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        self.worktree = Path(arguments.worktree).resolve()
        self.out = Path(arguments.out).resolve()
        self.slot = arguments.slot
        checkout = main_checkout(REHEARSAL_TREE)
        self.launcher_path = Path(
            arguments.launcher or REHEARSAL_TREE / "scripts" / "acceptance" / "launch.py"
        )
        gpu_slot = Path(arguments.gpu_slot or checkout / ".exulanica/bin/gpu-slot")
        self.gpu_slot = gpu_slot if gpu_slot.exists() else None
        quiet_slot = checkout / ".exulanica/bin/quiet-slot"
        self.quiet_slot = quiet_slot if quiet_slot.exists() else None
        self.steps, self.gates = steplist.load_checked()
        self.total_bound, self.bound, self.worker_bound = run_bounds(
            self.steps, arguments.bound_usd
        )
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.unreached: dict[str, str] = {}
        self.facts: dict[str, Any] = {}
        self.sessions_run: list[dict[str, Any]] = []
        self.timing_phase: dict[str, Any] | None = None
        self.timing_spend = Decimal(0)
        self.prepared: dict[str, dict[str, Any]] = {}
        self.launcher: ModuleType | None = None
        self.state: dict[str, Any] | None = None
        self.token: str | None = None
        self.preview_port: int | None = None
        self.build: dict[str, Any] = {}
        self.build_directory: Path | None = None
        self.model_configured = arguments.model_env is not None
        self.workers: dict[str, subprocess.Popen[bytes]] = {}
        self.worker_records: dict[str, dict[str, Any]] = {}
        self.deadlines: dict[str, int] = {}
        self.started_at = now()
        # Read when the run starts: a driver file edited while a run is going is not what ran.
        self.rehearsal_files = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(HERE.iterdir())
            if path.is_file()
        }

    # -- runtime --------------------------------------------------------------------------------

    def launcher_up(self) -> None:
        self.launcher = load_module("acceptance_launch", self.launcher_path)
        command = [
            sys.executable,
            str(self.launcher_path),
            "up",
            "--worktree",
            str(self.worktree),
            "--slot",
            str(self.slot),
        ]
        if self.arguments.reuse_database:
            command.append("--reuse-database")
        # The worker is this script's to start, as a deployment starts it: see worker_up.
        command.extend(["--production", "--no-derivative-worker"])
        # The host plays the run's own workspace, as the step list's living session needs.
        command.extend(self.steps["runtime"]["society_playback"]["launcher_flags"])
        if self.model_configured:
            command = [*self.key_handoff(), *command, "--model"]
        environment = clean_environment()
        if self.model_configured:  # the API itself then refuses a model call past the run's bound
            environment["EXULANICA_BUDGET_USD"] = str(self.bound)
            environment["EXULANICA_BUDGET_MAX_CALLS"] = str(self.steps["spend"]["max_calls"])
        completed = subprocess.run(command, capture_output=True, text=True, env=environment)
        (self.out / "launcher-up.txt").write_text(
            scrub(f"exit {completed.returncode}\n{completed.stdout}\n{completed.stderr}")
        )
        state_file = self.launcher.state_dir(self.worktree) / "state.json"
        if completed.returncode != 0:
            if state_file.exists():  # started some of it; `down` stops only what it started
                self.state = json.loads(state_file.read_text())
            raise Refused(f"the launcher refused: {completed.stderr.strip()[-600:]}")
        self.state = json.loads(state_file.read_text())
        self.token = Path(self.state["token_file"]).read_text().strip()
        # ``up --production`` serves the build on the slot's application port.
        self.preview_port = self.state["ports"]["vite"]

    def key_handoff(self) -> list[str]:
        """The child process that reads only the model key and replaces itself with a command."""
        return [
            sys.executable,
            "-c",
            KEY_HANDOFF,
            str(Path(self.arguments.model_env).resolve()),
            model_allowlist(self.worktree),
            "--",
        ]

    def workers_up(self) -> None:
        """Start every worker the step list's runtime names (an entry with a ``command``), in order."""
        for key, configured in self.steps["runtime"].items():
            if "command" in configured:
                self.worker_up(key, configured)

    def worker_up(self, key: str, configured: Mapping[str, Any]) -> None:
        """Start one worker main runs in production, as the step list configures it.

        The command is the worktree's own console script, over the run's database (the runtime
        role the launcher provisioned), data directory and workspace. The step list's environment
        is added to a clean one, and each variable its ``owner_environment`` names is the run
        database's owner URL, for a worker whose one write migration 0072 gives the owner alone.
        The key, when the run has a model and the entry says the worker asks one
        (``model_key``), comes through the same handoff as the API's, with the run's bound, so this
        process never holds it either.
        """
        assert self.state is not None
        program = self.worktree / ".venv" / "bin" / configured["command"]
        if not program.exists():
            raise Refused(f"the worktree has no {configured['command']} ({program})")
        environment = clean_environment() | dict(configured["environment"])
        environment |= {
            "EXULANICA_DATABASE_URL": self.state["database"]["runtime_url"],
            "EXULANICA_DATA_DIR": self.state["data_dir"],
            "EXULANICA_WORKSPACE_IDS": self.state["workspace_id"],
        }
        for name in configured.get("owner_environment", []):
            environment[name] = self.state["database"]["owner_url_for_evidence_reads"]
        command = [str(program), *configured.get("arguments", [])]
        with_key = self.model_configured and configured.get("model_key") is True
        if with_key:
            environment["EXULANICA_BUDGET_USD"] = str(self.worker_bound)
            environment["EXULANICA_BUDGET_MAX_CALLS"] = str(self.steps["spend"]["max_calls"])
            command = [*self.key_handoff(), *command]
        log_name = f"{key.replace('_', '-')}.log"
        log_file = self.out / log_name
        log = log_file.open("ab")
        self.workers[key] = subprocess.Popen(
            command,
            cwd=self.worktree,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=environment,
        )
        self.worker_records[key] = {
            "command": configured["command"],
            "arguments": list(configured.get("arguments", [])),
            "environment": dict(configured["environment"]),
            "owner_environment": list(configured.get("owner_environment", [])),
            "model": with_key,
            "log": log_name,
        }
        started = time.monotonic()
        deadline = started + configured["startup_seconds"]
        while time.monotonic() < deadline:
            events = worker_events(log_file)
            if any(e.get("event") == "startup" for e in events):
                self.worker_records[key]["startup_seconds"] = round(time.monotonic() - started, 1)
                return
            if any(e.get("event") == "startup_failed" for e in events) or self.workers[key].poll():
                break
            time.sleep(1)
        tail = scrub(log_file.read_text(errors="replace")[-800:])
        raise Refused(f"the {key.replace('_', ' ')} did not start: {tail}")

    def workers_down(self) -> None:
        for key, worker in self.workers.items():
            if worker.poll() is None:
                os.killpg(worker.pid, signal.SIGTERM)
                try:
                    worker.wait(timeout=self.steps["runtime"][key]["stop_seconds"])
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.wait()
            record = self.worker_records[key]
            record["exit"] = worker.returncode
            record["events"] = sorted(
                {str(e.get("event")) for e in worker_events(self.out / record["log"])}
            )

    def verify_town_worker(self) -> None:
        """Tie the launcher's actual bake events to the saved town's tiles and live worker."""
        outcome = self.outcomes.get("make-town-with-values")
        if outcome is None or outcome.get("status") == "not_reachable":
            return
        assert self.state is not None and self.launcher is not None
        observed_tiles = next(
            (
                item.get("observed", {}).get("tiles", [])
                for item in outcome.get("observations", [])
                if item.get("id") == "tiles-baked"
            ),
            [],
        )
        world_id = self.facts.get("town", {}).get("world_id")
        events = self.launcher.tile_worker_events(
            Path(self.state["run_dir"]) / "logs" / "generated-tile-worker.log"
        )
        baked = {
            (
                event.get("tile", [None, None])[0],
                event.get("tile", [None, None])[1],
                event.get("baked_tile_id"),
            )
            for event in events
            if event.get("event") == "bake"
            and event.get("status") == "baked"
            and event.get("world_id") == world_id
            and isinstance(event.get("tile"), list)
            and len(event["tile"]) == 2
        }
        expected = {
            (tile.get("tile_x"), tile.get("tile_y"), tile.get("baked_tile_id"))
            for tile in observed_tiles
            if tile.get("state") == "baked"
        }
        running = self.launcher.tile_worker_running(self.state)
        outcome.setdefault("observations", []).append(
            {
                "id": "launcher-worker-baked-town",
                "ok": bool(world_id) and bool(expected) and expected <= baked and running,
                "observed": {
                    "world_id": world_id,
                    "expected": sorted(expected),
                    "reported_baked": sorted(baked),
                    "worker_running": running,
                },
            }
        )

    def verify_town_arrival(self) -> None:
        """Measure the saved town's receipt and occupied geometry after its browser first frame."""
        outcome = self.outcomes.get("make-town-with-values")
        if outcome is None or outcome.get("status") == "not_reachable":
            return
        assert self.state is not None and self.token is not None
        try:
            status, listed = http(f"{self.api}/world-entries", token=self.token)
        except OSError as error:
            status, listed = None, None
            read_error = type(error).__name__
        else:
            read_error = None
        town = self.facts.get("town", {})
        entry = (
            next(
                (item for item in listed if item.get("entry_id") == town.get("entry_id")),
                None,
            )
            if status == 200 and isinstance(listed, list)
            else None
        )
        observed: dict[str, Any] = {
            "entry_status": status,
            "entry_found": entry is not None,
            "read_error": read_error,
        }
        if entry is not None and entry.get("generated_ground") is not None:
            command = [
                str(self.worktree / ".venv/bin/python"),
                str(HERE / "town_arrival_check.py"),
                "--workspace",
                self.state["workspace_id"],
                "--world",
                entry["world_id"],
                "--snapshot",
                entry["source_snapshot_id"],
            ]
            environment = clean_environment() | {
                "EXULANICA_DATABASE_URL": self.state["database"]["owner_url_for_evidence_reads"]
            }
            try:
                checked = subprocess.run(
                    command,
                    cwd=self.worktree,
                    env=environment,
                    input=json.dumps(entry["generated_ground"]),
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                observed["checker_exit"] = checked.returncode
                if checked.returncode in (0, 1):
                    observed["measurement"] = json.loads(checked.stdout)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                observed["checker_error"] = type(error).__name__
        outcome.setdefault("observations", []).append(
            {
                "id": "town-arrival-objects-clear",
                "ok": observed.get("checker_exit") == 0
                and observed.get("measurement", {}).get("ok") is True,
                "observed": observed,
            }
        )

    def launcher_down(self) -> None:
        if (
            self.launcher is None
            or not (self.launcher.state_dir(self.worktree) / "state.json").exists()
        ):
            return
        completed = subprocess.run(
            [sys.executable, str(self.launcher_path), "down", "--worktree", str(self.worktree)],
            capture_output=True,
            text=True,
            env=clean_environment(),
        )
        (self.out / "launcher-down.txt").write_text(
            scrub(f"exit {completed.returncode}\n{completed.stdout}\n{completed.stderr}")
        )

    def take_build(self) -> None:
        """Take the production build the launcher made and serves as this run's application.

        ``up --production`` built it with no development token in its environment and serves it
        with ``vite preview``; this records what was built and what the preview served, and checks
        that the preview's ``/api`` proxy answers.
        """
        assert self.state is not None and self.preview_port is not None
        app = self.state.get("app") or {}
        if app.get("mode") != "production" or "build" not in app:
            raise Refused(
                f"the launcher served no production build (mode {app.get('mode')!r}); "
                "a launcher without up --production cannot run the rehearsal"
            )
        self.build_directory = Path(self.state["run_dir"]) / "app-build"
        self.build = {
            **app["build"],
            "mode": "production",
            "made_by": "the acceptance launcher, up --production",
            "served_index_sha256": app["served_index_sha256"],
            "served_index_is_the_build": app["served_index_is_the_build"],
        }
        status, _ = wait_http(f"http://localhost:{self.preview_port}/api/healthz", 60)
        if status != 200:
            raise Refused(f"the preview's /api proxy answered {status}")
        self.deadlines = page_deadlines(self.worktree, self.steps["runtime"]["answer_deadlines"])

    @property
    def api(self) -> str:
        assert self.state is not None
        return f"http://127.0.0.1:{self.state['ports']['api']}"

    @property
    def app_url(self) -> str:
        return f"http://localhost:{self.preview_port}/"

    # -- steps ----------------------------------------------------------------------------------

    def status_of(self, step_id: str) -> str | None:
        outcome = self.outcomes.get(step_id)
        if outcome is None:
            return None
        step = next((item for item in self.steps["steps"] if item["id"] == step_id), None)
        if step is not None and steplist.timing_only_failure(step, outcome):
            return "passed"
        return outcome.get("status")

    def blocked(self, step: Mapping[str, Any], within: frozenset[str] = frozenset()) -> str | None:
        """Why a step cannot be reached now, or None. ``within`` are its own session's steps, whose
        outcomes the browser driver checks as the session reaches them."""
        for required in step.get("requires", []):
            if required in within:
                continue
            status = self.status_of(required)
            if status != "passed":
                return f"requires {required}, which {'was ' + status if status else 'did not run'}"
        if step.get("hosted_model"):
            if not self.model_configured:
                return "no hosted model is configured for this run (pass --model-env)"
            if self.reported_spend() >= self.bound:
                return f"reported hosted spend reached the run's bound of {self.bound} USD"
        return None

    def reported_spend(self) -> Decimal:
        return self.timing_spend + sum(
            (Decimal(str(o.get("spend_usd", "0"))) for o in self.outcomes.values()), Decimal(0)
        )

    def run_sessions(self) -> None:
        selected = (
            None if self.arguments.sessions is None else set(self.arguments.sessions.split(","))
        )
        for session in self.steps["sessions"]:
            members = [s for s in self.steps["steps"] if s.get("session") == session["id"]]
            if selected is not None and session["id"] not in selected:
                for step in members:
                    self.unreached[step["id"]] = (
                        f"session {session['id']} was not selected for this run"
                    )
                continue
            if session["runner"] == "orchestrator":
                self.run_orchestrated(members)
            else:
                self.run_browser_session(session, members)
        if self.arguments.timing_phase:
            self.run_timing_phase()

    def run_timing_phase(self) -> None:
        """Repeat only the timing claims after the functional run, under both shared slots."""
        timing_ids = ("play-and-watch-walking", "birds-fly-and-perch")
        if self.gpu_slot is None:
            self.timing_phase = {"status": "slot_unavailable", "reason": "no GPU slot is available"}
            return
        if self.quiet_slot is None:
            self.timing_phase = {
                "status": "slot_unavailable",
                "reason": "no quiet slot is available",
            }
            return
        if any(self.status_of(step_id) != "passed" for step_id in timing_ids):
            self.timing_phase = {
                "status": "prerequisite_failed",
                "steps": {step_id: self.status_of(step_id) for step_id in timing_ids},
            }
            return
        starter = self.facts.get("entry_id")
        if not starter or not self.facts.get("world_id"):
            self.timing_phase = {"status": "starter_unknown"}
            return
        assert self.state is not None
        directory = self.out / "sessions" / "timing"
        directory.mkdir(parents=True, exist_ok=False)
        members = [step for step in self.steps["steps"] if step["id"] in timing_ids]
        budget_seconds = 660
        plan = {
            "session": {
                "id": "timing",
                "budget_seconds": budget_seconds,
                "instruments": ["walker-positions", "bird-positions"],
            },
            "steps": members,
            "statuses": {key: self.status_of(key) for key in self.outcomes},
            "facts": {**self.facts, "open_entry_id": starter},
            "runtime": {
                "app_url": self.app_url,
                "api_base": self.api,
                "token_file": self.state["token_file"],
                "browser_port": self.state["ports"]["browser"],
                "chrome_flags": list(CHROME_GPU_FLAGS),
                "hosted_model": self.model_configured,
                "spend_bound_usd": str(self.bound),
                "spend_reported_usd": str(self.reported_spend()),
                "page_deadlines_ms": self.deadlines,
                "stand_ins": self.steps["stand_ins"],
            },
            "out": str(directory),
        }
        plan_file = directory / "plan.json"
        plan_file.write_text(json.dumps(plan, indent=2))
        receipt_file = directory / "timing-receipt.json"
        command = [
            str(self.gpu_slot),
            str(self.quiet_slot),
            sys.executable,
            str(HERE / "timing_phase.py"),
            "--plan",
            str(plan_file),
            "--receipt",
            str(receipt_file),
            "--timeout-seconds",
            str(budget_seconds + 30),
        ]
        with (directory / "slot.log").open("wb") as output:
            process = subprocess.Popen(
                command,
                cwd=REHEARSAL_TREE,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=clean_environment(),
                start_new_session=True,
            )
            try:
                process.wait(timeout=budget_seconds + GPU_SLOT_WAIT_SECONDS + 90)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        receipt = (
            json.loads(receipt_file.read_text())
            if receipt_file.exists()
            else {
                "status": "receipt_missing",
                "slot_exit": process.returncode,
            }
        )
        session_file = directory / "session.json"
        session = json.loads(session_file.read_text()) if session_file.exists() else {}
        self.timing_phase = {
            **receipt,
            "slot_exit": process.returncode,
            "application_tree": self.state.get("tree"),
            "served_index_sha256": self.build.get("served_index_sha256"),
            "outcomes": {
                step_id: {
                    "status": outcome.get("status"),
                    "reason": outcome.get("reason"),
                    "observations": [
                        {"id": item["id"], "ok": item["ok"]}
                        for item in outcome.get("observations", [])
                    ],
                    "screenshots": outcome.get("evidence", {}).get("screenshots", []),
                    "spend_usd": outcome.get("spend_usd"),
                }
                for step_id, outcome in session.get("outcomes", {}).items()
            },
        }
        self.timing_spend = sum(
            (
                Decimal(str(outcome.get("spend_usd") or "0"))
                for outcome in session.get("outcomes", {}).values()
            ),
            Decimal(0),
        )

    def run_orchestrated(self, members: list[Mapping[str, Any]]) -> None:
        for step in members:
            reason = self.blocked(step)
            if reason is not None:
                self.outcomes[step["id"]] = {"status": "not_reachable", "reason": reason}
                continue
            handler = ORCHESTRATED.get(step["id"])
            if handler is None:
                self.outcomes[step["id"]] = {
                    "status": "not_reachable",
                    "reason": "no orchestrator handler is registered for it",
                }
                continue
            started = now()
            observations: list[dict[str, Any]] = []
            evidence: dict[str, Any] = {}

            def observe(
                identifier: str, ok: bool, observed: object, into: list = observations
            ) -> None:
                into.append({"id": identifier, "ok": bool(ok), "observed": observed})

            try:
                handler(self, step, observe, evidence)
                status, reason = "passed", None
            except Exception as error:  # every failure is reported, with its type
                status, reason = "failed", f"{type(error).__name__}: {error}"
            if status == "passed" and not all(o["ok"] for o in observations):
                status = "failed"
                reason = "did not hold: " + ", ".join(o["id"] for o in observations if not o["ok"])
            spend = evidence.pop("spend_usd", None)
            self.outcomes[step["id"]] = {
                "status": status,
                "reason": reason,
                "observations": observations,
                "evidence": evidence,
                **({} if spend is None else {"spend_usd": spend}),
                "started_at": started,
                "finished_at": now(),
            }

    def run_browser_session(
        self, session: Mapping[str, Any], members: list[Mapping[str, Any]]
    ) -> None:
        assert self.state is not None
        directory = self.out / "sessions" / session["id"]
        directory.mkdir(parents=True, exist_ok=True)
        plan_steps = []
        within = frozenset(step["id"] for step in members)
        for step in members:
            reason = self.blocked(step, within)
            if reason is not None:
                self.outcomes[step["id"]] = {"status": "not_reachable", "reason": reason}
                continue
            plan_steps.append(step)
        if not plan_steps:
            return
        prepared: dict[str, Any] = {}
        if session.get("prepare") is not None:
            preparation = PREPARATIONS.get(session["prepare"])
            try:
                if preparation is None:
                    raise Refused(f"no preparation named {session['prepare']!r} is registered")
                prepared = preparation(self, session, directory)
            except (Refused, subprocess.CalledProcessError, OSError, ValueError) as error:
                for step in plan_steps:
                    self.outcomes[step["id"]] = {
                        "status": "not_reachable",
                        "reason": f"the session's preparation {session['prepare']} failed: {error}",
                    }
                return
            self.prepared[session["id"]] = prepared
        plan = {
            "session": {
                "id": session["id"],
                "budget_seconds": session["budget_seconds"],
                "instruments": session.get("instruments", []),
            },
            "steps": plan_steps,
            "statuses": {k: self.status_of(k) for k in self.outcomes},
            "facts": self.facts,
            "runtime": {
                "app_url": self.app_url,
                "api_base": self.api,
                "token_file": self.state["token_file"],
                "browser_port": self.state["ports"]["browser"],
                "chrome_flags": list(CHROME_GPU_FLAGS),
                "hosted_model": self.model_configured,
                "spend_bound_usd": str(self.bound),
                "spend_reported_usd": str(self.reported_spend()),
                "page_deadlines_ms": self.deadlines,
                "stand_ins": self.steps["stand_ins"],
                **prepared,
            },
            "out": str(directory),
        }
        plan_file = directory / "plan.json"
        plan_file.write_text(json.dumps(plan, indent=2))
        command = browser_slot_command(
            self.gpu_slot, self.quiet_slot, ["node", str(SESSION_DRIVER), str(plan_file)]
        )
        started = time.monotonic()
        log = (directory / "session.log").open("ab")
        process = subprocess.Popen(
            command,
            cwd=REHEARSAL_TREE,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=clean_environment(),
        )
        timed_out = False
        try:
            process.wait(timeout=session["budget_seconds"] + GPU_SLOT_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        # The driver stops its Chrome itself; this makes sure no Chrome outlives the session.
        subprocess.run(["pkill", "-f", str(directory / "chrome-profile")], check=False)
        report_file = directory / "session.json"
        report = json.loads(report_file.read_text()) if report_file.exists() else {}
        self.facts.update(report.get("facts", {}))
        for step_id, outcome in report.get("outcomes", {}).items():
            self.outcomes[step_id] = outcome
        if session["id"] == "town":
            self.verify_town_worker()
            self.verify_town_arrival()
        tail = scrub((directory / "session.log").read_text(errors="replace")[-1500:])
        for step in plan_steps:
            if step["id"] not in self.outcomes:
                self.unreached[step["id"]] = report.get("unreached", {}).get(step["id"]) or (
                    f"the page session ended before this step (exit {process.returncode}"
                    f"{', stopped after its time allowance' if timed_out else ''}); log tail: {tail}"
                )
        self.sessions_run.append(
            {
                "id": session["id"],
                "exit": process.returncode,
                "timed_out": timed_out,
                "seconds": round(time.monotonic() - started, 1),
                "gpu_slot": self.gpu_slot is not None,
                "chrome_argv": report.get("chrome_argv"),
            }
        )

    # -- result ---------------------------------------------------------------------------------

    def leak_check(self) -> list[str]:
        """Every file of the run directory or the production build that holds the token."""
        if self.token is None:
            return []
        needle = self.token.encode()
        places = [(self.out, self.out)]
        if self.build_directory is not None and self.build_directory.is_dir():
            places.append((self.build_directory, self.build_directory.parent))
        return sorted(
            str(path.relative_to(base))
            for root, base in places
            for path in root.rglob("*")
            if path.is_file() and needle in path.read_bytes()
        )

    def write_result(self) -> dict[str, Any]:
        state = self.state or {}
        run = {
            "started_at": self.started_at,
            "finished_at": now(),
            "command": [scrub(a) for a in sys.argv],
            "rehearsal_tree": tree_identity(REHEARSAL_TREE),
            # The files that ran, by content: a tree's diff does not see files git does not track.
            "rehearsal_files": self.rehearsal_files,
            "steps_sha256": steplist.digest(),
            "application_tree": state.get("tree"),
            "runtime": {
                "slot": self.slot,
                "ports": {**state.get("ports", {}), "preview": self.preview_port},
                "workspace": "a fresh synthetic workspace minted by the acceptance launcher for this run",
                "workspace_id": state.get("workspace_id"),
                "api_imported_exulanica_from": scrub(str(state.get("api_imported_exulanica_from"))),
                **self.worker_records,
                "launcher_tile_worker": {
                    "events": self.launcher.tile_worker_events(
                        Path(state["run_dir"]) / "logs" / "generated-tile-worker.log"
                    )
                    if self.launcher is not None and state.get("run_dir")
                    else [],
                },
                "launcher_in_process_worker": state.get("derivative_worker"),
                "page_deadlines_ms": self.deadlines,
                "society_playback": state.get("society_playback"),
                "launcher": scrub(str(self.launcher_path)),
            },
            "build": self.build,
            "access": (
                "the production build's credential gate: the launcher's synthetic token typed "
                "into its access-token field, on every page load; the account sign-in path is "
                "not exercised because the launcher configures none"
            ),
            "model": {
                "configured": self.model_configured,
                "allowlist": json.loads(model_allowlist(self.worktree))
                if self.model_configured
                else [],
                "credential": (
                    "read by a child process from the named environment file, by environment only"
                    if self.model_configured
                    else None
                ),
                "spend": {
                    "bound_usd": str(self.bound),
                    "worker_bound_usd": str(self.worker_bound),
                    "effective_total_cap_usd": str(self.total_bound),
                    "requested_total_cap_usd": self.arguments.bound_usd,
                    "step_list_total_cap_usd": self.steps["spend"]["total_cap_usd"],
                    "step_list_bound_usd": self.steps["spend"]["bound_usd"],
                    "ask_before_usd": self.steps["spend"]["ask_before_usd"],
                    "estimate_usd": str(steplist.spend_estimate(self.steps)),
                    "reported_usd": str(self.reported_spend()),
                },
            },
            "browser": {"gpu_slot": self.gpu_slot is not None, "sessions": self.sessions_run},
            "timing_phase": self.timing_phase,
            "prepared": {
                session: {key: value for key, value in inputs.items() if key != "photographs"}
                | {
                    "photographs": [
                        {k: v for k, v in photograph.items() if k != "path"}
                        for photograph in inputs.get("photographs", [])
                    ]
                }
                for session, inputs in self.prepared.items()
            },
            "facts": self.facts,
        }
        document = resultdoc.assemble(self.steps, self.gates, self.outcomes, self.unreached, run)
        (self.out / "result.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        (self.out / "summary.txt").write_text(summary(document))
        return document


def summary(document: Mapping[str, Any]) -> str:
    lines = [f"{'STEP':44} STATUS          REASON"]
    for step in document["steps"]:
        reason = (step.get("reason") or "").replace("\n", " ")
        lines.append(f"{step['id']:44} {step['status']:15} {reason[:160]}")
    lines.append("")
    lines.append(f"{'GATE':44} STATUS              FIRST FAILURE (OWNER AREA)")
    for gate in document["gates"]:
        failure = gate["first_failure"]
        first = "" if failure is None else f"{failure['step']} ({failure['owner_area']})"
        if gate["status"] == "not_served":
            first = gate["reason"]
        lines.append(f"{gate['gate']:44} {gate['status']:19} {first}")
        lines.extend(f"{'':44} {qualification}" for qualification in gate["qualification"])
    phase = document["run"].get("timing_phase")
    if phase is not None:
        lines.append("")
        lines.append(
            "TIMING PHASE: "
            + str(phase.get("status"))
            + f" (idle before {phase.get('idle_before_percent')}%, mean {phase.get('idle_mean_percent')}%)"
        )
    return "\n".join(lines) + "\n"


# -- orchestrated steps -------------------------------------------------------------------------

Observe = Callable[[str, bool, object], None]


def clean_start(
    run: Run, step: Mapping[str, Any], observe: Observe, evidence: dict[str, Any]
) -> None:
    assert run.state is not None and run.token is not None
    status, entries = http(f"{run.api}/world-entries", run.token)
    evidence["GET /world-entries"] = {"status": status, "body": entries}
    observe(
        "no-saved-world-yet",
        status == 200 and entries == [],
        {"status": status, "entries": entries},
    )
    ready = run.state.get("api_health", {}).get("readyz", [None])[0]
    status, health = http(f"http://localhost:{run.preview_port}/api/healthz")
    observe(
        "runtime-ready",
        ready == 200 and status == 200,
        {"api_readyz": ready, "preview_proxy_healthz": status, "body": health},
    )
    with urllib.request.urlopen(run.app_url, timeout=10) as response:
        served = response.read()
    assert run.build_directory is not None
    built = (run.build_directory / "index.html").read_bytes()
    observe(
        "production-build-served",
        served == built,
        {
            "served_index_sha256": hashlib.sha256(served).hexdigest(),
            "built_index_sha256": hashlib.sha256(built).hexdigest(),
        },
    )


def developer_client(
    run: Run, step: Mapping[str, Any], observe: Observe, evidence: dict[str, Any]
) -> None:
    assert run.token is not None
    parameters = step["parameters"]
    # The starter the person named and built in: the made world beside it holds no object of the
    # person's, and the client is sent to the world the application saved first.
    status, entries = http(f"{run.api}/world-entries", run.token)
    named = (
        [e for e in entries if e.get("entry_id") == run.facts.get("entry_id")]
        if status == 200
        else []
    )
    if len(named) != 1:
        raise AssertionError(f"expected the person's saved starter, found {status} {entries}")
    entry = named[0]
    status, assets = http(f"{run.api}/world/assets", run.token)
    available = [a["asset_key"] for a in assets if a.get("availability") == "available"]
    if not available:
        raise AssertionError(f"no reviewed asset is available to place: {assets}")
    directory = run.out / "developer-client"
    directory.mkdir(parents=True, exist_ok=True)
    transcript = directory / "walkthrough.json"
    argv = [
        sys.executable,
        "-S",
        "-s",
        "-E",
        "-m",
        "exulanica_client",
        "walkthrough",
        "--base-url",
        run.api,
        "--entry",
        entry["entry_id"],
        "--asset-key",
        available[0],
        "--origin-role",
        parameters["origin_role"],
        "--place",
        parameters["place_mm"],
        "--object-id",
        parameters["object_id"],
        "--transcript",
        str(transcript),
    ]
    completed = subprocess.run(
        argv,
        cwd=run.worktree / "clients/python",
        capture_output=True,
        text=True,
        timeout=300,
        env={"EXULANICA_TOKEN": run.token, "PATH": "/usr/bin:/bin"},
    )
    (directory / "client-output.txt").write_text(
        scrub(
            f"exit {completed.returncode}\n# stdout\n{completed.stdout}# stderr\n{completed.stderr}"
        )
    )
    record = json.loads(transcript.read_text()) if transcript.exists() else {}
    evidence["client"] = {
        "argv": [scrub(a) for a in argv[:-1]] + ["<run>/developer-client/walkthrough.json"],
        "interpreter_flags": "-S -s -E: no site-packages, no user site, no PYTHON* environment",
        "exit": completed.returncode,
        "transcript": "developer-client/walkthrough.json",
    }
    discovered = {(e["method"], e["path"]) for e in record.get("discovered", {}).get("edits", [])}
    observe(
        "discovers-capabilities",
        ("POST", "/world/versions/{version_id}/objects") in discovered
        and ("POST", "/world/versions/{version_id}/objects/{object_id}/behaviour") in discovered,
        sorted(" ".join(pair) for pair in discovered),
    )
    before = record.get("saved_world_before", {})
    observe(
        "reads-the-saved-version",
        before.get("entry_id") == entry["entry_id"]
        and before.get("authored_version_id") == entry["authored_version_id"],
        {
            "client_read": before,
            "person_saved": {
                k: entry[k] for k in ("entry_id", "authored_version_id", "authored_state_sha256")
            },
        },
    )
    refusal = record.get("refusal") or {}
    observe(
        "unsupported-edit-refused",
        refusal.get("status") == 422 and bool(refusal.get("detail")),
        refusal,
    )
    checks = record.get("checks", [])
    observe(
        "accepted-edit-confirmed",
        completed.returncode == 0
        and record.get("result") == "confirmed"
        and bool(checks)
        and all(c["holds"] for c in checks),
        {
            "result": record.get("result"),
            "reason": record.get("reason"),
            "failed_checks": [c for c in checks if not c["holds"]],
        },
    )
    run.facts["client_object_id"] = parameters["object_id"]
    run.facts["client_asset_key"] = available[0]


def developer_reads_comparison(
    run: Run, step: Mapping[str, Any], observe: Observe, evidence: dict[str, Any]
) -> None:
    """The developer client reads the comparison the owner started in the application.

    ``python -m exulanica_client comparisons`` with the run's token, which holds ``world.read``,
    over the town the comparison was started in, named by its world and version. The client reads
    the comparison, every run's outcome and each completed model run replayed with its decisions,
    and makes its own checks; this step records its transcript and compares what it read with
    what the compare step started.
    """
    assert run.token is not None
    started = run.facts.get("comparison") or {}
    if not started.get("comparison_id") or not started.get("world_id"):
        raise AssertionError(f"no comparison started in the application is recorded: {started}")
    directory = run.out / "developer-client"
    directory.mkdir(parents=True, exist_ok=True)
    transcript = directory / "comparison.json"
    argv = [
        sys.executable,
        "-S",
        "-s",
        "-E",
        "-m",
        "exulanica_client",
        "comparisons",
        "--base-url",
        run.api,
        "--world",
        started["world_id"],
        "--version",
        started["version_id"],
        "--comparison",
        started["comparison_id"],
        "--transcript",
        str(transcript),
    ]
    completed = subprocess.run(
        argv,
        cwd=run.worktree / "clients/python",
        capture_output=True,
        text=True,
        timeout=step["parameters"]["timeout_seconds"],
        env={"EXULANICA_TOKEN": run.token, "PATH": "/usr/bin:/bin"},
    )
    (directory / "comparison-output.txt").write_text(
        scrub(
            f"exit {completed.returncode}\n# stdout\n{completed.stdout}# stderr\n{completed.stderr}"
        )
    )
    record = json.loads(transcript.read_text()) if transcript.exists() else {}
    evidence["client"] = {
        "argv": [scrub(a) for a in argv[:-1]] + ["<run>/developer-client/comparison.json"],
        "interpreter_flags": "-S -s -E: no site-packages, no user site, no PYTHON* environment",
        "exit": completed.returncode,
        "transcript": "developer-client/comparison.json",
    }
    checks = record.get("checks", [])
    read = record.get("comparison") or {}
    observe(
        "client-read-the-comparison",
        completed.returncode == 0
        and record.get("result") == "confirmed"
        and bool(checks)
        and all(c["holds"] for c in checks),
        {
            "result": record.get("result"),
            "reason": record.get("reason"),
            "checks": checks,
            "runs": read.get("runs"),
        },
    )
    deciders = sorted(
        str((arm.get("decider") or {}).get("model_id"))
        for arm in read.get("arms", [])
        if arm.get("role") == "candidate"
    )
    wanted = sorted({str(model["model_id"]) for model in started.get("models", [])})
    observe(
        "same-comparison",
        read.get("comparison_id") == started["comparison_id"] and sorted(set(deciders)) == wanted,
        {
            "read": {k: read.get(k) for k in ("comparison_id", "phase", "arms", "verdict")},
            "started": started,
        },
    )


#: Where the judge seed the run exports is written, inside the run directory.
JUDGE_SEED_ARCHIVE = "judge-seed"
#: A database name the restore step creates on the run's own server: letters, digits, underscores.
_FRESH_DATABASE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _seed_command(
    run: Run, arguments: list[str], environment: Mapping[str, str], timeout: int, log: str
) -> subprocess.CompletedProcess[str]:
    """One ``exulanica-seed`` (or other application console script) run, its output kept."""
    completed = subprocess.run(
        [str(run.worktree / ".venv" / "bin" / arguments[0]), *arguments[1:]],
        cwd=run.worktree,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=clean_environment() | dict(environment),
    )
    with (run.out / log).open("a") as handle:
        handle.write(
            scrub(
                f"$ {' '.join(arguments[:2])}\nexit {completed.returncode}\n"
                f"{completed.stdout}{completed.stderr}\n"
            )
        )
    return completed


def export_judge_seed(
    run: Run, step: Mapping[str, Any], observe: Observe, evidence: dict[str, Any]
) -> None:
    """Export the run's workspace as a judge seed with the application's own command, and verify it.

    ``exulanica-seed export`` reads the run's database as its owner and the run's data directory,
    as a deployment's seeding job would read a source, into the run directory.
    ``exulanica-seed verify`` then re-hashes every file of the archive against its manifest.
    """
    assert run.state is not None
    timeout = step["parameters"]["timeout_seconds"]
    archive = run.out / JUDGE_SEED_ARCHIVE
    source = {
        "EXULANICA_DATABASE_URL": run.state["database"]["owner_url_for_evidence_reads"],
        "EXULANICA_DATA_DIR": run.state["data_dir"],
    }
    exported = _seed_command(
        run,
        [
            "exulanica-seed",
            "export",
            "--workspace",
            run.state["workspace_id"],
            "--into",
            str(archive),
            "--created-at",
            run.started_at,
        ],
        source,
        timeout,
        "judge-seed.txt",
    )
    verified = _seed_command(
        run, ["exulanica-seed", "verify", "--archive", str(archive)], {}, timeout, "judge-seed.txt"
    )
    manifest_file = archive / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    size = sum(path.stat().st_size for path in archive.rglob("*") if path.is_file())
    evidence["archive"] = {
        "directory": JUDGE_SEED_ARCHIVE,
        "bytes": size,
        "log": "judge-seed.txt",
        "manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest()
        if manifest_file.exists()
        else None,
    }
    run.facts["judge_seed"] = dict(evidence["archive"])
    observe(
        "archive-written",
        exported.returncode == 0 and manifest.get("workspace_id") == run.state["workspace_id"],
        {
            "exit": exported.returncode,
            "output": scrub(exported.stderr[-600:] or exported.stdout[-600:]),
            "seed_format_version": manifest.get("seed_format_version"),
            "totals": manifest.get("totals"),
            "bytes": size,
        },
    )
    observe(
        "archive-verifies",
        verified.returncode == 0,
        {
            "exit": verified.returncode,
            "output": scrub(verified.stdout[-600:] + verified.stderr[-600:]),
        },
    )


def restore_judge_seed(
    run: Run, step: Mapping[str, Any], observe: Observe, evidence: dict[str, Any]
) -> None:
    """Restore the exported seed into a fresh database and an empty data directory, as the judge
    deployment's jobs do (``exulanica-db``, then ``exulanica-seed role`` and ``restore``), and read
    each generated world's tiles back from them (``seedcheck.py``). The fresh database is created
    on the run's own server and dropped afterwards."""
    assert run.state is not None
    parameters = step["parameters"]
    timeout = parameters["timeout_seconds"]
    name = f"{parameters['database_prefix']}_{os.getpid()}"
    if not _FRESH_DATABASE.match(name):
        raise AssertionError(f"not a database name this step creates: {name}")
    owner = run.state["database"]["owner_url_for_evidence_reads"]
    parts = urllib.parse.urlsplit(owner)
    fresh = urllib.parse.urlunsplit(parts._replace(path=f"/{name}"))
    python = str(run.worktree / ".venv" / "bin" / "python")
    administer = (
        "import psycopg, sys\n"
        "with psycopg.connect(sys.argv[1], autocommit=True) as c:\n"
        "    c.execute(sys.argv[2] + ' database ' + sys.argv[3] + sys.argv[4])\n"
    )

    def database(verb: str, suffix: str = "") -> int:
        return subprocess.run(
            [python, "-c", administer, owner, verb, name, suffix],
            env=clean_environment(),
            capture_output=True,
            timeout=timeout,
        ).returncode

    data = run.out / parameters["data_directory"]
    data.mkdir(parents=True, exist_ok=True)
    target = {"EXULANICA_DATABASE_URL": fresh, "EXULANICA_DATA_DIR": str(data)}
    created = database("create")
    try:
        migrated = _seed_command(run, ["exulanica-db"], target, timeout, "judge-restore.txt")
        role = _seed_command(
            run, ["exulanica-seed", "role", "--no-password"], target, timeout, "judge-restore.txt"
        )
        restored = _seed_command(
            run,
            ["exulanica-seed", "restore", "--archive", str(run.out / JUDGE_SEED_ARCHIVE)],
            target,
            timeout,
            "judge-restore.txt",
        )
        checked = subprocess.run(
            [python, str(HERE / "seedcheck.py"), run.state["workspace_id"]],
            cwd=run.worktree,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_environment() | target,
        )
    finally:
        dropped = database("drop", " with (force)") if created == 0 else None
    try:
        towns = json.loads(checked.stdout)["generated_worlds"]
    except (ValueError, KeyError):
        towns = None
    evidence["restore"] = {
        "log": "judge-restore.txt",
        "fresh_database": {"created": created == 0, "dropped": dropped == 0},
        "data_directory": parameters["data_directory"],
    }
    observe(
        "restored-and-verified",
        created == 0
        and migrated.returncode == 0
        and role.returncode == 0
        and restored.returncode == 0,
        {
            "migrate_exit": migrated.returncode,
            "role_exit": role.returncode,
            "restore_exit": restored.returncode,
            "restore_output": scrub(restored.stdout[-800:] + restored.stderr[-800:]),
        },
    )
    tiles = [tile for town in towns or [] for tile in town["tiles"]]
    observe(
        "towns-drawn-from-the-seed",
        bool(towns)
        and bool(tiles)
        and all(t["state"] == "baked" and t["bytes_held_to_digest"] is True for t in tiles),
        {
            "generated_worlds": towns,
            "check_exit": checked.returncode,
            "check_error": scrub(checked.stderr[-600:]),
        },
    )


def synthetic_photographs(run: Run, session: Mapping[str, Any], directory: Path) -> dict[str, Any]:
    """Draw the session's synthetic photographs with the application's own environment."""
    recipe = directory / "photographs-recipe.json"
    recipe.write_text(json.dumps(session["inputs"]["photographs"], indent=2))
    target = directory / "photographs"
    drawn = subprocess.run(
        [str(run.worktree / ".venv/bin/python"), str(PHOTOGRAPHS_DRIVER), str(recipe), str(target)],
        cwd=run.worktree,
        env=clean_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    photographs = json.loads(drawn.stdout)
    for photograph in photographs:
        photograph["path"] = str(target / photograph["file"])
    return {
        "photographs": photographs,
        "photographs_reason": session["inputs"]["photographs_reason"],
    }


#: Inputs a session needs made before its page opens, by the name its ``prepare`` gives.
PREPARATIONS: Mapping[str, Callable[[Run, Mapping[str, Any], Path], dict[str, Any]]] = {
    "synthetic-photographs": synthetic_photographs,
}


#: The steps this process performs itself, by step id. Every other runnable step is the browser
#: driver's; a test holds both registries to the step list.
ORCHESTRATED: Mapping[str, Callable[[Run, Mapping[str, Any], Observe, dict[str, Any]], None]] = {
    "clean-start": clean_start,
    "developer-client-walkthrough": developer_client,
    "developer-client-reads-the-comparison": developer_reads_comparison,
    "export-judge-seed": export_judge_seed,
    "restore-judge-seed-into-a-fresh-stack": restore_judge_seed,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--worktree", required=True, help="the worktree whose application is rehearsed"
    )
    parser.add_argument(
        "--slot", type=int, required=True, help="the acceptance launcher's port slot"
    )
    parser.add_argument("--out", required=True, help="a new directory for this run's result")
    parser.add_argument(
        "--model-env", help="the operator's environment file; only NEBIUS_API_KEY is read"
    )
    parser.add_argument(
        "--bound-usd",
        help="a total hosted-spend cap for this run at or below the step list's total_cap_usd",
    )
    parser.add_argument("--sessions", help="run only these sessions, comma separated")
    parser.add_argument(
        "--timing-phase",
        action="store_true",
        help="repeat timing claims under CPU idle and both shared slots",
    )
    parser.add_argument("--reuse-database", action="store_true")
    parser.add_argument(
        "--launcher", help="the acceptance launcher (default: scripts/acceptance/launch.py here)"
    )
    parser.add_argument(
        "--gpu-slot", help="the machine's GPU slot command (default: the main checkout's)"
    )
    arguments = parser.parse_args()
    out = Path(arguments.out)
    if out.exists() and any(out.iterdir()):
        print(f"refused: {out} is not empty; every run gets its own directory", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    try:
        run = Run(arguments)
    except (steplist.StepListError, Refused) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    estimate = steplist.spend_estimate(run.steps)
    if run.model_configured and estimate > Decimal(run.steps["spend"]["ask_before_usd"]):
        print(
            f"refused: hosted steps are estimated at {estimate} USD; decide before running",
            file=sys.stderr,
        )
        return 2
    refused = None
    try:
        run.launcher_up()
        run.take_build()
        run.workers_up()
        run.run_sessions()
    except Refused as error:
        refused = str(error)
    finally:
        run.workers_down()
        run.launcher_down()
    if refused is not None:
        for step in run.steps["steps"]:
            if step["id"] not in run.outcomes and step.get("not_available") is None:
                run.unreached.setdefault(
                    step["id"], f"the run was refused before this step: {refused}"
                )
    document = run.write_result()
    print(summary(document), end="")
    leaked = run.leak_check()
    if leaked:
        print(f"TOKEN FOUND in: {', '.join(leaked)}", file=sys.stderr)
        return 3
    if refused is not None:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    counts = document["summary"]
    if arguments.timing_phase:
        phase = document["run"].get("timing_phase") or {}
        timing = {
            (step_id, item["id"]): item["ok"]
            for step_id, outcome in phase.get("outcomes", {}).items()
            for item in outcome.get("observations", [])
        }
        needed = {
            (step["id"], identifier)
            for step in run.steps["steps"]
            for identifier in step.get("timing_observations", [])
        }
        if (
            phase.get("status") != "eligible"
            or not needed
            or not all(timing.get(key) is True for key in needed)
        ):
            return 1
    return 0 if counts["failed"] == 0 and counts["not_reachable"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
