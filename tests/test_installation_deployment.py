"""The complete installation's deployment files: what they may fetch, and what they must equal.

Text checks, as the other deployment tests are: the client image fetches no package, refuses a
build that does not state its commit, bundle digest and toolchain, and serves the reviewer image's
nginx configuration exactly, so the two cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "deploy" / "installation" / "client.Dockerfile"


def _instructions(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_client_image_serves_the_reviewer_images_nginx_configuration():
    reviewer = (ROOT / "deploy" / "judge" / "web.Dockerfile").read_text(encoding="utf-8")
    embedded = reviewer.split("COPY <<'CONF' /etc/nginx/conf.d/default.conf\n", 1)[1]
    embedded = embedded.split("\nCONF\n", 1)[0] + "\n"
    ours = (ROOT / "deploy" / "installation" / "client-nginx.conf").read_text(encoding="utf-8")
    assert ours == embedded
    assert "COPY deploy/installation/client-nginx.conf /etc/nginx/conf.d/default.conf" in (
        _instructions(CLIENT)
    )


def test_the_client_image_fetches_nothing_and_states_its_provenance():
    instructions = _instructions(CLIENT)
    text = "\n".join(instructions)
    for fetch in ("pnpm install", "npm install", "npm ci", "yarn", "curl ", "wget ", "apk add"):
        assert fetch not in text, fetch
    assert instructions[0] == "FROM nginx:1.29-alpine"
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
    assert runtime == {"api", "derivative-worker", "scene-worker"} | publishes


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
