"""The deployment artefacts, checked at the level a text file can be checked at.

These are text assertions over a Dockerfile, a compose file and a workflow, and a text assertion
is the weaker half of any pair. What makes them worth having is that the failures they catch are
the ones nobody notices until a deployment: an image whose entry point cannot import its own
package, a health check pointing at readiness, a database volume the server does not write to.

No YAML parser is used, deliberately. There is none in the dev dependency closure, and adding one
so a test can read a file it could read as text is a dependency bought for a test.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
CHECK_WORKFLOW = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _directives(text: str) -> str:
    """The file with its comments stripped.

    Every check below is about what an artefact DOES, and a comment is not a directive. The first
    version of this file asserted over raw text and flagged the compose file's own comment
    explaining that a docker volume is not immutable, which is the sentence keeping the claim
    honest rather than making it.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )



def test_the_image_installs_the_package_it_claims_to_run():
    """The most valuable test here, because the failure is silent until the container starts.

    ``uv sync`` without ``--no-install-project`` builds and installs the project wheel. Hatchling
    builds it from the directory named by ``[tool.hatch.build.targets.wheel] packages``, and if
    that directory was never COPYed into the build context the wheel is EMPTY: uv then uninstalls
    the working package and installs the empty one over it, and the image's own entry points
    raise ModuleNotFoundError at start. Nothing about the build fails.
    """
    packages = re.search(r'packages\s*=\s*\["([^"]+)"\]', PYPROJECT)
    assert packages is not None, "pyproject no longer names the wheel's package directory"
    directory = packages.group(1)

    installing = [
        line
        for line in DOCKERFILE.splitlines()
        if "uv sync" in line and "--no-install-project" not in line
    ]
    assert installing, "no stage installs the project, so the image runs nothing"
    assert re.search(rf"^COPY\s+{re.escape(directory)}\s", DOCKERFILE, re.MULTILINE), (
        f"the Dockerfile runs `uv sync` without --no-install-project and never COPYs "
        f"{directory!r}. The wheel it builds is empty and every entry point in the image will "
        "raise ModuleNotFoundError."
    )


def test_the_image_never_installs_a_stale_wheel_of_its_own_package():
    """A surviving uv cache mount reused an older project wheel after COPY changed the sources.

    Observed 2026-09-05 on the reference scene worker image: the container ran code from the
    previous commit. Two guards, either sufficient alone: the sources are part of uv's cache key
    for this project, and the installing sync reinstalls the package regardless.
    """
    keys = re.search(r"^cache-keys\s*=\s*\[(.*)\]", PYPROJECT, re.MULTILINE)
    assert keys is not None, "pyproject declares no uv cache-keys, so source edits do not rebuild"
    assert 'file = "exulanica/**/*.py"' in keys.group(1)
    installing = [
        line
        for line in DOCKERFILE.splitlines()
        if "uv sync" in line and "--no-install-project" not in line
    ]
    assert installing and all("--reinstall-package exulanica" in line for line in installing)


def test_the_command_the_image_runs_can_actually_be_imported():
    """The CMD names a factory by string, so a rename anywhere else leaves it pointing at air."""
    import importlib

    match = re.search(r'"--factory",\s*"([\w.]+):(\w+)"', DOCKERFILE)
    assert match is not None, "the CMD no longer names an ASGI factory"
    module = importlib.import_module(match.group(1))
    assert callable(getattr(module, match.group(2), None)), (
        f"{match.group(1)}:{match.group(2)} is not importable and callable"
    )


def test_the_health_check_is_liveness_and_not_readiness():
    """A container restarted because its database blinked makes an incident worse.

    ``/healthz`` touches no dependency. ``/readyz`` opens a connection and an object store call,
    and is for a human or a load balancer to read, never for a supervisor to kill a process on.
    """
    directives = _directives(DOCKERFILE)
    healthcheck = [line for line in directives.splitlines() if "HEALTHCHECK" in line or (
        "healthz" in line and "CMD" in line)]
    assert healthcheck, "the image has no health check"
    assert "readyz" not in directives, "the health check probes readiness"


def test_the_image_runs_as_a_non_root_user():
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.MULTILINE)
    assert users, "the Dockerfile never drops privileges"
    assert users[-1] != "root", users


