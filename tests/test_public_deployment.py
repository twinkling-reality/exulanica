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

import hashlib
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
LONG_RUNNING = ("postgres", "api", "client", "maintenance", "preparation", "tile-worker", "edge")
#: The compose profiles this server never names. The reconstruction workers start only with
#: theirs: the seed of every world here is generated, not reconstructed from photographs. The piece
#: generation worker likewise starts only with its own: it serves an operator's GPU session, which
#: this server does not hold. A service under one of these is neither built nor pulled here.
UNNAMED_PROFILES = ('profiles: ["reconstruction"]', 'profiles: ["generation"]')


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


def _script_value(name: str) -> str:
    match = re.search(rf'^{name}="(\S+)"$', SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match is not None, name
    return match.group(1)


def test_the_edge_and_the_database_are_the_published_versions_pulled_by_digest():
    """One pinned Caddy across both edges and compose.yaml's PostgreSQL, each pulled by its index
    digest on the build host and loaded on the server under a name of its own: a moving tag is a
    proxy or a database that changes under a server, and a host never resolves one."""
    # The reviewer edge and compose.yaml name each image by the same tag and index digest the
    # script pulls by, so the three can never drift apart.
    pinned = re.findall(r"^\s+image: (caddy:\S+)$", _directives(JUDGE_EDGE), re.M)
    assert pinned == [f"{_script_value('edge_source')}@{_script_value('edge_digest')}"]
    assert re.fullmatch(r"caddy:\d+\.\d+\.\d+-alpine", _script_value("edge_source"))
    database = re.findall(r"^    image: (\S+)$", BASE_SERVICES["postgres"], re.M)
    assert database == [f"{_script_value('postgres_source')}@{_script_value('postgres_digest')}"]
    for name in ("edge_digest", "postgres_digest"):
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", _script_value(name)), name
    assert re.search(r"^    image: exulanica-public-edge$", OVERLAY_SERVICES["edge"], re.M)
    assert re.search(r"^    image: exulanica-public-postgres$", OVERLAY_SERVICES["postgres"], re.M)


def test_no_service_pulls_on_the_server():
    """Every service runs a loaded image and none is pulled, whatever the merged file names."""
    for name, block in OVERLAY_SERVICES.items():
        assert re.search(r"^    pull_policy: never$", block, re.M), name
    built_or_pulled = {
        name
        for name, block in BASE_SERVICES.items()
        if ("build:" in block or "image:" in block)
        and not any(profile in block for profile in UNNAMED_PROFILES)
    }
    assert built_or_pulled <= set(OVERLAY_SERVICES), built_or_pulled - set(OVERLAY_SERVICES)
    script = _directives(SCRIPT.read_text(encoding="utf-8")).replace("\\\n", " ")
    ups = [line for line in script.splitlines() if re.search(r"\bcompose up\b", line)]
    assert ups and all("--pull never" in line for line in ups), ups


def test_the_edge_host_and_certificate_line_have_no_default():
    edge = OVERLAY_SERVICES["edge"]
    assert "EXULANICA_PUBLIC_HOST: ${EXULANICA_PUBLIC_HOST:?" in edge
    # Set by init, possibly empty (a public authority with no contact); unset is refused.
    assert "EXULANICA_TLS_DIRECTIVE: ${EXULANICA_TLS_DIRECTIVE?" in edge
    assert re.search(r"^\{\$EXULANICA_PUBLIC_HOST\} \{$", CADDYFILE, re.M)
    assert re.search(r"^\t\{\$EXULANICA_TLS_DIRECTIVE\}$", CADDYFILE, re.M)
    assert "tls {$EXULANICA_TLS}" not in _directives(CADDYFILE)


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


def test_the_build_tags_a_held_amd64_image_by_its_digest_before_asking_the_registry():
    """A registry outage must not stop a build whose two published images are already here: each
    pinned index's linux/amd64 image is named by digest in the script and, when held, tagged
    without a registry call; otherwise the index is read and pulled by the platform's digest."""
    script = _directives(SCRIPT.read_text(encoding="utf-8"))
    for name in ("postgres_amd64_digest", "edge_amd64_digest"):
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", _script_value(name)), name
    build = script.split("\n  build)", 1)[1].split("\n    ;;", 1)[0]
    held = build.index('docker image inspect "${source%@*}@$amd64"')
    assert held < build.index("docker buildx imagetools inspect")
    assert 'docker tag "${source%@*}@$amd64" "$name"' in build


def test_every_long_running_service_keeps_bounded_logs_and_restarts():
    for name in LONG_RUNNING:
        block = OVERLAY_SERVICES[name]
        assert "logging: *bounded-logs" in block or "logging: &bounded-logs" in block, name
        restarts = BASE_SERVICES.get(name, "") + block
        assert "restart: unless-stopped" in restarts, name
    anchor = OVERLAY_SERVICES["edge"].split("logging: &bounded-logs", 1)[1]
    assert 'max-size: "10m"' in anchor and 'max-file: "10"' in anchor


def test_each_recipe_runs_under_one_image_name_the_script_loads():
    """A host loads six images by name; a service under any other name would make `up` build
    or pull something that was never checked."""
    named = {
        name: re.search(r"^    image: (\S+)$", block, re.M).group(1)
        for name, block in OVERLAY_SERVICES.items()
        if re.search(r"^    image: ", block, re.M)
    }
    built = {
        name
        for name, block in BASE_SERVICES.items()
        if "build:" in block and not any(profile in block for profile in UNNAMED_PROFILES)
    }
    assert built <= set(named), built - set(named)
    script = SCRIPT.read_text(encoding="utf-8")
    assert "reconstruction" not in _directives(script)
    assert "--profile generation" not in _directives(script)
    declared = {
        re.search(rf'^{variable}="(\S+)"$', script, re.M).group(1)
        for variable in (
            "backend_image",
            "maintenance_image",
            "client_image",
            "tiles_image",
            "postgres_image",
            "edge_image",
        )
    }
    assert set(named.values()) == declared
    # `images` is what `up` checks are loaded and `save` writes: every declared name.
    listed = re.search(r'^images="([^"]+)"$', script, re.M)
    assert listed is not None
    assert set(listed.group(1).split()) == {
        f"${variable}"
        for variable in (
            "backend_image",
            "maintenance_image",
            "client_image",
            "tiles_image",
            "postgres_image",
            "edge_image",
        )
    }


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
        "EXULANICA_GUEST_ENTRY": "open",
        "EXULANICA_GUEST_ENTRIES_PER_DAY": "100",
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
        "EXULANICA_TILES_ROLE_PASSWORD",
    )
    passwords = [lines[name] for name in roles]
    assert all(re.fullmatch(r"[0-9a-f]{48}", value) for value in passwords)
    assert len(set(passwords)) == len(roles)
    # The public profile, whose tile worker publishes only as the tile role.
    assert lines["EXULANICA_PROFILE"] == "public"
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


