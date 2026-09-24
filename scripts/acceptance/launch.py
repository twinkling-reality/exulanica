#!/usr/bin/env python3
"""The acceptance runtime: one checkout's application, on real services, on one port slot.

    python3 scripts/acceptance/launch.py up     --worktree PATH [--slot N] [--reuse-database]
                                                [--model] [--no-derivative-worker] [--production]
    python3 scripts/acceptance/launch.py status --worktree PATH
    python3 scripts/acceptance/launch.py down   --worktree PATH

``--worktree`` names any checkout of this repository, a linked worktree or a plain clone, with its
own ``.venv`` and installed web packages. ``scripts/rehearsal/rehearse.py --launcher`` names this
file. Standard library only, so it never imports the code it starts.

``up`` does, in order, and refuses by name at the first thing that is not as expected:

1.  Checks the checkout's interpreter and web toolchain, that ``exulanica`` imports from inside it,
    and records which tree runs: HEAD, the SHA-256 of ``git diff HEAD --binary`` and of the status.
2.  Starts the checkout's own disposable test server with ``scripts/test_postgres.py serve``. On
    first use the server's port file is written first, so it lands on the slot's database port. A
    server already running is refused unless ``--reuse-database``, and ``down`` never stops a
    reused one. The database it prints must be that server, on the port the server recorded.
3.  Makes a fresh synthetic workspace: new workspace and actor ids and a new bearer token, granted
    the account owner's permissions, and provisions the workspace's embedding partition.
4.  Starts the API as the non-owner runtime role with the read-only and purge URLs, a
    content-addressed store in the run directory and no Google configuration. With ``--model``
    it also passes ``NEBIUS_API_KEY``, ``EXULANICA_EGRESS_ALLOWLIST`` and ``EXULANICA_BUDGET_USD``
    from this process's environment, and refuses without any of them: a run with a model always
    states the bound the API enforces. Nothing writes the key anywhere.
5.  Serves the application on the slot's app port. By default that is the Vite development server,
    with the synthetic token built in as ``VITE_EXULANICA_TOKEN``. With ``--production`` it is a
    ``vite build`` into the run directory, made in a clean environment with no ``VITE_`` variable,
    served by ``vite preview``; the page then asks for the token, which is in the run directory's
    ``token`` file. Either way ``/api`` is proxied to the API through ``EXULANICA_API_URL``.

``down`` stops only what this launcher started, checked by process id and command line, and never
deletes a database cluster or a run record. Run state lives in the system temporary directory.

Nothing here depends on one machine: the port slots are the one fixed table, locations are derived
from the checkout, ``git`` and ``tempfile``, and anything else it needs is refused by name when it
is missing (see ``REFUSALS``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

#: The port slots, the one fixed table: slot N owns WIDTH ports from BASE + WIDTH * N, in the order
#: of ROLES. The spare port is where ``scripts/rehearsal/rehearse.py`` serves its own production
#: build, so it reads ``PORT_LIMIT`` and takes ``browser + 1``.
PORT_BASE = 19200
SLOT_WIDTH = 5
SLOT_COUNT = 7
PORT_ROLES = ("database", "api", "vite", "browser", "spare")
PORT_LIMIT = PORT_BASE + SLOT_WIDTH * SLOT_COUNT - 1

#: Where run state and run records live, under the system temporary directory: disposable, and
#: never inside a checkout.
RUNTIME_DIRECTORY_NAME = "exulanica-acceptance"

#: The account owner's grant, which a browser session in the owner role holds; everything but
#: ``tiles.materialise``. Stated here because this file imports nothing it starts;
#: ``tests/test_acceptance_launcher.py`` holds it equal to ``ACCOUNT_OWNER_PERMISSIONS``.
PERMISSIONS = (
    "library.read",
    "library.write",
    "model.invoke",
    "intake.write",
    "deletion.write",
    "consent.read",
    "consent.write",
    "admission.read",
    "admission.write",
    "world.read",
    "world.write",
    "operations.read",
    "operations.write",
)

#: What ``--model`` passes from this process's environment to the API, each required.
MODEL_VARIABLES = {
    "NEBIUS_API_KEY": "model-key-missing",
    "EXULANICA_EGRESS_ALLOWLIST": "model-allowlist-missing",
    "EXULANICA_BUDGET_USD": "budget-missing",
}

#: Environment prefixes dropped from every process this starts, so nothing in the caller's shell
#: can redirect a database, a model, a store, a token or a build.
SCRUBBED_PREFIXES = ("EXULANICA_", "PG", "NEBIUS_", "VITE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_")

#: How long each service may take to answer before the run is refused.
API_START_SECONDS = 90
READY_SECONDS = 30
TOKEN_PROBE_SECONDS = 10
APP_START_SECONDS = 90
PROXY_SECONDS = 30
#: A service asked to stop gets this many quarter-second polls before it is killed.
STOP_POLLS = 40
#: How much of a response or a log the run record and a refusal keep, in characters.
RECORD_EXCERPT_CHARACTERS = 2000
LOG_TAIL_CHARACTERS = 3000
REFUSAL_EXCERPT_CHARACTERS = 500
HEALTH_EXCERPT_CHARACTERS = 200

#: Every refusal, by the name it prints.
REFUSALS = {
    "lsof-missing": "lsof, which checks whether a slot's ports are free, is not on PATH",
    "slot-out-of-range": "the slot is outside the port table",
    "not-a-checkout": "the named directory is not a git checkout",
    "toolchain-missing": "the checkout lacks its own .venv, web packages or test server script",
    "state-exists": "a run of this checkout is recorded as up; run down first",
    "port-in-use": "a port of the slot is held by another process",
    "exulanica-elsewhere": "exulanica does not import from inside the checkout",
    "database-running": "the checkout's test server already runs and --reuse-database was not given",
    "database-not-its-own": "the database is not the checkout's own test server on its recorded port",
    "runtime-role": "the application URL does not name the non-owner runtime role",
    "serve-output": "scripts/test_postgres.py serve did not print a URL the run needs",
    "workspace-partition": "the synthetic workspace has no embedding partition",
    "model-key-missing": "--model needs NEBIUS_API_KEY in this environment",
    "model-allowlist-missing": "--model needs EXULANICA_EGRESS_ALLOWLIST in this environment",
    "budget-missing": "--model needs EXULANICA_BUDGET_USD, the bound the API enforces",
    "api-origin": "the API did not confirm it imported exulanica from the checkout",
    "token-refused": "the API did not accept the synthetic token",
    "no-answer": "a service did not answer in time",
    "build-failed": "vite build failed",
    "build-token": "the production build environment carries a VITE_ variable",
    "preview-proxy": "the production preview does not proxy /api to the API",
    "no-state": "nothing this launcher started is recorded for the checkout",
    "pg-ctl-missing": "the checkout is gone and the recorded pg_ctl cannot stop its server",
    "command-failed": "a command the run needs exited non-zero",
}


class Refused(Exception):
    """The run stopped for a named reason."""

    def __init__(self, name: str, detail: str) -> None:
        if name not in REFUSALS:
            raise KeyError(f"unregistered refusal {name!r}")
        super().__init__(f"{name}: {detail}")
        self.name = name
        self.detail = detail


def refuse(name: str, detail: str) -> NoReturn:
    raise Refused(name, detail)


API_WRAPPER = r"""
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
import exulanica
where = pathlib.Path(exulanica.__file__).resolve()
if not where.is_relative_to(root):
    print(f"ACCEPTANCE-REFUSED exulanica imported from {where}, not {root}", flush=True)
    raise SystemExit(3)
