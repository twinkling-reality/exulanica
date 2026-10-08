#!/usr/bin/env python3
"""The acceptance runtime: one checkout's application, on real services, on one port slot.

    python3 scripts/acceptance/launch.py up     --worktree PATH [--slot N] [--reuse-database]
                                                [--model] [--no-derivative-worker] [--production]
                                                [--society-playback [--society-tick-interval-ms MS]]
                                                [--tiles] [--port-base PORT] [--workspaces K]
                                                [--read-only-token] [--scripted-model PLAN]
                                                [--no-derivative-worker --depth-worker]
                                                [--database-latency]
    python3 scripts/acceptance/launch.py status --worktree PATH
    python3 scripts/acceptance/launch.py restart-api --worktree PATH [--revoke TOKEN_FILE]
    python3 scripts/acceptance/launch.py down   --worktree PATH

``--worktree`` names any checkout of this repository, a linked worktree or a plain clone, with its
own ``.venv`` and installed web packages. ``scripts/rehearsal/rehearse.py`` runs this file with
``up --production`` unless its ``--launcher`` names another. Standard library only, so it never
imports the code it starts.

``up`` does, in order, and refuses by name at the first thing that is not as expected:

1.  Checks the checkout's interpreter and web toolchain, that ``exulanica`` imports from inside it,
    and records which tree runs: HEAD, the SHA-256 of ``git diff HEAD --binary`` and of the status.
2.  Starts the checkout's own disposable test server with ``scripts/test_postgres.py serve``. On
    first use the server's port file is written first, so it lands on the slot's database port. A
    server already running is refused unless ``--reuse-database``, and ``down`` never stops a
    reused one. The database it prints must be that server, on the port the server recorded.
3.  Makes a fresh synthetic workspace: new workspace and actor ids and a new bearer token, granted
    the account owner's permissions, and provisions the workspace's embedding partition. With
    ``--tiles`` the token is also granted ``tiles.materialise`` and the workspace a tile quota of
    ``TILES_LIMIT``, declared as the owner, so the development page can walk a baked tile. Then
    publishes the character catalogs the checkout carries (``exulanica-character-catalog publish
    --apply``) over the owner connection into the run's data directory, as every serving database
    must be before anybody is drawn; its lines are kept in ``logs/character-catalogs.txt`` and the
    run state.
4.  Starts the API as the non-owner runtime role with the read-only and purge URLs, a
    content-addressed store in the run directory and no Google configuration. The purge URL is
    also written to ``purge-url`` in the run directory at 0600, named by the run state and never
    printed, for a client that runs the purge as an installation does. With ``--model``
    it also passes ``NEBIUS_API_KEY``, ``EXULANICA_EGRESS_ALLOWLIST``, ``EXULANICA_BUDGET_USD``,
    ``EXULANICA_BUDGET_MAX_CALLS`` and ``EXULANICA_SPENDING``
    from this process's environment, and refuses without any of them: a run with a model always
    states the bound the API enforces and how it spends, and a durable one is given the run's
    spending witness directory, as a scripted durable run is. Nothing writes the key anywhere. With
    ``--society-playback`` the API also plays the synthetic workspace's societies on their own
    (``EXULANICA_SOCIETY_CONTROL_WORKSPACES`` names that workspace alone), at the host's declared
    base wait or at ``--society-tick-interval-ms``, which the API validates. Without it the API
    plays nothing.
5.  Starts one generated-tile worker for the synthetic workspace, checks its startup event and
    records its process and bake events. It claims jobs as the runtime role and publishes baked
    tiles through the owner connection.
6.  Serves the application on the slot's app port. By default that is the Vite development server,
    with the synthetic token built in as ``VITE_EXULANICA_TOKEN``. With ``--production`` it is a
    ``vite build`` into the run directory, made in a clean environment with no ``VITE_`` variable,
    served by ``vite preview``; the page then asks for the token, which is in the run directory's
    ``token`` file. Either way ``/api`` is proxied to the API through ``EXULANICA_API_URL``.

With ``--society-playback``, ``up`` refuses unless the API's readiness says its playback worker runs
for exactly one listed workspace, and records the base wait that readiness states.

Three options serve runs that need more than one client, each off by default so a run without them
starts exactly what it always did:

- ``--port-base PORT`` moves the slot table to start at ``PORT`` instead of ``PORT_BASE``, so a run
  can sit inside a port block another table leases; ``--slot`` still counts slots of five from it.
- ``--workspaces K`` makes K synthetic workspaces instead of one, each with its own actor, token
  file (``token``, then ``token-2`` to ``token-K``) and embedding partition, all granted the same
  permissions and served by the one API. The first is the run's workspace: tiles, the tile worker
  and playback serve it alone.
- ``--scripted-model PLAN`` serves the API through ``scripted_model.py``, whose model transport
  answers from the plan and which refuses to start if a provider could be reached. The plan is
  copied into the run directory and its digest recorded; every model request is logged beside it.
  ``--spending process|durable`` states the scripted API's ``EXULANICA_SPENDING`` explicitly.
- ``--read-only-token`` adds one more token, ``token-read``, for the first workspace with
  ``world.read`` alone, so a client can be shown a refusal its grant earns.
- ``--door-bridges FILE`` admits the outside programs a JSON array of bridge declarations names
  (``EXULANICA_DOOR_BRIDGES``, digests only, never a credential), so an adapter can be run against
  the slot's API. An entry's ``"workspaces": "synthetic"`` becomes the run's synthetic workspace
  ids, which the file cannot know before the run makes them; the API's own loader checks the rest.
- ``--society-of-things`` offers the society of things on the slot's API
  (``EXULANICA_SOCIETY_OF_THINGS=on``), so a rehearsal can start a society over placed things. It
  is set for the API process alone, after the scrub of the shell's ``EXULANICA_`` variables, and
  recorded in the run state, so a restarted API offers it too. For rehearsal stacks on fresh
  acceptance databases only.
- ``--accounts-guest-code``, with ``--edge-port``, ``--tiles``, ``--scripted-model``,
  ``--spending durable`` and ``--society-playback``, also serves browser accounts with guest entry
  by code, Google sign-in unset, as a hosted server serves its judges: a code is drawn for the run
  into ``guest-code`` in the run directory (mode 0600) and only its SHA-256 reaches the API; the
  accounts role is given its tables; an authority and a guest policy are issued for every provider
  the manifest names before the API starts; and playback also plays every account's own workspace
  (``EXULANICA_SOCIETY_CONTROL_WORKER``), so a guest's world is played (by its routine: the host
  asks models only for the workspaces its environment lists).
  Accounts are served only over HTTPS, so the run also starts the deployment's edge shape
  (``deploy/acceptance/Caddyfile``, Caddy's own local authority for the name ``localhost``, in the
  pinned image already present: never pulled) on ``127.0.0.1:<edge port>`` in front of the API;
  the one browser origin is ``https://localhost:<edge port>``. Before the edge opens, the arrival
  worlds are made once in the run's own workspace and the run waits until their tiles are baked,
  as an installation prepares them before it admits guests; and a client trusts the edge's root
  certificate (``edge.root_certificate`` in the state) in its own process only, never in a system
  store. ``down`` removes the container it recorded.
- ``--peer-token`` adds ``token-peer``: a second actor in the first workspace with the same
  permissions, so a client can be shown what one actor's private work looks like to another.
- ``--depth-worker``, with ``--no-derivative-worker``, runs the production derivative worker
  (``exulanica-derivative-worker``) for every workspace of the run in place of the API's, with the
  depth model the manifest pins, read offline (``HF_HUB_OFFLINE``) from the local model cache on
  the CPU. It refuses when the pinned checkpoint is not in the cache, and never downloads it; the
  run state records the checkpoint's path, size and digest.
- ``--database-latency`` starts ``latency_proxy.py`` on the slot's spare port between the API
  and its PostgreSQL server and points the API's database URLs at it, so a run can add connection
  latency by writing whole milliseconds to ``database-delay-ms`` in the run directory (0 at start);
  workers and evidence reads connect directly. It takes the port ``--second-api`` would.
- ``--second-api`` starts a second API process on the slot's spare port with the same database,
  store, spending witness and grants, so clients can race through two processes at once.
  ``restart-api --api second`` restarts that one instead of the first.

``restart-api`` stops the recorded API and starts it again on the same port, database, store and
grants, rebuilt from the run's token files and recorded state, so a client can reopen its work from a
fresh process. ``--revoke NAME`` leaves the named token file's grant out of the restarted API, so a
client can be shown that a withdrawn credential is refused while the rest of the run continues.
Each restart is recorded in the run state with its time, process and any revoked grant.

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
import shlex
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

#: The port slots, the one fixed table: slot N owns WIDTH ports from BASE + WIDTH * N, in the order
#: of ROLES. The application is served on ``vite``, by the development server or, with
#: ``--production``, by ``vite preview``; ``spare`` is held for whatever a run adds.
PORT_BASE = 19200
SLOT_WIDTH = 5
SLOT_COUNT = 7
PORT_ROLES = ("database", "api", "vite", "browser", "spare")
PORT_LIMIT = PORT_BASE + SLOT_WIDTH * SLOT_COUNT - 1
#: The file in the run directory holding the purge role's URL, readable by its owner alone.
PURGE_URL_NAME = "purge-url"
#: The depth model the manifest pins, read from this local cache only: ``--depth-worker`` never
#: downloads it (``HF_HUB_OFFLINE``), and records the file's path and digest.
DEPTH_MODEL = "Ruicheng/moge-2-vitl"
DEPTH_CHECKPOINT = "model.pt"
DEPTH_WORKER_NAME = "acceptance-depth"
DEPTH_WORKER_START_SECONDS = 300
#: The file in the run directory naming the delay ``--database-latency`` adds, in milliseconds;
#: a run changes it while the stack runs.
DATABASE_DELAY_NAME = "database-delay-ms"
LATENCY_PROXY_START_SECONDS = 30
#: The database URLs the API connects with, which ``--database-latency`` points at the proxy.
API_DATABASE_URLS = ("EXULANICA_DATABASE_URL", "EXULANICA_READONLY_DATABASE_URL")

#: The ports a moved slot table may use: unprivileged ones, the whole run inside the port range.
PORT_MINIMUM = 1024
PORT_MAXIMUM = 65535
#: How many synthetic workspaces ``--workspaces`` may make.
WORKSPACES_MAXIMUM = 8
#: The token file ``--peer-token`` writes.
PEER_TOKEN_NAME = "token-peer"
#: The one permission ``--read-only-token`` grants.
READ_ONLY_PERMISSIONS = ("world.read",)

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
    "references.request",
    "door.grant",
)
#: What ``--tiles`` adds to the synthetic grant, which the account owner's does not carry.
TILES_PERMISSION = "tiles.materialise"
#: The tiles a ``--tiles`` run's workspace may be served: the development corridor's five tiles
#: at each of the two city grammar versions it is baked at, ten, and six to spare.
TILES_LIMIT = 16

#: What ``--model`` passes from this process's environment to the API, each required.
MODEL_VARIABLES = {
    "NEBIUS_API_KEY": "model-key-missing",
    "EXULANICA_EGRESS_ALLOWLIST": "model-allowlist-missing",
    "EXULANICA_BUDGET_USD": "budget-missing",
    "EXULANICA_BUDGET_MAX_CALLS": "call-ceiling-missing",
    "EXULANICA_SPENDING": "spending-mode-missing",
}

#: Environment prefixes dropped from every process this starts, so nothing in the caller's shell
#: can redirect a database, a model, a store, a token or a build.
SCRUBBED_PREFIXES = ("EXULANICA_", "PG", "NEBIUS_", "VITE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_")

#: How long each service may take to answer before the run is refused.
API_START_SECONDS = 90
READY_SECONDS = 30
TILE_WORKER_START_SECONDS = 60  # Schema and role checks complete before a tile job is claimed.
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
    "tile-quota": "--tiles did not declare the synthetic workspace's tile quota",
    "tile-worker-startup": "the generated-tile worker did not report a successful startup",
    "depth-worker-shape": "--depth-worker replaces the API's derivative worker: add "
    "--no-derivative-worker",
    "depth-checkpoint-missing": "the depth model's pinned checkpoint is not in the local model "
    "cache, and --depth-worker never downloads it",
    "depth-worker-startup": "the depth-capable derivative worker did not report a startup",
    "database-latency-shape": "--database-latency takes the slot's spare port, which "
    "--second-api also takes",
    "latency-proxy-startup": "the database latency proxy did not report a startup",
    "model-key-missing": "--model needs NEBIUS_API_KEY in this environment",
    "model-allowlist-missing": "--model needs EXULANICA_EGRESS_ALLOWLIST in this environment",
    "budget-missing": "--model needs EXULANICA_BUDGET_USD, the bound the API enforces",
    "call-ceiling-missing": "--model needs EXULANICA_BUDGET_MAX_CALLS, the call bound the API enforces",
    "spending-mode-missing": "--model needs EXULANICA_SPENDING, durable or process, how the API spends",
    "api-origin": "the API did not confirm it imported exulanica from the checkout",
    "token-refused": "the API did not accept the synthetic token",
    "door-bridges-file": "--door-bridges names a file holding one JSON array of bridge objects",
    "accounts-shape": "--accounts-guest-code needs --edge-port, --tiles, --scripted-model, "
    "--spending durable and --society-playback",
    "arrival-not-baked": "the arrival worlds' tiles were not baked in time",
    "edge-failed": "the local HTTPS edge in front of the API did not start or did not answer",
    "accounts-provision": "the accounts role could not be given its tables",
    "guest-policy": "an authority or guest policy for the guest entry could not be issued",
    "no-answer": "a service did not answer in time",
    "build-failed": "vite build failed",
    "build-token": "the production build environment carries a VITE_ variable",
    "preview-proxy": "the production preview does not proxy /api to the API",
    "no-state": "nothing this launcher started is recorded for the checkout",
    "pg-ctl-missing": "the checkout is gone and the recorded pg_ctl cannot stop its server",
    "command-failed": "a command the run needs exited non-zero",
    "society-interval-without-playback": "--society-tick-interval-ms needs --society-playback",
    "society-playback-not-running": "the API's readiness does not report playback of the workspace",
    "port-base-out-of-range": "--port-base puts a port of the slot outside the unprivileged range",
    "workspaces-out-of-range": "--workspaces is outside 1 to WORKSPACES_MAXIMUM",
    "token-file-unknown": "--revoke names no token file this run wrote",
    "scripted-with-model": "--scripted-model and --model cannot both be given",
    "scripted-plan-missing": "--scripted-model names no readable plan file",
    "no-second-api": "restart-api --api second names a run that started no second API",
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

#: The same checks, then the scripted-model API instead of the plain one
#: (``scripts/acceptance/scripted_model.py``, which binds loopback itself).
SCRIPTED_API_WRAPPER = r"""
import pathlib, runpy, sys
root = pathlib.Path(sys.argv[1]).resolve()
import exulanica
where = pathlib.Path(exulanica.__file__).resolve()
if not where.is_relative_to(root):
    print(f"ACCEPTANCE-REFUSED exulanica imported from {where}, not {root}", flush=True)
    raise SystemExit(3)
