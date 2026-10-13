-- 0198_a_world_kind_keeps_its_declared_requirements.sql
-- A workspace keeps both published world-kind document profiles. Version 2 adds source
-- offsets, declared requirement claims and pinned structural classes, validated by the kind
-- reader and its sample worlds. Version 1 documents and reports remain valid without changes.
--
-- Apply before an API saves version 2 kinds. Only the accepted profile set changes; kind,
-- version and origin must still match the row, including refusal of absent/null identities.
-- Stored rows are checked as the constraint is added; none is rewritten. No grants, policies,
-- triggers, functions, columns or indexes change. Returning to the version 1 constraint would
-- require resolving any version 2 rows first; an older reader cannot read those documents.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_kind_version
  drop constraint world_kind_version_names_itself;
alter table world_kind_version
  add constraint world_kind_version_names_itself check (
    (document->>'profile' in ('exulanica.world-kind/v1', 'exulanica.world-kind/v2')
      and document->>'kind' = kind
      and document->>'version' = version::text
      and document->>'origin' = origin) is true);

commit;
