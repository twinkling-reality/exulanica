"""The complete installation's deployment files: what they may fetch, and what they must equal.

Text checks, as the other deployment tests are: the client image fetches no package, refuses a
build that does not state its commit, bundle digest and toolchain, and serves the reviewer image's
nginx configuration exactly, so the two cannot drift apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "deploy" / "installation" / "client.Dockerfile"


def _instructions(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


MIB = 1024 * 1024


def _reviewer_configuration() -> str:
    reviewer = (ROOT / "deploy" / "judge" / "web.Dockerfile").read_text(encoding="utf-8")
    embedded = reviewer.split("COPY <<'CONF' /etc/nginx/conf.d/default.conf\n", 1)[1]
    return embedded.split("\nCONF\n", 1)[0] + "\n"


def _installation_configuration() -> str:
    return (ROOT / "deploy" / "installation" / "client-nginx.conf").read_text(encoding="utf-8")


def _body_cap(conf: str) -> int:
    caps = re.findall(r"^\s*client_max_body_size (\d+)m;$", conf, re.M)
    assert len(caps) == 1
    return int(caps[0]) * MIB


def _zone_seconds_per_request(conf: str, zone: str) -> int:
    """How many seconds one request of a limit zone's rate takes, read as nginx reads a rate: a
    whole number of requests per second (r/s) or per minute (r/m), its only two units. A rate in
    any other unit stops nginx from starting."""
    rate = re.search(rf"zone={zone}:\d+m rate=(\S+);", conf)
    assert rate is not None, zone
    stated = re.fullmatch(r"([1-9]\d*)r/(s|m)", rate.group(1))
    assert stated is not None, f"nginx cannot start with rate={rate.group(1)}"
    period = {"s": 1, "m": 60}[stated.group(2)]
    assert period % int(stated.group(1)) == 0
    return period // int(stated.group(1))


def _without_body_cap(conf: str) -> str:
    """The configuration with its body cap, the comment above it and the cap's refusal removed."""
    lines = conf.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("# BODY CAP."))
    end = next(i for i, line in enumerate(lines) if "client_max_body_size" in line)
    kept = lines[:start] + lines[end + 1 :]
    return "\n".join(re.sub(r"\d{6,}", "N", line) for line in kept)


def test_the_client_image_serves_the_reviewer_images_nginx_configuration_but_its_body_cap():
    """One proxy configuration for both, so they cannot drift apart, except the body cap: the
    installation's people upload photographs and a reviewer's token cannot."""
    ours, reviewer = _installation_configuration(), _reviewer_configuration()
    assert _without_body_cap(ours) == _without_body_cap(reviewer)
    assert "COPY deploy/installation/client-nginx.conf /etc/nginx/conf.d/default.conf" in (
        _instructions(CLIENT)
    )


def test_the_installation_proxy_passes_every_body_the_api_accepts():
    """The browser sends every chosen photograph in one POST /intake, so a cap below the API's own
    body limit refuses at the proxy an upload the API would take."""
    from exulanica.api.body_limit import MAX_BODY_BYTES

    assert _body_cap(_installation_configuration()) == MAX_BODY_BYTES
    assert _body_cap(_reviewer_configuration()) == 8 * MIB


