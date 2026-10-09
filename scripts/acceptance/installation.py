#!/usr/bin/env python3
"""The installation acceptance driver: rows L1, L2a and L2b on a complete installation composed here.

    python3 scripts/acceptance/installation.py run --worktree PATH --out DIR [--slot N --port-base N]
    python3 scripts/acceptance/installation.py down --worktree PATH

``run`` builds the composition's images from an export of the checkout's HEAD (``git archive``), so an
image holds exactly that commit, installs them from empty volumes as a Compose project of this
checkout's own, and checks three rows through the
installation's one entry point, ``exulanica-installation`` (docs/deployment.md section 9):

- L1, a clean install: every service healthy or completed; the facts' identity names HEAD, the
  images the running containers were started from and the schema the tree carries; no-model mode
  keeps ``/readyz`` 200; a saved world is created and read again from a recreated API container.
- L2a, a planned restore with ``--set-aside``: a photograph is taken in, a backup set taken and
  verified, the photograph's capture withdrawn after it and purged; with every writer stopped the
  set is restored; the withdrawal is replayed before anything serves; the set-aside source is then
  discarded.
- L2b, a declared crash recovery: after a new backup set, one withdrawal reaches the newest export
  and one is made after it; every volume is deleted; a declaration naming a missing, mismatched,
  older or out-of-bound authority is refused with nothing written; the declared recovery then
  replays the first withdrawal and states the second as inside its loss window.

Every row ends ``passed``, ``failed`` or ``blocked``. Times are this fixture's (one or two
photographs and a few hundred rows), never sizing figures; nothing here makes a timing claim.

The driver speaks HTTP to the installation as an independent client, and acts as its operator
through ``docker compose`` alone: ``exec`` and ``run`` of the composition's own services, and
``psql`` in its own database container for evidence reads and for the withdrawals, which no route
makes (a capture is tombstoned by its owner's SQL, as the deletion contract's tests do). Secrets are
generated per run into a private environment file and never printed. Docker reads a private client
configuration, so no credential helper runs. Only this checkout's project is touched; ``down``
removes its containers, networks and volumes, and the run takes it down at the end.

Outputs under ``--out``: ``results.json``, ``evidence/`` (command outputs without secrets, the build
log and what it downloaded) and ``manifest.json`` (the tree, this file's digest at start, the
images).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAUNCH = _load("exulanica_acceptance_launch", HERE / "launch.py")
#: This file's digest as the run began; a run records whether it changed before the run ended.
DRIVER_SHA256_AT_START = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

STATES = ("passed", "failed", "blocked")
#: The profile compose.yaml selects by default, built with the server extra alone.
PROFILE = "single-host-server-only"
BACKEND_EXTRAS = "--extra server"
#: Components that profile installs but whose workers the image cannot run.
UNAVAILABLE = {
    "derivatives": "image_built_without_extra",
    "pose_scene": "image_built_without_extra",
}
#: Services the default composition starts, one-shot jobs included.
SERVICES = ("postgres", "restore-marker", "migrate", "catalogs", "api", "maintenance", "client")
ONE_SHOT = ("restore-marker", "migrate", "catalogs")
#: Images the composition builds, by service.
BUILT = ("api", "migrate", "catalogs", "restore-marker", "maintenance", "restore", "client")
#: Base images the build may use, each already on this host; a pull is recorded as a download.
BASE_IMAGES = ("python:3.11-slim-trixie", "pgvector/pgvector:0.8.6-pg18", "nginx:1.29-alpine")
#: Lines of a plain-progress build that mean bytes were fetched from a network.
DOWNLOADED = re.compile(r"\b(Downloading|Downloaded|Pulling|pulling fs layer|Pull complete)\b")
OWNER = "exulanica"
DATABASE = "exulanica"
#: Paths inside the composition (compose.yaml).
BACKUP_MOUNT = "/var/lib/exulanica-backup"
CUSTODY_MOUNT = "/var/lib/exulanica-custody"
MEDIA = "/var/lib/exulanica"
UP_SECONDS = 600
BUILD_SECONDS = 3600
COMMAND_SECONDS = 600
READY_SECONDS = 180
#: The start of L1's one failure that is not about the installation working.
DISCOVERY = "F1 discovery"
#: Where the docker CLI plugins live: Docker Desktop's bundle, and the user's own plugin directory.
CLI_PLUGINS = (
    Path("/Applications/Docker.app/Contents/Resources/cli-plugins"),
    Path.home() / ".docker" / "cli-plugins",
)
#: The permissions the operator token holds: the account owner's (launch.py).
PERMISSIONS = list(LAUNCH.PERMISSIONS)

PROVISION = r"""
import sys, uuid, psycopg
from exulanica.db.migrate import provision_workspace
url, workspace = sys.stdin.readline().strip(), uuid.UUID(sys.argv[1])
with psycopg.connect(url, autocommit=True) as connection:
    provision_workspace(connection, workspace)
print("provisioned")
"""

STORED = r"""
import pathlib, sys
print(sum(1 for p in pathlib.Path(sys.argv[1]).rglob("*") if sys.argv[2] in p.name))
"""


# -- results ---------------------------------------------------------------------------------------


class Row:
    """One matrix row's result, with what was expected and what was seen."""

    def __init__(self, row: str, check: str, expected: str) -> None:
        self.row, self.check, self.expected = row, check, expected
        self.status = "blocked"
        self.observed: dict[str, Any] = {}
        self.failures: list[str] = []
        self.blocked_by: list[str] = []

    def expect(self, condition: bool, failure: str) -> bool:
        if not condition:
            self.failures.append(failure)
        return condition

    def close(self) -> Row:
        self.status = "blocked" if self.blocked_by else ("failed" if self.failures else "passed")
        return self

    def document(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "check": self.check,
            "status": self.status,
            "expected": self.expected,
            "failures": self.failures,
            "blocked_by": self.blocked_by,
            "observed": self.observed,
        }


# -- the composition -------------------------------------------------------------------------------


def project_name(worktree: Path) -> str:
    """This checkout's Compose project: its state directory's key, so two checkouts never share."""
    return "exulanica-acc-" + LAUNCH.state_dir(worktree).name.rsplit("-", 1)[-1]


