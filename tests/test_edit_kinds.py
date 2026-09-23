"""The edit-kind registry against every other statement of the same list.

``exulanica.world.edit_kinds`` is the one place the kinds are written. Each test here compares it
with a place that has to agree and cannot import it: the migrations that restate the log's CHECK
constraints, the live schema those migrations leave behind, the package verifiers' closed lists,
the undo table, the history reader and every ``kind=`` the repository writes. A kind added to one
and not to the others is what these catch; each has been shown to fail on such a drift.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib
import re

import pytest
from exulanica.world import VersionEdit, WorldObjectRepository
from exulanica.world.edit_kinds import (
    EDIT_KINDS,
    LOG_KINDS,
    UNDO,
    EditSubject,
    UnregisteredEditKind,
    edit_kind,
    kinds_of,
)
from exulanica.world_package import authored, environments

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "exulanica" / "migrations"
KIND_CHECK = "world_alternate_version_edit_kind_check"
SUBJECT_CHECK = "world_alternate_edit_names_its_subject"


def _names(listed: str) -> list[str]:
    return re.findall(r"'([a-z_]+)'", listed)


def _named_check(sql: str, name: str) -> str | None:
    """The body of ``add constraint <name> check(...)``, balanced on parentheses, or None."""
    found = re.search(rf"add constraint {name} check\s*\(", sql)
    if found is None:
        return None
    depth, start = 1, found.end()
    for index in range(start, len(sql)):
        depth += {"(": 1, ")": -1}.get(sql[index], 0)
        if depth == 0:
            return sql[start:index]
    raise AssertionError(f"unbalanced check {name}")


def _kind_list(sql: str) -> list[str] | None:
    """The kinds a migration's kind CHECK lists, named or (0042) inline in the create table."""
    named = _named_check(sql, KIND_CHECK)
    if named is not None:
        return _names(named)
    inline = re.search(
        r"create table world_alternate_version_edit \(.*?kind\s+text not null check \(\s*"
        r"kind in \(([^)]*)\)",
        sql,
        re.S,
    )
    return None if inline is None else _names(inline.group(1))


def _migrations() -> list[tuple[str, str]]:
    return sorted(
        (path.stem, path.read_text(encoding="utf-8")) for path in MIGRATIONS.glob("[0-9]*.sql")
    )


def _newest(parse) -> tuple[str, object]:
    stated = [(stem, parse(sql)) for stem, sql in _migrations()]
    stated = [(stem, value) for stem, value in stated if value is not None]
    assert stated, "no migration states this constraint"
    return stated[-1]


def _subject_disjuncts(body: str) -> dict[str, list[str]]:
    """``{column that must be set: kinds}`` from a subject CHECK, requiring the others null."""
    columns = {subject.column for subject in EditSubject}
    disjuncts: dict[str, list[str]] = {}
    for listed, conditions in re.findall(
        r"\(kind in \(([^)]*)\)((?:\s+and\s+\w+ is (?:not )?null)+)", body
    ):
        required = re.findall(r"(\w+) is not null", conditions)
        empty = set(re.findall(r"(\w+) is null", conditions))
        assert len(required) == 1, conditions
        assert empty == columns - set(required), (required, empty)
        disjuncts[required[0]] = _names(listed)
    assert re.search(r"or kind='undo'\s*$", body.strip()), "undo must stay subject-free"
    return disjuncts


# -- the registry itself -------------------------------------------------------------------------


def test_every_name_is_registered_once_and_undo_is_not_a_subject_kind():
    names = [kind.name for kind in EDIT_KINDS]
    assert len(names) == len(set(names))
    assert UNDO not in names
    assert frozenset(names) | {UNDO} == LOG_KINDS
    for subject in EditSubject:
        assert kinds_of(subject), f"{subject} has no kind"


@pytest.mark.parametrize("name", ["set_object_colour", UNDO, "", "Add_Object"])
def test_a_name_the_registry_does_not_hold_is_refused_by_name(name):
    with pytest.raises(UnregisteredEditKind) as refused:
        edit_kind(name)
    assert repr(name) in str(refused.value)


# -- the migrations and the live schema ----------------------------------------------------------


def test_the_newest_kind_check_lists_exactly_the_registered_kinds():
    stem, listed = _newest(_kind_list)
    assert len(listed) == len(set(listed)), f"{stem} lists a kind twice"
    assert set(listed) == LOG_KINDS, f"{stem} and the registry disagree"


def test_the_newest_subject_check_gives_every_kind_its_registered_subject():
    stem, body = _newest(lambda sql: _named_check(sql, SUBJECT_CHECK))
    disjuncts = _subject_disjuncts(body)
    assert set(disjuncts) == {subject.column for subject in EditSubject}, stem
    for subject in EditSubject:
        assert set(disjuncts[subject.column]) == kinds_of(subject), (stem, subject)


def test_each_kind_names_the_first_migration_that_admitted_it():
    firsts: dict[str, str] = {}
    for stem, sql in _migrations():
        for name in _kind_list(sql) or ():
            firsts.setdefault(name, stem)
    for kind in EDIT_KINDS:
        assert firsts.get(kind.name) == kind.admitted_by, kind