@needs_shell
def test_init_keeps_the_entry_code_s_digest_and_never_the_code(tmp_path):
    code = "a-code-only-the-judges-are-given"
    env = {
        **_init_env(tmp_path),
        "EXULANICA_GUEST_ENTRY": "code",
        "EXULANICA_GUEST_ENTRY_CODE": code,
    }
    result = _script(tmp_path, "init", **env)
    assert result.returncode == 0, result.stderr
    lines = _env_lines(tmp_path / "deploy" / "public.env")
    assert lines["EXULANICA_GUEST_ENTRY"] == "code"
    assert lines["EXULANICA_GUEST_ENTRY_CODE_SHA256"] == hashlib.sha256(code.encode()).hexdigest()
    assert lines["EXULANICA_PUBLIC_ORIGIN"] == "https://public.example"
    for path in (tmp_path / "deploy").rglob("*"):
        if path.is_file():
            assert code not in path.read_text(encoding="utf-8"), path


@needs_shell
def test_init_refuses_a_guest_entry_without_its_day_s_limit(tmp_path):
    env = {**_init_env(tmp_path)}
    del env["EXULANICA_GUEST_ENTRIES_PER_DAY"]
    refused = _script(tmp_path, "init", **env)
    assert refused.returncode != 0
    assert "EXULANICA_GUEST_ENTRIES_PER_DAY" in refused.stderr
    assert not (tmp_path / "deploy" / "public.env").exists()


def test_the_api_reaches_accounts_as_its_own_role_and_trusts_only_the_proxy_s_scheme():
    api = OVERLAY_SERVICES["api"]
    assert "EXULANICA_ACCOUNT_DATABASE_URL: postgresql://exulanica_accounts:" in api
    assert '"${EXULANICA_PUBLIC_ORIGIN:?' in api
    assert re.search(r"^    ports: !reset \[\]$", api, re.M)