class Installation:
    """One checkout's composed installation: its project, private files and operator token."""

    def __init__(self, worktree: Path, slot: int, port_base: int | None) -> None:
        self.worktree = worktree
        self.project = project_name(worktree)
        self.home = LAUNCH.state_dir(worktree) / "installation"
        self.ports = LAUNCH.ports(slot, port_base)
        self.api = f"http://127.0.0.1:{self.ports['api']}"
        self.client = f"http://127.0.0.1:{self.ports['vite']}"
        self.env_file = self.home / "compose.env"
        self.operator_file = self.home / "operator.json"
        self.backup = self.home / "backup"
        self.custody = self.home / "custody"
        self.docker_config = self.home / "docker-config"
        #: HEAD exported, the project directory and every build's context.
        self.tree = self.home / "tree"
        #: The fixture: identical intake probes (the default) or one per photograph.
        self.distinct_probes = False

    def prepare(self) -> None:
        # A clean install starts with no backup set and no custody: another run's exports name
        # tombstones this database never held, and a backup rightly refuses it (deployment.md 9.2).
        for directory in (self.backup, self.custody):
            if directory.exists():
                subprocess.run(["rm", "-rf", str(directory)], check=True)
        for directory in (self.home, self.backup, self.custody, self.docker_config):
            directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        # No credential store, so no helper runs; the CLI plugins (compose, buildx) are found
        # where Docker Desktop installs them, which a private configuration does not otherwise name.
        config = {"cliPluginsExtraDirs": [str(path) for path in CLI_PLUGINS if path.is_dir()]}
        (self.docker_config / "config.json").write_text(json.dumps(config))

    def environment(self) -> dict[str, str]:
        """What docker reads: nothing of the caller's EXULANICA_ or database settings, which
        Compose would otherwise prefer to the environment file, and a private client config."""
        keep = ("PATH", "HOME", "TMPDIR", "LANG")
        environment = {k: os.environ[k] for k in keep if k in os.environ}
        environment["DOCKER_CONFIG"] = str(self.docker_config)
        environment["BUILDKIT_PROGRESS"] = "plain"
        return environment

    def compose_command(self, *arguments: str) -> list[str]:
        return [
            "docker", "compose", "-p", self.project,
            "-f", str(self.tree / "compose.yaml"), "--env-file", str(self.env_file),
            *arguments,
        ]  # fmt: skip

    def compose(
        self, *arguments: str, stdin: str | None = None, timeout: float = COMMAND_SECONDS
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.compose_command(*arguments),
            cwd=self.tree,
            env=self.environment(),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def docker(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *arguments],
            env=self.environment(),
            capture_output=True,
            text=True,
            timeout=COMMAND_SECONDS,
            check=False,
        )

    def sql(self, statement: str, database: str = DATABASE) -> list[str]:
        """Rows of one statement as the owner, over the database container's local socket."""
        done = self.compose(
            "exec", "-T", "postgres", "psql", "-U", OWNER, "-d", database,
            "-v", "ON_ERROR_STOP=1", "-qAt", "-c", statement,
        )  # fmt: skip
        if done.returncode != 0:
            raise RuntimeError(f"psql: {done.stderr.strip()[:500]}")
        return [line for line in done.stdout.splitlines() if line]

    def operator(self, *arguments: str, service: str = "maintenance") -> tuple[int, Any, str]:
        """``exulanica-installation`` in a one-off container of ``service``, with that service's
        settings and volumes: its exit, the JSON it printed and its whole stderr."""
        done = self.compose(
            "--profile", "recovery", "run", "--rm", "--no-deps", "-T",
            "--entrypoint", "exulanica-installation", service, *arguments,
        )  # fmt: skip
        return done.returncode, parse_json(done.stdout), done.stderr.strip()

    def token(self) -> str:
        return json.loads(self.operator_file.read_text())["token"]

    def workspace(self) -> str:
        return json.loads(self.operator_file.read_text())["workspace_id"]


def parse_json(text: str) -> Any:
    """The last JSON document a command printed, or None."""
    for start in range(len(text)):
        if text[start] == "{":
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                continue
    return None


def http(
    method: str, url: str, token: str | None = None, body: object = None, timeout: float = 30
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as refused:
        raw, status = refused.read(), refused.code
    except (urllib.error.URLError, ConnectionError, TimeoutError) as failed:
        return 0, str(failed)
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, raw[:200].decode(errors="replace")


def upload(base: str, token: str, name: str, photo: bytes) -> tuple[int, Any]:
    """``POST /intake`` with one photograph."""
    boundary = f"q10-{uuid.uuid4().hex}"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + photo
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        f"{base}/intake",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"null")


def photograph(seed: int, distinct_probes: bool = False) -> bytes:
    """A small synthetic JPEG, different for every seed: development data, no person, no place.

    By default every photograph is 64x48 with no EXIF, so their intake probes are the same bytes:
    a capture live after a recovery then holds a withdrawn one's probe, which is the state L2b's
    finding names (candidate-8-installation-run1) and the test of its fix. ``distinct_probes``
    gives each seed its own width, so every probe differs, to observe the rest of the mechanics.
    """
    from PIL import Image

    width = 64 + seed if distinct_probes else 64
    image = Image.new("RGB", (width, 48), ((seed * 53) % 256, 90, (seed * 97) % 256))
    for x in range(width):
        image.putpixel((x, seed % 48), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def wait_ready(base: str, seconds: float = READY_SECONDS) -> float | None:
    """Seconds until ``/readyz`` answered 200, or None."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        status, _ = http("GET", f"{base}/readyz", timeout=5)
        if status == 200:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    return None


# -- building --------------------------------------------------------------------------------------


def main_checkout(worktree: Path) -> Path:
    common = LAUNCH.run(["git", "rev-parse", "--git-common-dir"], worktree).strip()
    return (worktree / common).resolve().parent


#: Where the checkout's own state reaches an image: the client bundle is built from the checkout's
#: web/, every other image from HEAD's archive. A change there would put other code in the image.
BUNDLE_SOURCES = ("web/",)


def export_head(installation: Installation) -> list[str]:
    """HEAD into the installation's tree directory, and the checkout's own changes, none of which
    may be in the client bundle's sources."""
    status = LAUNCH.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], installation.worktree
    )
    changed = sorted(line[3:] for line in status.splitlines() if line.strip())
    built = [path for path in changed if path.startswith(BUNDLE_SOURCES)]
    if built:
        raise SystemExit(f"the checkout changes the client bundle's sources: {built[:5]}")
    if installation.tree.exists():
        subprocess.run(["rm", "-rf", str(installation.tree)], check=True)
    installation.tree.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=installation.worktree,
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(installation.tree)], input=archive, check=True)
    return changed


def client_bundle(worktree: Path, evidence: Path) -> dict[str, str]:
    """The client bundle built on the host from the offline store, and its provenance."""
    web = worktree / "web"
    done = subprocess.run(
        ["pnpm", "--filter", "@exulanica/app", "build"],
        cwd=web,
        env=LAUNCH.production_build_environment(),
        capture_output=True,
        text=True,
        timeout=BUILD_SECONDS,
        check=False,
    )
    (evidence / "client-bundle.log.txt").write_text(done.stdout + done.stderr)
    if done.returncode != 0:
        raise RuntimeError("the client bundle did not build; see evidence/client-bundle.log.txt")
    dist = web / "packages" / "app" / "dist"
    lines = sorted(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(dist).as_posix()}\n"
        for p in dist.rglob("*")
        if p.is_file()
    )
    return {"dist": str(dist), **provenance(worktree, dist, lines)}


def provenance(worktree: Path, dist: Path, lines: list[str]) -> dict[str, str]:
    node = LAUNCH.run(["node", "--version"], worktree).strip()
    pnpm = LAUNCH.run(["pnpm", "--version"], worktree / "web").strip()
    return {
        # sha256 over the sorted "<file sha256>  <path>" lines of the built tree.
        "EXULANICA_CLIENT_TREE_SHA256": hashlib.sha256("".join(lines).encode()).hexdigest(),
        "EXULANICA_NODE_VERSION": node,
        "EXULANICA_PNPM_VERSION": pnpm,
    }