def test_the_live_schema_agrees_with_the_registry(repository):
    """The schema every migration leaves behind, read back rather than inferred from files."""
    definitions = {
        row["conname"]: row["definition"]
        for row in repository.connection.execute(
            "select conname,pg_get_constraintdef(oid) as definition from pg_constraint "
            "where conrelid='world_alternate_version_edit'::regclass and contype='c' "
            "and conname = any(%s)",
            ([KIND_CHECK, SUBJECT_CHECK],),
        ).fetchall()
    }
    assert set(re.findall(r"'([a-z_]+)'::text", definitions[KIND_CHECK])) == LOG_KINDS
    subjects = dict(
        (column, set(re.findall(r"'([a-z_]+)'::text", listed)))
        for listed, column in re.findall(
            r"kind = ANY \(ARRAY\[([^\]]*)\]\)\) AND \((\w+) IS NOT NULL\)",
            definitions[SUBJECT_CHECK],
        )
    )
    assert subjects == {subject.column: kinds_of(subject) for subject in EditSubject}
    assert "(kind = 'undo'::text)" in definitions[SUBJECT_CHECK]


# -- the package verifiers -----------------------------------------------------------------------


def test_each_package_verifier_admits_only_registered_kinds_with_their_subjects():
    """The verifiers are closed lists of a frozen extension format, so they may hold fewer."""
    families = {
        authored: {
            EditSubject.OBJECT: authored._OBJECT_EDITS,
            EditSubject.ELEMENT: authored._ELEMENT_EDITS,
        },
        environments: {
            EditSubject.OBJECT: environments._OBJECT_EDITS,
            EditSubject.ELEMENT: environments._ELEMENT_EDITS,
            EditSubject.ENVIRONMENT_INSTANCE: environments._ENVIRONMENT_EDITS,
        },
    }
    for verifier, by_subject in families.items():
        admitted = frozenset().union(*by_subject.values()) | {UNDO}
        assert admitted == verifier._EDIT_KINDS, verifier.__name__
        assert admitted.issubset(LOG_KINDS), verifier.__name__
        for subject, names in by_subject.items():
            assert names.issubset(kinds_of(subject)), (verifier.__name__, subject)


def test_every_kind_no_verifier_admits_is_withheld_by_the_projector():
    """A kind neither extension names must be withheld, or a signed package fails its verifier.

    Read from the projector's withholding queries, which name those kinds today. Moving those
    queries onto the registry changes where this looks, not what it requires.
    """
    projector = (ROOT / "exulanica" / "world_package" / "projector.py").read_text()
    exported = authored._EDIT_KINDS | environments._EDIT_KINDS
    for name in sorted(LOG_KINDS - exported):
        assert f"'{name}'" in projector, f"{name} is neither exported nor withheld"


# -- the repository ------------------------------------------------------------------------------


def test_every_subject_has_an_undo_rule():
    assert set(WorldObjectRepository._UNDO_RULES) == set(EditSubject)
    for method in WorldObjectRepository._UNDO_RULES.values():
        assert callable(getattr(WorldObjectRepository, method)), method


def test_history_and_the_log_writer_name_every_subject_column():
    columns = {subject.column for subject in EditSubject}
    history = {field.name for field in dataclasses.fields(VersionEdit)}
    assert {name for name in history if name.endswith("_id")} - {
        "edit_id",
        "undone_edit_id",
    } == columns
    writer = inspect.signature(WorldObjectRepository._append_edit).parameters
    assert {name for name in writer if name.endswith("_id")} - {
        "edit_id",
        "undone_edit_id",
    } == columns


def _append_edit_calls() -> list[tuple[str, ast.Call]]:
    calls = []
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls.extend(
            (f"{path.relative_to(ROOT)}:{node.lineno}", node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_append_edit"
        )
    return calls


def _is_none(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and value.value is None


def _literal_kinds(value: ast.expr, where: str) -> list[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, ast.IfExp):
        return _literal_kinds(value.body, where) + _literal_kinds(value.orelse, where)
    raise AssertionError(f"{where}: kind= must be a literal the registry can be checked against")


def test_every_kind_the_repository_writes_is_registered_with_the_subject_it_names():
    """Every ``kind=`` passed to the log writer, anywhere in the product, read from the AST."""
    written: set[str] = set()
    for where, call in _append_edit_calls():
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "kind" in keywords, where
        for name in _literal_kinds(keywords["kind"], where):
            assert name in LOG_KINDS, f"{where}: {name} is not registered"
            written.add(name)
            if name == UNDO:
                assert "undone_edit_id" in keywords, where
                continue
            subject = edit_kind(name).subject
            named = {
                each.column
                for each in EditSubject
                if each.column in keywords and not _is_none(keywords[each.column])
            }
            assert named == {subject.column}, f"{where}: {name} writes {named}"
    assert written == LOG_KINDS, f"registered but never written: {LOG_KINDS - written}"
