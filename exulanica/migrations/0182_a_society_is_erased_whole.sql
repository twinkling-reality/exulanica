-- 0182_a_society_is_erased_whole.sql
-- A world's society is erased whole, by itself or with its workspace: every row that records it.
--
-- WHAT A SOCIETY HOLDS. Its row and state; its inputs, requests and receipts, transitions and their
-- bindings, action requests, events, presences, choices and the answers of the people who play its
-- beings (each naming the account that posted it); its playback control and receipts; its world
-- clock with the clock's receipts, sealed traffic minutes and crossing occupancy; the appearance
-- revisions of its inhabitants; its asks to outside programs with their answers, and its crossings
-- with their bindings; the comparisons started from it, with their runs, decisions (each with the
-- request it asked), sealed hours (each with its end state), drawings, outcomes, starts, run starts
-- and cancellation; and the experiments run from it. A line a person typed for a being they play
-- reaches the answer, the receipt's proposal, the said event, the state's heard and said lines,
-- later requests' contexts, a comparison's decisions, hours and drawings, and an outside program's
-- asks. Every record is bound to the ones before it by digest (a receipt's own digest, an event's id
-- over its document's digest, each minute's state digest carried by the next), so nothing can be
-- blanked in place: an erasure removes every row, and nothing is left to replay.
--
-- AN ERASURE WRITES A TOMBSTONE, for 0082's, 0104's and 0172's reasons: every destroyed byte traces
-- to a tombstone, which records its actor and reason. The new scope is `society`, and the sentence
-- it makes true is:
--
--   A SOCIETY TOMBSTONE ERASES ONE SOCIETY OF A WORLD: EVERY ROW THAT RECORDS IT, ITS CLOCK, ITS
--   DOOR ASKS AND CROSSINGS, AND THE COMPARISONS AND EXPERIMENTS STARTED FROM IT, AND WITHDRAWS
--   THE COMPANION'S ANSWERS THAT CITED ITS WORLD VERSION; NOTHING ELSE.
--
-- Its subject is not a tombstone column, for 0172's reason: society_erasure names the society and
-- the tombstone written beside it, and nothing a person wrote. NOTHING IN THIS FILE USES THE NEW
-- VALUE AS AN ENUM, for 0082's measured reason: every reference is inside a plpgsql body or
-- compares `scope::text`.
--
-- The erasure's after-insert trigger, tg_society_erasure_erases, a SECURITY DEFINER owned by
-- exulanica_definer, works in the row's own workspace, which it asserts first. Where its tombstone
-- is held it withdraws the Companion's answers that cited the society's world version, as a
-- capture's tombstone withdraws those that cited the capture (0043), with their text kept: the
-- Companion never says what anybody said. It then deletes the society's rows, children first
-- (society_erase_rows). A workspace tombstone erases every society the workspace holds:
-- tg_society_erases_on_tombstone, a definer with the same owner, deletes each one's rows the same
-- way (0043 already withdraws every answer of an erased workspace). Each deletes what exists and
-- nothing else, so a restore's replay copy running it again changes nothing.
--
-- What the erasure leaves, and why: a door grant, its revisions, its program's declaration,
-- mapping and manifest, and the deliveries and gone notices keyed by the grant are the owner's
-- configuration and the things carried out, with no society text; a world project item's
-- references are event ids, each a uuid5 over a whole event document's digest; copies already sent
-- to hosted model providers and outside programs are beyond any erasure.
--
-- THE GUARDS. Every table the erasure deletes refused every delete. Each keeps its guard for what
-- it guarded besides (updates, and inserts where it binds them), and one more guard,
-- tg_society_record_erased_whole, refuses a delete made by anybody but exulanica_definer, whose
-- DELETE on them is this migration's grant, used by society_erase_rows alone (0161's rule for
-- every definer).
--
-- LOCKS. The product takes the workspace's lock before it writes the tombstone, and a tombstone
-- takes it without waiting (0137); a playback round, a manual step and an edit take it before they
-- lock a society's row, so they and an erasure never wait for each other in a cycle. Some writers
-- take no workspace lock: an answer to a played being (the society's row under a share lock), a
-- play and its give-back (the society's row), a door's answers and crossings, and a comparison's
-- host (its start). So before its first delete the erasure locks every parent such a writer adds
-- to, in one order: the society's row, its door asks, its comparisons' starts, then their runs.
-- Each such writer waits for the erasure and then finds its parent gone, or the erasure waits for
-- it; none adds a row between a child's delete and its parent's. 0172's creature erasure takes
-- the same workspace lock and touches none of these tables.
--
-- A RESTORE carries the erasure (exulanica/deletion/withdrawals.v2.json) before it replays any
-- tombstone, so the carried row deletes the society's rows from an older backup while its
-- tombstone is not yet held there. The Companion's answers it withdrew are not carried (the
-- catalog carries only a person's own withdrawal of an answer): the replayed society tombstone
-- withdraws them again, by the world version the carried erasure names, since the society's rows
-- are gone by then. That order is why society_erasure.tombstone_id names its tombstone without a
-- foreign key. Where the tombstone is held, it must be this workspace's and a society's; where it
-- is not, a restore's replay must be under way (restore_control replaying), so no other writer
-- erases without one.
--
-- WORKSPACES ERASED BEFORE THIS MIGRATION. A workspace tombstone written before it erased none of
-- a society's rows, since no trigger did then. Here every workspace with an effective workspace
-- tombstone loses them, as that tombstone's trigger below now takes them. No byte of them is in
-- the object store, so no purge job is due.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

alter type tombstone_scope add value if not exists 'society';

-- --------------------------------------------------------------------------------------------
-- 1. Only the erasure deletes a society's records.
-- --------------------------------------------------------------------------------------------

create function tg_society_record_erased_whole() returns trigger
language plpgsql as $fn$
begin
  if current_user = 'exulanica_definer' then
    return old;
  end if;
  raise exception '% is deleted only when its society is erased whole', tg_table_name
    using errcode = '23514';
end $fn$;

comment on function tg_society_record_erased_whole() is
  'Refuses a delete of a society''s record by anybody but the definers'' owner, which deletes '
  'them in society_erase_rows alone.';

-- Each table's guard keeps the events it guards besides delete: the trigger is made again with the
-- same name, function and events, but delete; the new guard takes delete.
do $$
declare
  t record;
begin
  for t in
    select * from (values
      ('comparison_cancellation', 'comparison_cancellation_append_only', 'update',
       'tg_comparison_fact_append_only'),
      ('comparison_run_start', 'comparison_run_start_append_only', 'update',
       'tg_comparison_fact_append_only'),
      ('door_answer', 'door_answer_append_only', 'update', 'tg_door_append_only'),
      ('door_ask', 'door_ask_append_only', 'update', 'tg_door_append_only'),
      ('door_crossing', 'door_crossing_append_only', 'update', 'tg_door_append_only'),
      ('door_crossing_binding', 'door_crossing_binding_append_only', 'update',
       'tg_door_append_only'),
      ('society_comparison', 'society_comparison_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_decision', 'society_comparison_decision_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_hour', 'society_comparison_hour_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_outcome', 'society_comparison_outcome_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_replay', 'society_comparison_replay_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_run', 'society_comparison_run_append_only', 'update',
       'tg_society_comparison_append_only'),
      ('society_comparison_start', 'tg_society_comparison_start_guard', 'update',
       'tg_society_comparison_start_guard'),
      ('society_experiment_attempt', 'society_experiment_attempt_append_only', 'update',
       'tg_society_experiment_append_only'),
      ('society_experiment_checkpoint', 'society_experiment_checkpoint_append_only', 'update',
       'tg_society_experiment_append_only'),
      ('society_experiment_definition', 'society_experiment_definition_append_only', 'update',
       'tg_society_experiment_append_only'),
      ('society_experiment_outcome', 'society_experiment_outcome_append_only', 'update',
       'tg_society_experiment_append_only'),
      ('world_character_appearance_revision', 'character_appearance_revision_guard',
       'insert or update', 'tg_character_appearance_revision'),
      ('world_clock', 'world_clock_guard', 'insert or update', 'tg_world_clock_guard'),
      ('world_clock_event', 'world_clock_event_guard', 'insert or update',
       'tg_world_clock_event_guard'),
      ('world_clock_traffic_minute', 'world_clock_traffic_minute_binding', 'insert or update',
       'tg_world_clock_traffic_minute_binding'),
      ('world_crossing_occupancy', 'world_crossing_occupancy_binding', 'insert or update',
       'tg_world_crossing_occupancy_binding'),
      ('world_society_action_request', 'world_society_action_request_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_control', 'society_control_guard', 'insert or update',
       'tg_society_control_guard'),
      ('world_society_control_event', 'society_control_event_guard', 'insert or update',
       'tg_society_control_event_guard'),
      ('world_society_decision', 'world_society_decision_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_decision_request', 'world_society_decision_request_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_event', 'tg_world_society_event_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_input', 'tg_world_society_input_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_model_choice', 'world_society_model_choice_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_person_answer', 'world_society_person_answer_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_presence', 'world_society_presence_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_transition', 'tg_world_society_transition_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_transition_action', 'world_society_transition_action_append_only', 'update',
       'tg_world_society_event_append_only'),
      ('world_society_transition_decision', 'world_society_transition_decision_append_only',
       'update', 'tg_world_society_event_append_only')
    ) as guards(tab, name, events, fn)
  loop
    execute format('drop trigger %I on %I', t.name, t.tab);
    execute format('create trigger %I before %s on %I for each row execute function %I()',
                   t.name, t.events, t.tab, t.fn);
    execute format('create trigger tg_society_record_erased_whole before delete on %I '
                   'for each row execute function tg_society_record_erased_whole()', t.tab);
  end loop;
end $$;

-- The society row had no delete guard: no role but its owner held DELETE on it.
create trigger tg_society_record_erased_whole before delete on world_society
  for each row execute function tg_society_record_erased_whole();

-- --------------------------------------------------------------------------------------------
-- 2. The erasure.
-- --------------------------------------------------------------------------------------------

create table society_erasure (
  workspace_id  uuid not null,
  erasure_id    uuid not null default uuidv7(),
  world_id      text not null check (length(world_id) between 1 and 200),
  -- The erased society's world version: a replayed tombstone withdraws the Companion's answers
  -- that cited it, after the society's rows are gone.
  version_id    uuid not null,
  -- The erased society: the name its restore matches it by, and nothing it said.
  society_id    uuid not null,
  -- The society tombstone written beside it; one each.
  tombstone_id  uuid not null,
  erased_by     uuid not null,
  erased_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, erasure_id),
  constraint society_erasure_has_its_own_tombstone unique (tombstone_id),
  constraint society_erasure_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id)
);

