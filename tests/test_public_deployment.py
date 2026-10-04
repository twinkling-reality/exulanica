"""The public server: the installation composition behind its TLS edge, and its operator script.

Text assertions over ``deploy/public/public.yaml`` and its ``Caddyfile``, as
``tests/test_judge_edge.py`` makes over the reviewer stack's edge, and for the same reason no YAML
parser. Each names a failure that produces a public server which looks fine and is not: an API
reachable around the edge and its write limit, a server that spends without the durable authority
or without a stated fuse, an edge that moves under a running server, a log that fills the disk.

The script tests run ``deploy/public/public.sh`` itself, in a temporary directory, for the steps
that need no Docker: writing the secrets, refusing a custody directory inside the backups,
refusing to start without the operator's ceilings, and keeping the model credential off disk.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "deploy" / "public"

OVERLAY = (PUBLIC / "public.yaml").read_text(encoding="utf-8")
CADDYFILE = (PUBLIC / "Caddyfile").read_text(encoding="utf-8")
SCRIPT = PUBLIC / "public.sh"
JUDGE_EDGE = (ROOT / "deploy" / "judge" / "edge.yaml").read_text(encoding="utf-8")
BASE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
#: A stand-in model credential the script must never write anywhere.
CREDENTIAL_PROBE = "must-not-be-written-anywhere"

#: The services that serve for the life of the server, each with a restart policy of its own in
#: compose.yaml or here.
LONG_RUNNING = ("postgres", "api", "client", "maintenance", "preparation", "edge")


def _directives(text: str) -> str:
    """The file with its comments stripped. A comment is not a directive."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _services(text: str) -> dict[str, str]:
    """Each top-level service's block of a compose file, by name."""
    body = _directives(text).split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    blocks: dict[str, str] = {}
    name = None
    for line in body.splitlines():
        header = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
        if header:
            name = header.group(1)
            blocks[name] = ""
        elif name is not None:
            blocks[name] += line + "\n"
    return blocks


OVERLAY_SERVICES = _services(OVERLAY)
BASE_SERVICES = _services(BASE)


def test_the_api_publishes_no_port_and_only_the_edge_binds_beyond_loopback():
    """The installation publishes the API's port for a host with its own proxy; here the edge is
    that proxy, and a published API port would be a way in around the write limit and body cap."""
    assert re.search(r"^    ports: !reset \[\]$", OVERLAY_SERVICES["api"], re.M)
    # Every other port the base file publishes is bound to loopback by the file itself.
    for name, block in BASE_SERVICES.items():
        if name == "api" or "ports:" not in block:
            continue
        published = re.findall(r'^\s+- "([^"]+)"$', block.split("ports:", 1)[1], re.M)
        assert published and all(port.startswith("127.0.0.1:") for port in published), name
    edge_ports = re.findall(r'^\s+- "([^"]+)"$', OVERLAY_SERVICES["edge"], re.M)
    edge_ports = [port for port in edge_ports if ":80" in port or ":443" in port]
    assert len(edge_ports) == 2
    for port in edge_ports:
        # The address has no default: a rehearsal never opens 80 and 443 by leaving it unset.
        assert port.startswith("${EXULANICA_EDGE_ADDRESS:?"), port


def test_the_edge_reaches_the_client_proxy_and_never_the_api():
    conf = _directives(CADDYFILE)
    upstreams = re.findall(r"reverse_proxy\s+(\S+)", conf)
    assert upstreams == ["client:8080"]
    assert "api:" not in conf


def test_the_edge_is_the_reviewer_edges_exact_version():
    """One pinned Caddy across both edges: a moving tag is a proxy that changes under a server."""
    pinned = re.findall(r"^\s+image: (caddy:\S+)$", _directives(JUDGE_EDGE), re.M)
    assert re.findall(r"^\s+image: (caddy:\S+)$", OVERLAY_SERVICES["edge"], re.M) == pinned
    assert re.fullmatch(r"caddy:\d+\.\d+\.\d+-alpine", pinned[0])


def test_the_edge_host_and_issuer_have_no_default():
    edge = OVERLAY_SERVICES["edge"]
    assert "EXULANICA_PUBLIC_HOST: ${EXULANICA_PUBLIC_HOST:?" in edge
    assert "EXULANICA_TLS: ${EXULANICA_TLS:?" in edge
    assert re.search(r"^\{\$EXULANICA_PUBLIC_HOST\} \{$", CADDYFILE, re.M)
    assert re.search(r"^\ttls \{\$EXULANICA_TLS\}$", CADDYFILE, re.M)


