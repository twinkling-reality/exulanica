"""The workspace guard's refusal names the setting its own reader takes.

Migration 0001 wrote the reader and the message together, both naming the setting ADR-0011 later
withdrew; 0028 moved the reader to `exulanica.workspace_id` and left the message. A writer who
followed the sentence exactly set something nothing reads and failed again on the next write. 0079
changes the words. These tests hold the words AND hold that nothing else moved with them.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import psycopg
import pytest

from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

#: The function as migration 0001 wrote it, taken from that file rather than retyped here: the
#: comparison is against what the repository actually shipped, and the withdrawn setting name stays
#: where the rename guard already allows it, in the migration.
AS_0001_WROTE_IT = "create or replace function assert_workspace_context"


def as_0001_wrote_it() -> str:
    """0001's own definition, under another name, so both can run in one schema."""
    spine = (
        Path(__file__).resolve().parents[1] / "exulanica/migrations/0001_spine.sql"
    ).read_text()
    start = spine.index(AS_0001_WROTE_IT)
    end = spine.index("end $fn$;", start) + len("end $fn$;")
    definition = spine[start:end]
    assert "workspace context missing or mismatched" in definition
    return definition.replace(
        "function assert_workspace_context(", "function assert_workspace_context_0001(", 1
    )


def withdrawn_setting() -> str:
    """The setting 0001's message asked for, read from 0001 rather than written down again."""
    named = re.search(r"set (\S+) to", as_0001_wrote_it())
    assert named, "0001's refusal no longer names a setting"
    return named.group(1)


def declare(connection, workspace: uuid.UUID | None) -> None:
    """Declare the session workspace, or clear it. SET takes no parameter, so set_config does."""
    connection.execute(
        "select set_config('exulanica.workspace_id', %s, false)",
        ("" if workspace is None else str(workspace),),
    )


def outcome(connection, function: str, workspace: uuid.UUID) -> tuple[str, str]:
    """Whether this function refuses for this workspace, and the sentence it raises when it does.

    The raised sentence only, not psycopg's rendering of it: the context line names the function
    that raised, so comparing two functions through str() would compare their names as well.
    """
    try:
        connection.execute(f"select {function}(%s)", (workspace,))
    except psycopg.errors.InsufficientPrivilege as refusal:
        connection.rollback()
        return "refused", refusal.diag.message_primary or ""
    return "allowed", ""


def test_the_refusal_names_the_setting_the_reader_actually_takes(spine_schema):
    _, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        state, message = outcome(connection, "assert_workspace_context", uuid.uuid4())
        assert state == "refused"
        assert "exulanica.workspace_id" in message
        assert withdrawn_setting() not in message
    finally:
        connection.close()


def test_setting_what_the_refusal_asks_for_is_what_lets_the_write_through(spine_schema):
    """The instruction, followed exactly, works: the sentence is now actionable."""
    _, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        workspace = uuid.uuid4()
        assert outcome(connection, "assert_workspace_context", workspace)[0] == "refused"
        declare(connection, workspace)
        assert outcome(connection, "assert_workspace_context", workspace)[0] == "allowed"
    finally:
        connection.close()


def test_nothing_but_the_words_moved(spine_schema):
    """The same inputs, through 0001's own function and the 0079 one, refuse and allow alike."""
    _, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        connection.execute(as_0001_wrote_it())
        connection.commit()
        mine, other = uuid.uuid4(), uuid.uuid4()
        states = {}
        for context in (None, mine, other):
            declare(connection, context)
            old_state, old_message = outcome(connection, "assert_workspace_context_0001", mine)
            new_state, new_message = outcome(connection, "assert_workspace_context", mine)
            states[context] = (old_state, new_state)
            if new_state == "refused":
                # The same sentence with the setting taken out of both: nothing else differs.
                assert withdrawn_setting() != "exulanica.workspace_id"
                assert new_message.replace("exulanica.workspace_id", "") == old_message.replace(
                    withdrawn_setting(), ""
                ), context
        assert states[None] == ("refused", "refused")
        assert states[mine] == ("allowed", "allowed")
        assert states[other] == ("refused", "refused")
    finally:
        connection.rollback()
        connection.close()


def test_a_guarded_table_still_refuses_a_session_that_declared_nothing(spine_schema):
    """The trigger path, unchanged: the function is reached through a write, not only by hand."""
    _, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        setting = re.escape("exulanica.workspace_id")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match=setting):
            connection.execute(
                "insert into place_record (workspace_id, member_digest, member_count) "
                "values (gen_random_uuid(), %s, 1)",
                (bytes(32),),
            )
    finally:
        connection.close()
