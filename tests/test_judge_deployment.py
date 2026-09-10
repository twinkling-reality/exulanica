"""The judge deployment artefacts, checked at the level a text file can be checked at.

The same approach and the same limits as ``tests/test_deployment.py``: text assertions over a
compose file and a Dockerfile, which is the weaker half of any pair. What makes them worth having
is the failures they catch, and here there are three that would each produce a judge stack that
looks fine and is not.

*   **The API connecting as** ``exulanica_app``. The judge deployment's whole boundary is that its
    API holds no privilege to write a source row or a deletion marker. The bearer token carries no
    permissions at all, so if that connection string names the ordinary runtime role there is
    nothing anywhere enforcing the sentence this deployment is built to make true.
*   **A worker in the stack.** A judge stack that can queue reconstruction is a judge stack that
    can spend money and change the world under the next visitor.
*   **The proxy losing its trailing slash.** ``proxy_pass http://api:8000`` without it turns every
    call into ``/api/graph`` at the API and 404s the entire client, which reads as a broken
    deployment rather than as one character.

No YAML parser, for the reason the neighbouring file gives: there is none in the dev dependency
closure and adding one so a test can read a file it can read as text is a dependency bought for a
test.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

JUDGE_COMPOSE = (ROOT / "deploy" / "judge" / "compose.yaml").read_text(encoding="utf-8")
JUDGE_WEB = (ROOT / "deploy" / "judge" / "web.Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _directives(text: str) -> str:
    """The file with its comments stripped. A comment is not a directive."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_api_connects_as_the_judge_role_and_never_as_the_runtime_role():
    """The one assertion this file exists for.

    ``exulanica_judge`` holds SELECT everywhere, INSERT and UPDATE on the thirteen tables a judge
    writes, and DELETE on nothing. ``exulanica_app`` may write sources. Nothing above the database
    can tell the two apart, because a token grants no permissions.
    """
    directives = _directives(JUDGE_COMPOSE)
    runtime_urls = [line for line in directives.splitlines() if "EXULANICA_DATABASE_URL:" in line]
    assert len(runtime_urls) == 3, runtime_urls
    owner, seeder, api = runtime_urls
    assert "postgresql://${POSTGRES_USER:-exulanica}:" in owner, owner
    assert "postgresql://${POSTGRES_USER:-exulanica}:" in seeder, seeder
    assert "postgresql://exulanica_judge:" in api, api
    assert "postgresql://exulanica_app:" not in directives


def test_the_selection_executor_keeps_its_own_read_only_role():
    """A plan derived from model output runs as ``exulanica_ro`` here as everywhere else."""
    assert "EXULANICA_READONLY_DATABASE_URL: postgresql://exulanica_ro:" in _directives(
        JUDGE_COMPOSE
    )


def test_the_judge_stack_runs_no_worker():
    """Reconstruction never runs in the live path, and the seed is already reconstructed."""
    directives = _directives(JUDGE_COMPOSE)
    assert "derivative-worker" not in directives
    assert "scene-worker" not in directives
    assert "exulanica-derivative-worker" not in directives
    assert "exulanica-scene-worker" not in directives
    assert 'EXULANICA_DERIVATIVE_WORKER: "off"' in directives


def test_the_stack_refuses_to_start_without_its_secrets():
    """Each one has no default, because a default would be a credential in a repository."""
    for variable in (
        "POSTGRES_PASSWORD",
        "EXULANICA_APP_ROLE_PASSWORD",
        "EXULANICA_EXECUTOR_ROLE_PASSWORD",
        "EXULANICA_JUDGE_ROLE_PASSWORD",
        "EXULANICA_API_TOKENS",
        "EXULANICA_SEED_ARCHIVE",
    ):
        assert f"${{{variable}:?" in JUDGE_COMPOSE, variable


def test_the_api_starts_only_after_the_seed_verified_what_it_loaded():
    """An API that is up is an API whose data was verified rather than merely written."""
    assert "exulanica-seed role && exulanica-seed restore --archive /seed" in JUDGE_COMPOSE
    assert JUDGE_COMPOSE.count("condition: service_completed_successfully") == 2
    assert 'exulanica-seed = "exulanica.orchestration.judge_seed_cli:main"' in PYPROJECT


def test_the_seed_archive_is_mounted_read_only():
    """The seeding job reads the archive and never writes back to it."""
    assert ":/seed:ro" in _directives(JUDGE_COMPOSE)


