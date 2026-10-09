"""The judge stack's public edge and its operator script.

Text assertions over ``deploy/judge/edge.yaml``, the ``Caddyfile``, the web proxy and the judge
compose file, as ``tests/test_judge_deployment.py`` makes over the rest of the stack, and for the
same reason no YAML parser. Each one names a failure that produces a public stack which looks fine
and is not: an edge that reaches the API around the write limit, a proxy that moves under a
running demonstration, a stack that spends without a stated ceiling.

The script tests run ``deploy/judge/stack.sh`` itself, in a temporary directory, for the steps
that need no Docker: writing the secrets file and refusing to start without a token.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JUDGE = ROOT / "deploy" / "judge"

EDGE = (JUDGE / "edge.yaml").read_text(encoding="utf-8")
CADDYFILE = (JUDGE / "Caddyfile").read_text(encoding="utf-8")
JUDGE_COMPOSE = (JUDGE / "compose.yaml").read_text(encoding="utf-8")
JUDGE_WEB = (JUDGE / "web.Dockerfile").read_text(encoding="utf-8")
STACK = JUDGE / "stack.sh"
#: A stand-in model credential the stack must never write anywhere.
CREDENTIAL_PROBE = "must-not-be-written-anywhere"

#: The services that serve for the life of the stack. `migrate` and `seed` run once.
LONG_RUNNING = ("postgres", "api", "web", "edge")


def _directives(text: str) -> str:
    """The file with its comments stripped. A comment is not a directive."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _services(text: str) -> dict[str, str]:
    """Each top-level service's block of an overlay, by name."""
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


def test_only_the_edge_publishes_ports_and_its_bind_address_has_no_default():
    """A laptop rehearsal must not open 80 and 443 on every interface because a value was unset."""
    services = _services(EDGE)
    publishing = sorted(name for name, block in services.items() if "ports:" in block)
    assert publishing == ["edge"]
    published = re.findall(r'^\s+- "([^"]+)"\s*$', services["edge"].split("ports:", 1)[1], re.M)
    assert len(published) == 2, published
    for entry in published:
        assert entry.startswith("${EXULANICA_EDGE_ADDRESS:?"), entry
    assert {entry.rsplit(":", 1)[1] for entry in published} == {"80", "443"}


def test_the_edge_image_is_pinned_to_an_exact_version():
    """A moving tag is a proxy that changes under a running demonstration."""
    images = re.findall(r"^\s+image:\s*(\S+)\s*$", _directives(EDGE), re.M)
    assert len(images) == 1, images
    assert re.fullmatch(r"caddy:\d+\.\d+\.\d+(-alpine)?@sha256:[0-9a-f]{64}", images[0]), images[0]


def test_the_edge_proxies_to_the_web_proxy_and_never_to_the_api():
    """`web` holds the prefix strip and the write limit; reaching `api` directly skips both."""
    proxied = re.findall(r"reverse_proxy\s+(\S+)", _directives(CADDYFILE))
    assert proxied == ["web:8080"]
    assert "api:8000" not in _directives(CADDYFILE)
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in _directives(EDGE)


def test_the_edge_host_and_issuer_have_no_default():
    for variable in ("EXULANICA_PUBLIC_HOST", "EXULANICA_TLS"):
        assert f"${{{variable}:?" in _directives(EDGE), variable
        assert f"{{${variable}}}" in _directives(CADDYFILE), variable


def test_the_stack_states_its_model_spend_ceiling():
    """The API has a default ceiling; a stack anybody outside can reach may not rely on it."""
    for variable in ("EXULANICA_BUDGET_USD", "EXULANICA_BUDGET_MAX_CALLS"):
        assert f"{variable}: ${{{variable}:?" in _directives(JUDGE_COMPOSE), variable


def test_every_long_running_service_restarts_and_keeps_bounded_logs():
    services = _services(EDGE)
    for name in LONG_RUNNING:
        assert "restart: unless-stopped" in services[name], name
        assert "logging:" in services[name], name
    assert "max-size:" in services["edge"] and "max-file:" in services["edge"]


def test_the_one_shot_services_never_restart():
    """A seed that restarted would restore the archive over the world a judge is using."""
    services = _services(EDGE)
    assert "migrate" not in services
    assert "seed" not in services
    assert "restart:" not in _directives(JUDGE_COMPOSE)


