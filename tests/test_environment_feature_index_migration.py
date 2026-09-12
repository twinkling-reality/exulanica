from __future__ import annotations

import uuid

from exulanica.db.roles import provision_runtime_role
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection


def test_feature_publication_is_forced_scoped_append_only_and_has_no_feature_rows(spine_schema):
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    try:
        row = connection.execute(
            """
            select c.relrowsecurity,c.relforcerowsecurity,
                   array_agg(t.tgname order by t.tgname) filter(where not t.tgisinternal) triggers
              from pg_class c
              join pg_namespace n on n.oid=c.relnamespace
              left join pg_trigger t on t.tgrelid=c.oid
             where n.nspname=current_schema()
               and c.relname='environment_feature_index_publication'
             group by c.relrowsecurity,c.relforcerowsecurity
            """
        ).fetchone()
        assert row["relrowsecurity"] and row["relforcerowsecurity"]
        assert {
            "aaa_asset_read_mutation",
            "tg_environment_feature_index_immutable",
            "tg_environment_feature_index_publication",
        }.issubset(row["triggers"])
        assert (
            connection.execute(
                "select count(*) n from information_schema.tables "
                "where table_schema=current_schema() and table_name like 'environment_feature%'"
            ).fetchone()["n"]
            == 1
        )
    finally:
        connection.close()


def test_read_role_can_select_but_cannot_publish_or_mutate_feature_indexes(spine_schema):
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    role = f"feature_index_ro_{uuid.uuid4().hex}"
    try:
        provision_runtime_role(connection, role=role, read_only=True)
        privileges = connection.execute(
            "select has_table_privilege(%s,%s,'SELECT') can_read,"
            "has_table_privilege(%s,%s,'INSERT') can_insert,"
            "has_table_privilege(%s,%s,'UPDATE') can_update,"
            "has_table_privilege(%s,%s,'DELETE') can_delete",
            (
                role,
                "environment_feature_index_publication",
                role,
                "environment_feature_index_publication",
                role,
                "environment_feature_index_publication",
                role,
                "environment_feature_index_publication",
            ),
        ).fetchone()
        assert privileges == {
            "can_read": True,
            "can_insert": False,
            "can_update": False,
            "can_delete": False,
        }
    finally:
        connection.execute(f'drop owned by "{role}"')
        connection.execute(f'drop role if exists "{role}"')
        connection.close()
