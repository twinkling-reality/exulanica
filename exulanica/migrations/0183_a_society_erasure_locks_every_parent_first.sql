-- 0183_a_society_erasure_locks_every_parent_first.sql
-- A society's erasure locks every parent a writer without the workspace lock adds to, and refuses a
-- held erasure of a society its workspace does not hold.
--
-- The society erasure (a_society_is_erased_whole) locks the society's row, its door asks and its
-- comparisons' starts and runs before its first delete. Two more writers take no workspace lock: a
-- door's asker, which records a decision under one of the society's decision requests, and the
-- experiment writers, which record attempts, checkpoints and outcomes under an experiment's
-- definition. The erasure now locks those parents too, in one order before its first delete: the
-- society's row, its decision requests, its door asks, its experiments' definitions, its
-- comparisons' starts, then their runs. Each such writer waits for the erasure and then finds its
-- parent gone, or the erasure waits for it; none adds a row between a child's delete and its
-- parent's. A row lock needs UPDATE on a column of its table: workspace_id, which no body writes,
-- on the two tables more.
--
-- The erasure refuses a row naming another world version than its society's. Where its tombstone
-- is held, which only the product's erasure writes in the same transaction, it now refuses a
-- society its workspace does not hold, too; a restore's carried erasure, written before its
-- tombstone is replayed, is written only where the backup holds the society.
--
-- Both functions keep their name, signature, owner, path and grants; their bodies are replaced
-- whole.

begin;

select pg_advisory_xact_lock(119622309);

create or replace function society_erase_rows(p_workspace uuid, p_society uuid) returns void
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(p_workspace);
  -- Every parent a writer without the workspace lock adds to, before the first delete (LOCKS).
  perform 1 from world_society s
   where s.workspace_id = p_workspace and s.society_id = p_society for update;
  perform 1 from world_society_decision_request x
   where x.workspace_id = p_workspace and x.society_id = p_society
   order by x.request_id for update;
  perform 1 from door_ask k
   where k.workspace_id = p_workspace and k.society_id = p_society
   order by k.grant_id, k.ask_seq for update;
  perform 1 from society_experiment_definition e
   where e.workspace_id = p_workspace and e.source_society_id = p_society
   order by e.experiment_id for update;
  perform 1 from society_comparison_start x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society)
   order by x.comparison_id for update of x;
  perform 1 from society_comparison_run x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society)
   order by x.run_id for update of x;
  delete from comparison_cancellation x
   where x.workspace_id = p_workspace and x.kind = 'society'
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from comparison_run_start x
   where x.workspace_id = p_workspace and x.kind = 'society'
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from door_answer a
   using door_ask k
   where a.workspace_id = p_workspace and k.workspace_id = p_workspace and k.society_id = p_society
     and a.grant_id = k.grant_id and a.ask_seq = k.ask_seq and a.request_id = k.request_id;
  delete from door_ask x where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from door_crossing_binding x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from door_crossing x where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from society_comparison_decision x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison_hour x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison_outcome x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison_replay x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison_run x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison_start x
   where x.workspace_id = p_workspace
     and x.comparison_id in (select c.comparison_id from society_comparison c
                              where c.workspace_id = p_workspace and c.society_id = p_society);
  delete from society_comparison x where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from society_experiment_checkpoint x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select e.experiment_id from society_experiment_definition e
                              where e.workspace_id = p_workspace
                                and e.source_society_id = p_society);
  delete from society_experiment_outcome x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select e.experiment_id from society_experiment_definition e
                              where e.workspace_id = p_workspace
                                and e.source_society_id = p_society);
  delete from society_experiment_attempt x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select e.experiment_id from society_experiment_definition e
                              where e.workspace_id = p_workspace
                                and e.source_society_id = p_society);
  delete from society_experiment_definition x
   where x.workspace_id = p_workspace and x.source_society_id = p_society;
  delete from world_character_appearance_revision x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  -- The clock's receipts and sealed traffic name its world version, not the society: the clock's.
  delete from world_clock_event x
   using world_clock k
   where x.workspace_id = p_workspace and k.workspace_id = p_workspace
     and k.society_id = p_society and x.world_id = k.world_id and x.version_id = k.version_id;
  delete from world_clock_traffic_minute x
   using world_clock k
   where x.workspace_id = p_workspace and k.workspace_id = p_workspace
     and k.society_id = p_society and x.world_id = k.world_id and x.version_id = k.version_id;
  delete from world_crossing_occupancy x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_clock x where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_transition_action x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_action_request x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_control_event x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_control x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_transition_decision x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_decision x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_decision_request x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_event x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_presence x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_transition x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_input x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_model_choice x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_person_answer x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society x where x.workspace_id = p_workspace and x.society_id = p_society;
end $fn$;

create or replace function tg_society_erasure_erases() returns trigger
language plpgsql security definer as $fn$
declare
  v_anchor text;
  v_effective timestamptz;
begin
  perform assert_workspace_context(new.workspace_id);
  -- The product writes the tombstone first, in this transaction. A restore carries the erasure
  -- before it replays tombstones, so there it is not yet held.
  select case when t.workspace_id = new.workspace_id and t.scope::text = 'society'
              then 'held' else 'another' end,
         t.effective_at
    into v_anchor, v_effective
    from tombstone t
   where t.tombstone_id = new.tombstone_id;
  if v_anchor = 'another' then
    raise exception 'an erasure is written beside a society tombstone of its own workspace'
      using errcode = 'check_violation';
  end if;
  if v_anchor is null
     and not exists (select 1 from restore_control r where r.state = 'replaying') then
    raise exception 'an erasure names a tombstone it holds, unless a restore''s replay carries it'
      using errcode = 'check_violation';
  end if;
  -- Its society at its own world version; where its tombstone is held, which only the product's
  -- erasure writes beside it, a society its workspace holds.
  if exists (select 1 from world_society s
              where s.workspace_id = new.workspace_id and s.society_id = new.society_id
                and (s.world_id, s.version_id) is distinct from (new.world_id, new.version_id))
     or (v_anchor = 'held'
         and not exists (select 1 from world_society s
                          where s.workspace_id = new.workspace_id
                            and s.society_id = new.society_id)) then
    raise exception 'an erasure names a society its workspace holds, at its own world version'
      using errcode = 'check_violation';
  end if;
  if v_anchor = 'held' then
    -- The Companion's answers that cited the society's world version, as 0043 withdraws those
    -- that cited a capture; their text holds no line, since the Companion never says what
    -- anybody said. A restore's replayed tombstone withdraws them again (below).
    update companion_answer a
       set status = 'withdrawn',
           withdrawn_at = v_effective,
           withdrawn_by = new.tombstone_id
     where a.workspace_id = new.workspace_id
       and a.status <> 'withdrawn'
       and exists (
             select 1
               from companion_answer_simulation_citation c
              where c.workspace_id = a.workspace_id
                and c.answer_id = a.answer_id
                and c.world_id = new.world_id
                and c.version_id = new.version_id);
  end if;
  perform society_erase_rows(new.workspace_id, new.society_id);
  return null;
end $fn$;

do $$ begin
  execute format('alter function society_erase_rows(uuid, uuid) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_society_erasure_erases() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function society_erase_rows(uuid, uuid) from public;
revoke all on function tg_society_erasure_erases() from public;
grant update (workspace_id) on world_society_decision_request, society_experiment_definition
  to exulanica_definer;
alter function society_erase_rows(uuid, uuid) owner to exulanica_definer;
alter function tg_society_erasure_erases() owner to exulanica_definer;

commit;