print(f"ACCEPTANCE-EXULANICA {where}", flush=True)
script = root / "scripts" / "acceptance" / "scripted_model.py"
sys.argv = [str(script), sys.argv[3], sys.argv[2]]
runpy.run_path(str(script), run_name="__main__")
"""
#: Where a scripted run keeps its plan and its log of every model request, in the run directory.
SCRIPTED_PLAN_NAME = "scripted-model-plan.json"
SCRIPTED_LOG_NAME = "scripted-model-calls.jsonl"
#: The spending authorities a scripted run may state (``EXULANICA_SPENDING``): the process's own
#: bounds from the plan, or the durable authority with its witness in the run directory.
SPENDING_MODES = ("process", "durable")
SPENDING_WITNESS_NAME = "spending-witness"


def scripted_environment(run_dir: Path, logs: Path, spending: str) -> dict[str, str]:
    """What a scripted API is given beyond the plain one's environment: its request log and the
    spending authority it states, never left to a default."""
    environment = {
        "EXULANICA_SCRIPTED_MODEL_LOG": str(logs / SCRIPTED_LOG_NAME),
        "EXULANICA_SPENDING": spending,
    }
    if spending == "durable":
        environment["EXULANICA_SPENDING_WITNESS_DIR"] = str(run_dir / SPENDING_WITNESS_NAME)
    return environment


def model_witness_environment(environment: Mapping[str, str], run_dir: Path) -> dict[str, str]:
    """What a ``--model`` API spending under the durable authority is given beyond
    ``model_environment``: the run's witness directory, the one its operator's grants are written
    with. A process without one refuses to spend under a witnessed authority."""
    if environment.get("EXULANICA_SPENDING") != "durable":
        return {}
    return {"EXULANICA_SPENDING_WITNESS_DIR": str(run_dir / SPENDING_WITNESS_NAME)}


def api_command(python: Path, worktree: Path, port: int, plan: Path | None) -> list[str]:
    """The API's command line: the plain application, or with a plan the scripted-model one."""
    if plan is None:
        return [str(python), "-c", API_WRAPPER, str(worktree), str(port)]
    return [str(python), "-c", SCRIPTED_API_WRAPPER, str(worktree), str(port), str(plan)]


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