@pytest.mark.parametrize("which", ["installation", "reviewer"])
def test_the_proxys_own_refusals_take_the_problem_shape(which):
    """The browser reads a failure's code and detail; nginx's own pages are HTML. A refusal that
    retrying cures says when; one that it does not, or that may have run, does not invite it."""
    conf = _installation_configuration() if which == "installation" else _reviewer_configuration()
    # Answers from the API pass through unchanged.
    assert not re.search(r"^\s*proxy_intercept_errors", conf, re.M)
    pages = sorted(set(re.findall(r"^\s*error_page (\d{3}) = @([a-z_]+);$", conf, re.M)))
    assert pages == [
        ("413", "body_too_large"),
        ("413", "guest_body_too_large"),
        ("429", "guest_entries_limited"),
        ("429", "rate_limited"),
        ("502", "upstream_unavailable"),
        ("504", "upstream_timeout"),
    ]
    # Each refusal's code and Retry-After, by the location that answers it: a limit's refusal asks
    # for the time its zone's rate gives one request, the guest entry's own and not the write's.
    expected = {
        "body_too_large": ("body_too_large", None),
        "guest_body_too_large": ("body_too_large", None),
        "rate_limited": ("rate_limited", _zone_seconds_per_request(conf, "exulanica_writes")),
        "guest_entries_limited": (
            "rate_limited",
            _zone_seconds_per_request(conf, "exulanica_guest_entries"),
        ),
        "upstream_unavailable": ("upstream_unavailable", 5),
        "upstream_timeout": ("upstream_timeout", None),
    }
    for status, location in pages:
        block = conf.split(f"location @{location} {{", 1)[1].split("\n    }", 1)[0]
        assert "default_type application/json;" in block
        answered = re.search(r"^\s*return (\d{3}) '(.*)';$", block, re.M)
        assert answered is not None and answered.group(1) == status
        # nginx ends a single-quoted string at the next quote: one inside stops it from starting.
        assert "'" not in answered.group(2), location
        body = json.loads(answered.group(2))
        code, retry_after = expected[location]
        assert body["code"] == code
        assert isinstance(body["detail"], str) and body["detail"]
        header = re.search(r'add_header Retry-After "(\d+)" always;', block)
        assert (int(header.group(1)) if header else None) == retry_after
        assert body.get("retry_after_seconds") == retry_after
        if location == "body_too_large":
            assert body["limit_bytes"] == _body_cap(conf)
        if location == "guest_body_too_large":
            guest = conf.split("location = /api/auth/guest {", 1)[1].split("\n    }", 1)[0]
            cap = re.search(r"client_max_body_size (\d+)k;", guest)
            assert cap is not None and body["limit_bytes"] == int(cap.group(1)) * 1024
        if status == "504":
            timeout = re.search(r"proxy_read_timeout (\d+)s;", conf)
            assert timeout is not None and f"within {timeout.group(1)} seconds" in body["detail"]
    # Every zone's rate is one nginx can start with. The write limit is one write every two
    # seconds; the guest entry's is far slower, and no slower than nginx can count.
    for zone in re.findall(r"^limit_req_zone \S+ zone=(\w+):", conf, re.M):
        _zone_seconds_per_request(conf, zone)
    assert _zone_seconds_per_request(conf, "exulanica_writes") == 2
    assert _zone_seconds_per_request(conf, "exulanica_guest_entries") == 60


@pytest.mark.parametrize("which", ["installation", "reviewer"])
def test_every_location_reaching_the_api_answers_the_proxys_four_problem_pages(which):
    """nginx gives a location that names any error_page only its own, not the server's beside
    them. So every location that reaches the API either names none, and takes the server's four,
    or names all four of 413, 429, 502 and 504: a dead API answers the problem shape, not nginx's
    HTML page, wherever the request went."""
    conf = _installation_configuration() if which == "installation" else _reviewer_configuration()
    server = set(re.findall(r"^    error_page (\d{3}) = @", conf, re.M))
    assert server == {"413", "429", "502", "504"}
    blocks = re.findall(r"^    location ([^@{][^{]*)\{(.*?)\n    \}", conf, re.M | re.S)
    reaching = [
        (name.strip(), body) for name, body in blocks if "proxy_pass http://api:8000" in body
    ]
    assert [name for name, _ in reaching] == ["= /api/auth/guest", "/api/"]
    for name, body in reaching:
        own = set(re.findall(r"^\s*error_page (\d{3}) = @", body, re.M))
        assert own in (set(), server), (name, own)
    guest = dict(reaching)["= /api/auth/guest"]
    assert re.search(r"^\s*client_max_body_size 1k;$", guest, re.M)