comment on table society_erasure is
  'A workspace''s erasure of one society of a world, naming the society, its world version and '
  'the society tombstone written with it; its trigger deletes every row that records the '
  'society, and a restore carries it. Appended; never updated or deleted by the runtime.';

-- The row is written as given: a restore writes a carried erasure again whole, and compares it so.
create function tg_society_erasure_binding() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;

create trigger tg_society_erasure_append_only before update or delete on society_erasure
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_society_erasure_binding before insert on society_erasure
  for each row execute function tg_society_erasure_binding();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on society_erasure
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
alter table society_erasure enable row level security;
alter table society_erasure force row level security;
create policy ws_isolation on society_erasure
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- Every row that records one society, children first, in the workspace the session is in.
create function society_erase_rows(p_workspace uuid, p_society uuid) returns void
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(p_workspace);
  -- Every parent a writer without the workspace lock adds to, before the first delete (LOCKS).
  perform 1 from world_society s
   where s.workspace_id = p_workspace and s.society_id = p_society for update;
  perform 1 from door_ask k
   where k.workspace_id = p_workspace and k.society_id = p_society
   order by k.grant_id, k.ask_seq for update;
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

comment on function society_erase_rows(uuid, uuid) is
  'Every row that records one society of a world, children first: its comparisons and '
  'experiments, door asks and crossings, clock, records and row. Runs as exulanica_definer, in '
  'the session''s own workspace; for the two erasure triggers alone.';

