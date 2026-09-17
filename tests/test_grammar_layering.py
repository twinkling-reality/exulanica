"""ADR-0008, tested for real: generated content cannot name a citation.

``exulanica.grammar`` sits below ``exulanica.evidence`` in the exhaustive import-linter layers,
and a forbidden contract names the six packages a generator must never reach. A contract that
has never failed is a contract nobody has tested, so this file makes it fail on purpose.

Checks, weakest first.

*   The package **exists and has modules**, so nothing below passes over an empty directory.
*   ``lint-imports`` **is green** on the committed tree.
*   The **negative control**: a temporary module that imports each forbidden package makes
    ``lint-imports`` exit non-zero and name the grammar contract as broken.
*   **No negative-control file is left behind**, so a killed run cannot leave a live violation
    in the tree.
*   No module **names a citation type**, even in an annotation or a string. The import contract
    catches imports; this catches the string that is one refactor from becoming one.
*   The **generic layer is generic**: it imports no grammar, and no city word appears in its
    code. A grammar that is not architecture registers and runs with no change to it.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = ROOT / "exulanica" / "grammar"
_GRAMMARS = _PACKAGE / "grammars"

GRAMMAR_CONTRACT = "Generated content cannot name a citation, because it cannot name one"
MATERIALS_CONTRACT = "Material objects cannot name a citation, open a database, or load a model"
PURE_CORE_CONTRACT = "The pure core does not know a database exists"

#: The fixed, greppable prefix of every negative-control module this file writes.
NEGATIVE_CONTROL_PREFIX = "_negative_control_"

#: Names that would mean this package had learned what a citation is. The same list
#: tests/test_reconstruction_is_not_evidence.py holds reconstruction to.
_FORBIDDEN_NAMES = ("EvidenceAddress", "BlobId", "span_digest", "evidence_span", "TimeInterval")

#: Words that belong to the city and must not appear in the code of the generic layer.
_CITY_WORDS = frozenset(
    {
        "block",
        "building",
        "city",
        "curb",
        "district",
        "facade",
        "frontage",
        "kerb",
        "lot",
        "massing",
        "parapet",
        "parcel",
        "premises",
        "roof",
        "storey",
        "street",
        "vitrine",
    }
)


def _sources() -> list[Path]:
    return sorted(_PACKAGE.rglob("*.py"))


def _generic_sources() -> list[Path]:
    return [path for path in _sources() if not path.is_relative_to(_GRAMMARS)]


def _lint_imports() -> subprocess.CompletedProcess[str]:
    executable = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert executable is not None, "lint-imports is not installed next to this interpreter"
    # The cache is disabled so a module written a moment ago is seen, and the terminal is wide
    # so a contract name is never wrapped across two lines of output.
    return subprocess.run(
        [executable, "--no-cache", "--no-logo"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "COLUMNS": "200"},
        check=False,
    )


def _contract_lines(output: str) -> dict[str, str]:
    """``{contract name: "KEPT" | "BROKEN"}`` from the summary lines of a lint-imports run."""
    found = {}
    for line in output.splitlines():
        matched = re.fullmatch(r"(.+) (KEPT|BROKEN)", line.strip())
        if matched:
            found[matched.group(1)] = matched.group(2)
    return found


# ---------------------------------------------------------------------------------------------
# The contract


def test_the_grammar_package_exists_and_has_something_to_check():
    # A check over an empty directory passes while checking nothing, which is the failure mode
    # this repository has already found twice.
    assert _PACKAGE.is_dir(), f"{_PACKAGE} is missing"
    assert len(_sources()) >= 2, _sources()
    assert len(_generic_sources()) >= 2, _generic_sources()


def test_the_layers_contract_is_still_exhaustive_and_places_both_new_slots():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    [layers] = [contract for contract in contracts if contract["type"] == "layers"]
    assert layers["exhaustive"] is True
    order = layers["layers"]
    at = order.index("grammar")
    assert order[at - 2 : at + 3] == [
        "reconstruction | capture",
        "evidence | migrations",
        "grammar",
        # Lettering shares the slot under `grammar` with material objects: a glyph catalog is
        # authored data and the layout rule that places a sign's letters is integer arithmetic on
        # it, so the city grammar's validator may import it while neither it nor materials can
        # reach the other. See docs/lettering.md and the contract's own comment.
        "materials | lettering",
        "canonical",
    ], order
    [grammar] = [contract for contract in contracts if contract["name"] == GRAMMAR_CONTRACT]
    assert grammar["type"] == "forbidden"
    assert grammar["source_modules"] == ["exulanica.grammar"]
    assert sorted(grammar["forbidden_modules"]) == sorted(
        f"exulanica.{name}"
        for name in ("evidence", "store", "db", "ingest", "identity", "selection")
    )
    [materials] = [contract for contract in contracts if contract["name"] == MATERIALS_CONTRACT]
    assert materials["type"] == "forbidden"
    assert materials["source_modules"] == ["exulanica.materials"]
    assert sorted(materials["forbidden_modules"]) == sorted(
        ["psycopg", "torch", "numpy", "cv2", "pycolmap"]
        + [
            f"exulanica.{name}"
            for name in (
                "db",
                "store",
                "evidence",
                "ingest",
                "migrations",
                "identity",
                "selection",
                "reconstruction",
                "capture",
            )
        ]
    )
    assert len([contract for contract in contracts if contract["type"] == "forbidden"]) >= 4


def test_lint_imports_is_green():
    result = _lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr
    lines = _contract_lines(result.stdout)
    assert lines.get(GRAMMAR_CONTRACT) == "KEPT", result.stdout
    assert set(lines.values()) == {"KEPT"}, result.stdout


@pytest.mark.parametrize(
    "imported,contract",
    [
        ("exulanica.evidence", GRAMMAR_CONTRACT),
        ("exulanica.store", GRAMMAR_CONTRACT),
        ("exulanica.db", GRAMMAR_CONTRACT),
        ("exulanica.ingest", GRAMMAR_CONTRACT),
        ("exulanica.identity", GRAMMAR_CONTRACT),
        ("exulanica.selection", GRAMMAR_CONTRACT),
        ("psycopg", PURE_CORE_CONTRACT),
    ],
)
def test_the_negative_control_breaks_the_contract(imported, contract):
    """A violating import in the grammar package fails the build and names the rule it broke."""
    module = _PACKAGE / f"{NEGATIVE_CONTROL_PREFIX}{imported.replace('.', '_')}.py"
    # Exclusive create: a file left by a killed run is a failure to report, not one to overwrite.
    with module.open("x", encoding="utf-8") as handle:
        handle.write(f"import {imported}  # a deliberate violation, deleted by the test\n")
    try:
        result = _lint_imports()
    finally:
        module.unlink()
    assert result.returncode != 0, result.stdout + result.stderr
    assert _contract_lines(result.stdout).get(contract) == "BROKEN", result.stdout


def test_no_negative_control_module_is_left_anywhere():
    """A killed run must not leave a live violation, committed or not."""
    tracked = subprocess.run(
        ["git", "ls-files", "exulanica"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [path for path in tracked if NEGATIVE_CONTROL_PREFIX in path] == []
    left = sorted(ROOT.joinpath("exulanica").rglob(f"{NEGATIVE_CONTROL_PREFIX}*"))
    assert left == [], f"delete these, a killed run left them: {left}"


# ---------------------------------------------------------------------------------------------
# The absence, by name


def test_the_grammar_package_never_names_a_citation_type():
    """Not in an import, an annotation, an attribute or a string."""
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.alias):
                names.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.append(node.value)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.append(node.name)
            elif isinstance(node, ast.arg):
                names.append(node.arg)
            for name in names:
                for forbidden in _FORBIDDEN_NAMES:
                    assert forbidden not in name, (
                        f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')} names "
                        f"{forbidden}. Generated content may not name a citation."
                    )


def test_the_grammar_package_imports_nothing_it_may_not():
    """The fast, self-explaining form of the contract, for when lint-imports is not at hand."""
    allowed = (
        "exulanica.grammar",
        "exulanica.materials",
        "exulanica.canonical",
        "exulanica.errors",
        "exulanica.env",
    )
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if module.split(".")[0] == "exulanica":
                    assert any(
                        module == name or module.startswith(f"{name}.") for name in allowed
                    ), f"{path.name} imports {module}"


# ---------------------------------------------------------------------------------------------
# The generic layer is generic


def _words(identifier: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier)
    return {word.lower() for word in re.split(r"[^A-Za-z0-9]+|_", spaced) if word}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def test_the_generic_layer_imports_no_grammar():
    for path in _generic_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("exulanica.grammar.grammars"), path
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("exulanica.grammar.grammars"), path


def test_no_city_concept_appears_in_the_code_of_the_generic_layer():
    """No street, parcel or facade in a shared class, enum, type, name or string.

    Prose is exempt: a docstring may say that the city is one grammar among others. Code is
    not, because code is what a second grammar would inherit.
    """
    for path in _generic_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.Name):
                text = node.id
            elif isinstance(node, ast.Attribute):
                text = node.attr
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                text = node.name
            elif isinstance(node, ast.arg):
                text = node.arg
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                text = node.value
            if text is None:
                continue
            leaked = _words(text) & _CITY_WORDS
            assert not leaked, (
                f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')} names {sorted(leaked)} "
                "in the generic layer"
            )


def test_the_box_grammar_does_not_lean_on_the_city():
    tree = ast.parse((_GRAMMARS / "box.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "city" not in (node.module or ""), node.module


def test_a_grammar_that_is_not_architecture_is_added_by_registration_alone(tmp_path):
    """A tree grammar, written here, with the generic contract untouched."""
    from exulanica.grammar import (
        CascadeBinding,
        Grammar,
        GrammarRegistry,
        StageContext,
        StageEmission,
        generate,
    )
    from exulanica.grammar.records import require_integer, require_record

    descriptor = tmp_path / "tree.v1.json"
    descriptor.write_text(
        '{"schema_version": 1, "grammar_id": "tree", "grammar_version": 1,'
        ' "subject_kind": "tree", "admissible_uses": ["render_batch"],'
        ' "cascade_levels": ["grove", "tree"],'
        ' "parameters": ['
        '  {"name": "habit", "kind": "choice", "options": ["upright", "spreading"],'
        '   "when_unset": "draw"},'
        '  {"name": "branch_count", "kind": "integer", "minimum": 1, "maximum": 9,'
        '   "when_unset": "required"}]}',
        encoding="utf-8",
    )

    @dataclass(frozen=True, slots=True)
    class BranchRecord:
        RECORD_KIND: ClassVar[str] = "tree.branch"
        RECORD_VERSION: ClassVar[int] = 1
        branch_ordinal: int
        length_mm: int

    def validate_branch(candidate: object) -> None:
        record = require_record(candidate, BranchRecord)
        require_integer("length_mm", record.length_mm, minimum=1)

    @dataclass(frozen=True, slots=True)
    class BranchStage:
        stage_id: str = "branches"
        stage_version: int = 1

        def emit(self, context: StageContext) -> StageEmission:
            cursor = context.cursor("length")
            count = context.parameters["branch_count"]
            records = tuple(
                BranchRecord(branch_ordinal=index, length_mm=cursor.integer(100, 900))
                for index in range(count)  # type: ignore[arg-type]
            )
            return StageEmission("branches", 1, "emitted", "", records)

        def validate(self, record: object) -> None:
            validate_branch(record)

    registry = GrammarRegistry()
    registry.register(Grammar.from_descriptor(descriptor, stages=(BranchStage(),)))
    tree = registry.get("tree", 1)
    generation = generate(
        tree,
        seed="ab" * 32,
        subject_identity="6c7a4f0e-2b1d-5e8f-9a3c-4d5e6f708192",
        bindings=(CascadeBinding.of("grove", {"branch_count": 3}),),
    )
    [emission] = generation.emissions
    assert len(emission.records) == 3
    assert generation.receipt.declared_semantics.plane == "invented"
    assert dict(generation.receipt.parameters.sources) == {"branch_count": "grove", "habit": "draw"}
    assert all(100 <= record.length_mm <= 900 for record in emission.records)
    assert [record.branch_ordinal for record in emission.records] == [0, 1, 2]