@pytest.mark.parametrize("which", ["installation", "reviewer"])
def test_a_guest_entry_is_counted_by_the_address_the_edge_set(which):
    """The guest entry's limit is per client address, and that address is the one the edge put in
    X-Forwarded-For: trusted only from a container network's private ranges, and without
    real_ip_recursive, which would let an address a client wrote earlier in the header be counted.
    The edge replaces the header it receives (its Caddyfile trusts no proxy before it)."""
    conf = _installation_configuration() if which == "installation" else _reviewer_configuration()
    # The trusted addresses are an included file, so the public composition can name its edge's
    # one address in their place; each image's own file names the container ranges.
    assert re.findall(r"^\s*include (\S+);$", conf, re.M) == [
        "/etc/nginx/exulanica-trusted-proxies.conf"
    ]
    assert not re.findall(r"^\s*set_real_ip_from", conf, re.M)
    trusted = (
        (ROOT / "deploy" / "installation" / "client-trusted-proxies.conf").read_text(
            encoding="utf-8"
        )
        if which == "installation"
        else (ROOT / "deploy" / "judge" / "web.Dockerfile")
        .read_text(encoding="utf-8")
        .split("COPY <<'TRUSTED' /etc/nginx/exulanica-trusted-proxies.conf\n", 1)[1]
        .split("\nTRUSTED\n", 1)[0]
    )
    assert re.findall(r"^set_real_ip_from (\S+);$", trusted, re.M) == [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]
    if which == "installation":
        assert (
            "COPY deploy/installation/client-trusted-proxies.conf "
            "/etc/nginx/exulanica-trusted-proxies.conf"
        ) in _instructions(CLIENT)
    assert re.search(r"^\s*real_ip_header X-Forwarded-For;$", conf, re.M)
    directives = "\n".join(line for line in conf.splitlines() if not line.lstrip().startswith("#"))
    assert "real_ip_recursive" not in directives
    mapping = conf.split("map $request_method $exulanica_guest_client {", 1)[1].split("}", 1)[0]
    assert re.search(r"^\s*POST \$binary_remote_addr;$", mapping, re.M)
    assert re.search(r'^\s*default "";$', mapping, re.M)
    zone = r"^limit_req_zone \$exulanica_guest_client zone=exulanica_guest_entries:"
    assert re.search(zone, conf, re.M)
    guest = conf.split("location = /api/auth/guest {", 1)[1].split("\n    }", 1)[0]
    assert "limit_req zone=exulanica_guest_entries burst=3 nodelay;" in guest
    assert "limit_req zone=exulanica_writes burst=20 nodelay;" in guest
    for caddyfile in ("deploy/judge/Caddyfile", "deploy/public/Caddyfile"):
        assert "trusted_proxies" not in (ROOT / caddyfile).read_text(encoding="utf-8")


@pytest.mark.parametrize("which", ["installation", "reviewer"])
def test_the_api_is_reached_at_the_host_and_port_the_browser_used(which):
    """The sign-in routes compare the origin they were reached at with the configured browser
    origin, which names its port when it is not the scheme's default (https://host:8443). nginx's
    $host drops the port, so every location that reaches the API passes the Host header as the
    browser sent it."""
    conf = _installation_configuration() if which == "installation" else _reviewer_configuration()
    locations = re.findall(r"location [^{]*\{(.*?)\n    \}", conf, re.S)
    reaching = [block for block in locations if "proxy_pass http://api:8000" in block]
    assert len(reaching) == 2
    for block in reaching:
        assert re.findall(r"proxy_set_header Host (\S+);", block) == ["$http_host"]


def test_the_client_image_fetches_nothing_and_states_its_provenance():
    instructions = _instructions(CLIENT)
    text = "\n".join(instructions)
    for fetch in ("pnpm install", "npm install", "npm ci", "yarn", "curl ", "wget ", "apk add"):
        assert fetch not in text, fetch
    assert re.fullmatch(r"FROM nginx:1\.29-alpine@sha256:[0-9a-f]{64}", instructions[0])
    for argument in (
        "EXULANICA_CODE_REVISION",
        "EXULANICA_CLIENT_TREE_SHA256",
        "EXULANICA_NODE_VERSION",
        "EXULANICA_PNPM_VERSION",
    ):
        assert f"ARG {argument}" in instructions
        assert f"${{{argument}}}" in text
    assert "COPY web/packages/app/dist /usr/share/nginx/html" in instructions


def test_the_client_context_is_an_allowlist_without_credentials():
    ignored = _instructions(ROOT / "deploy" / "installation" / "client.Dockerfile.dockerignore")
    assert ignored[0] == "*"
    assert set(ignored[1:]) == {
        "!web/packages/app/dist",
        "!deploy/installation/client-nginx.conf",
        "!deploy/installation/client-trusted-proxies.conf",
        "**/.env",
        "**/.env.*",
    }