def test_the_server_spends_through_the_durable_authority_within_a_stated_fuse():
    """Anybody can reach this server: the money is the durable authority, which a restart does not
    refill, and the process fuse has no default here although the API has one."""
    for name in ("api", "playback-worker"):
        assert re.search(r"^      EXULANICA_SPENDING: durable$", OVERLAY_SERVICES[name], re.M), name
    api = OVERLAY_SERVICES["api"]
    assert "EXULANICA_BUDGET_USD: ${EXULANICA_BUDGET_USD:?" in api
    assert "EXULANICA_BUDGET_MAX_CALLS: ${EXULANICA_BUDGET_MAX_CALLS:?" in api
    # The base file gives both the witness volume, which durable spending needs.
    for name in ("api", "playback-worker"):
        assert "spending-witness:/var/lib/exulanica-spending-witness" in BASE_SERVICES[name], name


def test_every_long_running_service_keeps_bounded_logs_and_restarts():
    for name in LONG_RUNNING:
        block = OVERLAY_SERVICES[name]
        assert "logging: *bounded-logs" in block or "logging: &bounded-logs" in block, name
        restarts = BASE_SERVICES.get(name, "") + block
        assert "restart: unless-stopped" in restarts, name
    anchor = OVERLAY_SERVICES["edge"].split("logging: &bounded-logs", 1)[1]
    assert 'max-size: "10m"' in anchor and 'max-file: "10"' in anchor


def test_each_recipe_runs_under_one_image_name_the_script_loads():
    """A host loads three images by name; a service under any other name would make `up` build
    or pull something that was never checked."""
    named = {
        name: re.search(r"^    image: (\S+)$", block, re.M).group(1)
        for name, block in OVERLAY_SERVICES.items()
        if name != "edge" and re.search(r"^    image: ", block, re.M)
    }
    # The reconstruction workers start only with their compose profile, which this server never
    # names: the seed of every world here is generated, not reconstructed from photographs.
    built = {
        name
        for name, block in BASE_SERVICES.items()
        if "build:" in block and 'profiles: ["reconstruction"]' not in block
    }
    assert built <= set(named), built - set(named)
    script = SCRIPT.read_text(encoding="utf-8")
    assert "reconstruction" not in _directives(script)
    declared = {
        re.search(rf'^{variable}="(\S+)"$', script, re.M).group(1)
        for variable in ("backend_image", "maintenance_image", "client_image")
    }
    assert set(named.values()) == declared


def test_the_server_never_builds_and_only_the_build_step_does():
    # One command per line: a line ending in a backslash continues on the next.
    script = _directives(SCRIPT.read_text(encoding="utf-8")).replace("\\\n", " ")
    ups = [line for line in script.splitlines() if re.search(r"\bcompose up\b", line)]
    assert ups and all("--no-build" in line for line in ups), ups
    builds = [line for line in script.splitlines() if re.search(r"\bdocker\b.*\sbuild(\s|$)", line)]
    assert len(builds) == 1
    build_step = script.split("\n  build)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert builds[0] in build_step
    # The bundle is built without any VITE_ setting, so no token is ever built into it.
    assert "VITE_" in build_step and "refuse" in build_step


def test_the_edges_own_refusals_take_the_client_proxys_problem_shape():
    conf = _directives(CADDYFILE)
    cap = re.search(r"max_size (\d+)MiB$", conf, re.M)
    assert cap is not None
    blocks = dict(re.findall(r"handle_errors (\d{3}) \{(.*?)\n\t\}", CADDYFILE, re.S))
    expected = {
        "413": ("body_too_large", None),
        "502": ("upstream_unavailable", 5),
        "504": ("upstream_timeout", None),
    }
    assert set(blocks) == set(expected)
    for status, block in blocks.items():
        answered = re.search(r"respond `(.*)` (\d{3})$", block, re.M)
        assert answered is not None and answered.group(2) == status
        body = json.loads(answered.group(1))
        code, retry_after = expected[status]
        assert body["code"] == code and body["detail"]
        header = re.search(r"header Retry-After (\d+)$", block, re.M)
        assert (int(header.group(1)) if header else None) == retry_after
        assert body.get("retry_after_seconds") == retry_after
    limit = json.loads(re.search(r"respond `(.*)` 413", blocks["413"]).group(1))["limit_bytes"]
    assert limit == int(cap.group(1)) * 1024 * 1024


needs_shell = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("openssl") is None,
    reason="bash and openssl are absent",
)


