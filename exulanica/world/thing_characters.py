"""Who a placed being is, as its world's owner writes it: ``exulanica.thing-character/v1``.

A character is fiction a world's owner writes for whoever decides for a being they placed: a name,
a few words about it, or both. It is written beside the placed thing, never in it (migration 0213),
as a look is chosen beside it: what a being is and does stays its kind's and its society's. It
reaches a society only through the society's input, and only a society whose first input records
the character module (``exulanica-ability/character/v1``), which shows it to that being's decider
alone, quoted, as fiction and not instructions (:mod:`exulanica.world.society_decision_contract`).
Nothing derives one from a photograph, a kind's description or a person.

*   :func:`screened_character` holds what an owner wrote to the character's shape, in Unicode
    normal form C, each part to the line rule within the module's bounds, and refuses any name the
    account holder saved, of any kind, since no right releases a saved name to whoever decides for
    a being;
*   :func:`write_character` appends one record for a placed being of a version, over the newest
    record the writer read (``base_revision``), or refuses by name;
*   :func:`character_of` reads the newest record for one placed thing, :func:`newest_records`
    the newest record of every placed thing of a version, a clearing one included, and
    :func:`newest_characters` the character of every placed being of a version that has one, as
    a society's next input carries them;
*   :func:`version_characters` answers ``exulanica.thing-characters/v1``: every placed thing's
    newest record in one read, what a reader following a world takes in place of a card a being.

Records are appended and never changed; a record holding neither part clears the character.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg

from exulanica.abilities.registry import built_module
from exulanica.epistemics.saved_names import SavedName, recognised_spans
from exulanica.world.errors import InvalidThingPlacement, UnknownWorldResource
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world.society_thing_inputs import CHARACTER_MODULE, check_character

__all__ = [
    "CHARACTERS_PROFILE",
    "CHARACTER_PROFILE",
    "THING_CHARACTER_CODES",
    "CharacterRecord",
    "ThingCharacterRefused",
    "character_of",
    "newest_characters",
    "newest_records",
    "screened_character",
    "society_reads_characters",
    "version_characters",
    "write_character",
]

CHARACTER_PROFILE: Final = "exulanica.thing-character/v1"
#: Every placed thing's newest record of one version, in one read.
CHARACTERS_PROFILE: Final = "exulanica.thing-characters/v1"
#: Why a character is not written, each answered by name.
THING_CHARACTER_CODES: Final = (
    "character_out_of_bounds",
    "character_carries_a_saved_name",
    "character_for_beings_only",
    "character_changed",
    "no_change",
)


class ThingCharacterRefused(ValueError):
    """A character not written, named by one of :data:`THING_CHARACTER_CODES`."""

    def __init__(self, code: str, detail: str, *, revision: int | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        #: The newest record's revision, where the refusal is that it moved.
        self.revision = revision


@dataclass(frozen=True, slots=True)
class CharacterRecord:
    """One record: the character it states (None where it clears one), by revision."""

    placed_id: str
    revision: int
    character: Mapping[str, str] | None
    written_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "character": None if self.character is None else dict(self.character),
            "written_at": self.written_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


def _bounds() -> tuple[int, int]:
    """The character module's own figures, as a new society records them."""
    row = built_module(CHARACTER_MODULE)
    return row.value("name_characters_maximum"), row.value("about_characters_maximum")


def screened_character(
    raw: Mapping[str, Any] | None, names: Sequence[SavedName]
) -> dict[str, str] | None:
    """What an owner wrote, as a character a record may hold, or None to clear one: each part
    in normal form C, held to the line rule within the module's bounds, carrying no name the
    account holder saved; else :class:`ThingCharacterRefused`."""
    if raw is None:
        return None
    written = {
        key: unicodedata.normalize("NFC", value) if isinstance(value, str) else value
        for key, value in raw.items()
    }
    name_maximum, about_maximum = _bounds()
    try:
        character = check_character(written, name_maximum=name_maximum, about_maximum=about_maximum)
    except ValueError as exc:
        raise ThingCharacterRefused("character_out_of_bounds", str(exc)) from exc
    if any(recognised_spans(text, names) for text in character.values()):
        raise ThingCharacterRefused(
            "character_carries_a_saved_name",
            "a character carries no name the account holder saved",
        )
    return character


def _record(row: Mapping[str, Any]) -> CharacterRecord:
    parts = {key: row[key] for key in ("name", "about") if row[key] is not None}
    return CharacterRecord(row["placed_id"], int(row["revision"]), parts or None, row["written_at"])


def character_of(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    placed_id: str,
) -> CharacterRecord | None:
    """The newest record for one placed thing of a version, a clearing one included; None where
    nobody wrote one."""
    row = connection.execute(
        "select placed_id,revision,name,about,written_at from world_thing_character "
        "where workspace_id=%s and world_id=%s and version_id=%s and placed_id=%s "
        "order by revision desc limit 1",
        (workspace_id, world_id, version_id, placed_id),
    ).fetchone()
    return None if row is None else _record(row)


