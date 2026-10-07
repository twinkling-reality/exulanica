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
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.things.looks import read_look
from exulanica.world.society_decision_contract import decision_contract

from agent_support import AGENTS_ROOT, PACKAGE, agent

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PACKAGES = ("exulanica", "exulanica_pieces")
#: Modules only an outside agent's side may load: the MCP SDK and the agent library itself.
OUTSIDE_ONLY = frozenset({"mcp", "mcp_types", "exulanica_agent"})


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
    packaged = json.loads((PACKAGE / "outside-agents.v1.json").read_text(encoding="utf-8"))
    assert entry["mapping_sha256"] == [sha256_of_canonical(packaged).hex()]
    assert entry["adapter_versions"] == [agent.VERSION]
    assert (entry["run_by"], entry["ai"]) == ("owner", True)
    assert "credential_sha256" not in entry
    # An agent needs one model call a turn; the door bounds a bridge's wait by the role contract.
    assert 1 <= entry["deadline_ms"] <= decision_contract().value("decision_deadline_ms")
    assert 1 <= entry["hold_seconds"] <= 25


def test_an_agents_own_body_is_a_shipped_kind_in_a_free_look():
    packaged = json.loads((PACKAGE / "outside-agents.v1.json").read_text(encoding="utf-8"))
    kinds = shipped_thing_kinds()
    looks = {}
    for path in sorted((ROOT / "assets" / "catalogs" / "things" / "looks").glob("*.json")):
        look = read_look(json.loads(path.read_text(encoding="utf-8")))
        looks[look.sha256] = look
    for visitor in packaged["visitors"]:
        kind = kinds[(visitor["kind"]["key"], visitor["kind"]["version"])]
        assert kind.kind == "visitor"
        for entry in visitor["looks"]:
            look = looks[entry["look"].removeprefix("sha256:")]
            assert look.body_plan == kind.plan
            assert look.document["origin"]["licence"]["spdx"] == entry["licence"]["spdx"]
            assert entry["licence"]["spdx"] == "CC0-1.0"
