-- 0116_a_comparison_scores_how_a_group_fared_under_each_model.sql
-- A comparison's second version: one group's model swapped, everybody else keeping theirs.
--
-- Migration 0113 records a comparison's definition and each run's outcome under exactly their
-- first profiles, exulanica.society-comparison/v1 and exulanica.society-comparison-run/v1. The
-- second version records a definition that names the group its arms decide for and what decides
-- for everybody else, the owner's model or their routine, and an outcome whose terms are the
-- group's need relief, apart from what the group's model answered
-- (exulanica/world/society_comparison_result.py). Both versions are admitted from here on, and
-- nothing a first-version row relied on is dropped:
--
-- society_comparison: the profile check, 0113's inline check under the name PostgreSQL gave it,
-- admits either profile; a second-version definition names a group of at least one person and
-- everybody outside it (society_comparison_names_its_group).
-- society_comparison_outcome: the completed-or-failed profile check, likewise under its given
-- name, admits either completed profile beside the one failure profile; and the outcome's binding
-- trigger, 0113's with one condition more, refuses a completed outcome whose version is not its
-- definition's, so a first-version outcome never scores a second-version comparison or the
-- reverse.
begin;
select pg_advisory_xact_lock(119622309);

alter table society_comparison drop constraint society_comparison_document_check1;
alter table society_comparison add constraint society_comparison_document_check1
  check ((document->>'profile' in ('exulanica.society-comparison/v1',
                                   'exulanica.society-comparison/v2')) is true);
alter table society_comparison add constraint society_comparison_names_its_group
  check ((document->>'profile' is distinct from 'exulanica.society-comparison/v2'
          or (jsonb_typeof(document->'group') = 'object'
              and jsonb_typeof(document->'group'->'people') = 'array'
              and jsonb_array_length(document->'group'->'people') >= 1
              and jsonb_typeof(document->'others') = 'array')) is true);

alter table society_comparison_outcome drop constraint society_comparison_outcome_check3;
alter table society_comparison_outcome add constraint society_comparison_outcome_check3
  check ((status = 'completed'
          and document->>'profile' in ('exulanica.society-comparison-run/v1',
                                       'exulanica.society-comparison-run/v2'))
      or (status = 'failed' and document->>'profile' = 'exulanica.society-comparison-failure/v1'));

-- 0113's outcome binding, with one condition more: a completed outcome's version is its
-- definition's.
create or replace function tg_society_comparison_outcome_binding() returns trigger
language plpgsql as $fn$
declare held society_comparison%rowtype; run society_comparison_run%rowtype; receipts bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880113));
  select * into run from society_comparison_run where workspace_id = new.workspace_id
    and world_id = new.world_id and run_id = new.run_id;
  select * into held from society_comparison where workspace_id = new.workspace_id
    and world_id = new.world_id and comparison_id = new.comparison_id;
  select count(*) into receipts from society_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if run.run_id is null or held.comparison_id is null
     or new.document->>'definition_sha256' is distinct from held.document_sha256
     or new.document->>'arm' is distinct from run.arm
     or new.document->>'seed_digest' is distinct from run.seed_digest
     or (new.status = 'completed'
         and (new.document->'receipts'->>'count') is distinct from receipts::text)
     or (new.status = 'completed'
         and (held.document->>'profile', new.document->>'profile') not in (
           ('exulanica.society-comparison/v1', 'exulanica.society-comparison-run/v1'),
           ('exulanica.society-comparison/v2', 'exulanica.society-comparison-run/v2'))) then
    raise exception 'comparison outcome binding mismatch' using errcode = '23514';
  end if;
  return new;
end $fn$;

commit;