create function tg_society_erasure_erases() returns trigger
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
  if exists (select 1 from world_society s
              where s.workspace_id = new.workspace_id and s.society_id = new.society_id
                and (s.world_id, s.version_id) is distinct from (new.world_id, new.version_id)) then
    raise exception 'an erasure names its society''s own world version'
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

comment on function tg_society_erasure_erases() is
  'An erasure''s withdrawals and deletes: the Companion''s answers citing the society''s world '
  'version, and every row that records the society. Runs as exulanica_definer, in the '
  'erasure''s own workspace.';

create trigger tg_society_erasure_erases after insert on society_erasure
  for each row execute function tg_society_erasure_erases();

-- A workspace tombstone erases every society the workspace holds, in its own workspace. A
-- society tombstone a restore replays withdraws again the Companion's answers its erasure withdrew:
-- the carried erasure is written first and names the version; in the product the tombstone comes
-- first, finds no erasure naming it yet, and the erasure's own trigger withdraws them.
create function tg_society_erases_on_tombstone() returns trigger
language plpgsql security definer as $fn$
declare
  v_society uuid;
begin
  if new.scope::text = 'society' then
    perform assert_workspace_context(new.workspace_id);
    update companion_answer a
       set status = 'withdrawn',
           withdrawn_at = new.effective_at,
           withdrawn_by = new.tombstone_id
     where a.workspace_id = new.workspace_id
       and a.status <> 'withdrawn'
       and exists (
             select 1
               from society_erasure e
               join companion_answer_simulation_citation c
                 on c.workspace_id = e.workspace_id and c.world_id = e.world_id
                and c.version_id = e.version_id
              where e.workspace_id = new.workspace_id
                and e.tombstone_id = new.tombstone_id
                and c.answer_id = a.answer_id);
    return new;
  end if;
  if new.scope::text <> 'workspace' then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  for v_society in
    select s.society_id from world_society s where s.workspace_id = new.workspace_id
     order by s.society_id
  loop
    perform society_erase_rows(new.workspace_id, v_society);
  end loop;
  return new;