def write_environment(installation: Installation, values: Mapping[str, str]) -> None:
    text = "".join(f"{key}='{value}'\n" for key, value in values.items())
    installation.env_file.write_text(text)
    os.chmod(installation.env_file, 0o600)


def secrets_environment(installation: Installation, head: str) -> dict[str, str]:
    """Fresh role passwords and an operator token, written to private files, never printed."""
    token = secrets.token_hex(24)
    workspace, actor = str(uuid.uuid4()), str(uuid.uuid4())
    installation.operator_file.write_text(json.dumps({"token": token, "workspace_id": workspace}))
    os.chmod(installation.operator_file, 0o600)
    grant = {token: {"workspace_id": workspace, "actor": actor, "permissions": PERMISSIONS}}
    return {
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "EXULANICA_APP_ROLE_PASSWORD": secrets.token_hex(16),
        "EXULANICA_EXECUTOR_ROLE_PASSWORD": secrets.token_hex(16),
        "EXULANICA_PURGE_ROLE_PASSWORD": secrets.token_hex(16),
        "EXULANICA_BACKUP_ROLE_PASSWORD": secrets.token_hex(16),
        "EXULANICA_API_TOKENS": json.dumps(grant, separators=(",", ":")),
        "EXULANICA_PROFILE": PROFILE,
        "EXULANICA_BACKEND_EXTRAS": BACKEND_EXTRAS,
        "EXULANICA_BACKUP_PATH": str(installation.backup),
        "EXULANICA_CUSTODY_PATH": str(installation.custody),
        "EXULANICA_PORT": f"127.0.0.1:{installation.ports['api']}",
        "EXULANICA_CLIENT_PORT": str(installation.ports["vite"]),
        "EXULANICA_CODE_REVISION": head,
        # Compose checks every service's required settings, started or not; the reconstruction
        # workers this profile does not start may drain only the operator's workspace.
        "EXULANICA_WORKSPACE_IDS": workspace,
    }


def image_ids(installation: Installation) -> dict[str, str]:
    found = {}
    for service in BUILT:
        done = installation.docker(
            "image", "inspect", f"{installation.project}-{service}", "--format", "{{.Id}}"
        )
        found[service] = done.stdout.strip() if done.returncode == 0 else ""
    return found


def base_image_ids(installation: Installation) -> dict[str, str]:
    found = {}
    for image in BASE_IMAGES:
        done = installation.docker("image", "inspect", image, "--format", "{{.Id}}")
        found[image] = done.stdout.strip() if done.returncode == 0 else ""
    return found


def build(installation: Installation, evidence: Path) -> dict[str, Any]:
    """Build every image of the composition, through quiet-slot unless ACCEPTANCE_QUIET_SLOT is
    off (root's 16:43 rule); record what it downloaded."""
    quiet = main_checkout(installation.worktree) / ".exulanica" / "bin" / "quiet-slot"
    slotted = quiet.exists() and os.environ.get("ACCEPTANCE_QUIET_SLOT", "on") != "off"
    before = base_image_ids(installation)
    command = installation.compose_command("--profile", "recovery", "build")
    if slotted:
        command = [str(quiet), *command]
    started = time.monotonic()
    done = subprocess.run(
        command,
        cwd=installation.worktree,
        env=installation.environment(),
        capture_output=True,
        text=True,
        timeout=BUILD_SECONDS,
        check=False,
    )
    log = done.stdout + done.stderr
    (evidence / "build.log.txt").write_text(log)
    after = base_image_ids(installation)
    downloads = [line[:300] for line in log.splitlines() if DOWNLOADED.search(line)]
    return {
        "exit": done.returncode,
        "through_quiet_slot": slotted,
        "seconds": round(time.monotonic() - started, 1),
        "download_lines": downloads,
        "metadata_lookups": sum("load metadata for" in line for line in log.splitlines()),
        "base_images_before": before,
        "base_images_after": after,
        "images": image_ids(installation),
    }


# -- shared steps ----------------------------------------------------------------------------------


def up(installation: Installation) -> tuple[int, float, str]:
    started = time.monotonic()
    done = installation.compose("up", "-d", "--no-build", "--wait", timeout=UP_SECONDS)
    return done.returncode, round(time.monotonic() - started, 1), done.stderr.strip()[-1500:]


def services(installation: Installation) -> dict[str, dict[str, Any]]:
    """Each service's container state, health, exit code and image."""
    done = installation.compose("ps", "-a", "--format", "json")
    found: dict[str, dict[str, Any]] = {}
    for line in done.stdout.splitlines():
        if not line.strip():
            continue
        entries = json.loads(line)
        for entry in entries if isinstance(entries, list) else [entries]:
            image = installation.docker("inspect", entry["ID"], "--format", "{{.Image}}")
            found[entry["Service"]] = {
                "state": entry.get("State"),
                "health": entry.get("Health"),
                "exit_code": entry.get("ExitCode"),
                "image": image.stdout.strip(),
            }
    return found


def facts(installation: Installation) -> tuple[int, Any]:
    return http("GET", f"{installation.api}/operations/installation", installation.token())


def capture_of(answer: Any) -> str | None:
    accepted = answer.get("accepted") if isinstance(answer, dict) else None
    return accepted[0].get("capture_id") if accepted else None


def take_photo(installation: Installation, seed: int) -> dict[str, Any]:
    photo = photograph(seed, installation.distinct_probes)
    status, answer = upload(installation.api, installation.token(), f"q10-{seed}.jpg", photo)
    return {
        "status": status,
        "capture_id": capture_of(answer),
        "blob_sha256": hashlib.sha256(photo).hexdigest(),
        "answer": answer if capture_of(answer) is None else None,
    }


