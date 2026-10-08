-- 0168_a_search_s_words_are_cleared_after_thirty_days.sql
-- Our record of a reference search keeps its query text for thirty days, then clears it.
--
-- reference_lookup (0148) keeps, for each search sent, the source, aspect, query text, outcome,
-- credits, the source's request id, the result count and the time, and is appended and never
-- changed. The query text is the planner's words, written from a person's description with saved
-- names replaced. Kept for good, a paraphrase of someone's words would outlive the draft it served.
-- From here a query is kept for reference_lookup_query_retention() (thirty days) after it was
-- sent, long enough to show a person what was searched for them and to review a misuse report
-- against the source's acceptable use policy, and is then cleared. The rest of the row stays: that
-- a search went out, where, about which aspect, with what outcome and cost, and when, holds none
-- of the person's words.
--
-- THE ONE CHANGE A ROW MAY TAKE. The append-only trigger is restated to allow exactly one update:
-- the query set to null, once, on a row sent at least the retention ago. The trigger stamps
-- query_cleared_at itself, so no caller chooses the time; nothing else in the row may change. A
-- row is recorded with its query (an insert with a cleared one is refused).
--
-- WHO CLEARS. The runtime role has no UPDATE on this table (exulanica/db/roles.py) and gets none:
-- with one it could clear any query at any age. reference_lookup_clear_queries(workspace) clears
-- that workspace's old queries as 0161's login-less owner, exulanica_definer, with its search path
-- pinned, revoked from PUBLIC and executable by the runtime role alone (granted here and at
-- provisioning, as door_prune is). It asserts the workspace context first; row-level security
-- binds its owner. A failed clear never fails what called it: the callers log it and go on.
-- The owner gets SELECT on the table and UPDATE on the query column alone: the trigger stamps
-- query_cleared_at, and a column a trigger sets needs no grant (GRANTS_BY_MIGRATION in
-- exulanica/db/definer_role.py).
--
-- Objects: reference_lookup.query (now nullable), reference_lookup.query_cleared_at (new),
-- reference_lookup_query_check (restated), reference_lookup_query_retention() (new),
-- reference_lookup_query_age (new partial index),
-- tg_reference_lookup_append_only() (replaced; its trigger unchanged),
-- reference_lookup_clear_queries(uuid) (new, security definer), the owner's grants above, and
-- EXECUTE on it to exulanica_app where that role exists.
begin;
select pg_advisory_xact_lock(119622309);

-- How long a search's words are kept: the one place the figure is written. Thirty days written as
-- hours, so a session's time zone and its daylight saving never move the cutoff.
create or replace function reference_lookup_query_retention() returns interval
language sql immutable as $fn$ select interval '720 hours' $fn$;

alter table reference_lookup add column if not exists query_cleared_at timestamptz;
alter table reference_lookup alter column query drop not null;
alter table reference_lookup drop constraint if exists reference_lookup_query_check;
alter table reference_lookup add constraint reference_lookup_query_check check (
  case when query_cleared_at is null
       then query is not null and char_length(query) between 1 and 80
       else query is null end);

-- The clear reads a workspace's queries not yet cleared, oldest first.
create index if not exists reference_lookup_query_age on reference_lookup (workspace_id, sent_at)
  where query is not null;

create or replace function tg_reference_lookup_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    if new.query is null or new.query_cleared_at is not null then
      raise exception 'a reference lookup is recorded with its query' using errcode = '23514';
    end if;
    if new.sent_at > clock_timestamp() then
      raise exception 'a reference lookup is recorded when it was sent, not later'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if old.query is not null and new.query is null
     and (to_jsonb(new) - array['query', 'query_cleared_at'])
         = (to_jsonb(old) - array['query', 'query_cleared_at']) then
    perform assert_workspace_context(new.workspace_id);
    if old.sent_at > clock_timestamp() - reference_lookup_query_retention() then
      raise exception 'a reference lookup''s query is kept until it is % old',
        reference_lookup_query_retention() using errcode = '23514';
    end if;
    new.query_cleared_at := clock_timestamp();
    return new;
  end if;
  raise exception 'a reference lookup record is appended and never changed, but for its query '
                  'cleared once it is old enough' using errcode = '23514';
end $fn$;

create or replace function reference_lookup_clear_queries(p_workspace uuid) returns integer
language plpgsql security definer as $fn$
declare
  cleared integer;
  cutoff timestamptz;
begin
  perform assert_workspace_context(p_workspace);
  cutoff := clock_timestamp() - reference_lookup_query_retention();
  update reference_lookup set query = null
   where workspace_id = p_workspace
     and query is not null
     and sent_at <= cutoff;
  get diagnostics cleared = row_count;
  return cleared;
end $fn$;

do $owner$ begin
  execute format('alter function reference_lookup_clear_queries(uuid) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $owner$;
alter function reference_lookup_clear_queries(uuid) owner to exulanica_definer;
revoke all on function reference_lookup_clear_queries(uuid) from public;
grant select on reference_lookup to exulanica_definer;
grant update (query) on reference_lookup to exulanica_definer;

-- The runtime role executes it from this migration on, as 0149 grants door_prune; provisioning
-- grants it again for a runtime role of another name (REFERENCE_RUNTIME_FUNCTIONS).
do $runtime$ begin
  if exists (select 1 from pg_roles where rolname = 'exulanica_app') then
    execute format('grant execute on function %I.reference_lookup_clear_queries(uuid) to %I',
                   current_schema(), 'exulanica_app');
  end if;
end $runtime$;

commit;