def test_writes_are_limited_per_address_and_reads_are_not():
    """Every route that can call a hosted model is a write, so writes are what the limit paces."""
    conf = _directives(JUDGE_WEB)
    api_location = conf.split("location /api/ {", 1)[1].split("}", 1)[0]
    assert "limit_req zone=exulanica_writes" in api_location
    zone = re.search(r"limit_req_zone \$(\w+) zone=exulanica_writes:", conf)
    assert zone is not None
    mapping = conf.split(f"map $request_method ${zone.group(1)} {{", 1)[1].split("}", 1)[0]
    exempt = set(re.findall(r'^\s*([A-Z]+)\s+"";', mapping, re.M))
    assert exempt == {"GET", "HEAD", "OPTIONS"}
    assert re.search(r"^\s*default \$binary_remote_addr;", mapping, re.M)
    assert "limit_req_status 429;" in conf


def test_the_client_address_is_trusted_only_from_private_ranges():
    """The edge sets X-Forwarded-For; a header from anywhere else must not choose the address."""
    trusted = re.findall(r"set_real_ip_from\s+(\S+);", _directives(JUDGE_WEB))
    assert trusted == ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


def test_the_host_never_builds_an_image():
    """What serves is the image verified where it was built, loaded by name."""
    script = _directives(STACK.read_text(encoding="utf-8"))
    ups = [line for line in script.splitlines() if re.search(r"\bcompose up\b", line)]
    assert len(ups) == 2, ups
    for line in ups:
        assert "--no-build" in line, line
    assert "--no-deps" in ups[0], "a later up must not run the seed job again"
    assert "docker build" not in script and "compose build" not in script


needs_shell = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("openssl") is None,
    reason="bash and openssl are absent",
)