#: Declare the synthetic workspace's tile quota as the owner, then print its ceiling.
DECLARE_TILE_QUOTA = r"""
import sys, uuid, psycopg
from psycopg.rows import dict_row
from exulanica.api.quotas import declare_tile_quota
workspace, actor = uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3])
with psycopg.connect(sys.argv[1], autocommit=True, row_factory=dict_row) as connection:
    connection.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    quota = declare_tile_quota(connection, workspace, tiles_limit=int(sys.argv[4]), declared_by=actor)
print(quota.tiles_limit)
"""

#: The checkout's test server as ``scripts/test_postgres.py`` sees it, and the PostgreSQL it uses.
LANE_SERVER_PROBE = (
    "import json,sys; sys.path.insert(0,'scripts'); import test_postgres as t; "
    "s=t.lane_server(); d=s.data.is_dir(); "
    "print(json.dumps({'root':str(s.root),'port':s.port,'initialised':d,"
    "'running':(d and s.running()),'bin':str(t.binaries())}))"
)


# -- slots, locations and environments ------------------------------------------------------------


def ports(slot: int, port_base: int | None = None) -> dict[str, int]:
    """The five ports of ``slot``, by role, in the table starting at ``port_base`` when one is
    given and at ``PORT_BASE`` otherwise."""
    if not 0 <= slot < SLOT_COUNT:
        refuse("slot-out-of-range", f"slot {slot}; slots are 0 to {SLOT_COUNT - 1}")
    table = PORT_BASE if port_base is None else port_base
    base = table + SLOT_WIDTH * slot
    if not (base >= PORT_MINIMUM and base + SLOT_WIDTH - 1 <= PORT_MAXIMUM):
        refuse("port-base-out-of-range", f"slot {slot} from {table} starts at {base}")
    return {role: base + offset for offset, role in enumerate(PORT_ROLES)}


def workspace_count(requested: int) -> int:
    """How many synthetic workspaces a run makes, or a refusal."""
    if not 1 <= requested <= WORKSPACES_MAXIMUM:
        refuse("workspaces-out-of-range", f"{requested}; 1 to {WORKSPACES_MAXIMUM}")
    return requested


def token_file_name(index: int) -> str:
    """The token file of the run's ``index``-th workspace, counted from 1: ``token`` for the first,
    as a run of one has always had."""
    return "token" if index == 1 else f"token-{index}"


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


def society_playback_environment(
    workspace_id: str | None, tick_interval_ms: int | None
) -> dict[str, str]:
    """What ``--society-playback`` hands the API: the run's own workspace and, when stated, the
    base wait. The API validates both at startup; with no workspace it plays nothing."""
    if workspace_id is None:
        if tick_interval_ms is not None:
            refuse(
                "society-interval-without-playback", REFUSALS["society-interval-without-playback"]
            )
        return {}
    environment = {"EXULANICA_SOCIETY_CONTROL_WORKSPACES": json.dumps([workspace_id])}
    if tick_interval_ms is not None:
        environment["EXULANICA_SOCIETY_TICK_INTERVAL_MS"] = str(tick_interval_ms)
    return environment


def society_playback_readiness(readyz: bytes, accounts: bool = False) -> dict[str, object]:
    """The playback readiness check of a ``--society-playback`` run, or a refusal saying why not.

    The run plays one workspace, its own, and discovers accounts' workspaces only with
    ``--accounts-guest-code``."""
    try:
        check = json.loads(readyz)["checks"]["society_playback"]
    except (ValueError, KeyError, TypeError):
        refuse("society-playback-not-running", readyz[:REFUSAL_EXCERPT_CHARACTERS].decode())
    if not (
        check.get("running") is True
        and check.get("listed_workspaces") == 1
        and check.get("account_discovery") is accounts
    ):
        refuse("society-playback-not-running", json.dumps(check)[:REFUSAL_EXCERPT_CHARACTERS])
    return check


def synthetic_permissions(tiles: bool) -> list[str]:
    """The synthetic token's permissions: the account owner's, and with ``--tiles`` the tile one."""
    return [*PERMISSIONS, TILES_PERMISSION] if tiles else list(PERMISSIONS)


def door_bridges_setting(path: Path, workspace_ids: Sequence[str]) -> str:
    """``EXULANICA_DOOR_BRIDGES`` from a file of bridge declarations: each entry's ``"workspaces":
    "synthetic"`` becomes the run's synthetic workspace ids; anything else is passed as written,
    for the API's own loader to admit or refuse at its start."""
    try:
        declared = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refuse("door-bridges-file", REFUSALS["door-bridges-file"])
    if not isinstance(declared, list) or not all(isinstance(entry, dict) for entry in declared):
        refuse("door-bridges-file", REFUSALS["door-bridges-file"])
    return json.dumps(
        [
            {**entry, "workspaces": list(workspace_ids)}
            if entry.get("workspaces") == "synthetic"
            else entry
            for entry in declared
        ]
    )


#: The file in the run directory holding the run's guest code (mode 0600), and the entries a day
#: its guest entry admits.
GUEST_CODE_NAME = "guest-code"
GUEST_ENTRIES_PER_DAY = 50
#: What each guest is granted per provider by the run's guest policy (recorded in the state, so a
#: row can hold an allowance to what was issued).
GUEST_POLICY_CEILING_USD = "0.05"
GUEST_POLICY_MAX_CALLS = 200
#: Give the accounts role its tables as the owner, as an installation's administration does.
PROVISION_ACCOUNTS = r"""
import sys, psycopg
from exulanica.db.account_roles import ACCOUNT_ROLE, provision_account_role
with psycopg.connect(sys.argv[1], autocommit=True) as connection:
    provision_account_role(connection)
print(ACCOUNT_ROLE)
"""
#: The manifest's providers, one an authority and a guest policy are issued for each.
MANIFEST_PROVIDERS = r"""
import json
from exulanica.models.manifest import load_manifest
print(json.dumps(sorted(load_manifest().providers)))
"""


#: The local HTTPS edge ``--accounts-guest-code`` starts: the deployment edge's shape for the name
#: ``localhost`` in the pinned image this machine already holds (never pulled), its configuration in
#: the checkout, and where Caddy's local authority writes its root certificate in the data volume.
EDGE_IMAGE = "caddy:2.11.4-alpine"
EDGE_CADDYFILE = Path("deploy") / "acceptance" / "Caddyfile"
EDGE_ROOT_CERTIFICATE = Path("caddy") / "pki" / "authorities" / "local" / "root.crt"
EDGE_START_SECONDS = 30


def edge_origin(edge_port: int) -> str:
    """The one browser origin of a run's accounts: the edge's HTTPS name and port."""
    return f"https://localhost:{edge_port}"