def _script(directory: pathlib.Path, *arguments: str, **env: str) -> subprocess.CompletedProcess:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("EXULANICA_") and key != "NEBIUS_API_KEY"
    }
    environment.update(EXULANICA_DEPLOY_DIR=str(directory / "deploy"), **env)
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _init_env(directory: pathlib.Path) -> dict[str, str]:
    backup, custody = directory / "backup", directory / "custody"
    backup.mkdir(exist_ok=True)
    custody.mkdir(exist_ok=True)
    return {
        "EXULANICA_PUBLIC_HOST": "public.example",
        "EXULANICA_TLS": "internal",
        "EXULANICA_EDGE_ADDRESS": "127.0.0.1",
        "EXULANICA_BACKUP_PATH": str(backup),
        "EXULANICA_CUSTODY_PATH": str(custody),
    }


def _env_lines(path: pathlib.Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


@needs_shell
def test_init_writes_secrets_private_and_leaves_the_fuse_to_the_operator(tmp_path):
    result = _script(
        tmp_path, "init", **{"NEBIUS_API_KEY": CREDENTIAL_PROBE}, **_init_env(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    deploy = tmp_path / "deploy"
    env_file = deploy / "public.env"
    assert stat.S_IMODE(deploy.stat().st_mode) == 0o700
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    lines = _env_lines(env_file)
    roles = (
        "POSTGRES_PASSWORD",
        "EXULANICA_APP_ROLE_PASSWORD",
        "EXULANICA_EXECUTOR_ROLE_PASSWORD",
        "EXULANICA_PURGE_ROLE_PASSWORD",
        "EXULANICA_BACKUP_ROLE_PASSWORD",
        "EXULANICA_ACCOUNT_ROLE_PASSWORD",
    )
    passwords = [lines[name] for name in roles]
    assert all(re.fullmatch(r"[0-9a-f]{48}", value) for value in passwords)
    assert len(set(passwords)) == len(roles)
    assert lines["EXULANICA_BUDGET_USD"] == ""
    assert lines["EXULANICA_BUDGET_MAX_CALLS"] == ""
    # The model credential is passed through at `up`, never written.
    for path in deploy.rglob("*"):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
            assert CREDENTIAL_PROBE not in path.read_text(encoding="utf-8"), path
    assert "NEBIUS_API_KEY" not in env_file.read_text(encoding="utf-8")


@needs_shell
def test_the_operator_token_reads_operations_and_does_nothing_else(tmp_path):
    assert _script(tmp_path, "init", **_init_env(tmp_path)).returncode == 0
    grants = json.loads((tmp_path / "deploy" / "tokens.json").read_text(encoding="utf-8"))
    assert len(grants) == 1
    ((token, grant),) = grants.items()
    assert len(token) >= 32
    assert grant["permissions"] == ["operations.read"]


@needs_shell
def test_init_refuses_custody_inside_the_backups_and_refuses_to_overwrite(tmp_path):
    env = _init_env(tmp_path)
    inside = pathlib.Path(env["EXULANICA_BACKUP_PATH"]) / "custody"
    inside.mkdir()
    refused = _script(tmp_path, "init", **{**env, "EXULANICA_CUSTODY_PATH": str(inside)})
    assert refused.returncode == 2
    assert "custody must not be inside the backup directory" in refused.stderr
    assert not (tmp_path / "deploy" / "public.env").exists()

    assert _script(tmp_path, "init", **env).returncode == 0
    first = (tmp_path / "deploy" / "public.env").read_bytes()
    again = _script(tmp_path, "init", **env)
    assert again.returncode == 2
    assert (tmp_path / "deploy" / "public.env").read_bytes() == first


@needs_shell
def test_up_refuses_until_the_operator_states_the_fuse(tmp_path):
    assert _script(tmp_path, "init", **_init_env(tmp_path)).returncode == 0
    refused = _script(tmp_path, "up")
    assert refused.returncode == 2
    assert "fill in EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS" in refused.stderr


@needs_shell
def test_a_rehearsal_visitor_cannot_take_the_operators_label(tmp_path):
    assert _script(tmp_path, "init", **_init_env(tmp_path)).returncode == 0
    refused = _script(tmp_path, "mint", "operator")
    assert refused.returncode == 2
    refused = _script(tmp_path, "revoke", "operator")
    assert refused.returncode == 2
