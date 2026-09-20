-- 0085_authored_starter_world_entries.sql
-- Saved entries distinguish personal-source worlds from source-independent authored starters.

begin;

select pg_advisory_xact_lock(119622309);

alter table saved_world_entry
  drop constraint saved_world_entry_source_kind_check;

alter table saved_world_entry
  add constraint saved_world_entry_source_kind_check
  check (source_kind in ('personal', 'authored'));

commit;