end $fn$;

comment on function tg_society_erases_on_tombstone() is
  'A workspace tombstone''s erasure of every society the workspace keeps, at once, and a '
  'replayed society tombstone''s withdrawal of the Companion''s answers its erasure withdrew. '
  'Runs as exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_society_erases_on_tombstone
  after insert on tombstone
  for each row execute function tg_society_erases_on_tombstone();

-- --------------------------------------------------------------------------------------------
-- 3. Workspaces erased before this migration (above).
-- --------------------------------------------------------------------------------------------

-- These statements read every workspace: FORCE is lifted on each table they touch and
-- row_security is off, so filtering would raise rather than skip a row, and the new delete guard
-- is disabled for the deletes alone. Children first, and only what society_erase_rows deletes:
-- a society comparison's run starts and cancellation, and a society clock's receipts and traffic.
set local row_security = off;
alter table tombstone no force row level security;
alter table society_comparison no force row level security;
alter table world_clock no force row level security;
do $$ declare t text; begin
  foreach t in array array[
    'comparison_cancellation', 'comparison_run_start', 'door_answer', 'door_ask',
    'door_crossing_binding', 'door_crossing', 'society_comparison_decision',
    'society_comparison_hour', 'society_comparison_outcome', 'society_comparison_replay',
    'society_comparison_run', 'society_comparison_start', 'society_comparison',
    'society_experiment_checkpoint', 'society_experiment_outcome', 'society_experiment_attempt',
    'society_experiment_definition', 'world_character_appearance_revision', 'world_clock_event',
    'world_clock_traffic_minute', 'world_crossing_occupancy', 'world_clock',
    'world_society_transition_action', 'world_society_action_request',
    'world_society_control_event', 'world_society_control', 'world_society_transition_decision',
    'world_society_decision', 'world_society_decision_request', 'world_society_event',
    'world_society_presence', 'world_society_transition', 'world_society_input',
    'world_society_model_choice', 'world_society_person_answer', 'world_society'
  ] loop
    execute format('alter table %I no force row level security', t);
    execute format('alter table %I disable trigger tg_society_record_erased_whole', t);
    execute format(
      'delete from %I x where exists (select 1 from tombstone tb '
      'where tb.workspace_id = x.workspace_id and tb.scope = ''workspace'' '
      'and tb.effective_at <= now())', t)
      || case
           when t in ('comparison_cancellation', 'comparison_run_start') then
             ' and x.kind = ''society'' and x.comparison_id in (select c.comparison_id '
             'from society_comparison c where c.workspace_id = x.workspace_id)'
           when t in ('world_clock_event', 'world_clock_traffic_minute') then
             ' and exists (select 1 from world_clock k where k.workspace_id = x.workspace_id '
             'and k.world_id = x.world_id and k.version_id = x.version_id)'
           else ''
         end;
    execute format('alter table %I enable trigger tg_society_record_erased_whole', t);
    execute format('alter table %I force row level security', t);
  end loop;
