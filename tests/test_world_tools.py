"""The tools a world is made by from a person's words: one catalog, read once, each tool real.

Expected values are read from the catalog's file and from the composer modules themselves, not
from the reader under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.composers import composer_module
from exulanica.world.world_tools import CATALOG_PATH, DRAFTERS, tool_for_unsure, world_tools

STATED = {entry["key"]: entry for entry in json.loads(CATALOG_PATH.read_text("utf-8"))["entries"]}


def test_every_tool_drives_a_composer_that_exists_at_the_version_it_states() -> None:
    tools = world_tools()
    assert {tool.key for tool in tools} == set(STATED)
    for tool in tools:
        stated = STATED[tool.key]
        module = composer_module(stated["composer_key"], stated["composer_version"])
        assert tool.composer_key == module.COMPOSER_KEY
        assert tool.composer_version in module.COMPOSER_VERSIONS
        assert tool.drafter in DRAFTERS
        # A chooser is shown these words and nothing else, so each says something of its own.
        assert tool.makes == stated["makes"] and tool.cannot == stated["cannot"]
        assert chr(0x2014) not in tool.makes + tool.cannot
    assert len({tool.makes for tool in tools}) == len(tools)


def test_exactly_one_tool_is_taken_where_the_choice_is_unsure() -> None:
    unsure = [key for key, entry in STATED.items() if entry["unsure"] == 1]
    assert [tool_for_unsure().key] == unsure


@pytest.mark.parametrize(
    "change",
    [
        lambda entries: [entry.update(unsure=0) for entry in entries],
        lambda entries: [entry.update(unsure=1) for entry in entries],
        lambda entries: entries[1].update(composer_key=entries[0]["composer_key"]),
        lambda entries: entries[0].update(drafter="oracle"),
        lambda entries: entries[0].update(makes="one line" + chr(10) + "and another"),
        lambda entries: entries[0].update(composer_key="Site Plan"),
    ],
)
def test_a_catalog_that_breaks_a_tool_s_rules_is_refused(tmp_path: Path, change) -> None:
    document = json.loads(CATALOG_PATH.read_text("utf-8"))
    change(document["entries"])
    path = tmp_path / "world-tool.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogError):
        world_tools(path)