print(f"ACCEPTANCE-EXULANICA {where}", flush=True)
import uvicorn
uvicorn.run("exulanica.api.app:create_app", factory=True, host="127.0.0.1",
            port=int(sys.argv[2]), log_level="info")
"""

#: The marker the API wrapper prints, and that ``down`` requires in the command line it stops.
API_MARKER = "ACCEPTANCE-EXULANICA"

#: Provision the workspace's embedding partition as the owner, then print the partition. Without
#: one, the first embedding write fails with "no partition of relation embedding found".
PROVISION_WORKSPACE = r"""
import sys, uuid, psycopg
from exulanica.db.migrate import provision_workspace
workspace = uuid.UUID(sys.argv[2])
with psycopg.connect(sys.argv[1], autocommit=True) as connection:
    provision_workspace(connection, workspace)
    row = connection.execute("select to_regclass(%s)", (f"embedding_ws_{workspace.hex}",)).fetchone()
print(row[0] if row is not None else "")
"""

#: The checkout's test server as ``scripts/test_postgres.py`` sees it, and the PostgreSQL it uses.
LANE_SERVER_PROBE = (
    "import json,sys; sys.path.insert(0,'scripts'); import test_postgres as t; "
    "s=t.lane_server(); d=s.data.is_dir(); "
    "print(json.dumps({'root':str(s.root),'port':s.port,'initialised':d,"
    "'running':(d and s.running()),'bin':str(t.binaries())}))"
)


# -- slots, locations and environments ------------------------------------------------------------


def ports(slot: int) -> dict[str, int]:
    """The five ports of ``slot``, by role."""
    if not 0 <= slot < SLOT_COUNT:
        refuse("slot-out-of-range", f"slot {slot}; slots are 0 to {SLOT_COUNT - 1}")
    base = PORT_BASE + SLOT_WIDTH * slot
    return {role: base + offset for offset, role in enumerate(PORT_ROLES)}


def runtime_root() -> Path:
    return Path(tempfile.gettempdir()) / RUNTIME_DIRECTORY_NAME


def state_dir(worktree: Path) -> Path:
    """Where one checkout's run state lives: its name, and a digest of its path to keep two
    checkouts with one name apart."""
    resolved = Path(worktree).resolve()
    key = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
    return runtime_root() / f"{resolved.name}-{key}"


def clean_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items() if not k.startswith(SCRUBBED_PREFIXES)}


def model_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What ``--model`` hands the API, or a refusal naming the first variable that is absent."""
    source = os.environ if environ is None else environ
    passed = {}
    for name, refusal in MODEL_VARIABLES.items():
        value = source.get(name, "").strip()
        if not value:
            refuse(refusal, REFUSALS[refusal])
        passed[name] = value
    return passed