def test_the_database_is_the_same_target_the_suite_verifies():
    """A judge stack on a different PostgreSQL proves less about the product than it looks."""
    tag = "pgvector/pgvector:0.8.6-pg18"
    assert tag in _directives(JUDGE_COMPOSE)
    assert tag in _directives(COMPOSE)


def test_the_database_volume_is_where_postgres_18_actually_writes():
    directives = _directives(JUDGE_COMPOSE)
    assert "pgdata:/var/lib/postgresql" in directives
    assert "/var/lib/postgresql/data" not in directives


def _published_ports(text: str) -> list[str]:
    """Every entry under a ``ports:`` key, and nothing under ``expose:`` or a command array.

    Written out rather than matched with one regex over the whole file, because ``- "8000"``
    under ``expose:`` looks identical to a published port and means the opposite.
    """
    found: list[str] = []
    inside = False
    for line in _directives(text).splitlines():
        stripped = line.strip()
        if stripped == "ports:":
            inside = True
            continue
        if inside:
            if stripped.startswith("- "):
                found.append(stripped[2:].strip().strip('"'))
                continue
            inside = False
    return found


def test_only_the_browser_client_publishes_a_port_and_only_on_the_loopback():
    """A LAN address over plain http is not a secure context, and the client needs one.

    ``geometry-api.ts`` refuses every region when ``crypto.subtle`` is absent. A judge reaching a
    stack published on 0.0.0.0 over http would see the world without its geometry and read that
    as a broken reconstruction rather than as a missing certificate.
    """
    assert _published_ports(JUDGE_COMPOSE) == ["127.0.0.1:${EXULANICA_JUDGE_PORT:-8080}:8080"]
    # The API is reachable only from inside the compose network.
    assert "expose:" in _directives(JUDGE_COMPOSE)


def test_the_proxy_strips_the_api_prefix():
    """With the trailing slash, ``/api/graph`` reaches the API as ``/graph``. Without it, 404."""
    assert "proxy_pass http://api:8000/;" in JUDGE_WEB


def test_the_client_bundle_carries_no_baked_token():
    """A build-time token is a string literal anybody who can fetch the JavaScript can read."""
    assert "VITE_EXULANICA_TOKEN" not in _directives(JUDGE_WEB)


def test_the_web_build_context_carries_the_shared_typescript_bases():
    """Every package's tsconfig extends ``../../tsconfig.base.json`` and Vite reads it.

    Without them the build fails with "failed to resolve extends" after transforming zero
    modules, which is a build that succeeds at everything except producing the application.
    """
    assert "COPY tsconfig.json tsconfig.base.json ./" in JUDGE_WEB


def test_no_judge_artefact_names_a_deployment_target():
    """The same rule as ``tests/test_deployment.py``: a hostname checked in is a decision typed."""
    for text, name in ((JUDGE_COMPOSE, "deploy/judge/compose.yaml"), (JUDGE_WEB, "web.Dockerfile")):
        for pattern in (r"\.amazonaws\.com", r"\.azure\b", r"\.googleapis\.com", r"\bacct-\d"):
            assert not re.search(pattern, text), f"{name} names a deployment target: {pattern}"


#: Invariant 10's vocabulary, as whole words. Substring matching would flag `bookworm`, which is
#: a Debian release, and the point of the invariant is claims rather than spellings.
_STORAGE_OVERCLAIMS = (r"\bimmutable\b", r"\bworm\b", r"tamper[- ]proof", r"write-once")


def test_no_judge_artefact_claims_a_storage_property_the_platform_does_not_have():
    """Invariant 10. A docker volume is append-only by policy and nothing stronger.

    ``Cache-Control: immutable`` is excluded, and it is worth saying why rather than quietly
    weakening the check: it is an HTTP response directive about a hashed URL, not a claim about
    what the storage guarantees. The invariant is about the second.
    """
    for text, name in (
        (JUDGE_COMPOSE, "deploy/judge/compose.yaml"),
        (JUDGE_WEB, "deploy/judge/web.Dockerfile"),
    ):
        lowered = "\n".join(
            line for line in _directives(text).lower().splitlines() if "cache-control" not in line
        )
        found = [word for word in _STORAGE_OVERCLAIMS if re.search(word, lowered)]
        assert found == [], f"{name} claims {found}, which the platform does not provide"
