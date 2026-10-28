"""The integrations catalog beside the manifest: what a person's worlds can connect to.

Every provider the manifest bills, the provider on this computer and the web source have an entry,
so the Integrations page names none of them itself. Each entry's kind says where its state is read,
its words are the catalog's own, and a file wrong in any of the ways the loader checks is refused by
name. ``GET /integrations`` answers the file's own content to any session, a guest's included. No
database: the route takes no connection, and a token resolves without one.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import GUEST_PERMISSIONS
from exulanica.api.services import Services
from exulanica.db.session import Database
from exulanica.models.integrations import (
    INTEGRATIONS_PATH,
    KINDS,
    LINE_MAXIMUM,
    REPOSITORY,
    IntegrationsError,
    integrations,
    read_integrations,
)
from exulanica.models.manifest import load_manifest
from exulanica.references.catalogs import web_source
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from tests_support_api import EVERY_PERMISSION

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = json.loads(INTEGRATIONS_PATH.read_text(encoding="utf-8"))
EM_DASH = chr(0x2014)
GUEST = "integrations-guest-token-long-enough-to-be-accepted"
OWNER = "integrations-owner-token-long-enough-to-be-accepted"
SETUP = {"document": "docs/development-setup.md", "heading": "Running your own install"}


def _entries(document: dict) -> dict[str, dict]:
    return {entry["key"]: entry for entry in document["entries"]}


def test_the_shipped_file_loads_with_every_guide_held_to_a_heading_of_this_checkout():
    assert REPOSITORY == ROOT and (ROOT / "docs").is_dir(), "the guides were read from here"
    assert integrations() == DOCUMENT
    assert read_integrations(copy.deepcopy(DOCUMENT), ROOT) == DOCUMENT
    # Each call answers a copy: a caller changing it changes nothing the next one reads.
    integrations()["entries"].clear()
    assert integrations() == DOCUMENT


def test_every_provider_the_manifest_bills_the_one_on_this_computer_and_the_web_source_has_one():
    manifest = load_manifest()
    billed = set(manifest.billing_providers())
    assert billed, "the positive control: the manifest bills a provider"
    entries = _entries(DOCUMENT)
    providers = {key for key, entry in entries.items() if entry["kind"] == "provider"}
    assert billed | {"ollama_local"} <= providers
    # A provider runs on this computer exactly where the manifest bills it nothing.
    assert {key: entries[key]["local"] for key in providers} == {
        key: key not in billed for key in providers
    }
    assert providers <= set(manifest.providers)
    source = web_source()
    assert source is not None, "the positive control: the reference catalog holds a web source"
    assert entries[source.key]["kind"] == "web"


def test_each_entry_is_of_its_kind_in_the_catalog_s_own_words():
    web = web_source().key
    assert {entry["kind"] for entry in DOCUMENT["entries"]} == KINDS
    assert [
        (entry["key"], entry["kind"], entry.get("local"), entry.get("ai"))
        for entry in DOCUMENT["entries"]
    ] == [
        ("nebius_token_factory", "provider", False, None),
        ("ollama_local", "provider", True, None),
        (web, "web", None, None),
        ("github", "github", None, None),
        ("door", "door", None, None),
        ("door.agent", "grant", None, True),
        ("door.game", "grant", None, False),
    ]
    entries = _entries(DOCUMENT)
    assert {key: (entry["name"], entry["line"]) for key, entry in entries.items()} == {
        "nebius_token_factory": ("Nebius Token Factory", "Open models answer for your people."),
        "ollama_local": ("Ollama", "Runs open models on this computer."),
        web: ("Tavily", "Searches the web before something is made."),
        "github": ("GitHub", f"Keeps a world{chr(0x2019)}s versions in a repository."),
        "door": ("Agents and games", "Act for people you grant them, through MCP."),
        "door.agent": ("AI agents", "Decide for people you grant them, through MCP."),
        "door.game": ("Games", "Play people you grant them, or bring their own."),
    }
    assert {key: entry.get("guide") for key, entry in entries.items()} == {
        "nebius_token_factory": SETUP,
        "ollama_local": SETUP,
        web: {"document": "docs/reference-notes-contract.md", "heading": "7. Configuration"},
        "github": {"document": "docs/world-memory-package.md", "heading": "Following a world"},
        "door": {
            "document": "docs/capabilities/outside-agents.md",
            "heading": "On your own install",
        },
        "door.agent": None,
        "door.game": None,
    }
    # Agents are drawn as the door is, and a game by its own mark.
    assert entries["door.agent"]["mark"] == entries["door"]["mark"] != entries["door.game"]["mark"]


def _repeated(document: dict) -> None:
    document["entries"].append(copy.deepcopy(_entries(document)["door.game"]))


def _unheaded(document: dict) -> None:
    _entries(document)["github"]["guide"]["heading"] = "Kept on GitHub"


def _dashed(document: dict) -> None:
    _entries(document)["door"]["line"] = f"Agents and games {EM_DASH} through MCP."


def _polygon(document: dict) -> None:
    _entries(document)["ollama_local"]["mark"].append({"polygon": {"points": "4 4 20 20"}})


def _handler(document: dict) -> None:
    _entries(document)["door.game"]["mark"][0]["path"]["onload"] = "alert(1)"


def _long(document: dict) -> None:
    _entries(document)["github"]["line"] = "a" * (LINE_MAXIMUM + 1)


def _unkinded(document: dict) -> None:
    _entries(document)["github"]["kind"] = "repository"


def _unflagged(document: dict) -> None:
    del _entries(document)["door.agent"]["ai"]


def _misplaced(document: dict) -> None:
    _entries(document)["ollama_local"]["local"] = False


@pytest.mark.parametrize(
    ("change", "why"),
    [
        pytest.param(_repeated, r"^door\.game: a second entry with this key$", id="duplicate-key"),
        pytest.param(
            _unheaded,
            r"^github: 'Kept on GitHub' is not a heading of docs/world-memory-package\.md$",
            id="missing-guide-heading",
        ),
        pytest.param(_dashed, r"^door: line holds an em dash$", id="em-dash"),
        pytest.param(
            _polygon,
            r"^ollama_local: a mark draws 'polygon', not a rect, circle or path$",
            id="bad-mark-shape",
        ),
        pytest.param(
            _handler, r"^door\.game: a path states some of \['d'\] only$", id="mark-handler"
        ),
        pytest.param(_long, rf"^github: line is one line of {LINE_MAXIMUM} ", id="long-line"),
        pytest.param(_unkinded, r"^github: kind 'repository' is not one of ", id="unknown-kind"),
        pytest.param(_unflagged, r"^door\.agent: a grant states ", id="grant-without-ai"),
        pytest.param(
            _misplaced,
            r"^ollama_local: local is false, but the manifest bills it nothing$",
            id="local-against-the-manifest",
        ),
    ],
)
def test_a_file_wrong_in_a_way_the_loader_checks_is_refused_by_name(
    tmp_path: Path, change: Callable[[dict], None], why: str
):
    unchanged = tmp_path / "unchanged.json"
    unchanged.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    assert integrations(unchanged) == DOCUMENT, "the positive control: the file as shipped reads"
    document = copy.deepcopy(DOCUMENT)
    change(document)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(IntegrationsError, match=why):
        integrations(changed)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # Never connected: the route takes no connection, and a token resolves without one.
    unused = Database(url="postgresql://unused.invalid/none")
    # A guest's browser session holds GUEST_PERMISSIONS; a token holding exactly those reaches
    # what the guest's session reaches, since the floor decides from what is held.
    grants = {
        GUEST: sorted(str(permission) for permission in GUEST_PERMISSIONS),
        OWNER: EVERY_PERMISSION,
    }
    tokens = load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    token: {
                        "workspace_id": str(uuid.uuid4()),
                        "actor": str(uuid.uuid4()),
                        "permissions": permissions,
                    }
                    for token, permissions in grants.items()
                }
            )
        }
    )
    services = Services(
        database=unused,
        readonly_database=unused,
        store=LocalContentAddressedStore(tmp_path / "store"),
        tokens=tokens,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    # Not entered as a context manager: the lifespan checks a database this route never needs.
    return TestClient(create_app(services, verify=False))


def test_the_route_answers_the_file_s_own_content_to_any_session(client: TestClient):
    assert client.get("/integrations").status_code == 401
    for token in (GUEST, OWNER):
        response = client.get("/integrations", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        assert response.json() == DOCUMENT
        assert response.headers["cache-control"] == "private, no-store"