def api_environment(
    *,
    exports: Mapping[str, str],
    grant: Mapping[str, object],
    data_dir: Path,
    model: bool,
    derivative_worker: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = clean_environment(environ)
    if model:
        environment.update(model_environment(environ))
    environment.update(
        {
            "EXULANICA_DATABASE_URL": exports["EXULANICA_DATABASE_URL"],
            "EXULANICA_READONLY_DATABASE_URL": exports["EXULANICA_READONLY_DATABASE_URL"],
            "EXULANICA_PURGE_DATABASE_URL": exports["EXULANICA_PURGE_DATABASE_URL"],
            "EXULANICA_API_TOKENS": json.dumps(dict(grant)),
            "EXULANICA_DATA_DIR": str(data_dir),
        }
    )
    if not derivative_worker:
        # Absence means on, so the production shape, a separately started worker, is spelled.
        environment["EXULANICA_DERIVATIVE_WORKER"] = "off"
    return environment


def app_directory(worktree: Path) -> Path:
    return worktree / "web" / "packages" / "app"


def vite_program(worktree: Path) -> Path:
    return app_directory(worktree) / "node_modules" / ".bin" / "vite"


def build_directory(run_dir: Path) -> Path:
    return run_dir / "app-build"


def api_url(slot_ports: Mapping[str, int]) -> str:
    return f"http://127.0.0.1:{slot_ports['api']}"


def development_command(vite: Path, port: int) -> list[str]:
    return [str(vite), "--port", str(port), "--strictPort"]


def development_environment(
    slot_ports: Mapping[str, int], token: str, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    environment = clean_environment(environ)
    environment.update(
        {
            "EXULANICA_API_URL": api_url(slot_ports),
            "VITE_EXULANICA_TOKEN": token,
            "BROWSER": "none",
        }
    )
    return environment


def production_build_command(vite: Path, run_dir: Path) -> list[str]:
    return [str(vite), "build", "--outDir", str(build_directory(run_dir)), "--emptyOutDir"]


def production_build_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The caller's environment without any ``VITE_`` variable, so no token is built in."""
    environment = clean_environment(environ)
    carried = sorted(name for name in environment if name.startswith("VITE_"))
    if carried:
        refuse("build-token", ", ".join(carried))
    return environment


def preview_command(vite: Path, run_dir: Path, port: int) -> list[str]:
    return [
        str(vite),
        "preview",
        "--outDir",
        str(build_directory(run_dir)),
        "--port",
        str(port),
        "--strictPort",
    ]


def preview_environment(
    slot_ports: Mapping[str, int], environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    environment = clean_environment(environ)
    environment.update({"EXULANICA_API_URL": api_url(slot_ports), "BROWSER": "none"})
    return environment


# -- processes ------------------------------------------------------------------------------------


def run(command: list[str], cwd: Path, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        refuse(
            "command-failed",
            f"{' '.join(command[:3])} exited {completed.returncode}:\n"
            f"{completed.stdout}\n{completed.stderr}",
        )
    return completed.stdout


def listening(port: int) -> bool:
    completed = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(completed.stdout.strip())


def http_get(url: str, headers: Mapping[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_http(
    url: str, seconds: float, headers: Mapping[str, str] | None = None
) -> tuple[int, bytes]:
    deadline = time.monotonic() + seconds
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            return http_get(url, headers)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            last = str(error)
        time.sleep(0.5)
    refuse("no-answer", f"{url} did not answer within {seconds:.0f} s ({last})")


def spawn(command: list[str], cwd: Path, env: Mapping[str, str], log: Path) -> int:
    with log.open("ab") as handle:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(env),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return process.pid


def command_of(pid: int) -> str:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


def stop(pid: int, marker: str, label: str) -> None:
    command = command_of(pid)
    if not command:
        print(f"{label}: pid {pid} already gone")
        return
    if marker not in command:
        print(f"{label}: pid {pid} is now '{command[:120]}', not ours; left alone")
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(STOP_POLLS):
        if not command_of(pid):
            print(f"{label}: stopped pid {pid}")
            return
        time.sleep(0.25)
    os.killpg(pid, signal.SIGKILL)
    print(f"{label}: killed pid {pid} after SIGTERM timeout")


# -- the run ---------------------------------------------------------------------------------------


def tree_identity(worktree: Path) -> dict[str, str]:
    head = run(["git", "rev-parse", "HEAD"], worktree).strip()
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--binary"], cwd=worktree, capture_output=True, check=True
    ).stdout
    status = run(["git", "status", "--porcelain", "--untracked-files=all"], worktree)
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], worktree).strip()
    return {
        "branch": branch,
        "head": head,
        "diff_head_sha256": hashlib.sha256(diff).hexdigest(),
        "diff_head_bytes": str(len(diff)),
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "changed_paths": str(len(status.splitlines())),
    }


def checkout(path: str) -> Path:
    """The top of the checkout ``path`` names, found by git, or a refusal."""
    completed = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        refuse("not-a-checkout", f"{path}: {completed.stderr.strip()}")
    return Path(completed.stdout.strip()).resolve()


def check_toolchain(worktree: Path) -> Path:
    """The checkout's own interpreter, once its interpreter, web packages and test server exist."""
    python = worktree / ".venv" / "bin" / "python"
    for required in (python, vite_program(worktree), worktree / "scripts" / "test_postgres.py"):
        if not required.exists():
            refuse("toolchain-missing", f"{required} is missing")
    return python


def lane_server(worktree: Path, python: Path) -> dict:
    return json.loads(run([str(python), "-c", LANE_SERVER_PROBE], worktree))


def served_exports(served: str) -> dict[str, str]:
    exports = {}
    for line in served.splitlines():
        if line.startswith("export "):
            key, value = line[len("export ") :].split("=", 1)
            exports[key] = value
        if line.startswith("owner "):
            exports["OWNER_URL"] = line.split()[1]
    for key in (
        "EXULANICA_DATABASE_URL",
        "EXULANICA_READONLY_DATABASE_URL",
        "EXULANICA_PURGE_DATABASE_URL",
        "OWNER_URL",
    ):
        if key not in exports:
            refuse("serve-output", f"no {key} in:\n{served}")
    return exports


def url_port(url: str) -> int:
    return int(url.rsplit(":", 1)[1].split("/")[0])


def write_state(state_file: Path, state: Mapping[str, object]) -> None:
    state_file.write_text(json.dumps(state, indent=2))


def up(arguments: argparse.Namespace) -> None:
    worktree = checkout(arguments.worktree)
    python = check_toolchain(worktree)
    if arguments.model:
        model_environment()  # refuse before anything starts, not after the database has
    directory = state_dir(worktree)
    state_file = directory / "state.json"
    if state_file.exists():
        refuse("state-exists", str(state_file))
    chosen = ports(arguments.slot)
    for role in ("api", "vite", "browser"):
        if listening(chosen[role]):
            refuse("port-in-use", f"port {chosen[role]} ({role})")

    resolved = run(
        [
            str(python),
            "-c",
            "import exulanica,pathlib;print(pathlib.Path(exulanica.__file__).resolve())",
        ],
        worktree,
    ).strip()
    if not Path(resolved).is_relative_to(worktree):
        refuse("exulanica-elsewhere", f"exulanica resolves to {resolved}, outside {worktree}")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = directory / run_id
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True)
    logs = run_dir / "logs"
    logs.mkdir()

    # The database: the checkout's own disposable test server.
    server = lane_server(worktree, python)
    started_database = False
    if server["running"]:
        if not arguments.reuse_database:
            refuse(
                "database-running",
                f"port {server['port']} ({server['root']}); pass --reuse-database to use it "
                "without owning it",
            )
    else:
        root = Path(server["root"])
        port_file = root / "port"
        if not server["initialised"] and not port_file.exists():
            root.mkdir(parents=True, exist_ok=True)
            port_file.write_text(str(chosen["database"]))
        started_database = True
    # Recorded before serve starts anything, so down can stop the server after any later refusal.
    token_file = run_dir / "token"
    state: dict = {
        "launcher": str(Path(__file__).resolve()),
        "worktree": str(worktree),
        "tree": tree_identity(worktree),
        "slot": arguments.slot,
        "ports": chosen,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "data_dir": str(data_dir),
        "token_file": str(token_file),
        "database": {
            "started_by_launcher": started_database,
            "lane_server_root": server["root"],
            "postgres_bin": server["bin"],
        },
        "pids": {},
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    write_state(state_file, state)
    served = run([str(python), "scripts/test_postgres.py", "serve"], worktree)
    (logs / "database-serve.txt").write_text(served)
    exports = served_exports(served)
    database_port = url_port(exports["EXULANICA_DATABASE_URL"])
    after = lane_server(worktree, python)
    state["database"].update(
        {
            "port": database_port,
            "runtime_url": exports["EXULANICA_DATABASE_URL"],
            "owner_url_for_evidence_reads": exports["OWNER_URL"],
            "lane_server_root": after["root"],
        }
    )
    write_state(state_file, state)
    if not after["running"] or database_port != after["port"]:
        refuse(
            "database-not-its-own",
            f"serve printed port {database_port}; the test server at {after['root']} records "
            f"{after['port']} and is {'running' if after['running'] else 'stopped'}",
        )
    if "exulanica_app@" not in exports["EXULANICA_DATABASE_URL"]:
        refuse("runtime-role", "the application URL does not name exulanica_app")

    # A fresh synthetic workspace and an explicit grant.
    workspace_id = str(uuid.uuid4())
    actor = str(uuid.uuid4())
    token = secrets.token_urlsafe(48)
    token_file.write_text(token)
    token_file.chmod(0o600)
    grant = {
        token: {"workspace_id": workspace_id, "actor": actor, "permissions": list(PERMISSIONS)}
    }
    partition = run(
        [str(python), "-c", PROVISION_WORKSPACE, exports["OWNER_URL"], workspace_id], worktree
    ).strip()
    if partition != f"embedding_ws_{uuid.UUID(workspace_id).hex}":
        refuse("workspace-partition", f"workspace {workspace_id} left {partition!r}")
    (logs / "workspace-provision.txt").write_text(f"{workspace_id} -> {partition}\n")

    environment = api_environment(
        exports=exports,
        grant=grant,
        data_dir=data_dir,
        model=arguments.model,
        derivative_worker=not arguments.no_derivative_worker,
    )
    api_log = logs / "api.log"
    api_pid = spawn(
        [str(python), "-c", API_WRAPPER, str(worktree), str(chosen["api"])],
        worktree,
        environment,
        api_log,
    )
    state.update(
        {
            "workspace_id": workspace_id,
            "embedding_partition": partition,
            "derivative_worker": "off" if arguments.no_derivative_worker else "in-process",
            "model": bool(arguments.model),
            "budget_usd": environment.get("EXULANICA_BUDGET_USD"),
            "actor": actor,
            "permissions": list(PERMISSIONS),
        }
    )
    state["pids"]["api"] = api_pid
    write_state(state_file, state)

    status, body = wait_http(f"{api_url(chosen)}/healthz", API_START_SECONDS)
    log_text = api_log.read_text(errors="replace")
    imported = [line for line in log_text.splitlines() if line.startswith("ACCEPTANCE-")]
    if not imported or not imported[0].startswith(f"{API_MARKER} "):
        refuse("api-origin", log_text[-LOG_TAIL_CHARACTERS:])
    state["api_imported_exulanica_from"] = imported[0].split(" ", 1)[1]
    ready_status, ready_body = wait_http(f"{api_url(chosen)}/readyz", READY_SECONDS)
    state["api_health"] = {
        "healthz": [status, body.decode(errors="replace")],
        "readyz": [ready_status, ready_body.decode(errors="replace")],
    }
    probe_status, probe_body = wait_http(
        f"{api_url(chosen)}/world-entries",
        TOKEN_PROBE_SECONDS,
        {"Authorization": f"Bearer {token}"},
    )
    state["api_token_probe"] = {
        "route": "GET /world-entries",
        "status": probe_status,
        "body": probe_body.decode(errors="replace")[:RECORD_EXCERPT_CHARACTERS],
    }
    write_state(state_file, state)
    if probe_status != 200:
        refuse("token-refused", f"{probe_status} {probe_body[:REFUSAL_EXCERPT_CHARACTERS]!r}")

    if arguments.production:
        serve_production(worktree, run_dir, chosen, logs, state, state_file)
    else:
        serve_development(worktree, chosen, token, logs, state, state_file)
    shown = ("worktree", "tree", "ports", "run_dir", "workspace_id", "api_imported_exulanica_from")
    print(json.dumps({key: state[key] for key in (*shown, "api_health", "app")}, indent=2))
    print(f"app: http://localhost:{chosen['vite']}/  token file: {token_file}")


def serve_development(
    worktree: Path,
    chosen: Mapping[str, int],
    token: str,
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    pid = spawn(
        development_command(vite_program(worktree), chosen["vite"]),
        app_directory(worktree),
        development_environment(chosen, token),
        logs / "vite.log",
    )
    state["pids"]["vite"] = pid
    write_state(state_file, state)
    root_status, _ = wait_http(f"http://localhost:{chosen['vite']}/", APP_START_SECONDS)
    proxied, proxied_body = wait_http(
        f"http://localhost:{chosen['vite']}/api/healthz", PROXY_SECONDS
    )
    state["app"] = {
        "mode": "development",
        "root_status": root_status,
        "api_proxy_healthz": [
            proxied,
            proxied_body.decode(errors="replace")[:HEALTH_EXCERPT_CHARACTERS],
        ],
    }
    write_state(state_file, state)


def serve_production(
    worktree: Path,
    run_dir: Path,
    chosen: Mapping[str, int],
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    vite = vite_program(worktree)
    target = build_directory(run_dir)
    started = time.monotonic()
    completed = subprocess.run(
        production_build_command(vite, run_dir),
        cwd=app_directory(worktree),
        env=production_build_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    (logs / "build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode != 0:
        refuse(
            "build-failed", f"vite build exited {completed.returncode}; see {logs / 'build.log'}"
        )
    version = run([str(vite), "--version"], app_directory(worktree)).strip()
    index = (target / "index.html").read_bytes()
    build = {
        "command": "vite build --outDir <run>/app-build --emptyOutDir",
        "vite": version,
        "seconds": round(time.monotonic() - started, 1),
        "development_token_in_environment": False,
        "index_html_sha256": hashlib.sha256(index).hexdigest(),
        "scripts": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(target.glob("assets/*.js"))
        },
    }
    pid = spawn(
        preview_command(vite, run_dir, chosen["vite"]),
        app_directory(worktree),
        preview_environment(chosen),
        logs / "preview.log",
    )
    state["pids"]["vite"] = pid
    write_state(state_file, state)
    root_status, served = wait_http(f"http://localhost:{chosen['vite']}/", APP_START_SECONDS)
    proxied, proxied_body = wait_http(
        f"http://localhost:{chosen['vite']}/api/healthz", PROXY_SECONDS
    )
    state["app"] = {
        "mode": "production",
        "build": build,
        "root_status": root_status,
        "served_index_sha256": hashlib.sha256(served).hexdigest(),
        "served_index_is_the_build": served == index,
        "api_proxy_healthz": [
            proxied,
            proxied_body.decode(errors="replace")[:HEALTH_EXCERPT_CHARACTERS],
        ],
    }
    write_state(state_file, state)
    if proxied != 200:
        refuse("preview-proxy", f"/api/healthz through the preview answered {proxied}")


def status(arguments: argparse.Namespace) -> None:
    worktree = recorded_checkout(arguments.worktree)
    state_file = state_dir(worktree) / "state.json"
    if not state_file.exists():
        print("not running (no state file)")
        return
    state = json.loads(state_file.read_text())
    for name, pid in state["pids"].items():
        print(f"{name}: pid {pid} {'alive' if command_of(pid) else 'gone'}")
    shown = ("tree", "ports", "run_dir", "workspace_id", "database")
    print(json.dumps({key: state.get(key) for key in shown}, indent=2))


def recorded_checkout(path: str) -> Path:
    """The checkout ``up`` recorded: its top as git finds it, or the path once it is gone."""
    if Path(path).exists():
        return checkout(path)
    return Path(path).resolve()


def down(arguments: argparse.Namespace) -> None:
    worktree = recorded_checkout(arguments.worktree)
    state_file = state_dir(worktree) / "state.json"
    if not state_file.exists():
        refuse("no-state", str(state_file))
    state = json.loads(state_file.read_text())
    if "vite" in state["pids"]:
        stop(state["pids"]["vite"], "vite", "app")
    if "api" in state["pids"]:
        stop(state["pids"]["api"], API_MARKER, "api")
    if state["database"]["started_by_launcher"]:
        python = worktree / ".venv" / "bin" / "python"
        if python.exists():
            print(run([str(python), "scripts/test_postgres.py", "stop"], worktree).strip())
        else:
            # The checkout went while its runtime was up; stop its server by the recorded data
            # directory, with the pg_ctl its own test server used.
            data = Path(state["database"]["lane_server_root"]) / "data"
            pg_ctl = Path(state["database"]["postgres_bin"]) / "pg_ctl"
            if not pg_ctl.exists():
                refuse("pg-ctl-missing", f"{pg_ctl} cannot stop the server at {data}")
            print(run([str(pg_ctl), "-D", str(data), "stop", "-m", "fast"], data.parent).strip())
    else:
        print("database: reused, not started here, left running")
    finished = Path(state["run_dir"]) / "state.json"
    state["stopped_at"] = dt.datetime.now(dt.UTC).isoformat()
    write_state(finished, state)
    state_file.unlink()
    print(f"run record kept at {finished}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "status", "down"):
        command = commands.add_parser(name)
        command.add_argument("--worktree", required=True, help="the checkout to run")
        if name == "up":
            command.add_argument("--slot", type=int, default=0, help="the port slot, 0 to 6")
            command.add_argument("--reuse-database", action="store_true")
            command.add_argument(
                "--model",
                action="store_true",
                help="pass NEBIUS_API_KEY, EXULANICA_EGRESS_ALLOWLIST and EXULANICA_BUDGET_USD "
                "through to the API (default: no model)",
            )
            command.add_argument(
                "--no-derivative-worker",
                action="store_true",
                help="start the API with EXULANICA_DERIVATIVE_WORKER=off, the production shape",
            )
            command.add_argument(
                "--production",
                action="store_true",
                help="serve a production build with vite preview instead of the development server",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if shutil.which("lsof") is None:
            refuse("lsof-missing", REFUSALS["lsof-missing"])
        {"up": up, "status": status, "down": down}[arguments.command](arguments)
    except Refused as refused:
        print(f"refused ({refused.name}): {refused.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