def stored(installation: Installation, blob: str) -> int:
    """How many files in the media volume carry the blob's digest in their name."""
    done = installation.compose(
        "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "api", "-c", STORED, MEDIA, blob
    )
    return int(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else -1


def withdraw(installation: Installation, capture: str, reason: str) -> dict[str, str]:
    """Tombstone a capture as its owner (no route makes one), returning the row's id and time."""
    workspace = installation.workspace()
    rows = installation.sql(
        f"select set_config('exulanica.workspace_id', '{workspace}', false); "
        "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
        f"values ('{workspace}', 'capture', '{capture}', gen_random_uuid(), '{reason}') "
        "returning tombstone_id || ' ' || "
        "to_char(requested_at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"
    )
    tombstone, requested_at = rows[-1].split(" ", 1)
    return {"tombstone_id": tombstone, "requested_at": requested_at}


#: Every other artifact carrying one of a photograph's derived bytes, live capture or not: which
#: artifact, of what kind, from which bytes, and whether its capture is live.
SHARERS = (
    "select b.artifact_id || ' kind=' || b.kind || ' stage=' || b.stage_key || ' from=' || "
    "left(encode(b.source_blob_sha256, 'hex'), 12) || ' purged=' || (b.purged_at is not null) || "
    "' captures=' || coalesce((select string_agg(c.capture_id || ':' || "
    "case when c.deleted_at is null then 'live' else 'deleted' end, ',') from capture c "
    "where c.blob_sha256 = b.source_blob_sha256), 'none') "
    "from artifact a join artifact b on b.content_sha256 = a.content_sha256 "
    "and b.artifact_id <> a.artifact_id "
    "where a.source_blob_sha256 = decode('{blob}', 'hex') order by 1"
)


def live_captures(installation: Installation, capture: str) -> int:
    """The capture's row while it is live: a withdrawal marks it deleted rather than removing it."""
    return int(
        installation.sql(
            f"select count(*) from capture where capture_id = '{capture}' and deleted_at is null"
        )[0]
    )


#: How many live captures' unpurged artifacts carry each of a photograph's derived bytes: what the
#: purge's release question (purge_releases_bytes) counts as still holding them.
SHARED = (
    "select encode(a.content_sha256, 'hex') || ' kind=' || a.kind || ' live_sharers=' || ("
    "select count(*) from artifact b join capture c on c.blob_sha256 = b.source_blob_sha256 "
    "and c.workspace_id = b.workspace_id where b.content_sha256 = a.content_sha256 "
    "and b.purged_at is null and c.deleted_at is null and b.artifact_id <> a.artifact_id) "
    "from artifact a where a.source_blob_sha256 = decode('{blob}', 'hex') "
    "and a.content_sha256 is not null order by 1"
)


def tombstones_for(installation: Installation, capture: str) -> int:
    return int(
        installation.sql(f"select count(*) from tombstone where capture_id = '{capture}'")[0]
    )


def databases(installation: Installation) -> list[str]:
    return installation.sql(
        "select datname from pg_database where datname like 'exulanica%' order by 1", "postgres"
    )


def exports(installation: Installation) -> list[dict[str, Any]]:
    """Custody's exported records, oldest first: file, covered_through, source and digest."""
    found = []
    for path in sorted(installation.custody.glob("*.json")):
        try:
            entry = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        record = entry.get("record") or {}
        if entry.get("state") != "exported" or "covered_through" not in record:
            continue
        found.append(
            {
                "file": path.name,
                "covered_through": record["covered_through"],
                "source": str(record.get("source_identity", ""))[:12],
                "record_sha256": entry.get("record_sha256"),
                "tombstones": len(record.get("tombstones", [])),
            }
        )
    return sorted(found, key=lambda e: e["covered_through"])


def maintenance_pass(installation: Installation) -> dict[str, Any]:
    code, status, _ = installation.operator("maintenance", "--once")
    status = status or {}
    return {
        "exit": code,
        "failures": status.get("failures"),
        "withdrawal_export": status.get("withdrawal_export"),
        "objects_not_in_backup_listed": status.get("objects_not_in_backup_listed"),
    }


def backup_set(installation: Installation) -> tuple[int, str | None, dict[str, Any] | None]:
    """A backup set and its verification: exit, the set's name, the verification."""
    code, taken, error = installation.operator("backup")
    if code != 0 or not taken:
        return code, None, {"error": error.splitlines()[-1][:400] if error else ""}
    name = Path(taken["backup_set"]).name
    verified_code, verified, error = installation.operator(
        "verify", "--backup-set", f"{BACKUP_MOUNT}/sets/{name}"
    )
    return code, name, {"exit": verified_code, "result": verified, "error": error[-300:]}


def holders(installation: Installation, blob: str, capture: str) -> dict[str, Any]:
    """What a refused restore's database holds about one withdrawn photograph, for diagnosis:
    its captures, the artifacts derived from its bytes, its tombstones and their purge jobs."""
    database = DATABASE if DATABASE in databases(installation) else None
    if database is None:
        return {"database": None}
    found: dict[str, Any] = {"database": database}
    for name, statement in {
        "derived_bytes": SHARED.format(blob=blob),
        "sharers": SHARERS.format(blob=blob),
        "captures": f"select capture_id || ' deleted_at=' || coalesce(deleted_at::text, 'null') "
        f"from capture where blob_sha256 = decode('{blob}', 'hex')",
        "artifacts": "select a.artifact_id || ' kind=' || a.kind || ' purged_at=' || "
        "coalesce(a.purged_at::text, 'null') from artifact a "
        f"where a.source_blob_sha256 = decode('{blob}', 'hex')",
        "tombstones": "select tombstone_id || ' purge_completed_at=' || "
        "coalesce(purge_completed_at::text, 'null') from tombstone "
        f"where capture_id = '{capture}'",
        "purge_jobs": "select j.target_kind || ' ' || j.state || ' ' || coalesce(j.last_error, '') "
        "from purge_job j join tombstone t on t.tombstone_id = j.tombstone_id "
        f"where t.capture_id = '{capture}'",
    }.items():
        try:
            found[name] = installation.sql(statement, database)
        except RuntimeError as failed:
            found[name] = str(failed)[:300]
    return found


def restore_marker(installation: Installation) -> Any:
    done = installation.compose(
        "--profile", "recovery", "run", "--rm", "--no-deps", "-T", "--entrypoint", "cat",
        "restore", "/var/lib/exulanica-restore/restore.json",
    )  # fmt: skip
    return parse_json(done.stdout) if done.returncode == 0 else None


# -- the rows --------------------------------------------------------------------------------------


def row_l1(installation: Installation, built: dict[str, Any], head: str) -> Row:
    row = Row(
        "L1",
        "install.clean",
        "From empty volumes and images built from HEAD with no download, every service is healthy "
        "or completed; the facts name HEAD, the images the containers run and the tree's schema; "
        "components match the profile (derivatives and pose_scene unavailable "
        "image_built_without_extra); no-model /readyz 200; F1 discovery carries the installation's "
        "component states; exulanica-installation check exits 0; a saved world reads again from a "
        "recreated API container.",
    )
    row.observed["build"] = {k: v for k, v in built.items() if k != "images"}
    row.expect(built["exit"] == 0, f"the build exited {built['exit']}")
    row.expect(not built["download_lines"], "the build downloaded something")
    row.expect(
        built["base_images_before"] == built["base_images_after"],
        "a base image changed during the build",
    )
    row.expect(all(built["images"].values()), "an image was not built")
    if row.failures:
        return row.close()
    installation.compose("--profile", "recovery", "down", "-v", "--remove-orphans")
    code, seconds, error = up(installation)
    running = services(installation)
    row.observed["up"] = {"exit": code, "seconds_this_fixture": seconds, "services": running}
    if not row.expect(code == 0, f"up exited {code}: {error[-300:]}"):
        return row.close()
    for service in SERVICES:
        state = running.get(service, {})
        if service in ONE_SHOT:
            row.expect(state.get("exit_code") == 0, f"{service} did not complete")
        else:
            row.expect(
                state.get("state") == "running" and state.get("health") in ("healthy", ""),
                f"{service} is {state.get('state')} {state.get('health')}",
            )
    images = built["images"]
    row.expect(running.get("api", {}).get("image") == images["api"], "api runs another image")
    row.expect(
        running.get("client", {}).get("image") == images["client"], "client runs another image"
    )
    label = installation.docker(
        "image", "inspect", images["client"], "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
    ).stdout.strip()  # fmt: skip
    row.expect(label == head, f"the client image's revision label is {label!r}")

    provision = installation.compose(
        "exec", "-T", "api", "python", "-c", PROVISION, installation.workspace(),
        stdin=owner_url(installation) + "\n",
    )  # fmt: skip
    row.expect(provision.returncode == 0, "the operator workspace was not provisioned")

    ready, readyz = http("GET", f"{installation.api}/readyz")
    unauthorised, _ = http("GET", f"{installation.api}/operations/installation")
    status, document = facts(installation)
    row.observed["readyz"] = {"status": ready, "installation": (readyz or {}).get("installation")}
    row.expect(ready == 200, f"/readyz answered {ready} in no-model mode")
    row.expect(unauthorised == 401, f"facts without a token answered {unauthorised}")
    row.expect(status == 200, f"facts answered {status}")
    document = document if isinstance(document, dict) else {}
    identity = document.get("identity", {})
    schema = identity.get("schema", {})
    expected_schema = max(
        int(p.name[:4]) for p in (installation.tree / "exulanica" / "migrations").glob("0*.sql")
    )
    components = {c["component"]: c for c in document.get("components", [])}
    row.observed["facts"] = {
        "installation": document.get("installation"),
        "identity": identity,
        "components": {k: [v.get("state"), v.get("reason")] for k, v in components.items()},
        "models": (document.get("models") or {}).get("mode"),
        "serving": (document.get("serving") or {}).get("state"),
        "restore_state": (document.get("recovery") or {}).get("restore_state"),
    }
    row.expect(identity.get("code_revision") == head, "facts name another revision")
    row.expect(
        identity.get("images") == {"backend": images["api"], "client": images["client"]},
        "facts name other images than the containers run",
    )
    row.expect(
        str(schema.get("applied")) == str(schema.get("expected"))
        and _number(schema.get("applied")) == expected_schema,
        f"schema {schema} against the tree's {expected_schema:04d}",
    )
    row.expect((document.get("installation") or {}).get("id") == PROFILE, "another profile")
    for component, reason in UNAVAILABLE.items():
        entry = components.get(component, {})
        row.expect(
            entry.get("state") == "unavailable" and entry.get("reason") == reason,
            f"{component} is {entry.get('state')} {entry.get('reason')}",
        )
    refused = [k for k, v in components.items() if v.get("state") == "refused"]
    row.expect(not refused, f"refused components: {refused}")
    row.expect(row.observed["facts"]["models"] == "no_model", "models are not no_model")
    row.expect(row.observed["facts"]["serving"] == "open", "serving is not open")

    checked, checked_document, _ = installation.operator("check", service="api")
    row.observed["check"] = {
        "exit": checked,
        "same_identity": (checked_document or {}).get("identity", {}).get("code_revision") == head,
    }
    row.expect(checked == 0, f"exulanica-installation check exited {checked}")

    entry_status, entry = http(
        "POST", f"{installation.api}/world-entries/starter", installation.token(),
        {"title": "Q10 installation"},
    )  # fmt: skip
    entry_id = (entry or {}).get("entry_id") if isinstance(entry, dict) else None
    row.expect(entry_status == 200 and entry_id, f"the starter answered {entry_status}")
    discovery = discovery_dependencies(installation, entry)
    row.observed["discovery"] = discovery
    row.expect(
        bool(discovery["named_components"]),
        f"{DISCOVERY} names no installation component: every operation's dependencies are empty "
        "while the facts report derivatives and pose_scene unavailable",
    )
    recreated = installation.compose(
        "up",
        "-d",
        "--no-build",
        "--no-deps",
        "--force-recreate",
        "--wait",
        "api",
        timeout=UP_SECONDS,
    )
    again_status, again = http(
        "GET", f"{installation.api}/world-entries/{entry_id}", installation.token()
    )
    row.observed["reopen"] = {
        "entry_id": entry_id,
        "recreate_exit": recreated.returncode,
        "status": again_status,
        "same": isinstance(again, dict) and again.get("entry_id") == entry_id,
    }
    row.expect(
        recreated.returncode == 0 and again_status == 200 and row.observed["reopen"]["same"],
        "the saved world did not read again from a recreated API container",
    )
    client_status, _ = http("GET", f"{installation.client}/")
    client_ready, _ = http("GET", f"{installation.client}/api/readyz")
    row.observed["client"] = {"index": client_status, "api_readyz": client_ready}
    row.expect(client_status == 200 and client_ready == 200, "the client does not serve")
    # What L2a and L2b need is a working installation; discovery's projection is L1's alone.
    row.observed["installed"] = not [f for f in row.failures if not f.startswith(DISCOVERY)]
    return row.close()


def _number(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def discovery_dependencies(installation: Installation, entry: Any) -> dict[str, Any]:
    """Which installation components F1 discovery names, over every operation it lists."""
    reads = []
    status, worlds = http("GET", f"{installation.api}/worlds/capabilities", installation.token())
    reads.append(("worlds", status, worlds))
    if isinstance(entry, dict) and entry.get("authored_version_id"):
        version = entry["authored_version_id"]
        status, version_read = http(
            "GET",
            f"{installation.api}/world/versions/{version}/capabilities?world_id={entry['world_id']}",
            installation.token(),
        )
        reads.append(("version", status, version_read))
    named: dict[str, list[str]] = {}
    operations = 0
    for name, _, body in reads:
        for operation in _operations(body):
            operations += 1
            for dependency in operation.get("dependencies") or []:
                key = (
                    dependency.get("component") if isinstance(dependency, dict) else str(dependency)
                )
                named.setdefault(key, []).append(f"{name}:{operation.get('operation')}")
    return {
        "reads": [[name, status] for name, status, _ in reads],
        "operations": operations,
        "named_components": named,
    }


def _operations(body: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(body, dict):
        if "operation" in body and "dependencies" in body:
            found.append(body)
        for value in body.values():
            found += _operations(value)
    elif isinstance(body, list):
        for value in body:
            found += _operations(value)
    return found


def owner_url(installation: Installation) -> str:
    values = dict(
        line.split("=", 1) for line in installation.env_file.read_text().splitlines() if "=" in line
    )
    password = values["POSTGRES_PASSWORD"].strip("'")
    return f"postgresql://{OWNER}:{password}@postgres:5432/{DATABASE}"


def row_l2a(installation: Installation, l1: Row) -> Row:
    row = Row(
        "L2a",
        "install.restore_planned",
        "A photograph taken in, a verified backup set, the capture withdrawn after it and purged; "
        "with every writer stopped a planned restore with --set-aside loads the set and replays "
        "the withdrawal before serving (capture row gone, bytes absent, receipt planned); every "
        "earlier withdrawal is still held; the restored installation checks, backs up and "
        "verifies; the set-aside source is reported, then discarded.",
    )
    if not l1.observed.get("installed"):
        row.blocked_by.append("L1's installation did not install and serve")
        return row.close()
    installation.compose("stop", "maintenance")
    photo = take_photo(installation, 1)
    row.observed["photo"] = photo
    if not row.expect(photo["status"] in (200, 202) and photo["capture_id"], "photo refused"):
        return row.close()
    code, name, verified = backup_set(installation)
    row.observed["backup"] = {"exit": code, "set": name, "verify": verified}
    if not row.expect(
        code == 0 and name and verified and verified.get("exit") == 0, "no verified set"
    ):
        return row.close()
    withdrawn = withdraw(installation, photo["capture_id"], "Q10 L2a withdrawal after the backup")
    passed = maintenance_pass(installation)
    before = installation.sql("select tombstone_id from tombstone order by 1")
    row.observed["after_backup"] = {
        "withdrawal": withdrawn,
        "pass": passed,
        "live_bytes": stored(installation, photo["blob_sha256"]),
        "tombstones": len(before),
    }
    row.expect(passed["failures"] == [], f"the pass failed {passed['failures']}")
    installation.compose("stop", "api", "client")
    started = time.monotonic()
    code, result, error = installation.operator(
        "restore", "planned", "--backup-set", f"{BACKUP_MOUNT}/sets/{name}",
        "--checkpoint", f"{CUSTODY_MOUNT}/planned-checkpoint.json", "--set-aside",
        service="restore",
    )  # fmt: skip
    restored_in = round(time.monotonic() - started, 3)
    row.observed["restore"] = {
        "exit": code,
        "result": result,
        "error": error[-500:] if code else "",
    }
    if not row.expect(code == 0, f"the planned restore exited {code}"):
        row.observed["holders"] = holders(installation, photo["blob_sha256"], photo["capture_id"])
        return row.close()
    upped, _, _ = up(installation)
    ready = wait_ready(installation.api)
    status, document = facts(installation)
    after = installation.sql("select tombstone_id from tombstone order by 1")
    kept = [d for d in databases(installation) if d != DATABASE]
    row.observed["after_restore"] = {
        "restore_seconds_this_fixture": restored_in,
        "up_exit": upped,
        "readyz_after_up_seconds": ready,
        "restore_state": ((document or {}).get("recovery") or {}).get("restore_state"),
        "serving": ((document or {}).get("serving") or {}).get("state"),
        "live_captures": live_captures(installation, photo["capture_id"]),
        "tombstones_for_capture": tombstones_for(installation, photo["capture_id"]),
        "live_bytes": stored(installation, photo["blob_sha256"]),
        "earlier_withdrawals_held": set(before) <= set(after),
        # A planned restore's receipt leaves the declared window, and its mode, null.
        "receipt": installation.sql(
            "select restore_id || ' mode=' || coalesce(recovery_mode, 'null') "
            "from restore_replay_receipt"
        ),
        "databases": databases(installation),
    }
    seen = row.observed["after_restore"]
    row.expect(status == 200 and seen["restore_state"] == "complete", "restore state not complete")
    row.expect(seen["serving"] == "open", "the restored installation does not serve")
    row.expect(seen["live_captures"] == 0, "the withdrawn capture is live again")
    row.expect(seen["tombstones_for_capture"] >= 1, "the withdrawal was lost")
    row.expect(seen["live_bytes"] == 0, "the withdrawn bytes are in the live store")
    row.expect(seen["earlier_withdrawals_held"], "an earlier withdrawal was lost")
    restore_id = (result or {}).get("restore_id")
    row.expect(
        seen["receipt"] == [f"{restore_id} mode=null"],
        f"receipt {seen['receipt']} for {restore_id}",
    )
    row.expect(len(kept) == 1 and kept[0].startswith("exulanica_before_"), f"set aside {kept}")
    installation.compose("stop", "maintenance")
    reported = maintenance_pass(installation)
    checked, _, _ = installation.operator("check", service="api")
    code, again, verified = backup_set(installation)
    discarded, gone, _ = installation.operator(
        "restore", "discard-set-aside", "--checkpoint", f"{CUSTODY_MOUNT}/planned-checkpoint.json",
        service="restore",
    )  # fmt: skip
    clean = maintenance_pass(installation)
    row.observed["afterwards"] = {
        "pass_with_set_aside": reported,
        "check": checked,
        "backup": {"exit": code, "set": again, "verify": verified},
        "discard": {"exit": discarded, "result": gone},
        "pass_after_discard": clean,
        "databases": databases(installation),
    }
    row.expect(
        "set_aside_database_present" in (reported["failures"] or []),
        "the set-aside source was not reported",
    )
    row.expect(checked == 0, f"check exited {checked}")
    row.expect(
        code == 0 and verified and verified.get("exit") == 0, "the restored set did not verify"
    )
    row.expect(
        discarded == 0 and databases(installation) == [DATABASE], "the source was not discarded"
    )
    row.expect(clean["failures"] == [], f"the pass after discard failed {clean['failures']}")
    return row.close()


def declaration(export: Mapping[str, Any], incident: dt.datetime, digest: str | None = None) -> str:
    return json.dumps(
        {
            "profile": "exulanica.recovery-declaration/v1",
            "declaration_id": str(uuid.uuid4()),
            "export_sha256": digest or export["record_sha256"],
            "incident_at": incident.isoformat(),
            "reason": "Q10 L2b acceptance: every volume of the installation is deleted",
        }
    )


def row_l2b(installation: Installation, l2a: Row, l1: Row) -> Row:
    row = Row(
        "L2b",
        "install.restore_declared",
        "After a new backup set, withdrawal W1 reaches the newest export and W2 is made after it; "
        "every volume is deleted; declarations naming a missing export, another export's digest, "
        "an older export, an incident before the export or beyond the lag bound are refused with "
        "no marker and no database written, and no override exists; the declared recovery then "
        "replays W1 (row gone, bytes absent, tombstone held), states W2 inside its loss window "
        "(its row still present), serves, and checks; the time to the first ready /readyz and "
        "first served read is recorded as this fixture's.",
    )
    if not l1.observed.get("installed"):
        row.blocked_by.append("L1's installation did not install and serve")
        return row.close()
    installation.compose("stop", "maintenance")
    first, second = take_photo(installation, 2), take_photo(installation, 3)
    row.observed["photos"] = {"w1": first, "w2": second}
    if not row.expect(first["capture_id"] and second["capture_id"], "a photograph was refused"):
        return row.close()
    status, listed = http("GET", f"{installation.api}/world-entries", installation.token())
    entries = listed if isinstance(listed, list) else (listed or {}).get("entries", [])
    entry_id = entries[0]["entry_id"] if entries else None
    code, name, verified = backup_set(installation)
    row.observed["backup"] = {"exit": code, "set": name, "verify": verified}
    if not row.expect(
        code == 0 and name and verified and verified.get("exit") == 0, "no verified set"
    ):
        return row.close()
    w1 = withdraw(installation, first["capture_id"], "Q10 L2b W1, before the last export")
    passed = maintenance_pass(installation)
    time.sleep(2)
    w2 = withdraw(installation, second["capture_id"], "Q10 L2b W2, after the last export")
    held = exports(installation)
    newest = held[-1] if held else None
    older = held[0] if len(held) > 1 else None
    row.observed["before_loss"] = {
        "w1": w1,
        "w2": w2,
        "pass": passed,
        "w1_live_bytes": stored(installation, first["blob_sha256"]),
        "w1_derived_bytes": installation.sql(SHARED.format(blob=first["blob_sha256"])),
        "w1_sharers": installation.sql(SHARERS.format(blob=first["blob_sha256"])),
        "exports": held,
    }
    row.expect(passed["failures"] == [], f"the pass failed {passed['failures']}")
    if not row.expect(newest is not None and older is not None, "custody lacks two exports"):
        return row.close()
    covered = dt.datetime.fromisoformat(newest["covered_through"])
    incident = dt.datetime.now(dt.UTC)
    (installation.custody / "declaration.json").write_text(declaration(newest, incident))

    lost = installation.compose("--profile", "recovery", "down", "-v", "--remove-orphans")
    volumes = installation.docker(
        "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={installation.project}"
    ).stdout.split()
    row.observed["loss"] = {"down_exit": lost.returncode, "volumes_left": len(volumes)}
    row.expect(lost.returncode == 0 and not volumes, "the volumes were not all deleted")
    empty = installation.compose("up", "-d", "--no-build", "--wait", "postgres", timeout=UP_SECONDS)
    installation.sql(f"drop database {DATABASE}", "postgres")
    row.expect(empty.returncode == 0, "the empty server did not start")

    set_dir = f"{BACKUP_MOUNT}/sets/{name}"
    later = covered + dt.timedelta(seconds=700)
    earlier = covered - dt.timedelta(seconds=60)
    cases = {
        "missing_export": (f"{CUSTODY_MOUNT}/absent-export.json", declaration(newest, incident)),
        "mismatched_digest": (newest["file"], declaration(newest, incident, digest="0" * 64)),
        "older_export": (older["file"], declaration(older, incident)),
        "incident_before_export": (newest["file"], declaration(newest, earlier)),
        "beyond_lag_bound": (newest["file"], declaration(newest, later)),
    }
    refusals = {}
    for case, (export, stated) in cases.items():
        (installation.custody / f"declaration-{case}.json").write_text(stated)
        path = export if export.startswith("/") else f"{CUSTODY_MOUNT}/{export}"
        code, _, error = installation.operator(
            "restore", "declared", "--backup-set", set_dir, "--export", path,
            "--declaration", f"{CUSTODY_MOUNT}/declaration-{case}.json", service="restore",
        )  # fmt: skip
        refusals[case] = {
            "exit": code,
            "named": "Traceback" not in error,
            "said": error.splitlines()[-1][:300] if error else "",
            "marker": restore_marker(installation),
            "databases": databases(installation),
        }
        row.expect(
            code == 1 and refusals[case]["named"], f"{case} exited {code} without a named refusal"
        )
        row.expect(refusals[case]["marker"] is None, f"{case} wrote a marker")
        row.expect(refusals[case]["databases"] == [], f"{case} created a database")
    usage = installation.compose(
        "--profile", "recovery", "run", "--rm", "--no-deps", "-T", "restore", "declared", "--help"
    ).stdout
    # The usage alone: compose may print build lines, which carry flags of their own, before it.
    usage = usage[usage.find("usage:") :] if "usage:" in usage else ""
    options = sorted(set(re.findall(r"--[a-z][a-z-]+", usage)))
    row.observed["refusals"] = refusals
    row.observed["declared_options"] = options
    row.expect(
        not any(word in o for o in options for word in ("force", "override", "ignore", "skip")),
        f"an override option exists: {options}",
    )

    started = time.monotonic()
    code, result, error = installation.operator(
        "restore", "declared", "--backup-set", set_dir, "--export", f"{CUSTODY_MOUNT}/{newest['file']}",
        "--declaration", f"{CUSTODY_MOUNT}/declaration.json", service="restore",
    )  # fmt: skip
    restored = round(time.monotonic() - started, 3)
    row.observed["restore"] = {
        "exit": code,
        "result": result,
        "error": error[-500:] if code else "",
    }
    if not row.expect(code == 0, f"the declared recovery exited {code}"):
        row.observed["holders"] = holders(installation, first["blob_sha256"], first["capture_id"])
        return row.close()
    installation.compose(
        "up", "-d", "--no-build", "api", "client", "maintenance", timeout=UP_SECONDS
    )
    ready = None if wait_ready(installation.api) is None else round(time.monotonic() - started, 3)
    first_read = None
    while time.monotonic() - started < UP_SECONDS and entry_id:
        status, _ = http(
            "GET", f"{installation.api}/world-entries/{entry_id}", installation.token()
        )
        if status == 200:
            first_read = round(time.monotonic() - started, 3)
            break
        time.sleep(1)
    status, document = facts(installation)
    receipt = installation.sql(
        "select recovery_mode || ' ' || coalesce(loss_window_microseconds::text, '') "
        "from restore_replay_receipt"
    )
    marker = restore_marker(installation) or {}
    recovery = marker.get("recovery") or {}
    window = (
        dt.datetime.fromisoformat(recovery["covered_through"]),
        dt.datetime.fromisoformat(recovery["incident_at"]),
    ) if recovery.get("covered_through") and recovery.get("incident_at") else None  # fmt: skip
    w2_at = dt.datetime.fromisoformat(w2["requested_at"])
    row.observed["after"] = {
        "restore_seconds_this_fixture": restored,
        "first_ready_seconds_this_fixture": ready,
        "first_read_seconds_this_fixture": first_read,
        "restore_state": ((document or {}).get("recovery") or {}).get("restore_state"),
        "serving": ((document or {}).get("serving") or {}).get("state"),
        "receipt": receipt,
        "loss_window": result.get("loss_window") if isinstance(result, dict) else None,
        "w1_live_captures": live_captures(installation, first["capture_id"]),
        "w1_tombstones": tombstones_for(installation, first["capture_id"]),
        "w1_live_bytes": stored(installation, first["blob_sha256"]),
        "w2_live_captures": live_captures(installation, second["capture_id"]),
        "w2_tombstones": tombstones_for(installation, second["capture_id"]),
        "w2_inside_window": bool(window and window[0] <= w2_at <= window[1]),
    }
    seen = row.observed["after"]
    row.expect(status == 200 and seen["restore_state"] == "complete", "restore state not complete")
    row.expect(seen["serving"] == "open", "the recovered installation does not serve")
    row.expect(ready is not None and first_read is not None, "no ready /readyz or no served read")
    row.expect(any(r.startswith("declared") for r in receipt), f"receipt {receipt}")
    row.expect(seen["w1_live_captures"] == 0, "W1's capture is live again")
    row.expect(seen["w1_tombstones"] >= 1, "W1's withdrawal was lost")
    row.expect(seen["w1_live_bytes"] == 0, "W1's bytes are in the live store")
    row.expect(
        seen["w2_tombstones"] == 0 and seen["w2_live_captures"] == 1, "W2 is not as declared"
    )
    row.expect(seen["w2_inside_window"], "W2 is not inside the stated loss window")
    left_open(row, installation, first, result)
    checked, _, _ = installation.operator("check", service="api")
    row.observed["check"] = checked
    row.expect(checked == 0, f"check exited {checked}")
    return row.close()


def left_open(row: Row, installation: Installation, first: dict[str, Any], result: Any) -> None:
    """What a recovery leaves open, and why: a withdrawn photograph's derived bytes that a record
    live in the recovered database still holds stay stored, their purge job skipped and their
    tombstone open, named in the result; with no such holder nothing is left open (fix-7)."""
    named = (result or {}).get("tombstones_left_open", {}) if isinstance(result, dict) else {}
    shared = installation.sql(SHARED.format(blob=first["blob_sha256"]))
    held = [line.split(" ", 1)[0] for line in shared if not line.endswith("live_sharers=0")]
    tombstones = installation.sql(
        "select tombstone_id || ' ' || (purge_completed_at is not null) from tombstone "
        f"where capture_id = '{first['capture_id']}'"
    )
    jobs = installation.sql(
        "select j.target_kind || ' ' || j.state || ' ' || coalesce(j.last_error, '') "
        "from purge_job j join tombstone t on t.tombstone_id = j.tombstone_id "
        f"where t.capture_id = '{first['capture_id']}' order by 1"
    )
    ids = {line.split(" ", 1)[0] for line in tombstones}
    row.observed["left_open"] = {
        "result": named,
        "held_by_live_records": held,
        "tombstones_complete": tombstones,
        "purge_jobs": jobs,
        "held_bytes_stored": {digest: stored(installation, digest) for digest in held},
    }
    if not held:
        row.expect(not named, f"a recovery with nothing held left {named} open")
        row.expect(all(line.endswith(" true") for line in tombstones), "a tombstone stayed open")
        return
    open_here = [tombstone for tombstone in named if tombstone in ids]
    row.expect(bool(open_here), f"the result names none of W1's tombstones open: {named}")
    # Targets are named "<kind>:<digest>", as the purge queue names them.
    targets = {target.split(":", 1)[-1] for t in open_here for target in named[t]}
    row.expect(set(held) <= targets, f"the held bytes {held} are not the targets named open")
    row.expect(
        any(line.endswith(" false") for line in tombstones), "W1's tombstone was marked complete"
    )
    row.expect(any(" skipped " in line for line in jobs), "no purge job of W1's was skipped")
    row.expect(
        all(count > 0 for count in row.observed["left_open"]["held_bytes_stored"].values()),
        "bytes a live record holds were destroyed",
    )


# -- commands --------------------------------------------------------------------------------------


def run(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    installation = Installation(worktree, arguments.slot, arguments.port_base)
    installation.distinct_probes = arguments.distinct_probes
    tree = LAUNCH.tree_identity(worktree)
    busy = [
        port
        for port in (installation.ports["api"], installation.ports["vite"])
        if LAUNCH.listening(port)
    ]
    if busy:
        raise SystemExit(f"ports in use: {busy}; take the acceptance stack down first")
    out = Path(arguments.out).resolve()
    evidence = out / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    installation.prepare()
    started = dt.datetime.now(dt.UTC).isoformat()
    tooling = export_head(installation)
    values = secrets_environment(installation, tree["head"])
    bundle = client_bundle(worktree, evidence)
    # web/ is HEAD's (export_head refuses any other change), so the bundle is built from HEAD.
    subprocess.run(
        [
            "cp",
            "-R",
            bundle.pop("dist"),
            str(installation.tree / "web" / "packages" / "app" / "dist"),
        ],
        check=True,
    )
    values |= bundle
    write_environment(installation, values)
    built = build(installation, evidence)
    values |= {
        "EXULANICA_IMAGE_BACKEND": built["images"].get("api", ""),
        "EXULANICA_IMAGE_CLIENT": built["images"].get("client", ""),
    }
    write_environment(installation, values)
    rows: list[Row] = []
    try:
        l1 = row_l1(installation, built, tree["head"])
        rows.append(l1)
        l2a = row_l2a(installation, l1)
        rows.append(l2a)
        rows.append(row_l2b(installation, l2a, l1))
    finally:
        down = installation.compose("--profile", "recovery", "down", "-v", "--remove-orphans")
        left = installation.docker(
            "ps", "-a", "-q", "--filter", f"label=com.docker.compose.project={installation.project}"
        ).stdout.split()
        teardown = {"down_exit": down.returncode, "containers_left": len(left)}
        images_at_end = image_ids(installation)
    results = {
        "profile": "q10-installation-acceptance-results/v1",
        "candidate": {"head": tree["head"], "images_built_from": "git archive HEAD"},
        "project": installation.project,
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "fixture": "distinct_probes" if installation.distinct_probes else "identical_probes",
        "teardown": teardown,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(r.status == state for r in rows) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str))
    manifest = {
        "driver": str(Path(__file__).resolve().relative_to(REPOSITORY)),
        "driver_sha256": DRIVER_SHA256_AT_START,
        "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != DRIVER_SHA256_AT_START,
        "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
        "compose_sha256": hashlib.sha256((worktree / "compose.yaml").read_bytes()).hexdigest(),
        "command": ["installation.py", *sys.argv[1:]],
        "tree": tree,
        "images_built_from": f"git archive {tree['head']}",
        "checkout_changes_beyond_head": tooling,
        "images": built["images"],
        # compose run may rebuild a service's image from cache; the run's images must not change.
        "images_at_end": images_at_end,
        "images_unchanged": images_at_end == built["images"],
        "base_images": built["base_images_after"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    for row in rows:
        print(f"{row.row:6} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    print(json.dumps(results["counts"]), json.dumps(teardown))
    return 0 if results["counts"]["failed"] == 0 else 1


def down(arguments: argparse.Namespace) -> int:
    installation = Installation(LAUNCH.checkout(arguments.worktree), 0, None)
    if not installation.env_file.exists():
        print("nothing to take down")
        return 0
    done = installation.compose("--profile", "recovery", "down", "-v", "--remove-orphans")
    print(done.stderr.strip()[-500:])
    return done.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    started = commands.add_parser("run", help="build, install, restore and recover; rows L1 to L2b")
    started.add_argument("--worktree", required=True)
    started.add_argument("--out", required=True)
    started.add_argument("--slot", type=int, default=0)
    started.add_argument("--port-base", type=int, default=None)
    started.add_argument(
        "--distinct-probes",
        action="store_true",
        help="give each photograph its own width, so no two intake probes are the same bytes",
    )
    started.set_defaults(handler=run)
    stopped = commands.add_parser("down", help="remove this checkout's installation project")
    stopped.add_argument("--worktree", required=True)
    stopped.set_defaults(handler=down)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
