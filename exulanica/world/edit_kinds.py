"""The edit kinds an alternate version's log can hold, stated once, as data.

An edit kind is a name ``world_alternate_version_edit.kind`` stores and the subject that edit
changes: an authored object, an element of the source snapshot, a placed environment instance or
a placed photo point map. Each subject has one id column in the log, and the schema requires an
edit to name exactly that column (``world_alternate_edit_names_its_subject``). ``undo`` is the one
kind with no subject of its own: it names the edit it reverses in ``undone_edit_id`` and repeats
that edit's subject columns.

**Why a registry rather than a list in each place.** Every migration that admits a kind (0042,
0050, 0093, 0096) restates the whole list, and the projector's SQL and both package verifiers name
kinds by hand. A kind added in one place and not another is lost without a sound: a migration that
restates the CHECK from an older list drops a kind a parallel change has just added, and undo, when
it held its own list, sent every kind it did not recognise to the element-override branch. Here the
list is one tuple. Undo dispatches on the subject it names and refuses a kind it does not know, by
name, and ``tests/test_edit_kinds.py`` holds this tuple equal to the newest migration's two CHECK
constraints and to the live schema's, requires every subject to have an undo rule and a history
column, keeps each package verifier's closed list inside it, and requires every ``kind=`` the
repository writes to be registered with the subject it writes. ``tests/test_authored_delta.py``
requires every subject to have a delta section.

What it does not do: migrations stay the storage authority and stay immutable, so a new kind is
still a new migration that restates both CHECK constraints with every kind this tuple lists. The
parity test is what makes a restatement that drops one fail.

Pure: no connection and no SQL, so a verifier can read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from exulanica.world.errors import InvalidObjectState

__all__ = [
    "EDIT_KINDS",
    "LOG_KINDS",
    "UNDO",
    "EditKind",
    "EditSubject",
    "UnregisteredEditKind",
    "edit_kind",
    "kinds_of",
]


class EditSubject(StrEnum):
    """What an edit changes, and so which id column of the log names it."""

    OBJECT = "object"
    ELEMENT = "element"
    ENVIRONMENT_INSTANCE = "environment_instance"
    POINT_MAP_INSTANCE = "point_map_instance"

    @property
    def column(self) -> str:
        """The ``world_alternate_version_edit`` column that holds this subject's id."""
        return f"{self.value}_id"


@dataclass(frozen=True, slots=True)
class EditKind:
    """One kind of edit: its stored name, its subject, and the migration that admitted it."""

    name: str
    subject: EditSubject
    #: The migration whose CHECK first listed this kind, named by its file stem. Provenance, and
    #: something the parity test can hold: that migration's kind CHECK must list the name.
    admitted_by: str


#: Every edit kind except ``undo``, in the order the log's CHECK constraints list them.
EDIT_KINDS: Final[tuple[EditKind, ...]] = (
    EditKind("add_object", EditSubject.OBJECT, "0042_authored_world_objects"),
    EditKind("move_object", EditSubject.OBJECT, "0042_authored_world_objects"),
    EditKind("remove_object", EditSubject.OBJECT, "0042_authored_world_objects"),
    EditKind(
        "set_object_behaviour", EditSubject.OBJECT, "0096_a_placed_object_s_behaviour_can_change"
    ),
    EditKind("suppress_element", EditSubject.ELEMENT, "0042_authored_world_objects"),
    EditKind("transform_element", EditSubject.ELEMENT, "0042_authored_world_objects"),
    EditKind(
        "add_environment",
        EditSubject.ENVIRONMENT_INSTANCE,
        "0050_durable_environment_composition",
    ),
    EditKind(
        "move_environment",
        EditSubject.ENVIRONMENT_INSTANCE,
        "0050_durable_environment_composition",
    ),
    EditKind(
        "remove_environment",
        EditSubject.ENVIRONMENT_INSTANCE,
        "0050_durable_environment_composition",
    ),
    EditKind(
        "add_point_map",
        EditSubject.POINT_MAP_INSTANCE,
        "0093_a_photograph_s_point_map_placed_in_a_world",
    ),
    EditKind(
        "move_point_map",
        EditSubject.POINT_MAP_INSTANCE,
        "0093_a_photograph_s_point_map_placed_in_a_world",
    ),
    EditKind(
        "remove_point_map",
        EditSubject.POINT_MAP_INSTANCE,
        "0093_a_photograph_s_point_map_placed_in_a_world",
    ),
)

#: The kind that reverses another edit. It has no subject of its own and is never itself undone.
UNDO: Final = "undo"

#: Every value ``world_alternate_version_edit.kind`` may hold.
LOG_KINDS: Final[frozenset[str]] = frozenset(kind.name for kind in EDIT_KINDS) | {UNDO}

_BY_NAME: Final[dict[str, EditKind]] = {kind.name: kind for kind in EDIT_KINDS}


class UnregisteredEditKind(InvalidObjectState):
    """The log holds an edit whose kind this registry does not name.

    No rule exists here to act on it, so nothing is written. Guessing a rule is what this refusal
    replaces: undo used to treat every unrecognised kind as an element override, which raised on
    the other subject's document or recorded an undo that changed nothing.
    """


def edit_kind(name: str) -> EditKind:
    """The registered kind of this name. ``undo`` is not one: it has no subject to look up."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise UnregisteredEditKind(f"no rule exists for the edit kind {name!r}") from None


def kinds_of(subject: EditSubject) -> frozenset[str]:
    """The names of every kind that changes this subject."""
    return frozenset(kind.name for kind in EDIT_KINDS if kind.subject is subject)
