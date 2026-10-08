"""Outside agents stay outside the product: one door, no agent-specific core.

An outside AI agent reaches a world only through the door, as a game's adapter does: its library
and MCP facade live in ``bridges/agents``, which the product never imports, never depends on and
never packages. What the deployment pins for the agents' door (the mapping's digest, the admitted
library version, the timing and who runs it) must be true of what ``bridges/agents`` ships, and
the body an agent brings must be a thing kind and a free look the product itself ships. Expected
values come from the product's own canonical digest, catalogs and decision contract.
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from exulanica.canonical import sha256_of_canonical
from exulanica.door.mapping import check_mapping
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.things.looks import read_look
from exulanica.world.society_decision_contract import decision_contract

from agent_support import AGENTS_ROOT, PACKAGE, agent

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PACKAGES = ("exulanica", "exulanica_pieces")
#: Modules only an outside agent's side may load: the MCP SDK and the agent library itself.
OUTSIDE_ONLY = frozenset({"mcp", "mcp_types", "exulanica_agent"})
#: Every library version published, with the mapping file it presents at hello, oldest first. A
#: deployment keeps admitting each, so an agent built on an earlier version keeps its door; a new
#: version adds a row and never removes one.
PUBLISHED = (("0.1.0", "outside-agents.v1.json"), ("0.2.0", "outside-agents.v2.json"))


def _packaged(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def _imported_roots(source: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def offenders(packages: tuple[str, ...] = PRODUCT_PACKAGES, root: Path = ROOT) -> dict[str, list]:
    """Every product module that imports an outside agent's module, by path."""
    found = {}
    for package in packages:
        for source in sorted((root / package).rglob("*.py")):
            hit = _imported_roots(source) & OUTSIDE_ONLY
            if hit:
                found[str(source.relative_to(root))] = sorted(hit)
    return found


def test_no_product_module_imports_the_agents_side():
    assert offenders() == {}


def test_the_guard_catches_a_product_module_that_imports_the_facade(tmp_path):
    (tmp_path / "exulanica").mkdir()
    (tmp_path / "exulanica" / "agents_inside.py").write_text(
        "from exulanica_agent.mcp_server import serve_stdio\n", encoding="utf-8"
    )
    assert offenders(("exulanica",), tmp_path) == {
        "exulanica/agents_inside.py": ["exulanica_agent"]
    }


def test_the_product_neither_depends_on_nor_packages_the_agents_side():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(project["project"]["dependencies"])
    for extra in project["project"].get("optional-dependencies", {}).values():
        requirements += extra
    names = {
        requirement.split(";")[0].split("[")[0].split("=")[0].split(">")[0].split("<")[0]
        for requirement in requirements
    }
    assert not {name.strip().lower() for name in names} & {"mcp", "exulanica-agent"}
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert sorted(wheel) == sorted(PRODUCT_PACKAGES)
    allowed = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("!")
    ]
    assert not [line for line in allowed if line.lstrip("!").startswith("bridges")]


def test_the_example_bridge_entry_pins_what_the_library_ships():
    entry = json.loads((AGENTS_ROOT / "examples" / "bridge-entry.json").read_text())
    assert entry["mapping_sha256"] == [
        sha256_of_canonical(_packaged(name)).hex() for _version, name in PUBLISHED
    ]
    assert entry["adapter_versions"] == [version for version, _name in PUBLISHED]
    # The library is the newest published version and presents its mapping.
    version, name = PUBLISHED[-1]
    assert version == agent.VERSION
    assert agent.mapping() == _packaged(name)
    assert sorted(path.name for path in PACKAGE.glob("outside-agents.v*.json")) == sorted(
        name for _version, name in PUBLISHED
    )
    assert (entry["run_by"], entry["ai"]) == ("owner", True)
    assert "credential_sha256" not in entry
    # An agent needs one model call a turn; the door bounds a bridge's wait by the role contract.
    assert 1 <= entry["deadline_ms"] <= decision_contract().value("decision_deadline_ms")
    assert 1 <= entry["hold_seconds"] <= 25


def test_every_published_mapping_passes_the_doors_own_reader():
    for _version, name in PUBLISHED:
        assert check_mapping(_packaged(name))["key"] == "outside-agents", name


def _shipped_look(entry: dict, looks: dict) -> object:
    """The catalog look a mapping's look entry names: by digest in profile v1, by the thing
    library's key, version and digest in profile v2."""
    named = entry["look"]
    if isinstance(named, str):
        return looks[named.removeprefix("sha256:")]
    look = looks[named["sha256"]]
    assert (look.document["look"], look.document["version"]) == (named["look"], named["version"])
    return look


def test_an_agents_own_body_is_a_shipped_kind_in_a_free_look():
    kinds = shipped_thing_kinds()
    looks = {}
    for path in sorted((ROOT / "assets" / "catalogs" / "things" / "looks").glob("*.json")):
        look = read_look(json.loads(path.read_text(encoding="utf-8")))
        looks[look.sha256] = look
    for _version, name in PUBLISHED:
        for visitor in _packaged(name)["visitors"]:
            kind = kinds[(visitor["kind"]["key"], visitor["kind"]["version"])]
            assert kind.kind == "visitor"
            for entry in visitor["looks"]:
                look = _shipped_look(entry, looks)
                assert look.body_plan == kind.plan
                assert look.document["origin"]["licence"]["spdx"] == entry["licence"]["spdx"]
                assert entry["licence"]["spdx"] == "CC0-1.0"
    # An agent's body arrives in the two-tone mannequin unless it asks for another look.
    [visitor] = _packaged(PUBLISHED[-1][1])["visitors"]
    first = _shipped_look(visitor["looks"][0], looks)
    assert first.document["look"] == "kaykit-mannequin"
    assert first.document["label"] == "two-tone mannequin"
