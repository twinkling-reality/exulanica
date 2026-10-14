"""Undo and redo as one rule over a version's edit log, held to an editor's two stacks.

A redo is an undo that names an undo (:mod:`exulanica.world.edit_kinds`). The rule reads which
edits stand undone, what an undo would reverse and what a redo would reverse from the log alone.
Here it is held, step by step over many seeded sequences of edits, undos and redos, to the model
every editor uses: an undo stack of edits in effect and a redo stack of undos, where a new edit
empties the redo stack and an undo or a redo never does.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

import pytest
from exulanica.world.edit_kinds import UNDO, redo_candidate, undo_candidate, undone_edits


@dataclass(frozen=True)
class Row:
    edit_id: uuid.UUID
    kind: str
    undone_edit_id: uuid.UUID | None = None


class Editor:
    """The model: what an editor's two stacks say, and the log the server would write."""

    def __init__(self) -> None:
        self.log: list[Row] = []
        self.in_effect: list[uuid.UUID] = []
        self.redoable: list[uuid.UUID] = []
        self.target: dict[uuid.UUID, uuid.UUID] = {}

    def edit(self) -> None:
        row = Row(uuid.uuid4(), "move_thing")
        self.log.append(row)
        self.in_effect.append(row.edit_id)
        self.redoable.clear()

    def undo(self) -> bool:
        if not self.in_effect:
            return False
        reversed_edit = self.in_effect.pop()
        row = Row(uuid.uuid4(), UNDO, reversed_edit)
        self.log.append(row)
        self.target[row.edit_id] = reversed_edit
        self.redoable.append(row.edit_id)
        return True

    def redo(self) -> bool:
        if not self.redoable:
            return False
        undo = self.redoable.pop()
        self.log.append(Row(uuid.uuid4(), UNDO, undo))
        self.in_effect.append(self.target[undo])
        return True


def _agrees(editor: Editor) -> None:
    assert undo_candidate(editor.log) == (editor.in_effect[-1] if editor.in_effect else None)
    assert redo_candidate(editor.log) == (editor.redoable[-1] if editor.redoable else None)
    dos = {row.edit_id for row in editor.log if row.kind != UNDO}
    assert undone_edits(editor.log) == dos - set(editor.in_effect)


@pytest.mark.parametrize("seed", range(200))
def test_the_rule_names_what_an_editor_s_two_stacks_name(seed):
    rng = random.Random(seed)
    editor = Editor()
    _agrees(editor)
    for _ in range(40):
        step = rng.choices(("edit", "undo", "redo"), weights=(3, 3, 2))[0]
        getattr(editor, step)()
        _agrees(editor)


def test_redo_steps_forward_through_every_undo_in_turn():
    editor = Editor()
    editor.edit()
    editor.edit()
    first, second = (row.edit_id for row in editor.log)
    editor.undo()
    editor.undo()
    assert undone_edits(editor.log) == {first, second}
    editor.redo()
    assert undone_edits(editor.log) == {second}
    editor.redo()
    assert undone_edits(editor.log) == frozenset()
    assert redo_candidate(editor.log) is None


def test_a_new_edit_ends_redo_and_an_undo_after_a_redo_reverses_the_redone_edit():
    editor = Editor()
    editor.edit()
    redone = editor.log[0].edit_id
    editor.undo()
    editor.redo()
    assert undo_candidate(editor.log) == redone
    editor.undo()
    assert undone_edits(editor.log) == {redone}
    editor.edit()
    assert redo_candidate(editor.log) is None


def test_an_empty_log_has_nothing_to_undo_or_redo():
    assert (undo_candidate([]), redo_candidate([]), undone_edits([])) == (None, None, frozenset())