def edge_command(
    name: str, edge_port: int, api_port: int, caddyfile: Path, data: Path, config: Path
) -> list[str]:
    """The ``docker run`` starting a run's edge: loopback only, the API reached from the container
    as ``host.docker.internal``, and the pinned image used as present."""
    return [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--pull",
        "never",
        "--publish",
        f"127.0.0.1:{edge_port}:443",
        "--env",
        f"EXULANICA_EDGE_UPSTREAM=host.docker.internal:{api_port}",
        "--volume",
        f"{caddyfile}:/etc/caddy/Caddyfile:ro",
        "--volume",
        f"{data}:/data",
        "--volume",
        f"{config}:/config",
        EDGE_IMAGE,
    ]


def start_edge(
    worktree: Path, run_dir: Path, edge_port: int, api_port: int, state: dict, state_file: Path
) -> None:
    """Start the run's edge, record its container before checking it (so ``down`` removes it
    whatever follows), then wait for its root certificate and the API's health through it."""
    data, config = run_dir / "edge" / "data", run_dir / "edge" / "config"
    data.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    name = f"exulanica-acceptance-edge-{edge_port}"
    started = subprocess.run(
        edge_command(name, edge_port, api_port, worktree / EDGE_CADDYFILE, data, config),
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        refuse("edge-failed", started.stderr.strip()[-REFUSAL_EXCERPT_CHARACTERS:])
    certificate = data / EDGE_ROOT_CERTIFICATE
    state["edge"] = {
        "container": started.stdout.strip(),
        "name": name,
        "image": EDGE_IMAGE,
        "port": edge_port,
        "origin": edge_origin(edge_port),
        "upstream_api_port": api_port,
        "root_certificate": str(certificate),
    }
    write_state(state_file, state)
    deadline = time.monotonic() + EDGE_START_SECONDS
    last = "no root certificate yet"
    while time.monotonic() < deadline:
        if certificate.exists():
            context = ssl.create_default_context(cafile=str(certificate))
            try:
                with urllib.request.urlopen(
                    f"{edge_origin(edge_port)}/healthz", timeout=5, context=context
                ) as response:
                    if response.status == 200:
                        state["edge"]["healthz"] = response.status
                        write_state(state_file, state)
                        return
                    last = f"healthz {response.status}"
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
                last = str(error)
        time.sleep(0.5)
    refuse(
        "edge-failed", f"{edge_origin(edge_port)}/healthz within {EDGE_START_SECONDS} s ({last})"
    )


def stop_edge(state: Mapping[str, object], logs: Path) -> None:
    """Remove the edge container this run recorded, after checking the id still names it; its log
    is kept beside the run's others."""
    edge = state["edge"]
    assert isinstance(edge, Mapping)
    container, name = str(edge["container"]), str(edge["name"])
    found = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}} {{.Name}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        print(f"edge: container {container[:12]} is already gone")
        return
    if found.stdout.split() != [container, f"/{name}"]:
        refuse("edge-failed", f"container {container[:12]} is not the recorded {name}")
    log = subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=False)
    if logs.is_dir():
        (logs / "edge.log").write_text(log.stdout + log.stderr)
    subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)
    print(f"edge: removed {name}")


#: Whether every arrival world's tiles are baked and servable, as a guest's entry will ask.
ARRIVAL_BAKED = r"""
import sys, uuid
from exulanica.db.session import Database
from exulanica.world.arrival_worlds import arrival_tiles_baked, load_arrival_worlds
with Database.from_env().session(uuid.UUID(sys.argv[1])) as connection:
    print(all(arrival_tiles_baked(connection, world) for world in load_arrival_worlds()))
"""
ARRIVAL_BAKE_SECONDS = 900