def test_the_backend_image_ships_the_character_catalog_and_the_profiles():
    """The image carries the character catalogs it publishes, and the profiles read by name."""
    from exulanica.world.character_appearance import load_character_catalog

    dockerfile = _instructions(ROOT / "Dockerfile")
    allowed = _instructions(ROOT / ".dockerignore")
    assert (
        "COPY assets/characters/catalog.json assets/characters/looks.json /app/assets/characters/"
        in dockerfile
    )
    assert "COPY deploy/profiles /app/deploy/profiles" in dockerfile
    for path in (
        "assets/characters/catalog.json",
        "assets/characters/looks.json",
        "deploy/profiles",
    ):
        assert f"!{path}" in allowed
    # The layered catalog and its looks load as a pair. Everything publishing reads is held by
    # tests/test_image_ships_character_catalogs.py.
    catalog, looks = load_character_catalog(ROOT / "assets" / "characters")
    assert catalog and looks is not None


def test_the_composition_gives_backup_and_purge_credentials_to_maintenance_alone():
    """The backup role to maintenance alone; the purge role also to the operator's restore job,
    which replays as it and never starts outside the recovery profile."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    body = compose.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    blocks = {
        block.strip().split(":", 1)[0]: block
        for block in re.split(r"\n(?=  [a-z][a-z-]*:\n)", "\n" + body)
        if block.strip()
    }

    def holders(setting: str) -> set[str]:
        return {name for name, block in blocks.items() if f"{setting}:" in block}

    assert holders("EXULANICA_BACKUP_DATABASE_URL") == {"maintenance"}
    assert holders("EXULANICA_PURGE_DATABASE_URL") == {"maintenance", "restore"}
    # One-shot jobs only: the operator's restore, and the first-install marker check.
    assert holders("EXULANICA_RESTORE_DATABASE_URL") == {"restore", "restore-marker"}
    assert 'profiles: ["recovery"]' in blocks["restore"]
    assert "spending-witness:/var/lib/exulanica-spending-witness:ro" in compose
    assert '"127.0.0.1:${EXULANICA_CLIENT_PORT:-8080}:8080"' in compose


def test_the_default_composition_claims_no_worker_it_does_not_start():
    import json
    import re

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    defaults = set(re.findall(r"\$\{EXULANICA_PROFILE:-([a-z-]+)\}", compose))
    example = re.search(r"^EXULANICA_PROFILE=(.*)$", (ROOT / ".env.example").read_text(), re.M)
    assert example and defaults == {example.group(1)}
    profile = json.loads((ROOT / "deploy" / "profiles" / f"{example.group(1)}.json").read_text())
    # The reconstruction workers start only with `--profile reconstruction`.
    for component in ("derivatives", "pose_scene"):
        assert profile["components"][component].get("unavailable_reason")
    assert "${EXULANICA_BACKEND_EXTRAS:---extra server}" in compose


def test_every_profile_that_installs_preparation_is_composed_with_a_preparation_worker():
    """A profile that says preparation is installed is one compose starts a worker for by default,
    and the worker reads that profile, which names every registered preparer: a preparer added in
    code is declared installed or not, never left for the worker to run unannounced."""
    import json

    import yaml
    from exulanica.world.asset_preparation import PREPARERS

    service = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"][
        "preparation"
    ]
    assert "profiles" not in service
    assert service["command"] == ["exulanica-asset-preparation"]
    assert service["environment"]["EXULANICA_INSTALLATION_PROFILE"] == (
        "/app/deploy/profiles/${EXULANICA_PROFILE:-single-host-server-only}.json"
    )
    for credential in ("BACKUP", "PURGE", "RESTORE", "TILE_PUBLISHER"):
        assert not any(credential in key for key in service["environment"]), credential
    registered = {f"{key[0]}@{key[1]}" for key in PREPARERS}
    for name in ("single-host", "single-host-server-only", "shared-store"):
        profile = json.loads((ROOT / "deploy" / "profiles" / f"{name}.json").read_text())
        preparation = profile["components"]["preparation"]
        assert preparation["installed"] is True, name
        assert set(preparation["preparers"]) == registered, name
        assert preparation["preparers"]["exulanica.static-glb-preparer@1"] == {"installed": True}
        assert preparation["preparers"]["exulanica.makehuman-parametric-preparer@1"] == {
            "installed": False,
            "reason": "preparer_tool_absent",
        }
    reviewer = json.loads((ROOT / "deploy" / "profiles" / "reviewer.json").read_text())
    assert reviewer["components"]["preparation"] == {"installed": False}


def test_the_playback_worker_plays_by_exactly_the_apis_playback_settings():
    """The API reads the playback process's liveness by the digest of the playback settings, so
    the two take them from one place; the worker starts only on request, because a composition
    that names no society to play would have it refuse and restart for ever; and it stops after a
    round's lease, not in the middle of a round."""
    import tomllib

    import yaml
    from exulanica.world.society_controls import LEASE_SECONDS

    document = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    shared = document["x-society-playback"]
    api = document["services"]["api"]["environment"]
    worker_service = document["services"]["playback-worker"]
    worker = worker_service["environment"]
    for setting, value in shared.items():
        assert api[setting] == worker[setting] == value, setting
    assert set(shared) == {
        "EXULANICA_SOCIETY_CONTROL_WORKSPACES",
        "EXULANICA_SOCIETY_CONTROL_WORKER",
        "EXULANICA_SOCIETY_TICK_INTERVAL_MS",
    }
    assert api["EXULANICA_PLAYBACK_WORKER"] == "${EXULANICA_PLAYBACK_WORKER:-on}"
    assert worker["EXULANICA_PLAYBACK_WORKER"] == "process"
    assert worker_service["profiles"] == ["playback"]
    assert worker_service["command"] == ["exulanica-playback-worker"]
    assert int(worker_service["stop_grace_period"].removesuffix("s")) > LEASE_SECONDS
    assert worker["EXULANICA_INSTALLATION_PROFILE"] == api["EXULANICA_INSTALLATION_PROFILE"]
    assert "restore-control:/var/lib/exulanica-restore:ro" in worker_service["volumes"]
    for credential in ("BACKUP", "PURGE", "RESTORE", "TILE_PUBLISHER"):
        assert not any(credential in key for key in worker), credential
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"
    ]
    assert scripts["exulanica-playback-worker"] == "exulanica.orchestration.playback_worker:main"
    # A process that plays societies elsewhere leaves simulation to the profile's declaration.
    for name in ("single-host", "single-host-server-only", "shared-store"):
        profile = json.loads((ROOT / "deploy" / "profiles" / f"{name}.json").read_text())
        assert profile["components"]["simulation"] == {"installed": True}, name


