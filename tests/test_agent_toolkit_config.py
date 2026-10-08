"""The toolkit example's configuration as ``bridges/agents/checks/nat_run.py`` writes it: another
mind, name and maker reach the model the toolkit calls, the declaration the facade sends and the
name the instructions use; the example's own values stay when none is chosen."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from exulanica.door.protocol import DECLARED_CHARACTERS_MAXIMUM, declared_fault

from agent_support import AGENTS_ROOT

CHECKS = AGENTS_ROOT / "checks"
if str(CHECKS) not in sys.path:
    sys.path.insert(0, str(CHECKS))
# The checks are scripts beside the library, loaded by their folder as the library is.
nat_check = importlib.import_module("nat_check")

EXAMPLE = yaml.safe_load(nat_check.EXAMPLE.read_text(encoding="utf-8"))
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"


def _written(folder: Path, **chosen: str) -> dict[str, Any]:
    path = nat_check._config("python3", None, folder, **chosen)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _env(config: dict[str, Any]) -> dict[str, str]:
    return config["function_groups"]["world"]["server"]["env"]


def test_a_chosen_mind_name_and_maker_reach_the_model_the_declaration_and_the_instructions(
    tmp_path: Path,
) -> None:
    config = _written(tmp_path, mind=NANO, name="Wanderer", maker="Exulanica demo")
    assert config["llms"]["nemotron"]["model_name"] == NANO
    env = _env(config)
    assert (env["EXULANICA_AGENT_MIND"], env["EXULANICA_AGENT_NAME"]) == (NANO, "Wanderer")
    assert env["EXULANICA_AGENT_MAKER"] == "Exulanica demo"
    instructions = config["workflow"]["additional_instructions"]
    assert "named Wanderer." in instructions
    assert _env(EXAMPLE)["EXULANICA_AGENT_NAME"] not in instructions


def test_the_examples_own_values_stay_when_none_is_chosen(tmp_path: Path) -> None:
    config = _written(tmp_path)
    assert (config["llms"], config["workflow"]) == (EXAMPLE["llms"], EXAMPLE["workflow"])
    for key in ("EXULANICA_AGENT_NAME", "EXULANICA_AGENT_MAKER", "EXULANICA_AGENT_MIND"):
        assert _env(config)[key] == _env(EXAMPLE)[key]


@pytest.mark.parametrize("name", ["& Co (a test)", "- O'Brien, + Sons", "Ünïcödé 名前"])
def test_a_name_with_marks_the_door_allows_reads_back_as_written(tmp_path: Path, name: str) -> None:
    assert declared_fault(name, maximum=DECLARED_CHARACTERS_MAXIMUM) is None
    env = _env(_written(tmp_path, name=name, maker=name))
    assert (env["EXULANICA_AGENT_NAME"], env["EXULANICA_AGENT_MAKER"]) == (name, name)


def test_a_name_that_would_add_a_line_to_the_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _written(tmp_path, name="Wanderer\n        EXULANICA_URL: elsewhere")
    assert not (tmp_path / "agent.yml").exists()
