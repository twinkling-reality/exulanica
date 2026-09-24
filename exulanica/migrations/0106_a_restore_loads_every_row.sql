-- 0106_a_restore_loads_every_row.sql
-- A restore loads every row: the recursive canonicaliser resolves its own names.
--
-- A dump made by pg_dump sets search_path to the empty string before anything else, and psql and
-- pg_restore then copy each table's rows with its CHECK constraints in force. `privacy_canonical`
-- (0040) writes a JSON value's canonical form by calling itself on each member, unqualified, and
-- eight receipt CHECKs call it: decoded_source (0045), environment_source_admission and
-- derived_environment_asset (0048), environment_feature_index_publication (0049),
-- personal_model_right (0073), scene_training_right (0080), place_source_frame (0091) and
-- place_name_right_event (0097). Each constraint stores its own call with the name resolved, but
-- the function body is parsed when it runs, and under the empty path its inner call names no
-- function. So COPY stops at the first row whose receipt holds an object. Measured in both dump
-- formats, psql over a plain dump and pg_restore over a custom one: a backup holding one model right
-- could not be restored, and a restore that stops there replays nothing.
--
-- 0036 met the same failure in the JSON-schema validators and fixed it the same way: the function
-- carries its own path, so it resolves its own name under any caller's path, the restorer's empty
-- one included. Nothing else changes: same body, same result for every input.
--
-- A DUMP TAKEN BEFORE THIS MIGRATION holds the function as it was. `exulanica-local-db` restores
-- one anyway: it loads the schema, pins every function the rows will run that resolves names
-- through the path (`exulanica/db/load_functions.py`), then loads the rows. psql over such a plain
-- dump still stops where it stopped. `tests/test_restore_loads_every_row.py` asks the schema for
-- every such function, so one added later is held to the same rule.

begin;
select pg_advisory_xact_lock(119622309);

do $pin$
begin
  execute format('alter function %I.privacy_canonical(jsonb) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema(), current_schema());
end $pin$;

commit;
