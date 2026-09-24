"""Every function a restore runs while it loads rows resolves its own names.

``exulanica.db.load_functions`` says why a restore needs this and asks the catalog for every
function that does not. Measured before migration 0106: ``privacy_canonical`` (0040), recursing
inside the receipt CHECK of ``personal_model_right`` (0073), stopped ``COPY personal_model_right``
in both dump formats, so a backup holding one model right could not be restored.
"""

from __future__ import annotations

import pytest
from exulanica.db.load_functions import loading_functions_without_a_path, pin_loading_functions

pytestmark = pytest.mark.postgres


def test_every_function_a_restore_runs_while_loading_rows_resolves_its_own_names(
    repository, spine_schema
):
    _, schema = spine_schema
    assert loading_functions_without_a_path(repository.connection, schema=schema) == []


def test_the_question_finds_a_function_that_calls_itself_through_the_path(repository, spine_schema):
    """The positive control: a CHECK calling a function whose body recurses through the path."""
    _, schema = spine_schema
    connection = repository.connection
    with connection.transaction(force_rollback=True):
        connection.execute(
            "create function r3_control_depth(p jsonb) returns int language plpgsql immutable "
            "as $fn$ begin if jsonb_typeof(p)='array' then "
            "return 1 + coalesce((select max(r3_control_depth(e)) "
            "from jsonb_array_elements(p) e), 0); end if; return 0; end $fn$"
        )
        connection.execute("create table r3_control (v jsonb check (r3_control_depth(v) < 3))")
        [found] = loading_functions_without_a_path(connection, schema=schema)
        assert (found.names, found.schemas) == (("r3_control_depth",), (schema,))
        assert found.used_by == ("check r3_control_v_check",)

        assert pin_loading_functions(connection, schema=schema) == [found]
        assert loading_functions_without_a_path(connection, schema=schema) == []
        [config] = (
            connection.execute("select proconfig from pg_proc where proname='r3_control_depth'")
            .fetchone()
            .values()
        )
        assert config == [f"search_path={schema}, pg_catalog, pg_temp"]
