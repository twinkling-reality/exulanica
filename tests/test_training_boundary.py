"""The training code in ``ml/`` stays outside the product, in both directions that matter.

The product never imports it: the import contract in ``pyproject.toml`` says so over the import
graph, and this reads the source, for a tree where the training package is not installed and so is
absent from that graph. The training code never reaches the product's database, store or API
either, and it never trains on anything but invented, published data; ``ml/tests`` holds that half.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "ml"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_nothing_in_the_product_imports_the_training_code():
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "exulanica").rglob("*.py")
        if any(name.split(".")[0] == "exulanica_training" for name in _imports(path))
    )
    assert offenders == []


def test_the_import_contract_names_the_training_package():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    (contract,) = [
        c for c in contracts if c["name"] == "The product never imports the training code"
    ]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["exulanica"]
    assert contract["forbidden_modules"] == ["exulanica_training"]


def test_the_training_code_reaches_nothing_of_the_product():
    for path in (TRAINING / "exulanica_training").rglob("*.py"):
        for name in _imports(path):
            top = name.split(".")[0]
            assert top != "exulanica", f"{path.relative_to(ROOT)} imports {name}"
            assert top not in {"psycopg", "fastapi", "requests", "httpx", "urllib3"}, (
                f"{path.relative_to(ROOT)} imports {name}; training reads files and nothing else"
            )


def test_the_training_code_has_its_own_environment_and_the_product_s_does_not_carry_it():
    training = tomllib.loads((TRAINING / "pyproject.toml").read_text(encoding="utf-8"))
    assert training["project"]["name"] == "exulanica-training"
    assert any(dependency.startswith("torch") for dependency in training["project"]["dependencies"])
    product = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert product["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["exulanica"]
    assert product["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    for recipe in (
        TRAINING / "container" / "Dockerfile",
        ROOT / "deploy" / "material-bake" / "Dockerfile",
    ):
        text = recipe.read_text(encoding="utf-8")
        assert "*@sha256:*) ;; *) exit 1" in text, f"{recipe} accepts a base that is not pinned"
    run = (TRAINING / "container" / "run.sh").read_text(encoding="utf-8")
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "readonly",
        "EXULANICA_TRAINING_APPROVAL",
    ):
        assert flag in run, flag