def prepare_arrival_worlds(
    python: Path,
    worktree: Path,
    exports: Mapping[str, str],
    data_dir: Path,
    workspace_id: str,
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    """Make the arrival worlds once in the run's own workspace, as an installation does before it
    admits guests (``deploy/public/public.sh prepare-towns``), and wait until the tile worker has
    baked them, so a guest's entry makes its arrival world at once."""
    environment = {
        **clean_environment(),
        "EXULANICA_DATABASE_URL": exports["EXULANICA_DATABASE_URL"],
        "EXULANICA_DATA_DIR": str(data_dir),
    }
    program = worktree / ".venv" / "bin" / "exulanica-arrival-worlds"
    if not program.exists():
        refuse("toolchain-missing", f"the checkout lacks {program}")
    started = time.monotonic()
    prepared = run([str(program), "prepare", "--workspace", workspace_id], worktree, environment)
    (logs / "arrival-worlds.txt").write_text(prepared)
    deadline = started + ARRIVAL_BAKE_SECONDS
    while time.monotonic() < deadline:
        baked = run([str(python), "-c", ARRIVAL_BAKED, workspace_id], worktree, environment)
        if baked.strip().splitlines()[-1] == "True":
            state["arrival_worlds"] = {
                "prepared_in": workspace_id,
                "baked_after_seconds": round(time.monotonic() - started),
            }
            write_state(state_file, state)
            return
        time.sleep(5)
    refuse(
        "arrival-not-baked", f"the arrival worlds were not baked within {ARRIVAL_BAKE_SECONDS} s"
    )


def role_url(url: str, role: str) -> str:
    """A lane server's connection URL for ``role``: the same server and database, another user."""
    scheme, rest = url.split("://", 1)
    return f"{scheme}://{role}@{rest.split('@', 1)[1] if '@' in rest else rest}"


def accounts_environment(account_url: str, origin: str, code_sha256: str) -> dict[str, str]:
    """What ``--accounts-guest-code`` hands the API: the accounts role, the one browser origin, guest
    entry by the code's digest only, and playback of every account's own workspace."""
    return {
        "EXULANICA_ACCOUNT_DATABASE_URL": account_url,
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS": json.dumps([origin]),
        "EXULANICA_GUEST_ENTRY": "code",
        "EXULANICA_GUEST_ENTRY_CODE_SHA256": code_sha256,
        "EXULANICA_GUEST_ENTRIES_PER_DAY": str(GUEST_ENTRIES_PER_DAY),
        "EXULANICA_SOCIETY_CONTROL_WORKER": "on",
    }


def api_environment(
    *,
    exports: Mapping[str, str],
    grant: Mapping[str, object],
    data_dir: Path,
    model: bool,
    derivative_worker: bool,
    society_playback: Mapping[str, str],
    door_bridges: str | None = None,
    society_of_things: bool = False,
    accounts: Mapping[str, str] | None = None,
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
    environment.update(society_playback)
    if door_bridges is not None:
        environment["EXULANICA_DOOR_BRIDGES"] = door_bridges
    if society_of_things:
        environment["EXULANICA_SOCIETY_OF_THINGS"] = "on"
    if accounts is not None:
        environment.update(accounts)
    return environment


def publication_command(python: Path) -> list[str]:
    """The host's character catalog publication, run by the checkout's own interpreter."""
    return [
        str(python),
        "-m",
        "exulanica.world.character_catalog_publication",
        "publish",
        "--apply",
    ]


def publication_environment(
    owner_url: str, data_dir: Path, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """A clean environment holding the owner connection and the run's data directory alone, so
    the containers land in the store the run's API serves from and nowhere else."""
    return clean_environment(environ) | {
        "EXULANICA_DATABASE_URL": owner_url,
        "EXULANICA_DATA_DIR": str(data_dir),
    }


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


def tile_worker_events(log: Path) -> list[dict[str, object]]:
    """Read only the worker's structured events, never treating other output as success."""
    if not log.exists():
        return []
    events = []
    for line in log.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("component") == "generated-tile-worker":
            events.append(event)
    return events


def start_tile_worker(
    worktree: Path,
    exports: Mapping[str, str],
    data_dir: Path,
    workspace_id: str,
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    """Start the production baker for this workspace and wait for its role check."""
    program = worktree / ".venv" / "bin" / "exulanica-generated-tile-worker"
    if not program.exists():
        refuse("toolchain-missing", f"the checkout lacks {program}")
    environment = clean_environment()
    environment.update(
        {
            "EXULANICA_DATABASE_URL": exports["EXULANICA_DATABASE_URL"],
            "EXULANICA_TILE_PUBLISHER_DATABASE_URL": exports["OWNER_URL"],
            "EXULANICA_DATA_DIR": str(data_dir),
        }
    )
    log = logs / "generated-tile-worker.log"
    pid = spawn([str(program), "--workspace", workspace_id], worktree, environment, log)
    state["pids"]["tile_worker"] = pid
    write_state(state_file, state)
    deadline = time.monotonic() + TILE_WORKER_START_SECONDS
    expected = {"executable": str(program), "workspace": workspace_id}
    while time.monotonic() < deadline:
        events = tile_worker_events(log)
        if any(event.get("event") == "startup_failed" for event in events):
            refuse("tile-worker-startup", str(events[-1])[:REFUSAL_EXCERPT_CHARACTERS])
        command = command_of(pid)
        if command and not worker_command_matches(command, expected):
            break
        started = process_started_at(pid)
        if command and started and "tile_worker_identity" not in state:
            state["tile_worker_identity"] = {**expected, "started_at": started}
            write_state(state_file, state)
        if any(event.get("event") == "startup" for event in events):
            if tile_worker_running(state):
                return
            break
        if not command:
            break
        time.sleep(0.5)
    refuse("tile-worker-startup", log.read_text(errors="replace")[-REFUSAL_EXCERPT_CHARACTERS:])


def depth_checkpoint(worktree: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The depth checkpoint the manifest pins, found in the local Hugging Face cache by its
    revision, with its digest: what a depth-capable worker will load, offline."""
    environ = os.environ if environ is None else environ
    manifest = json.loads((worktree / "exulanica" / "models" / "models.manifest.json").read_text())
    revision = manifest["local_models"][DEPTH_MODEL]["revision"]
    hub = Path(environ.get("HF_HOME") or Path(environ.get("HOME", "~")) / ".cache" / "huggingface")
    snapshot = hub.expanduser() / "hub" / f"models--{DEPTH_MODEL.replace('/', '--')}" / "snapshots"
    checkpoint = snapshot / revision / DEPTH_CHECKPOINT
    if not checkpoint.is_file():
        refuse("depth-checkpoint-missing", str(checkpoint))
    digest = hashlib.sha256()
    with checkpoint.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return {
        "model": DEPTH_MODEL,
        "revision": revision,
        "path": str(checkpoint),
        "resolved": str(checkpoint.resolve()),
        "bytes": str(checkpoint.stat().st_size),
        "sha256": digest.hexdigest(),
    }


def start_depth_worker(
    worktree: Path,
    exports: Mapping[str, str],
    data_dir: Path,
    workspaces: list[str],
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    """Start the production derivative worker with the depth model, offline, for every workspace
    of the run, as a deployment runs it beside its API, and wait for its startup event."""
    program = worktree / ".venv" / "bin" / "exulanica-derivative-worker"
    if not program.exists():
        refuse("toolchain-missing", f"the checkout lacks {program}")
    state["depth_worker"] = {"checkpoint": depth_checkpoint(worktree)}
    environment = clean_environment()
    environment.update(
        {
            "EXULANICA_DATABASE_URL": exports["EXULANICA_DATABASE_URL"],
            "EXULANICA_DATA_DIR": str(data_dir),
            "EXULANICA_DEPTH_MODEL": "moge",
            "EXULANICA_DEPTH_DEVICE": "cpu",
            "HF_HUB_OFFLINE": "1",
        }
    )
    command = [str(program), "--name", DEPTH_WORKER_NAME]
    for workspace in workspaces:
        command += ["--workspace", workspace]
    log = logs / "depth-worker.log"
    state["pids"]["depth_worker"] = spawn(command, worktree, environment, log)
    write_state(state_file, state)
    deadline = time.monotonic() + DEPTH_WORKER_START_SECONDS
    while time.monotonic() < deadline:
        events = []
        for line in log.read_text(errors="replace").splitlines() if log.exists() else []:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("component") == "derivative-worker":
                events.append(event.get("event"))
        if "startup_failed" in events or not command_of(state["pids"]["depth_worker"]):
            break
        if "startup" in events:
            state["depth_worker"]["environment"] = {
                key: environment[key]
                for key in ("EXULANICA_DEPTH_MODEL", "EXULANICA_DEPTH_DEVICE", "HF_HUB_OFFLINE")
            }
            write_state(state_file, state)
            return
        time.sleep(0.5)
    refuse("depth-worker-startup", log.read_text(errors="replace")[-REFUSAL_EXCERPT_CHARACTERS:])


def through_proxy(exports: Mapping[str, str], port: int) -> dict[str, str]:
    """The exports with the API's database URLs pointed at the latency proxy on ``port``."""
    proxied = dict(exports)
    for name in API_DATABASE_URLS:
        upstream = url_port(proxied[name])
        proxied[name] = proxied[name].replace(f":{upstream}/", f":{port}/", 1)
    return proxied


def start_latency_proxy(
    worktree: Path,
    upstream: int,
    port: int,
    run_dir: Path,
    logs: Path,
    state: dict,
    state_file: Path,
) -> None:
    """Start ``latency_proxy.py`` between the API and its PostgreSQL server, with no delay until a
    run writes one to the delay file, and wait for its startup event."""
    delay_file = run_dir / DATABASE_DELAY_NAME
    delay_file.write_text("0")
    log = logs / "latency-proxy.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "latency_proxy.py"),
        "--listen",
        str(port),
        "--upstream",
        str(upstream),
        "--delay-file",
        str(delay_file),
    ]
    state["pids"]["latency_proxy"] = spawn(command, worktree, clean_environment(), log)
    state["database_latency"] = {"port": port, "upstream": upstream, "delay_file": str(delay_file)}
    write_state(state_file, state)
    deadline = time.monotonic() + LATENCY_PROXY_START_SECONDS
    while time.monotonic() < deadline:
        text = log.read_text(errors="replace") if log.exists() else ""
        if '"event": "startup"' in text:
            return
        if not command_of(state["pids"]["latency_proxy"]):
            break
        time.sleep(0.2)
    refuse(
        "latency-proxy-startup", (log.read_text(errors="replace") if log.exists() else "")[-400:]
    )


def command_of(pid: int) -> str:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


def process_started_at(pid: int) -> str:
    """The OS creation identity, so a recycled PID cannot stand for this worker."""
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def worker_command_matches(command: str, identity: Mapping[str, str]) -> bool:
    """Accept the exact entry point, with only its workspace argument and optional interpreter."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    expected = [identity["executable"], "--workspace", identity["workspace"]]
    return argv == expected or (
        len(argv) == 4 and Path(argv[0]).name.lower().startswith("python") and argv[1:] == expected
    )


def tile_worker_running(state: Mapping[str, object]) -> bool:
    pids = state.get("pids")
    identity = state.get("tile_worker_identity")
    if not isinstance(pids, dict) or not isinstance(identity, dict):
        return False
    pid = pids.get("tile_worker")
    if not isinstance(pid, int) or not all(
        isinstance(identity.get(key), str) and identity[key]
        for key in ("executable", "workspace", "started_at")
    ):
        return False
    return (
        worker_command_matches(command_of(pid), identity)
        and process_started_at(pid) == identity["started_at"]
    )


def stop_tile_worker(state: Mapping[str, object]) -> None:
    """Stop only the recorded process group when command, workspace and creation still match."""
    pid = state["pids"]["tile_worker"]
    if not tile_worker_running(state):
        print(f"tile worker: pid {pid} is gone or does not match this run; left alone")
        return
    try:
        if os.getpgid(pid) != pid or not tile_worker_running(state):
            print(f"tile worker: pid {pid} is not this run's process group; left alone")
            return
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(STOP_POLLS):
        if not tile_worker_running(state):
            print(f"tile worker: stopped pid {pid}")
            return
        time.sleep(0.25)
    if tile_worker_running(state) and os.getpgid(pid) == pid:
        os.killpg(pid, signal.SIGKILL)
        print(f"tile worker: killed pid {pid} after SIGTERM timeout")


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


def guest_entry(
    python: Path, worktree: Path, exports: Mapping[str, str], run_dir: Path, logs: Path, origin: str
) -> dict[str, str]:
    """The accounts host ``--accounts-guest-code`` starts: the accounts role given its tables, the
    run's code drawn into a file only this user reads, and an authority and guest policy issued for
    every provider before any guest can enter. The code is never printed or logged."""
    provisioned = subprocess.run(
        [str(python), "-c", PROVISION_ACCOUNTS, exports["OWNER_URL"]],
        cwd=worktree,
        env=clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if provisioned.returncode != 0:
        refuse("accounts-provision", provisioned.stderr.strip()[-REFUSAL_EXCERPT_CHARACTERS:])
    role = provisioned.stdout.strip().splitlines()[-1]
    code = secrets.token_urlsafe(18)
    code_file = run_dir / GUEST_CODE_NAME
    code_file.write_text(code)
    code_file.chmod(0o600)
    providers = json.loads(run([str(python), "-c", MANIFEST_PROVIDERS], worktree))
    operator_environment = {
        **clean_environment(),
        "EXULANICA_DATABASE_URL": exports["OWNER_URL"],
        "EXULANICA_SPENDING_WITNESS_DIR": str(run_dir / SPENDING_WITNESS_NAME),
    }
    issued = []
    for provider in providers:
        authority = subprocess.run(
            [
                str(python),
                "-m",
                "exulanica.spending",
                "issue",
                "--provider",
                provider,
                "--ceiling-usd",
                "1.00",
                "--max-calls",
                "1000",
                "--valid-until",
                "2027-01-01T00:00:00Z",
                "--operator",
                "acceptance",
                "--reason",
                "acceptance guest entry",
            ],
            cwd=worktree,
            env=operator_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if authority.returncode != 0:
            refuse("guest-policy", authority.stderr.strip()[-REFUSAL_EXCERPT_CHARACTERS:])
        authority_id = json.loads(authority.stdout)["authority_id"]
        policy = subprocess.run(
            [
                str(python),
                "-m",
                "exulanica.spending",
                "guest-policy",
                "--authority",
                authority_id,
                "--ceiling-usd",
                GUEST_POLICY_CEILING_USD,
                "--max-calls",
                str(GUEST_POLICY_MAX_CALLS),
                "--valid-for-days",
                "7",
                "--grants-per-day",
                "100",
                "--operator",
                "acceptance",
                "--reason",
                "acceptance guest entry",
            ],
            cwd=worktree,
            env=operator_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if policy.returncode != 0:
            refuse("guest-policy", policy.stderr.strip()[-REFUSAL_EXCERPT_CHARACTERS:])
        issued.append(
            {"provider": provider, "authority": authority.stdout, "policy": policy.stdout}
        )
    (logs / "guest-policy.txt").write_text(json.dumps(issued, indent=2))
    return accounts_environment(
        role_url(exports["EXULANICA_DATABASE_URL"], role),
        origin,
        hashlib.sha256(code.encode()).hexdigest(),
    )


def up(arguments: argparse.Namespace) -> None:
    worktree = checkout(arguments.worktree)
    python = check_toolchain(worktree)
    if arguments.database_latency and arguments.second_api:
        refuse("database-latency-shape", REFUSALS["database-latency-shape"])
    if arguments.depth_worker and not arguments.no_derivative_worker:
        refuse("depth-worker-shape", REFUSALS["depth-worker-shape"])
    if arguments.scripted_model is not None:
        if arguments.model:
            refuse("scripted-with-model", REFUSALS["scripted-with-model"])
        if not Path(arguments.scripted_model).is_file():
            refuse("scripted-plan-missing", str(arguments.scripted_model))
    if arguments.model:
        model_environment()  # refuse before anything starts, not after the database has
    if not arguments.society_playback:
        society_playback_environment(None, arguments.society_tick_interval_ms)  # likewise
    if arguments.door_bridges is not None:
        door_bridges_setting(arguments.door_bridges, [])  # likewise
    if arguments.accounts_guest_code and (
        arguments.edge_port is None
        or not arguments.tiles
        or arguments.scripted_model is None
        or arguments.spending != "durable"
        or not arguments.society_playback
    ):
        refuse("accounts-shape", REFUSALS["accounts-shape"])
    directory = state_dir(worktree)
    state_file = directory / "state.json"
    if state_file.exists():
        refuse("state-exists", str(state_file))
    chosen = ports(arguments.slot, arguments.port_base)
    count = workspace_count(arguments.workspaces)
    spare = arguments.second_api or arguments.database_latency
    for role in ("api", "vite", "browser", *(("spare",) if spare else ())):
        if listening(chosen[role]):
            refuse("port-in-use", f"port {chosen[role]} ({role})")
    if arguments.accounts_guest_code:
        if arguments.edge_port in chosen.values():
            refuse("port-in-use", f"port {arguments.edge_port} (edge) is one of the slot's roles")
        if listening(arguments.edge_port):
            refuse("port-in-use", f"port {arguments.edge_port} (edge)")

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
    # The purge role's URL, for a client that runs the purge as an installation does: in a file of
    # its own at 0600, named by the state and never printed with it.
    purge_url_file = run_dir / PURGE_URL_NAME
    purge_url_file.write_text(exports["EXULANICA_PURGE_DATABASE_URL"])
    purge_url_file.chmod(0o600)
    state["purge_url_file"] = str(purge_url_file)
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
        token: {
            "workspace_id": workspace_id,
            "actor": actor,
            "permissions": synthetic_permissions(arguments.tiles),
        }
    }
    partition = run(
        [str(python), "-c", PROVISION_WORKSPACE, exports["OWNER_URL"], workspace_id], worktree
    ).strip()
    if partition != f"embedding_ws_{uuid.UUID(workspace_id).hex}":
        refuse("workspace-partition", f"workspace {workspace_id} left {partition!r}")
    (logs / "workspace-provision.txt").write_text(f"{workspace_id} -> {partition}\n")
    tiles_limit = None
    if arguments.tiles:
        declared = run(
            [
                str(python),
                "-c",
                DECLARE_TILE_QUOTA,
                exports["OWNER_URL"],
                workspace_id,
                actor,
                str(TILES_LIMIT),
            ],
            worktree,
        ).strip()
        if declared != str(TILES_LIMIT):
            refuse("tile-quota", f"workspace {workspace_id} declared {declared!r}")
        tiles_limit = TILES_LIMIT
    # Further synthetic workspaces, each its own tenant under the one API, and a read-only token.
    others = []
    for index in range(2, count + 1):
        other_workspace, other_actor = str(uuid.uuid4()), str(uuid.uuid4())
        other_token = secrets.token_urlsafe(48)
        other_file = run_dir / token_file_name(index)
        other_file.write_text(other_token)
        other_file.chmod(0o600)
        grant[other_token] = {
            "workspace_id": other_workspace,
            "actor": other_actor,
            "permissions": synthetic_permissions(arguments.tiles),
        }
        other_partition = run(
            [str(python), "-c", PROVISION_WORKSPACE, exports["OWNER_URL"], other_workspace],
            worktree,
        ).strip()
        if other_partition != f"embedding_ws_{uuid.UUID(other_workspace).hex}":
            refuse("workspace-partition", f"workspace {other_workspace} left {other_partition!r}")
        with (logs / "workspace-provision.txt").open("a") as provisioned:
            provisioned.write(f"{other_workspace} -> {other_partition}\n")
        others.append(
            {
                "index": index,
                "workspace_id": other_workspace,
                "actor": other_actor,
                "token_file": str(other_file),
                "embedding_partition": other_partition,
            }
        )
    read_only_grant = None
    if arguments.read_only_token:
        read_only = secrets.token_urlsafe(48)
        read_only_file = run_dir / "token-read"
        read_only_file.write_text(read_only)
        read_only_file.chmod(0o600)
        grant[read_only] = {
            "workspace_id": workspace_id,
            "actor": str(uuid.uuid4()),
            "permissions": list(READ_ONLY_PERMISSIONS),
        }
        read_only_grant = {"token_file": str(read_only_file), **grant[read_only]}
    peer_grant = None
    if arguments.peer_token:
        peer = secrets.token_urlsafe(48)
        peer_file = run_dir / PEER_TOKEN_NAME
        peer_file.write_text(peer)
        peer_file.chmod(0o600)
        grant[peer] = {
            "workspace_id": workspace_id,
            "actor": str(uuid.uuid4()),
            "permissions": synthetic_permissions(arguments.tiles),
        }
        peer_grant = {"token_file": str(peer_file), **grant[peer]}

    door_bridges = None
    if arguments.door_bridges is not None:
        door_bridges = door_bridges_setting(
            arguments.door_bridges, [workspace_id, *(other["workspace_id"] for other in others)]
        )
        state["door_bridges"] = door_bridges
    if arguments.society_of_things:
        state["society_of_things"] = True

    accounts = None
    if arguments.accounts_guest_code:
        accounts = guest_entry(
            python, worktree, exports, run_dir, logs, edge_origin(arguments.edge_port)
        )
        state["accounts"] = {
            "code_file": str(run_dir / GUEST_CODE_NAME),
            "origin": edge_origin(arguments.edge_port),
            "guest_policy": {
                "ceiling_usd": GUEST_POLICY_CEILING_USD,
                "max_calls": GUEST_POLICY_MAX_CALLS,
            },
            "environment": accounts,
        }

    # People are drawn only from published catalogs (migration 0131), so a run publishes before
    # its API starts, exactly as a deployment must.
    published = run(
        publication_command(python),
        worktree,
        publication_environment(exports["OWNER_URL"], data_dir),
    )
    (logs / "character-catalogs.txt").write_text(published)
    state["character_catalogs"] = [line for line in published.splitlines() if line.strip()]
    write_state(state_file, state)

    api_exports = exports
    if arguments.database_latency:
        start_latency_proxy(
            worktree, database_port, chosen["spare"], run_dir, logs, state, state_file
        )
        api_exports = through_proxy(exports, chosen["spare"])
    environment = api_environment(
        exports=api_exports,
        grant=grant,
        data_dir=data_dir,
        model=arguments.model,
        derivative_worker=not arguments.no_derivative_worker,
        society_playback=society_playback_environment(
            workspace_id if arguments.society_playback else None,
            arguments.society_tick_interval_ms,
        ),
        door_bridges=door_bridges,
        society_of_things=arguments.society_of_things,
        accounts=accounts,
    )
    environment.update(model_witness_environment(environment, run_dir))
    plan = None
    if arguments.scripted_model is not None:
        plan = run_dir / SCRIPTED_PLAN_NAME
        plan.write_bytes(Path(arguments.scripted_model).read_bytes())
        environment.update(scripted_environment(run_dir, logs, arguments.spending))
        state["scripted_model"] = {
            "plan": str(plan),
            "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
            "log": str(logs / SCRIPTED_LOG_NAME),
            "spending": arguments.spending,
        }
    api_log = logs / "api.log"
    api_pid = spawn(
        api_command(python, worktree, chosen["api"], plan),
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
            "society_playback": bool(arguments.society_playback),
            "budget_usd": environment.get("EXULANICA_BUDGET_USD"),
            "actor": actor,
            "permissions": synthetic_permissions(arguments.tiles),
            "tiles_limit": tiles_limit,
        }
    )
    if arguments.port_base is not None:
        state["port_base"] = arguments.port_base
    if others:
        state["other_workspaces"] = others
    if read_only_grant is not None:
        state["read_only_token"] = read_only_grant
    if peer_grant is not None:
        state["peer_token"] = peer_grant
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
    if arguments.society_playback:
        check = society_playback_readiness(ready_body, accounts=accounts is not None)
        state["society_playback"] = {
            "workspace_id": workspace_id,
            "base_tick_interval_ms": check.get("base_tick_interval_ms"),
            "readyz": check,
        }
        write_state(state_file, state)
    start_tile_worker(worktree, exports, data_dir, workspace_id, logs, state, state_file)
    if accounts is not None:
        prepare_arrival_worlds(
            python, worktree, exports, data_dir, workspace_id, logs, state, state_file
        )
    if arguments.depth_worker:
        start_depth_worker(
            worktree,
            exports,
            data_dir,
            [workspace_id, *(w["workspace_id"] for w in state.get("other_workspaces", []))],
            logs,
            state,
            state_file,
        )
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
    if arguments.second_api:
        second_log = logs / "api-2.log"
        state["pids"]["api_2"] = spawn(
            api_command(python, worktree, chosen["spare"], plan), worktree, environment, second_log
        )
        state["second_api"] = {"port": chosen["spare"], "log": str(second_log)}
        write_state(state_file, state)
        second_status, _ = wait_http(
            f"http://127.0.0.1:{chosen['spare']}/world-entries",
            API_START_SECONDS,
            {"Authorization": f"Bearer {token}"},
        )
        state["second_api"]["token_probe"] = second_status
        write_state(state_file, state)
        if second_status != 200:
            refuse("token-refused", f"the second API answered {second_status}")

    if accounts is not None:
        start_edge(worktree, run_dir, arguments.edge_port, chosen["api"], state, state_file)

    if arguments.production:
        serve_production(worktree, run_dir, chosen, logs, state, state_file)
    else:
        serve_development(worktree, chosen, token, logs, state, state_file)
    shown = ("worktree", "tree", "ports", "run_dir", "workspace_id", "api_imported_exulanica_from")
    extra = ("society_playback",) if arguments.society_playback else ()
    extra += tuple(
        key
        for key in ("other_workspaces", "read_only_token", "peer_token", "second_api", "edge")
        if key in state
    )
    print(json.dumps({key: state[key] for key in (*shown, "api_health", "app", *extra)}, indent=2))
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
        command = command_of(pid)
        alive = tile_worker_running(state) if name == "tile_worker" else bool(command)
        print(f"{name}: pid {pid} {'alive' if alive else 'gone'}")
    if "tile_worker" in state["pids"]:
        events = tile_worker_events(Path(state["run_dir"]) / "logs" / "generated-tile-worker.log")
        bakes = [event for event in events if event.get("event") == "bake"]
        print(
            "tile worker: "
            + json.dumps(
                {
                    "running": tile_worker_running(state),
                    "started": any(event.get("event") == "startup" for event in events),
                    "baked": sum(event.get("status") == "baked" for event in bakes),
                    "failed": sum(event.get("status") != "baked" for event in bakes),
                    "last_event": events[-1] if events else None,
                }
            )
        )
    shown = ("tree", "ports", "run_dir", "workspace_id", "database", "society_playback")
    print(json.dumps({key: state.get(key) for key in shown}, indent=2))


def recorded_grants(state: Mapping[str, object], run_dir: Path) -> dict[str, dict[str, object]]:
    """Every grant the run's API was started with, by token file name, rebuilt from the token
    files and the state that recorded whom each token names."""
    grants: dict[str, dict[str, object]] = {
        token_file_name(1): {
            "workspace_id": state["workspace_id"],
            "actor": state["actor"],
            "permissions": list(state["permissions"]),
        }
    }
    for other in state.get("other_workspaces", []):
        grants[Path(other["token_file"]).name] = {
            "workspace_id": other["workspace_id"],
            "actor": other["actor"],
            "permissions": list(state["permissions"]),
        }
    for key in ("read_only_token", "peer_token"):
        recorded = state.get(key)
        if isinstance(recorded, Mapping):
            grants[Path(recorded["token_file"]).name] = {
                "workspace_id": recorded["workspace_id"],
                "actor": recorded["actor"],
                "permissions": list(recorded["permissions"]),
            }
    for name in grants:
        if not (run_dir / name).is_file():
            refuse("token-file-unknown", f"{name} is recorded but absent from {run_dir}")
    return grants


def restart_api(arguments: argparse.Namespace) -> None:
    worktree = recorded_checkout(arguments.worktree)
    state_file = state_dir(worktree) / "state.json"
    if not state_file.exists():
        refuse("no-state", str(state_file))
    state = json.loads(state_file.read_text())
    second = arguments.api == "second"
    if second and "api_2" not in state["pids"]:
        refuse("no-second-api", REFUSALS["no-second-api"])
    run_dir = Path(state["run_dir"])
    logs = run_dir / "logs"
    grants = recorded_grants(state, run_dir)
    revoked = arguments.revoke
    if revoked is not None:
        if revoked not in grants:
            refuse("token-file-unknown", f"{revoked}; this run wrote {', '.join(sorted(grants))}")
        grants.pop(revoked)
    if state.get("model"):
        model_environment()  # refuse before the running API is stopped, not after
    exports = served_exports((logs / "database-serve.txt").read_text())
    if isinstance(state.get("database_latency"), Mapping):
        exports = through_proxy(exports, int(state["database_latency"]["port"]))
    grant = {(run_dir / name).read_text(): granted for name, granted in grants.items()}
    playback = state.get("society_playback")
    environment = api_environment(
        exports=exports,
        grant=grant,
        data_dir=Path(state["data_dir"]),
        model=bool(state.get("model")),
        derivative_worker=state.get("derivative_worker") != "off",
        society_playback=society_playback_environment(
            state["workspace_id"] if playback else None,
            playback.get("base_tick_interval_ms") if isinstance(playback, Mapping) else None,
        ),
        door_bridges=state.get("door_bridges"),
        society_of_things=bool(state.get("society_of_things")),
        accounts=(state.get("accounts") or {}).get("environment"),
    )
    environment.update(model_witness_environment(environment, run_dir))
    scripted = state.get("scripted_model")
    if isinstance(scripted, Mapping):
        environment.update(
            scripted_environment(run_dir, logs, scripted.get("spending", SPENDING_MODES[0]))
        )
    pid_key, port_role, log_name = (
        ("api_2", "spare", "api-2.log") if second else ("api", "api", "api.log")
    )
    stop(state["pids"][pid_key], API_MARKER, pid_key)
    chosen = state["ports"]
    if listening(chosen[port_role]):
        refuse("port-in-use", f"port {chosen[port_role]} ({pid_key}) is still held after the stop")
    api_pid = spawn(
        api_command(
            worktree / ".venv" / "bin" / "python",
            worktree,
            chosen[port_role],
            Path(scripted["plan"]) if isinstance(scripted, Mapping) else None,
        ),
        worktree,
        environment,
        logs / log_name,
    )
    state["pids"][pid_key] = api_pid
    restart = {
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "pid": api_pid,
        "api": arguments.api,
        "revoked_token_file": revoked,
        "grants": sorted(grants),
    }
    state.setdefault("restarts", []).append(restart)
    write_state(state_file, state)
    healthz, _ = wait_http(f"http://127.0.0.1:{chosen[port_role]}/healthz", API_START_SECONDS)
    restart["healthz"] = healthz
    write_state(state_file, state)
    print(json.dumps(restart, indent=2))


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
    if "edge" in state:
        stop_edge(state, Path(state["run_dir"]) / "logs")
    if "tile_worker" in state["pids"]:
        stop_tile_worker(state)
    if "latency_proxy" in state["pids"]:
        stop(state["pids"]["latency_proxy"], "latency_proxy.py", "latency proxy")
    if "depth_worker" in state["pids"]:
        stop(state["pids"]["depth_worker"], DEPTH_WORKER_NAME, "depth worker")
    if "vite" in state["pids"]:
        stop(state["pids"]["vite"], "vite", "app")
    if "api_2" in state["pids"]:
        stop(state["pids"]["api_2"], API_MARKER, "api_2")
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
    for name in ("up", "status", "down", "restart-api"):
        command = commands.add_parser(name)
        command.add_argument("--worktree", required=True, help="the checkout to run")
        if name == "restart-api":
            command.add_argument(
                "--api",
                choices=("primary", "second"),
                default="primary",
                help="which API process to restart (default: primary)",
            )
            command.add_argument(
                "--revoke",
                metavar="TOKEN_FILE",
                help="leave this token file's grant out of the restarted API (default: none)",
            )
        if name == "up":
            command.add_argument("--slot", type=int, default=0, help="the port slot, 0 to 6")
            command.add_argument("--reuse-database", action="store_true")
            command.add_argument(
                "--model",
                action="store_true",
                help="pass NEBIUS_API_KEY, EXULANICA_EGRESS_ALLOWLIST, EXULANICA_BUDGET_USD "
                "and EXULANICA_BUDGET_MAX_CALLS "
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
            command.add_argument(
                "--society-playback",
                action="store_true",
                help="the API advances this run's workspace's playing societies on its own "
                "(default: it advances nothing)",
            )
            command.add_argument(
                "--tiles",
                action="store_true",
                help="grant the synthetic token tiles.materialise and declare its workspace a "
                "tile quota of TILES_LIMIT (default: neither)",
            )
            command.add_argument(
                "--port-base",
                type=int,
                help="start the slot table at this port instead of PORT_BASE (default: PORT_BASE)",
            )
            command.add_argument(
                "--workspaces",
                type=int,
                default=1,
                help="how many synthetic workspaces to make, each with its own token file, "
                "1 to WORKSPACES_MAXIMUM (default: 1)",
            )
            command.add_argument(
                "--scripted-model",
                metavar="PLAN",
                help="serve the API with scripts/acceptance/scripted_model.py answering model "
                "requests from PLAN; refused with --model (default: no model)",
            )
            command.add_argument(
                "--spending",
                choices=SPENDING_MODES,
                default=SPENDING_MODES[0],
                help="with --scripted-model, the EXULANICA_SPENDING the API states: the plan's "
                "process bounds, or the durable authority with its witness in the run directory "
                "(default: process)",
            )
            command.add_argument(
                "--peer-token",
                action="store_true",
                help="also write token-peer, a second actor in the first workspace with the same "
                "permissions",
            )
            command.add_argument(
                "--second-api",
                action="store_true",
                help="start a second API process on the slot's spare port with the same database, "
                "store, spending witness and grants",
            )
            command.add_argument(
                "--read-only-token",
                action="store_true",
                help="also write token-read, granting the first workspace world.read alone",
            )
            command.add_argument(
                "--database-latency",
                action="store_true",
                help="put latency_proxy.py between the API and PostgreSQL on the slot's spare "
                "port, adding the delay the run directory's database-delay-ms names "
                "(default: no proxy)",
            )
            command.add_argument(
                "--depth-worker",
                action="store_true",
                help="with --no-derivative-worker, run the production derivative worker with the "
                "depth model from the local model cache, offline (default: no depth)",
            )
            command.add_argument(
                "--door-bridges",
                metavar="FILE",
                help="admit the outside programs a JSON array of bridge declarations names "
                '(EXULANICA_DOOR_BRIDGES; an entry\'s "workspaces": "synthetic" becomes the '
                "run's synthetic workspaces) (default: no bridge)",
            )
            command.add_argument(
                "--society-of-things",
                action="store_true",
                help="offer the society of things on the API (EXULANICA_SOCIETY_OF_THINGS=on), "
                "for rehearsal stacks on fresh acceptance databases only (default: not offered)",
            )
            command.add_argument(
                "--accounts-guest-code",
                action="store_true",
                help="also serve browser accounts with guest entry by a code drawn for the run "
                "(its SHA-256 only reaches the API), an authority and guest policy per provider, "
                "and playback of accounts' own workspaces; needs --edge-port, --tiles, "
                "--scripted-model, --spending durable and --society-playback (default: no accounts)",
            )
            command.add_argument(
                "--edge-port",
                type=int,
                help="with --accounts-guest-code, the loopback port of the local HTTPS edge in "
                "front of the API; the browser origin is https://localhost:<port> (default: none)",
            )
            command.add_argument(
                "--society-tick-interval-ms",
                type=int,
                help="with --society-playback, the host's base wait between simulated minutes "
                "(default: the API's declared default)",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if shutil.which("lsof") is None:
            refuse("lsof-missing", REFUSALS["lsof-missing"])
        commands = {"up": up, "status": status, "down": down, "restart-api": restart_api}
        commands[arguments.command](arguments)
    except Refused as refused:
        print(f"refused ({refused.name}): {refused.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