end $$;
alter table world_clock force row level security;
alter table society_comparison force row level security;
alter table tombstone force row level security;
set local row_security = on;

-- --------------------------------------------------------------------------------------------
-- 4. The three definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ begin
  execute format('alter function society_erase_rows(uuid, uuid) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_society_erasure_erases() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_society_erases_on_tombstone() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function society_erase_rows(uuid, uuid) from public;
revoke all on function tg_society_erasure_erases() from public;
revoke all on function tg_society_erases_on_tombstone() from public;

-- The deletes and the reads they make; the Companion's withdrawal, three columns of an answer,
-- and the erasure a replayed tombstone reads. The tombstone and restore_control they read are
-- 0161's grants.
grant select, delete on comparison_cancellation, comparison_run_start, door_answer, door_ask,
  door_crossing_binding, door_crossing, society_comparison_decision, society_comparison_hour,
  society_comparison_outcome, society_comparison_replay, society_comparison_run,
  society_comparison_start, society_comparison, society_experiment_checkpoint,
  society_experiment_outcome, society_experiment_attempt, society_experiment_definition,
  world_character_appearance_revision, world_clock_event, world_clock_traffic_minute,
  world_crossing_occupancy, world_clock, world_society_transition_action,
  world_society_action_request, world_society_control_event, world_society_control,
  world_society_transition_decision, world_society_decision, world_society_decision_request,
  world_society_event, world_society_presence, world_society_transition, world_society_input,
  world_society_model_choice, world_society_person_answer, world_society to exulanica_definer;
grant select on companion_answer, companion_answer_simulation_citation, society_erasure
  to exulanica_definer;
grant update (status, withdrawn_at, withdrawn_by) on companion_answer to exulanica_definer;
-- A row lock needs UPDATE on a column of its table: workspace_id, which no body writes.
grant update (workspace_id) on world_society, door_ask, society_comparison_start,
  society_comparison_run to exulanica_definer;
alter function society_erase_rows(uuid, uuid) owner to exulanica_definer;
alter function tg_society_erasure_erases() owner to exulanica_definer;
alter function tg_society_erases_on_tombstone() owner to exulanica_definer;

commit;
