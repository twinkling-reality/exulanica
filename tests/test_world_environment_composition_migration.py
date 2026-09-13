from __future__ import annotations

from psycopg.rows import dict_row

from pg_harness import open_scratch_connection


def test_environment_instance_relation_is_forced_scoped_and_composite_bound(spine_schema) -> None:
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    try:
        relation = connection.execute(
            """
            select c.relrowsecurity,c.relforcerowsecurity,
                   array_agg(t.tgname order by t.tgname)
                     filter(where not t.tgisinternal) triggers
              from pg_class c
              join pg_namespace n on n.oid=c.relnamespace
              left join pg_trigger t on t.tgrelid=c.oid
             where n.nspname=current_schema()
               and c.relname='world_alternate_environment_instance'
             group by c.relrowsecurity,c.relforcerowsecurity
            """
        ).fetchone()
        assert relation["relrowsecurity"] and relation["relforcerowsecurity"]
        assert "tg_world_environment_binding" in relation["triggers"]
        targets = {
            row["target"]
            for row in connection.execute(
                """
                select confrelid::regclass::text target
                  from pg_constraint
                 where conrelid='world_alternate_environment_instance'::regclass
                   and contype='f'
                """
            ).fetchall()
        }
        assert targets == {
            "world_alternate_version",
            "environment_source_admission",
            "derived_environment_asset",
            "environment_feature_index_publication",
        }
    finally:
        connection.close()
