from __future__ import annotations

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pg_harness import open_scratch_connection


def test_environment_tables_are_forced_scoped_and_guard_asset_reads(spine_schema):
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    try:
        rows = connection.execute(
            """
            select c.relname,c.relrowsecurity,c.relforcerowsecurity,
                   array_agg(t.tgname order by t.tgname) filter(where not t.tgisinternal) triggers
            from pg_class c
            join pg_namespace n on n.oid=c.relnamespace
            left join pg_trigger t on t.tgrelid=c.oid
            where n.nspname=current_schema()
              and c.relname in ('environment_source_admission','derived_environment_asset')
            group by c.relname,c.relrowsecurity,c.relforcerowsecurity
            order by c.relname
            """
        ).fetchall()
        assert [row["relname"] for row in rows] == [
            "derived_environment_asset",
            "environment_source_admission",
        ]
        assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        assert all("aaa_asset_read_mutation" in row["triggers"] for row in rows)
        assert "tg_environment_source_immutable" in rows[1]["triggers"]
        assert "tg_derived_environment_asset_immutable" in rows[0]["triggers"]
    finally:
        connection.close()


def test_database_rights_validation_fails_closed(spine_schema):
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    try:
        complete = {
            "display": True,
            "extract": True,
            "index": True,
            "persist": True,
            "modify": True,
            "compose": True,
            "export": False,
            "model_processing": False,
        }
        assert connection.execute(
            "select environment_rights_valid(%s) ok", (Jsonb(complete),)
        ).fetchone()["ok"]
        for malformed in (
            {key: value for key, value in complete.items() if key != "export"},
            {**complete, "redistribute": True},
            {**complete, "display": "true"},
        ):
            assert not connection.execute(
                "select environment_rights_valid(%s) ok", (Jsonb(malformed),)
            ).fetchone()["ok"]
        assert not connection.execute(
            "select environment_resource_allows(%s,'source',gen_random_uuid(),'download',now()) ok",
            ("00000000-0000-0000-0000-000000000001",),
        ).fetchone()["ok"]
    finally:
        connection.close()