def test_each_proxy_trusts_forwarded_headers_from_the_one_address_before_it():
    """A process on a Linux host reaches every container at its bridge address, from the network's
    gateway. So the API trusts forwarded headers from the client proxy's fixed address alone, and
    the client proxy trusts X-Forwarded-For from the edge's fixed address alone, both inside the
    network's fixed range and neither its gateway."""
    import ipaddress

    subnet = re.search(r"^        - subnet: (\S+)$", OVERLAY, re.M)
    assert subnet is not None
    network = ipaddress.ip_network(subnet.group(1))

    def address(service: str) -> ipaddress.IPv4Address:
        found = re.search(r"^\s+ipv4_address: (\S+)$", OVERLAY_SERVICES[service], re.M)
        assert found is not None, service
        return ipaddress.ip_address(found.group(1))

    edge, client = address("edge"), address("client")
    for pinned in (edge, client):
        assert pinned in network and pinned != next(network.hosts())
    forwarded = re.search(r'^      FORWARDED_ALLOW_IPS: "(\S+)"$', OVERLAY_SERVICES["api"], re.M)
    assert forwarded is not None and ipaddress.ip_address(forwarded.group(1)) == client
    mount = (
        "./deploy/public/client-trusted-proxies.conf:/etc/nginx/exulanica-trusted-proxies.conf:ro"
    )
    assert mount in OVERLAY_SERVICES["client"]
    trusted = (PUBLIC / "client-trusted-proxies.conf").read_text(encoding="utf-8")
    assert re.findall(r"^set_real_ip_from (\S+);$", trusted, re.M) == [str(edge)]


@needs_shell
def test_init_refuses_an_entry_code_short_enough_to_guess(tmp_path):
    """Only the code's unsalted SHA-256 is kept and a wrong code is answered at once, so a short
    code falls to guessing: init refuses one under 20 characters."""
    env = {**_init_env(tmp_path), "EXULANICA_GUEST_ENTRY": "code"}
    refused = _script(tmp_path, "init", **env, EXULANICA_GUEST_ENTRY_CODE="nineteen-characters")
    assert len("nineteen-characters") == 19
    assert refused.returncode != 0 and "at least 20 characters" in refused.stderr
    assert not (tmp_path / "deploy" / "public.env").exists()
    accepted = _script(tmp_path, "init", **env, EXULANICA_GUEST_ENTRY_CODE="twenty-characters-ok")
    assert accepted.returncode == 0, accepted.stderr


