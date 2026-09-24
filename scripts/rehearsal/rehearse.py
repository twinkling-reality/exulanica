#!/usr/bin/env python3
"""Rehearse the first demonstration in the real application and write what every step showed.

    python3 scripts/rehearsal/rehearse.py --worktree PATH --slot N --out DIR [--model-env FILE]
        [--sessions ID,ID] [--reuse-database] [--launcher PATH] [--gpu-slot PATH]

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
    ``/api`` to the API. With ``--model-env`` the launcher runs with ``--model``: a short child
    process reads the one variable ``NEBIUS_API_KEY`` from that file, puts it in its own
    environment with ``EXULANICA_EGRESS_ALLOWLIST`` set to the origin of the model manifest's
    ``base_url`` in the worktree, and replaces itself with the launcher, with the step list's
    ``spend.bound_usd`` as ``EXULANICA_BUDGET_USD`` so the API itself refuses a call past it. The key
    never enters this process, and nothing here prints, logs or writes it.
3.  Takes the launcher's record of that build (its script and index hashes, and the hash of the page
    the preview served) as this run's build, and checks the preview's ``/api`` proxy answers.
4.  Runs the sessions in step-list order. An orchestrator session is run here; a browser session is
    one ``node session.mjs`` process, one headless Chrome with one page, queued behind the
    machine's GPU slot (``.exulanica/bin/gpu-slot``) because browser work on this machine takes
    turns. A step that requires a step that did not pass is reported ``not_reachable`` with that
    reason; a hosted-model step is not started once reported spend reaches the step list's bound.
5.  Writes ``result.json`` (``result.schema.json``) and ``summary.txt``, checks that no file in the
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
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from decimal import Decimal
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


def model_allowlist(worktree: Path) -> str:
    """The egress allowlist the API needs: the origin of the manifest's endpoint, nothing more."""
    manifest = json.loads((worktree / "exulanica/models/models.manifest.json").read_text())
    endpoint = urllib.parse.urlsplit(manifest["base_url"])
    return json.dumps([f"{endpoint.scheme}://{endpoint.netloc}"])


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
        self.steps, self.gates = steplist.load_checked()
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.unreached: dict[str, str] = {}
        self.facts: dict[str, Any] = {}
        self.sessions_run: list[dict[str, Any]] = []
        self.prepared: dict[str, dict[str, Any]] = {}
        self.launcher: ModuleType | None = None
        self.state: dict[str, Any] | None = None
        self.token: str | None = None
        self.preview_port: int | None = None
        self.build: dict[str, Any] = {}
        self.build_directory: Path | None = None
        self.model_configured = arguments.model_env is not None
        self.started_at = now()

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
        command.append("--production")
        if self.model_configured:
            command = [
                sys.executable,
                "-c",
                KEY_HANDOFF,
                str(Path(self.arguments.model_env).resolve()),
                model_allowlist(self.worktree),
                "--",
                *command,
                "--model",
            ]
        environment = clean_environment()
        if self.model_configured:  # the API itself then refuses a model call past the run's bound
            environment["EXULANICA_BUDGET_USD"] = self.steps["spend"]["bound_usd"]
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
        return None if outcome is None else outcome.get("status")

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
            bound = Decimal(self.steps["spend"]["bound_usd"])
            if self.reported_spend() >= bound:
                return f"reported hosted spend reached the run's bound of {bound} USD"
        return None

    def reported_spend(self) -> Decimal:
        return sum(
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
            self.outcomes[step["id"]] = {
                "status": status,
                "reason": reason,
                "observations": observations,
                "evidence": evidence,
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
            "session": {"id": session["id"], "budget_seconds": session["budget_seconds"]},
            "steps": plan_steps,
            "statuses": {k: v["status"] for k, v in self.outcomes.items()},
            "facts": self.facts,
            "runtime": {
                "app_url": self.app_url,
                "api_base": self.api,
                "token_file": self.state["token_file"],
                "browser_port": self.state["ports"]["browser"],
                "chrome_flags": list(CHROME_GPU_FLAGS),
                "hosted_model": self.model_configured,
                "spend_bound_usd": self.steps["spend"]["bound_usd"],
                "spend_reported_usd": str(self.reported_spend()),
                **prepared,
            },
            "out": str(directory),
        }
        plan_file = directory / "plan.json"
        plan_file.write_text(json.dumps(plan, indent=2))
        command = ["node", str(SESSION_DRIVER), str(plan_file)]
        if self.gpu_slot is not None:
            command = [str(self.gpu_slot), *command]
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
            "rehearsal_files": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(HERE.iterdir())
                if path.is_file()
            },
            "steps_sha256": steplist.digest(),
            "application_tree": state.get("tree"),
            "runtime": {
                "slot": self.slot,
                "ports": {**state.get("ports", {}), "preview": self.preview_port},
                "workspace": "a fresh synthetic workspace minted by the acceptance launcher for this run",
                "workspace_id": state.get("workspace_id"),
                "api_imported_exulanica_from": scrub(str(state.get("api_imported_exulanica_from"))),
                "derivative_worker": state.get("derivative_worker"),
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
                    "bound_usd": self.steps["spend"]["bound_usd"],
                    "ask_before_usd": self.steps["spend"]["ask_before_usd"],
                    "estimate_usd": str(steplist.spend_estimate(self.steps)),
                    "reported_usd": str(self.reported_spend()),
                },
            },
            "browser": {"gpu_slot": self.gpu_slot is not None, "sessions": self.sessions_run},
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
    lines.append(f"{'GATE':44} STATUS          FIRST FAILURE (OWNER AREA)")
    for gate in document["gates"]:
        failure = gate["first_failure"]
        first = "" if failure is None else f"{failure['step']} ({failure['owner_area']})"
        lines.append(f"{gate['gate']:44} {gate['status']:15} {first}")
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
    status, entries = http(f"{run.api}/world-entries", run.token)
    if status != 200 or len(entries) != 1:
        raise AssertionError(f"expected the person's one saved world, found {status} {entries}")
    entry = entries[0]
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
    parser.add_argument("--sessions", help="run only these sessions, comma separated")
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
    except steplist.StepListError as error:
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
        run.run_sessions()
    except Refused as error:
        refused = str(error)
    finally:
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
    return 0 if counts["failed"] == 0 and counts["not_reachable"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