def _stack(directory: pathlib.Path, *arguments: str, **env: str) -> subprocess.CompletedProcess:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("EXULANICA_") and key != "NEBIUS_API_KEY"
    }
    environment.update(EXULANICA_DEPLOY_DIR=str(directory / "deploy"), **env)
    return subprocess.run(
        ["bash", str(STACK), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _archive(directory: pathlib.Path) -> pathlib.Path:
    archive = directory / "seed"
    archive.mkdir()
    (archive / "manifest.json").write_text('{"workspace_id": "w"}', encoding="utf-8")
    return archive


INIT_ENV = {
    "EXULANICA_PUBLIC_HOST": "judge.example",
    "EXULANICA_TLS": "internal",
    "EXULANICA_EDGE_ADDRESS": "127.0.0.1",
}


@needs_shell
def test_init_writes_secrets_private_and_leaves_the_budget_to_the_operator(tmp_path):
    archive = _archive(tmp_path)
    result = _stack(
        tmp_path,
        "init",
        EXULANICA_SEED_ARCHIVE=str(archive),
        **{"NEBIUS_API_KEY": CREDENTIAL_PROBE},
        **INIT_ENV,
    )
    assert result.returncode == 0, result.stderr
    deploy = tmp_path / "deploy"
    env_file = deploy / "judge.env"
    assert stat.S_IMODE(deploy.stat().st_mode) == 0o700
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    lines = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    passwords = [
        lines[name]
        for name in (
            "POSTGRES_PASSWORD",
            "EXULANICA_APP_ROLE_PASSWORD",
            "EXULANICA_EXECUTOR_ROLE_PASSWORD",
            "EXULANICA_JUDGE_ROLE_PASSWORD",
        )
    ]
    assert all(re.fullmatch(r"[0-9a-f]{48}", value) for value in passwords)
    assert len(set(passwords)) == 4
    assert lines["EXULANICA_BUDGET_USD"] == ""
    assert lines["EXULANICA_BUDGET_MAX_CALLS"] == ""
    assert lines["EXULANICA_SEED_ARCHIVE"] == str(archive)
    # The model credential is passed through at `up`, never written.
    assert "NEBIUS_API_KEY" not in env_file.read_text(encoding="utf-8")
    assert CREDENTIAL_PROBE not in env_file.read_text(encoding="utf-8")


@needs_shell
def test_init_refuses_to_overwrite_and_refuses_a_directory_that_is_not_an_archive(tmp_path):
    not_an_archive = tmp_path / "empty"
    not_an_archive.mkdir()
    refused = _stack(tmp_path, "init", EXULANICA_SEED_ARCHIVE=str(not_an_archive), **INIT_ENV)
    assert refused.returncode == 2
    assert "not a seed archive" in refused.stderr

    archive = _archive(tmp_path)
    assert _stack(tmp_path, "init", EXULANICA_SEED_ARCHIVE=str(archive), **INIT_ENV).returncode == 0
    first = (tmp_path / "deploy" / "judge.env").read_bytes()
    again = _stack(tmp_path, "init", EXULANICA_SEED_ARCHIVE=str(archive), **INIT_ENV)
    assert again.returncode == 2
    assert (tmp_path / "deploy" / "judge.env").read_bytes() == first


@needs_shell
def test_up_refuses_before_any_token_is_minted(tmp_path):
    archive = _archive(tmp_path)
    assert _stack(tmp_path, "init", EXULANICA_SEED_ARCHIVE=str(archive), **INIT_ENV).returncode == 0
    refused = _stack(tmp_path, "up")
    assert refused.returncode == 2
    assert "no judge token has been minted" in refused.stderr


def test_the_client_bundle_is_built_on_the_build_host_platform():
    """The bundle is architecture-independent; building it under emulation segfaults esbuild.

    A linux/amd64 build on an arm64 host failed with exit 139 in ``pnpm install`` until the Node
    stage ran on the build host's own platform. Only the nginx stage is built for the target.
    """
    stages = re.findall(r"^FROM\s+(.+)$", _directives(JUDGE_WEB), re.M)
    assert stages[0].startswith("--platform=$BUILDPLATFORM node:"), stages[0]
    assert "--platform" not in stages[-1], stages[-1]


#: A relative module specifier in the web workspace's source, including glob patterns.
_RELATIVE_SPECIFIER = re.compile(r"""['"]((?:\.\./)+[^'"\n]+)['"]""")


def _paths_the_bundle_reads_outside_web() -> set[str]:
    """Every repository path a web source file names by a relative specifier that leaves web/.

    Derived from the source rather than listed, so an import added later is checked too. Tests
    are left out: they are not part of the bundle.
    """
    web = (ROOT / "web").resolve()
    found: set[str] = set()
    for source in (ROOT / "web" / "packages").glob("*/src/**/*"):
        if source.suffix not in (".ts", ".tsx") or ".test." in source.name:
            continue
        for match in _RELATIVE_SPECIFIER.finditer(source.read_text(encoding="utf-8")):
            specifier = match.group(1).split("?", 1)[0].split("*", 1)[0]
            target = (source.parent / specifier).resolve()
            if not target.is_relative_to(web) and target.is_relative_to(ROOT.resolve()):
                found.add(target.relative_to(ROOT.resolve()).as_posix().rstrip("/"))
    return found


def test_the_web_image_context_carries_everything_the_bundle_imports_from_outside_web():
    """`vite build` fails on the first import its context lacks; this names every one first."""
    allowed = [
        line[1:].rstrip("/")
        for line in (JUDGE / "web.Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
        if line.startswith("!")
    ]
    needed = _paths_the_bundle_reads_outside_web()
    assert needed, "the scan found no import leaving web/, so it is not reading the sources"
    missing = sorted(
        path
        for path in needed
        if not any(path == entry or path.startswith(entry + "/") for entry in allowed)
    )
    assert missing == [], f"web.Dockerfile.dockerignore does not admit {missing}"
    copied = re.findall(r"^COPY\s+(?!--)(\S+)\s", _directives(JUDGE_WEB), re.M)
    for path in needed:
        if path.startswith("web/"):
            continue
        assert any(path == c or path.startswith(c.rstrip("/") + "/") for c in copied), path


def test_the_edges_own_refusals_take_the_web_proxys_problem_shape():
    """The edge answers a body over its cap and a web proxy it cannot reach itself; those answers
    carry the codes, cap and Retry-After the web proxy's own refusals carry."""
    import json

    from test_installation_deployment import _body_cap, _reviewer_configuration

    conf = _directives(CADDYFILE)
    assert re.search(r"max_size 8MiB$", conf, re.M)
    blocks = dict(re.findall(r"handle_errors (\d{3}) \{(.*?)\n\t\}", CADDYFILE, re.S))
    assert set(blocks) == {"413", "502", "504"}
    expected = {
        "413": ("body_too_large", None),
        "502": ("upstream_unavailable", 5),
        "504": ("upstream_timeout", None),
    }
    for status, block in blocks.items():
        assert "header Content-Type application/json" in block
        answered = re.search(r"respond `(.*)` (\d{3})$", block, re.M)
        assert answered is not None and answered.group(2) == status
        body = json.loads(answered.group(1))
        code, retry_after = expected[status]
        assert body["code"] == code and body["detail"]
        header = re.search(r"header Retry-After (\d+)$", block, re.M)
        assert (int(header.group(1)) if header else None) == retry_after
        assert body.get("retry_after_seconds") == retry_after
    assert json.loads(re.search(r"respond `(.*)` 413", blocks["413"]).group(1))["limit_bytes"] == (
        _body_cap(_reviewer_configuration())
    )