def test_only_the_edge_publishes_a_port_and_up_checks_the_merged_configuration():
    """The client proxy trusts X-Forwarded-For from private ranges and the API trusts forwarded
    headers from anything that reaches it, so neither may publish a port: the overlay resets
    both, and `up` reads the merged configuration Compose runs, not this text, before it starts."""
    for name in ("api", "client"):
        assert re.search(r"^    ports: !reset \[\]$", OVERLAY_SERVICES[name], re.M), name
    script = SCRIPT.read_text(encoding="utf-8")
    up = script.split("\n  up)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert "compose config --format json" in up
    assert '("api", "client")' in up
    assert "refuse" in up.split("compose config --format json", 1)[1]
    # The check runs before anything starts.
    assert up.index("compose config --format json") < up.index("compose up -d")


def test_the_edge_log_drops_the_csrf_token_and_keeps_only_an_address_s_network():
    log = CADDYFILE.split("\tlog {", 1)[1].split("\n\t}\n", 1)[0]
    assert "request>headers>X-Csrf-Token delete" in log
    for field in ("request>remote_ip", "request>client_ip"):
        block = log.split(f"{field} ip_mask {{", 1)[1].split("}", 1)[0]
        assert "ipv4 24" in block and "ipv6 48" in block


def test_the_guest_policy_states_its_grants_a_day_and_can_be_withdrawn():
    script = SCRIPT.read_text(encoding="utf-8")
    policy = script.split("\n  guest-policy)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert '--grants-per-day "$grants_per_day"' in policy
    assert (
        "EXULANICA_GUEST_GRANTS_PER_DAY" in policy and "EXULANICA_GUEST_ENTRIES_PER_DAY" in policy
    )
    withdraw = script.split("\n  guest-policy-withdraw)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert "python -m exulanica.spending guest-policy-withdraw" in withdraw


def test_up_refuses_a_service_that_keeps_restarting():
    """A service that exits at once can read healthy for a moment before its first restart, as
    a client proxy whose nginx configuration nginx refuses did in a rehearsal; `up` looks again
    after starting and refuses while any service is restarting."""
    script = SCRIPT.read_text(encoding="utf-8")
    up = script.split("\n  up)\n", 1)[1].split("\n    ;;\n", 1)[0]
    started = up.index("compose up -d")
    check = up.index("compose ps --status restarting --services")
    assert started < check
    assert "refuse" in up[check:]


def test_guests_towns_play_in_the_api_with_their_settings_from_init():
    """Account discovery plays the guests' towns and asks their models (S4) only in a process that
    reads the guest entry: the API. The overlay turns discovery on and keeps playback in the API,
    and the base composition hands the API the two guest playback settings."""
    api = OVERLAY_SERVICES["api"]
    assert re.search(r'^      EXULANICA_SOCIETY_CONTROL_WORKER: "on"$', api, re.M)
    assert re.search(r'^      EXULANICA_PLAYBACK_WORKER: "on"$', api, re.M)
    base_api = BASE_SERVICES["api"]
    for name in ("EXULANICA_GUEST_PLAY_SECONDS", "EXULANICA_GUEST_PLAYING_MAXIMUM"):
        assert f"{name}: ${{{name}:-}}" in base_api
    # The playback pool's size, which init writes.
    assert "EXULANICA_PLAYBACK_WORKERS: ${EXULANICA_PLAYBACK_WORKERS:-}" in base_api


def test_only_the_api_makes_a_society_of_things_and_prepare_towns_dresses_the_arrival():
    """A guest's arrival town is dressed with a scene whose beings live in a society of things
    (exulanica/api/arrival_dressing.py): only the API is handed the setting, off by default; the
    installation's own copy is made and dressed by the same module, so a host that cannot dress it
    says so at prepare-towns rather than on a guest's first look."""
    for name, block in {**BASE_SERVICES, **OVERLAY_SERVICES}.items():
        if name != "api":
            assert "EXULANICA_SOCIETY_OF_THINGS" not in block, name
    # Off unless public.env turns it on: a server deployed from these files plays no society of
    # things until its operator says so.
    assert re.search(
        r"^      EXULANICA_SOCIETY_OF_THINGS: \$\{EXULANICA_SOCIETY_OF_THINGS:-off\}$",
        OVERLAY_SERVICES["api"],
        re.M,
    )
    assert "EXULANICA_SOCIETY_OF_THINGS" not in BASE_SERVICES["api"]
    prepare = _directives(SCRIPT.read_text(encoding="utf-8")).split("  prepare-towns)", 1)[1]
    prepare = prepare.split(";;", 1)[0]
    assert "exec -T api python -m exulanica.api.arrival_dressing prepare" in prepare


@needs_shell
def test_init_writes_the_guests_play_window_and_maximum(tmp_path):
    env = {
        **_init_env(tmp_path),
        "EXULANICA_GUEST_PLAY_SECONDS": "600",
        "EXULANICA_GUEST_PLAYING_MAXIMUM": "12",
    }
    result = _script(tmp_path, "init", **env)
    assert result.returncode == 0, result.stderr
    lines = _env_lines(tmp_path / "deploy" / "public.env")
    assert (lines["EXULANICA_GUEST_PLAY_SECONDS"], lines["EXULANICA_GUEST_PLAYING_MAXIMUM"]) == (
        "600",
        "12",
    )
    # Four playback workers unless the operator says otherwise (JDAY's measurement, 10-08).
    assert lines["EXULANICA_PLAYBACK_WORKERS"] == "4"
    again = tmp_path / "again"
    again.mkdir()
    result = _script(again, "init", **{**_init_env(again), "EXULANICA_PLAYBACK_WORKERS": "2"})
    assert result.returncode == 0, result.stderr
    assert _env_lines(again / "deploy" / "public.env")["EXULANICA_PLAYBACK_WORKERS"] == "2"


#: A host a public certificate authority can certify, as the judges' server's sslip.io name.
PUBLIC_NAME = "203-0-113-7.sslip.io"


def _derived_line(tmp_path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run init, then a compose command against a stand-in docker that writes down the edge's
    certificate line compose was handed: what the edge would read."""
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    seen = tmp_path / "line"
    (shim / "docker").write_text(
        f'#!/bin/sh\nprintf "%s" "$EXULANICA_TLS_DIRECTIVE" > "{seen}"\n', encoding="utf-8"
    )
    (shim / "docker").chmod(0o755)
    path = {"PATH": f"{shim}:{os.environ['PATH']}"}
    created = _script(tmp_path, "init", **{**env, **path})
    if created.returncode != 0:
        return created
    return _script(tmp_path, "down", **path)


@needs_shell
@pytest.mark.parametrize(
    ("tls", "host", "address", "line"),
    [
        ("internal", "public.example", "127.0.0.1", "tls internal"),
        ("acme", PUBLIC_NAME, "0.0.0.0", ""),
        ("operator@example.org", PUBLIC_NAME, "0.0.0.0", "tls operator@example.org"),
        # Caddy's local authority on a public address: no browser trusts it.
        ("internal", PUBLIC_NAME, "0.0.0.0", None),
        # A public authority for a name it cannot certify falls back to the local one silently.
        ("acme", "203.0.113.7", "0.0.0.0", None),
        ("acme", "server.local", "0.0.0.0", None),
        ("acme", "box.internal", "0.0.0.0", None),
        ("acme", "edge.localhost", "0.0.0.0", None),
        ("acme", "https://judges.example.org", "0.0.0.0", None),
        ("acme", "judges.example.org:443", "0.0.0.0", None),
        ("acme", "Judges.Example.Org", "0.0.0.0", None),
        ("operator@example.org", "203.0.113.7", "0.0.0.0", None),
        # Not one of the three shapes, with and without whitespace.
        ("not-an-email", PUBLIC_NAME, "0.0.0.0", None),
        ("not an email", PUBLIC_NAME, "0.0.0.0", None),
        ("x@y.example\ntls internal", PUBLIC_NAME, "0.0.0.0", None),
        ("x@y.example }", PUBLIC_NAME, "0.0.0.0", None),
    ],
)
def test_the_certificate_line_is_derived_for_its_host_and_address_or_refused(
    tmp_path, tls, host, address, line
):
    env = {
        **_init_env(tmp_path),
        "EXULANICA_TLS": tls,
        "EXULANICA_PUBLIC_HOST": host,
        "EXULANICA_EDGE_ADDRESS": address,
    }
    result = _derived_line(tmp_path, env)
    if line is None:
        assert result.returncode == 2, result.stderr
        assert "EXULANICA_TLS" in result.stderr
        assert not (tmp_path / "deploy" / "public.env").exists()
        return
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "line").read_text(encoding="utf-8") == line
    # Derived on every call, never stored beside EXULANICA_TLS.
    stored = (tmp_path / "deploy" / "public.env").read_text(encoding="utf-8")
    assert "EXULANICA_TLS_DIRECTIVE" not in stored


@needs_shell
def test_a_hand_edit_to_an_unsafe_certificate_shape_stops_every_compose_command(tmp_path):
    env = {
        **_init_env(tmp_path),
        "EXULANICA_TLS": "acme",
        "EXULANICA_PUBLIC_HOST": PUBLIC_NAME,
        "EXULANICA_EDGE_ADDRESS": "0.0.0.0",
    }
    assert _derived_line(tmp_path, env).returncode == 0
    env_file = tmp_path / "deploy" / "public.env"
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            "EXULANICA_TLS=acme", "EXULANICA_TLS=internal"
        ),
        encoding="utf-8",
    )
    (tmp_path / "line").unlink()
    path = {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
    refused = _script(tmp_path, "down", **path)
    assert refused.returncode == 2
    assert "only for an edge on a loopback address" in refused.stderr
    assert not (tmp_path / "line").exists(), "docker was reached"


def test_every_docker_run_runs_a_loaded_image_and_the_build_pulls_by_the_platforms_digest():
    script = _directives(SCRIPT.read_text(encoding="utf-8")).replace("\\\n", " ")
    runs = [line for line in script.splitlines() if re.search(r"\bdocker run\b", line)]
    assert runs and all("--pull never" in line for line in runs), runs
    build_step = script.split("\n  build)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert "docker buildx imagetools inspect --raw" in build_step
    pulls = [line for line in build_step.splitlines() if "docker pull" in line]
    assert pulls and all('@$manifest"' in line for line in pulls), pulls


def test_the_api_keeps_the_address_the_client_proxy_found_at_its_start():
    """nginx in the client proxy finds `api` by name once, when it starts. In a rehearsal an `up`
    that recreated the API beside the preparation and tile workers gave it a new address, and the
    proxy answered 502 for every API path while the API was well. The API holds a fixed address in
    the network's range, apart from the edge's, the client's and the gateway."""
    import ipaddress

    subnet = re.search(r"^        - subnet: (\S+)$", OVERLAY, re.M)
    assert subnet is not None
    network = ipaddress.ip_network(subnet.group(1))
    pinned = {}
    for service in ("edge", "client", "api"):
        found = re.search(r"^\s+ipv4_address: (\S+)$", OVERLAY_SERVICES[service], re.M)
        assert found is not None, service
        pinned[service] = ipaddress.ip_address(found.group(1))
    assert all(a in network and a != next(network.hosts()) for a in pinned.values()), pinned
    assert len(set(pinned.values())) == 3, pinned


def _watch_section() -> str:
    script = _directives(SCRIPT.read_text(encoding="utf-8")).replace("\\\n", " ")
    return script.split("\n  watch)\n", 1)[1].split("\n    ;;\n", 1)[0]


def test_watch_reads_the_path_the_edge_takes_to_the_api():
    """The edge proxies to the client proxy at the port watch reads it on, from inside the edge."""
    upstream = re.search(r"^\s*reverse_proxy (\S+) \{$", _directives(CADDYFILE), re.M)
    assert upstream is not None
    assert f"http://{upstream.group(1)}/api/healthz" in _watch_section()
    assert re.search(r'proxied="\$\(compose exec -T edge ', _watch_section())


#: Stand-ins for docker and curl: each answers what the scenario says and logs every action.
_WATCH_STUBS = {
    "docker": """#!/bin/sh
case " $* " in
  *" exec -T client "*) echo "$WATCH_INSIDE" ;;
  *" exec -T edge "*) echo "$WATCH_PROXIED" ;;
  *" ps -a -q api "*) [ -n "${WATCH_REPLACED-container}" ] && echo "${WATCH_REPLACED-container}" ;;
  *" inspect "*)
    echo "PATH=/usr/bin"
    [ -n "${WATCH_HELD_KEY:-}" ] && printf 'NEBIUS_API_KEY=%s\n' "$WATCH_HELD_KEY"
    echo "EXULANICA_SPENDING=durable" ;;
  *" up "*)
    echo "up $*" >>"$WATCH_ACTIONS"
    printf '%s' "${NEBIUS_API_KEY:-}" >"$WATCH_ACTIONS.key" ;;
  *" restart "*) echo "restart $*" >>"$WATCH_ACTIONS" ;;
  *) echo "unexpected docker $*" >>"$WATCH_ACTIONS"; exit 1 ;;
esac
""",
    "curl": """#!/bin/sh
printf '%s' "$WATCH_LIVE"
""",
}


def _watch(
    tmp_path: pathlib.Path, inside: str, proxied: str, live: str, **extra: str
) -> tuple[str, list[str]]:
    stubs = tmp_path / "stubs"
    if not stubs.exists():
        stubs.mkdir()
        for name, body in _WATCH_STUBS.items():
            (stubs / name).write_text(body, encoding="utf-8")
            (stubs / name).chmod(0o755)
        assert _script(tmp_path, "init", **_init_env(tmp_path)).returncode == 0
    actions = tmp_path / "actions.log"
    actions.write_text("", encoding="utf-8")
    result = _script(
        tmp_path,
        "watch",
        PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}",
        WATCH_INSIDE=inside,
        WATCH_PROXIED=proxied,
        WATCH_LIVE=live,
        WATCH_ACTIONS=str(actions),
        **extra,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr, actions.read_text(encoding="utf-8").splitlines()


@needs_shell
def test_watch_restarts_the_client_proxy_when_it_cannot_reach_a_live_api(tmp_path):
    """The rehearsal's failure: the API well inside, the proxy's path to it failing, the edge 502.
    The third check in a row restarts the client proxy, which finds the API again; the API is
    never recreated for it."""
    for _ in range(2):
        _, actions = _watch(tmp_path, inside="200", proxied="000", live="502")
        assert actions == []
    output, actions = _watch(tmp_path, inside="200", proxied="000", live="502")
    assert (
        len(actions) == 1
        and actions[0].startswith("restart ")
        and actions[0].endswith(" restart client")
    ), actions
    assert "restarting the client proxy after 3 failures" in output
    assert "edge failing" not in output, "the next check says whether the repair worked"
    assert "proxy_failures=3" in output and "failures=0" in output
    output, actions = _watch(tmp_path, inside="200", proxied="000", live="502")
    assert actions == [], "the count starts again after the restart"
    assert "edge failing: 4 checks" in output, "a repair that did not help is reported"


@needs_shell
def test_watch_recreates_an_api_that_fails_its_own_liveness_and_not_the_proxy(tmp_path):
    """A failing API fails the proxy's path too; that is the API's to repair, so the proxy's
    count stays at zero and the third check recreates the API alone."""
    for _ in range(2):
        _, actions = _watch(tmp_path, inside="000", proxied="000", live="502")
        assert actions == []
    output, actions = _watch(tmp_path, inside="000", proxied="000", live="502")
    assert len(actions) == 1 and "--force-recreate api" in actions[0], actions
    assert "proxy_failures=0" in output


def _recreation(tmp_path: pathlib.Path, **extra: str) -> tuple[str, list[str], str]:
    """The third failed liveness check in a row, which recreates the API: what watch printed, the
    docker commands it ran, and the model credential the recreating command held."""
    for _ in range(2):
        _watch(tmp_path, inside="000", proxied="000", live="502", **extra)
    output, actions = _watch(tmp_path, inside="000", proxied="000", live="502", **extra)
    held = (tmp_path / "actions.log.key").read_text(encoding="utf-8")
    return output, actions, held


@needs_shell
def test_a_recreated_api_keeps_the_model_credential_of_the_one_it_replaces(tmp_path):
    """The timer that runs watch holds no model credential, so the recreation takes it from the
    container it replaces: the recreating command holds exactly that value, and it appears in
    nothing watch prints and in no command line."""
    output, actions, held = _recreation(tmp_path, WATCH_HELD_KEY=CREDENTIAL_PROBE)
    assert held == CREDENTIAL_PROBE
    assert len(actions) == 1 and "--force-recreate api" in actions[0], actions
    assert CREDENTIAL_PROBE not in output
    assert CREDENTIAL_PROBE not in "\n".join(actions)
    assert "held no NEBIUS_API_KEY" not in output
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "actions.log.key" and path.parent.name != "stubs":
            assert CREDENTIAL_PROBE.encode() not in path.read_bytes(), path


@needs_shell
@pytest.mark.parametrize(
    "extra",
    [{}, {"WATCH_REPLACED": ""}],
    ids=["the container holds none", "no container to replace"],
)
def test_a_recreation_with_no_credential_to_keep_says_so_by_the_variable_s_name(tmp_path, extra):
    """A replaced container with no credential, or none to replace, still recreates the API
    (liveness comes first) and the journal names the variable, never a value."""
    output, actions, held = _recreation(tmp_path, **extra)
    assert len(actions) == 1 and "--force-recreate api" in actions[0], actions
    assert held == ""
    assert "the replaced api held no NEBIUS_API_KEY" in output


@needs_shell
def test_a_watch_that_holds_a_credential_hands_its_own_to_the_recreation(tmp_path):
    """The rule is one for `watch` and `up` alike: a process that holds a credential hands that
    one on and reads no container for another."""
    typed = "held-by-the-watching-shell"
    output, _, held = _recreation(
        tmp_path, WATCH_HELD_KEY=CREDENTIAL_PROBE, **{"NEBIUS_API_KEY": typed}
    )
    assert held == typed
    assert CREDENTIAL_PROBE not in output and typed not in output


#: Stand-ins for an `up`: every image is loaded, the merged configuration publishes nothing, and
#: the command that starts the services writes down the model credential it held.
_UP_STUBS = {
    "docker": """#!/bin/sh
case " $* " in
  *" image inspect "*) echo sha256:stand-in ;;
  *" config --format json "*) echo '{"services": {}}' ;;
  *" ps -a -q api "*) [ -n "${WATCH_REPLACED-container}" ] && echo "${WATCH_REPLACED-container}" ;;
  *" inspect "*)
    echo "PATH=/usr/bin"
    [ -n "${WATCH_HELD_KEY:-}" ] && printf 'NEBIUS_API_KEY=%s\\n' "$WATCH_HELD_KEY"
    echo "EXULANICA_SPENDING=durable" ;;
  *" up "*)
    echo "up $*" >>"$WATCH_ACTIONS"
    printf '%s' "${NEBIUS_API_KEY:-}" >"$WATCH_ACTIONS.key" ;;
  *" ps "*) : ;;
  *) echo "unexpected docker $*" >>"$WATCH_ACTIONS"; exit 1 ;;
esac
""",
    "sleep": "#!/bin/sh\n",
}


def _up(tmp_path: pathlib.Path, **extra: str) -> tuple[subprocess.CompletedProcess, list[str], str]:
    """`up` on an initialised server with its fuse stated, against the stand-ins: the result, the
    docker commands that started anything, and the model credential that command held."""
    stubs = tmp_path / "up-stubs"
    stubs.mkdir()
    for name, body in _UP_STUBS.items():
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(0o755)
    assert _script(tmp_path, "init", **_init_env(tmp_path)).returncode == 0
    env_file = tmp_path / "deploy" / "public.env"
    stated = env_file.read_text(encoding="utf-8")
    stated = stated.replace("EXULANICA_BUDGET_USD=\n", "EXULANICA_BUDGET_USD=1\n")
    stated = stated.replace("EXULANICA_BUDGET_MAX_CALLS=\n", "EXULANICA_BUDGET_MAX_CALLS=10\n")
    env_file.write_text(stated, encoding="utf-8")
    actions = tmp_path / "actions.log"
    actions.write_text("", encoding="utf-8")
    result = _script(
        tmp_path,
        "up",
        PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}",
        WATCH_ACTIONS=str(actions),
        **extra,
    )
    held = pathlib.Path(f"{actions}.key")
    return (
        result,
        actions.read_text(encoding="utf-8").splitlines(),
        held.read_text(encoding="utf-8") if held.exists() else "",
    )


@needs_shell
def test_up_from_a_shell_with_no_credential_keeps_the_replaced_api_s(tmp_path):
    """A redeploy or a changed setting is an `up` from a shell that holds no model credential: the
    services it starts hold the one the replaced API held, which appears in nothing `up` prints,
    in no command line and in no file of the deploy directory; `up` says only that it was kept."""
    result, actions, held = _up(tmp_path, WATCH_HELD_KEY=CREDENTIAL_PROBE)
    assert result.returncode == 0, result.stderr
    assert held == CREDENTIAL_PROBE
    assert len(actions) == 1 and " up -d --wait " in actions[0], actions
    assert "NEBIUS_API_KEY is kept from the api container this up replaces" in result.stderr
    assert "NEBIUS_API_KEY is not set" not in result.stderr
    assert CREDENTIAL_PROBE not in result.stdout + result.stderr + "\n".join(actions)
    for path in (tmp_path / "deploy").rglob("*"):
        if path.is_file():
            assert CREDENTIAL_PROBE.encode() not in path.read_bytes(), path


@needs_shell
def test_a_shell_that_holds_a_credential_always_replaces_the_one_the_api_held(tmp_path):
    """How an operator changes the credential: `up` from a shell that holds one hands that one
    over, whatever the replaced container held, and reads no container for it."""
    typed = "typed-by-the-operator-now"
    result, _, held = _up(tmp_path, WATCH_HELD_KEY=CREDENTIAL_PROBE, **{"NEBIUS_API_KEY": typed})
    assert result.returncode == 0, result.stderr
    assert held == typed
    assert "is kept from" not in result.stderr and "is not set" not in result.stderr
    assert CREDENTIAL_PROBE not in result.stdout + result.stderr


@needs_shell
@pytest.mark.parametrize(
    "extra",
    [{}, {"WATCH_REPLACED": ""}],
    ids=["the container holds none", "no container to replace"],
)
def test_up_with_no_credential_anywhere_starts_and_says_so_by_the_variable_s_name(tmp_path, extra):
    """A first `up` with no credential, or one over an API that held none, starts the server as
    before and names the variable: every route that asks a model will say none is configured."""
    result, actions, held = _up(tmp_path, **extra)
    assert result.returncode == 0, result.stderr
    assert held == "" and len(actions) == 1
    assert "NEBIUS_API_KEY is not set" in result.stderr
    assert "is kept from" not in result.stderr


@needs_shell
def test_watch_reports_a_failing_edge_and_restarts_nothing_for_it(tmp_path):
    """A failed issuance or a rate-limited certificate makes the edge fail while the proxy and the
    API are well; neither restart fixes it. From the third check in a row it is reported in the
    journal, and nothing is restarted; a passing check starts the count again."""
    for checks in range(1, 5):
        output, actions = _watch(tmp_path, inside="200", proxied="200", live="000")
        assert actions == []
        assert f"edge_failures={checks}" in output
        assert ("edge failing" in output) == (checks >= 3)
    output, _ = _watch(tmp_path, inside="200", proxied="200", live="200")
    assert "edge_failures=0" in output and "edge failing" not in output