def test_the_build_context_is_an_allowlist_that_cannot_carry_a_credential():
    """``credentials.py`` walks up from the working directory looking for a `.env`.

    So a denylist is one forgotten line away from an image that carries a credential. The first
    non-comment line must exclude everything, and `.env` must not be added back.
    """
    lines = [
        line.strip()
        for line in DOCKERIGNORE.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines[0] == "*", f"the build context is not an allowlist: it opens with {lines[0]!r}"
    assert not any(line.lstrip("!").startswith(".env") for line in lines), lines


def test_every_allowlisted_path_exists():
    """An allowlist entry naming a file that moved silently stops being copied."""
    missing = [
        line.strip().lstrip("!")
        for line in DOCKERIGNORE.splitlines()
        if line.strip().startswith("!") and not (ROOT / line.strip().lstrip("!")).exists()
    ]
    assert missing == [], f"the build context allows paths that do not exist: {missing}"


def test_the_server_extra_is_what_the_image_installs():
    """uvicorn stays out of the library's dependencies and an image still has to pick one."""
    assert "server = [" in PYPROJECT
    assert "--extra server" in DOCKERFILE


@pytest.mark.parametrize(
    ("text", "name"), [(COMPOSE, "compose.yaml"), (CHECK_WORKFLOW, "check.yml")]
)
def test_the_database_is_the_documented_target(text: str, name: str):
    """PostgreSQL 18 with pgvector 0.8.6, matched exactly.

    ``tests/pg_harness.py`` refuses a server that cannot run the schema rather than substituting
    for it, which is how R11 was found: 430 tests passed against a substituted `bytea` column and
    the vector path had never executed once. A different tag here means the suite verifies a
    schema the deployment does not run.
    """
    assert "pgvector/pgvector:0.8.6-pg18" in text, name


def test_continuous_integration_turns_a_missing_server_into_a_failure():
    """Locally a machine with no database is normal. In CI it is a suite that proved nothing.

    The 19 postgres-marked tests are the only executable proof of invariant 4.
    """
    assert "EXULANICA_REQUIRE_POSTGRES" in CHECK_WORKFLOW


def test_continuous_integration_runs_the_whole_battery():
    """Every command in the documented battery, so CI and a local run agree about green."""
    for command in ("ruff check", "lint-imports", "uv run pytest", "pnpm check"):
        assert command in CHECK_WORKFLOW, command


def test_the_database_volume_is_where_postgres_18_actually_writes():
    """PostgreSQL 18 moved PGDATA and the image's VOLUME with it.

    Mounting the old ``/var/lib/postgresql/data`` gives a volume the server does not write to,
    and the symptom is a database that is empty after every restart rather than an error.
    """
    directives = _directives(COMPOSE)
    assert "pgdata:/var/lib/postgresql" in directives
    assert "/var/lib/postgresql/data" not in directives


def test_the_composition_refuses_to_start_without_the_token_directory():
    """An API that started with an empty token directory would accept nobody and look healthy."""
    assert "EXULANICA_API_TOKENS: ${EXULANICA_API_TOKENS:?" in COMPOSE


def test_runtime_containers_use_the_rls_role_and_only_migrations_use_the_owner():
    directives = _directives(COMPOSE)
    runtime_urls = [
        line for line in directives.splitlines() if "EXULANICA_DATABASE_URL:" in line
    ]
    assert len(runtime_urls) == 4, runtime_urls
    assert "postgresql://${POSTGRES_USER:-exulanica}:" in runtime_urls[0], runtime_urls
    assert all("postgresql://exulanica_app:" in line for line in runtime_urls[1:]), runtime_urls
    assert "EXULANICA_APP_ROLE_PASSWORD:?" in COMPOSE


def test_the_derivative_worker_is_a_separate_restartable_command():
    assert "derivative-worker:" in COMPOSE
    assert "exulanica-derivative-worker" in COMPOSE
    assert "restart: unless-stopped" in COMPOSE
    assert "EXULANICA_DERIVATIVE_WORKER: \"off\"" in COMPOSE
    assert 'EXULANICA_SYNC_EXTRAS: "--extra reconstruction"' in COMPOSE
    assert "EXULANICA_DEPTH_MODEL: moge" in COMPOSE
    assert "HF_HOME: /var/lib/exulanica/model-cache" in COMPOSE
    assert 'exulanica-derivative-worker = "exulanica.ingest.worker_command:main"' in PYPROJECT
    assert 'exulanica-derivative-worker = "exulanica.ingest.worker_command:main"' in PYPROJECT


def test_the_pose_worker_is_separate_restartable_and_provenance_configured():
    assert "scene-worker:" in COMPOSE
    assert "exulanica-scene-worker" in COMPOSE
    assert "EXULANICA_CODE_REVISION: ${EXULANICA_CODE_REVISION:?" in COMPOSE
    assert "EXULANICA_POSE_RUNTIME_IMAGE: ${EXULANICA_POSE_RUNTIME_IMAGE:?" in COMPOSE
    assert "EXULANICA_CODE_REVISION=" in ENV_EXAMPLE
    assert "EXULANICA_POSE_RUNTIME_IMAGE=" in ENV_EXAMPLE
    assert '--extra server --extra pose' in DOCKERFILE
    assert 'exulanica-scene-worker = "exulanica.ingest.scene_worker_command:main"' in PYPROJECT
    assert 'exulanica-scene-worker = "exulanica.ingest.scene_worker_command:main"' in PYPROJECT


def test_non_http_workers_do_not_inherit_the_api_health_probe():
    assert COMPOSE.count('"import os; os.kill(1, 0)"') == 2


def test_no_deployment_artefact_names_a_target():
    """The deployment target and domain are a human decision and are not made here.

    A hostname or an account id checked in is a decision somebody made by typing rather than by
    deciding, and it is the kind that survives for years.
    """
    for text, name in ((COMPOSE, "compose.yaml"), (DOCKERFILE, "Dockerfile")):
        for pattern in (r"\.amazonaws\.com", r"\.azure\b", r"\.googleapis\.com", r"\bacct-\d"):
            assert not re.search(pattern, text), f"{name} names a deployment target: {pattern}"


def test_no_artefact_claims_a_storage_property_the_platform_does_not_have():
    """Invariant 10. The wording is "append-only by policy" and nothing stronger.

    A docker volume supports no Object Lock, no Legal Hold and no write-once retention, so those
    words would be an overclaim wherever they appeared, including in a comment.
    """
    forbidden = ("immutable", "worm", "tamper-proof", "tamper proof", "write-once")
    for text, name in (
        (COMPOSE, "compose.yaml"),
        (DOCKERFILE, "Dockerfile"),
        (CHECK_WORKFLOW, "check.yml"),
    ):
        lowered = _directives(text).lower()
        found = [word for word in forbidden if word in lowered]
        assert found == [], f"{name} claims {found}, which the platform does not provide"
