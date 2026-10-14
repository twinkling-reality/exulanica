"""The guard list names tests that exist, once each, and ``--guards`` keeps exactly those."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import conftest
import guard_selection
from guard_selection import GUARDS, guard_files, is_guard

TESTS = Path(__file__).resolve().parent


def _module_functions(file_name: str) -> set[str]:
    tree = ast.parse((TESTS / file_name).read_text())
    return {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


@pytest.mark.parametrize("entry", sorted(GUARDS))
def test_every_guard_names_a_test_that_exists(entry):
    file_name, _, function = entry.partition("::")
    assert file_name.startswith("test_") and file_name.endswith(".py"), entry
    assert (TESTS / file_name).is_file(), f"{entry}: no such test file"
    if function:
        assert function.startswith("test_"), entry
        assert function in _module_functions(file_name), f"{entry}: no such test function"


def test_a_file_is_listed_whole_or_by_function_never_both():
    whole = {entry for entry in GUARDS if "::" not in entry}
    by_function = {entry.partition("::")[0] for entry in GUARDS if "::" in entry}
    assert not whole & by_function


def test_the_list_is_in_order_and_says_in_one_line_what_each_guard_holds():
    assert list(GUARDS) == sorted(GUARDS)
    for entry, holds in GUARDS.items():
        assert holds.strip() and "\n" not in holds, entry


def test_a_listed_file_keeps_every_test_and_a_listed_function_only_itself(monkeypatch):
    monkeypatch.setattr(
        guard_selection,
        "GUARDS",
        {"test_whole.py": "every test", "test_mixed.py::test_listed": "one test"},
    )
    assert is_guard("test_whole.py", "test_anything")
    assert is_guard("test_mixed.py", "test_listed")
    assert not is_guard("test_mixed.py", "test_unlisted")
    assert not is_guard("test_elsewhere.py", "test_listed")
    assert guard_files() == {"test_whole.py", "test_mixed.py"}


def _config(*, guards: bool, deselected: list | None = None) -> SimpleNamespace:
    """A configuration with only what the two hooks read: the options and the deselect hook."""
    options = {"guards": guards, "part": None}
    sink = [] if deselected is None else deselected
    return SimpleNamespace(
        getoption=options.__getitem__,
        hook=SimpleNamespace(pytest_deselected=lambda items: sink.extend(items)),
    )


def test_under_guards_a_test_file_holding_no_guard_is_never_imported():
    config = _config(guards=True)
    listed = sorted(guard_files())[0]
    assert conftest.pytest_ignore_collect(TESTS / "test_not_a_guard.py", config) is True
    assert conftest.pytest_ignore_collect(TESTS / listed, config) is None
    assert conftest.pytest_ignore_collect(TESTS / "route_probes.py", config) is None
    assert conftest.pytest_ignore_collect(TESTS, config) is None
    assert (
        conftest.pytest_ignore_collect(TESTS / "test_not_a_guard.py", _config(guards=False)) is None
    )


def test_under_guards_only_the_listed_functions_of_a_file_are_kept(monkeypatch):
    monkeypatch.setattr(guard_selection, "GUARDS", {"test_mixed.py::test_listed": "one test"})

    def item(function: str, parameters: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            path=TESTS / "test_mixed.py",
            name=function + parameters,
            originalname=function,
            fixturenames=(),
        )

    items = [item("test_listed", "[GET-/a]"), item("test_unlisted"), item("test_listed")]
    deselected: list = []
    conftest.pytest_collection_modifyitems(_config(guards=True, deselected=deselected), items)
    assert [each.name for each in items] == ["test_listed[GET-/a]", "test_listed"]
    assert [each.name for each in deselected] == ["test_unlisted"]