def test_the_shared_store_override_gives_the_purge_identity_to_maintenance_and_restore_alone():
    import yaml

    base = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
    override = yaml.safe_load(
        (ROOT / "deploy" / "installation" / "compose.shared-store.yaml").read_text(encoding="utf-8")
    )["services"]

    def environment(name):
        return override.get(name, {}).get("environment", {})

    # Every service that reads the profile or touches stored bytes states the object store.
    touching = {
        name
        for name, service in base.items()
        if "EXULANICA_INSTALLATION_PROFILE" in (service.get("environment") or {})
        or any(str(volume).startswith("media:") for volume in service.get("volumes", []))
    }
    assert touching <= set(override)
    for name in touching:
        assert environment(name)["EXULANICA_STORE_KIND"] == "object"
        assert environment(name)["EXULANICA_INSTALLATION_PROFILE"].endswith("/shared-store.json")
    purge = {
        name
        for name in override
        if "EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID" in environment(name)
    }
    runtime = {
        name for name in override if "EXULANICA_OBJECT_STORE_ACCESS_KEY_ID" in environment(name)
    }
    assert purge == {"maintenance", "restore"}
    publishes = {"catalogs"} if _publishes_character_catalogs() else set()
    assert (
        runtime
        == {
            "api",
            "derivative-worker",
            "scene-worker",
            "preparation",
            "playback-worker",
            "tile-worker",
            "piece-generation",
        }
        | publishes
    )


def _publishes_character_catalogs() -> bool:
    """Whether this tree carries the character catalog publish command, read from its own
    pyproject: when it does, a host serves people only from catalogs it has published."""
    import tomllib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return "exulanica-character-catalog" in scripts.get("scripts", {})


def test_a_tree_that_publishes_character_catalogs_composes_the_publish_before_the_api():
    import yaml

    services = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
    if not _publishes_character_catalogs():
        # Nothing to publish in this tree, and so nothing composed for it.
        assert "catalogs" not in services
        return
    job = services["catalogs"]
    assert job["command"][:2] == ["exulanica-character-catalog", "publish"]
    assert "--apply" in job["command"]
    assert job["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert job["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["catalogs"]["condition"] == (
        "service_completed_successfully"
    )
    # The store the API serves, with the runtime identity and never the purge one.
    assert "media:/var/lib/exulanica" in job.get("volumes", [])
    assert not any("PURGE" in name for name in job.get("environment", {}))