def newest_records(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
) -> list[CharacterRecord]:
    """The newest record of every placed thing of a version anyone wrote one for, a clearing one
    included, in placed id order. The database picks the one row per thing."""
    rows = connection.execute(
        "select distinct on (placed_id) placed_id,revision,name,about,written_at "
        "from world_thing_character "
        "where workspace_id=%s and world_id=%s and version_id=%s "
        "order by placed_id, revision desc",
        (workspace_id, world_id, version_id),
    ).fetchall()
    return [_record(row) for row in rows]


def newest_characters(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
) -> dict[str, dict[str, str]]:
    """The character of every placed thing of a version whose newest record states one, by placed
    id: what a society that records the character module is told in its next input."""
    return {
        record.placed_id: dict(record.character)
        for record in newest_records(connection, workspace_id, world_id, version_id)
        if record.character is not None
    }


def version_characters(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
) -> dict[str, Any]:
    """``exulanica.thing-characters/v1``: every placed thing's newest record (``placed_id``,
    ``revision``, ``character``, null where the record clears it, and ``written_at``), and
    whether the version's society shows a character (``society``, as the write answers it). An
    absent version, or another workspace's, is
    :class:`~exulanica.world.errors.UnknownWorldResource`."""
    held = connection.execute(
        "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
        "and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if held is None:
        raise UnknownWorldResource("no such alternate version")
    return {
        "profile": CHARACTERS_PROFILE,
        "version_id": str(version_id),
        "characters": [
            {"placed_id": record.placed_id, **record.document()}
            for record in newest_records(connection, workspace_id, world_id, version_id)
        ],
        "society": society_reads_characters(connection, workspace_id, world_id, version_id),
    }


def society_reads_characters(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> str:
    """Whether the version's society shows a character: ``runs_characters`` where its first input
    records the character module, ``began_before_characters`` where it records none, and ``none``
    where the version holds no society of things yet (its first input will record the module)."""
    row = connection.execute(
        "select i.document->'modules' as modules from world_society s "
        "join world_society_input i on i.workspace_id=s.workspace_id "
        "and i.society_id=s.society_id and i.input_seq=1 "
        "where s.workspace_id=%s and s.world_id=%s and s.version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if row is None:
        return "none"
    modules = row["modules"] or ()
    return "runs_characters" if CHARACTER_MODULE in modules else "began_before_characters"


def _being(row: Mapping[str, Any]) -> bool:
    """Whether a placed thing is a being: a kind its workspace keeps always is; a shipped kind is
    where its document says so."""
    if row["kind_source"] == "workspace":
        return True
    try:
        kind = shipped_kind(
            ThingKindReference(row["kind"], row["kind_version"], bytes(row["kind_sha256"]).hex())
        )
    except InvalidThingPlacement:
        return False
    return kind.document["class"] == "being"


def write_character(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    placed_id: str,
    base_revision: int | None,
    character: Mapping[str, str] | None,
    actor: uuid.UUID,
) -> CharacterRecord:
    """Append one record for the placed being ``placed_id`` of the version, over the newest record
    the writer read (``base_revision``, None where it read none), and answer it. The caller holds
    the workspace's lock in the transaction, so the newest record cannot move before the write; a
    writer that read an older one is refused ``character_changed``, one that would write what the
    newest already states ``no_change``. A thing removed, never placed or of another version is
    :class:`~exulanica.world.errors.UnknownWorldResource`; an object is refused
    ``character_for_beings_only``."""
    thing = connection.execute(
        "select kind_source,kind,kind_version,kind_sha256,removed from world_alternate_thing "
        "where workspace_id=%s and world_id=%s and version_id=%s and thing_id=%s",
        (workspace_id, world_id, version_id, placed_id),
    ).fetchone()
    if thing is None or thing["removed"]:
        raise UnknownWorldResource(f"no placed thing {placed_id} in this version")
    if not _being(thing):
        raise ThingCharacterRefused(
            "character_for_beings_only", "a character is written for a placed being"
        )
    newest = character_of(connection, workspace_id, world_id, version_id, placed_id)
    held = None if newest is None else newest.revision
    if base_revision != held:
        raise ThingCharacterRefused(
            "character_changed",
            "another character was written since this one was read",
            revision=held,
        )
    stated = None if newest is None else newest.character
    if (None if character is None else dict(character)) == (
        None if stated is None else dict(stated)
    ):
        raise ThingCharacterRefused("no_change", "the newest character already says this")
    row = connection.execute(
        "insert into world_thing_character(workspace_id,world_id,version_id,placed_id,name,"
        "about,base_revision,actor) values (%s,%s,%s,%s,%s,%s,%s,%s) "
        "returning placed_id,revision,name,about,written_at",
        (
            workspace_id,
            world_id,
            version_id,
            placed_id,
            None if character is None else character.get("name"),
            None if character is None else character.get("about"),
            base_revision,
            actor,
        ),
    ).fetchone()
    return _record(row)
