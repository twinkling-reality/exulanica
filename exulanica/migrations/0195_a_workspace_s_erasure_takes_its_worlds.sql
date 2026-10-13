-- 0195_a_workspace_s_erasure_takes_its_worlds.sql
-- A world's rows are erased whole, and a workspace's erasure erases every world it holds.
--
-- WHAT A WORLD HOLDS. Its registration and the receipt it was generated from (for a place drafted
-- from a sentence, the whole kind document); its structure, topology, appearance and interaction
-- history; its authored versions with their titles, every edit's before and after documents, and
-- what was placed in them; the looks chosen for its things and the budget set for its minds; its
-- saved entry, with the title a person typed, and the entry's sources; its traffic signal records
-- and signal comparisons; its door grants with their revisions, revocations, deliveries, presence
-- and secrets; its piece requests with their look steps, outputs and settlements; its projects,
-- with their items, revisions, sources, bindings and shares; the Companion's citations of its
-- versions and the names its placeholders stood for; and its societies, each with everything
-- 0182 lists. Until now a workspace's tombstone erased the societies and left the rest: a
-- registration, a receipt, a title and an edit's documents outlived the workspace they were
-- made in.
--
-- world_erase_rows(workspace, world) DELETES ALL OF IT, CHILDREN FIRST, AND THE REGISTRATION LAST.
-- Nothing is blanked in place, since nothing of the world stays to hold a blank. It erases each
-- society with society_erase_rows (0183), then deletes from every table that names the world: by
-- the world's id where a table carries it, and through the row that does where it does not (a
-- grant, a piece request, an entry, a project, an item, an experiment, a citing answer). The society
-- tables that carry the world's id are among them, for the rows that name the world and no
-- society of it: a signal comparison's run starts and cancellation, an appearance revision of no
-- society. No foreign key cascades, so the order is the order the keys allow, read from the
-- migrated schema; a table added later that references a world's row and is not deleted here
-- makes the erasure fail on its key rather than leave a row behind.
--
-- WHAT IT KEEPS. society_erasure's rows: an erasure's record is never deleted. Its foreign key to
-- world_identity is dropped, the one constraint that changes; the record goes on naming its
-- world by id. A kind a person keeps (world_kind_version) is the workspace's and not any one
-- world's, so the function deletes none; the workspace tombstone's trigger below deletes them
-- all. What a world does not own is not touched: baked tiles and generated pieces are shared and
-- content-addressed, a look and a creature are the workspace's.
--
-- THIS MIGRATION RUNS IT FOR A WORKSPACE TOMBSTONE ONLY: tg_world_erases_on_tombstone erases every
-- world the workspace holds and then its kept kinds. Among the after-insert triggers on tombstone,
-- which fire in name order, it sorts after tg_a_tombstone_never_waits_for_its_workspace_s_lock
-- (0137), after tg_society_erases_on_tombstone and after every tg_tombstone_ and tg_workspace_
-- trigger, so piece batches, projects' withdrawals and bytes' purge jobs are settled first; it
-- sorts before tg_world_structure_invalidate_on_tombstone (0020), which then finds no snapshot
-- of an erased workspace to invalidate. Removing one world by itself, with a tombstone of its
-- own scope and a record of its own, is a later migration's: it calls this function.
--
-- THE GUARDS. Every table the function deletes from either refused every delete or had no guard
-- at all (no role but its owner held DELETE). Each guard that also guarded updates or inserts is
-- made again with the same name, function and events, but delete; a guard that guarded delete
-- alone is dropped; and every one of the tables gains tg_world_record_erased_whole, which refuses
-- a delete by anybody but exulanica_definer, whose DELETE on them is this migration's grant,
-- used by world_erase_rows and the workspace trigger alone (0161's rule for every definer).
-- world_minds_budget's guard is not touched here. door_secret is the one table another definer
-- deletes from: door_prune, whose own statement keeps a secret for thirty days after its end;
-- the row trigger no longer repeats that rule, so that a world's erasure takes a grant's
-- secrets at any age.
--
-- LOCKS. The product takes the workspace's lock before it writes a tombstone, and a tombstone
-- takes it without waiting (0137); every writer that holds it first never meets the erasure.
-- Some writers of a world's rows take no workspace lock: a project's writers (0127), a style
-- write of a world with no saved entry, a preview's discard, a traffic signal's controller, a
-- signal comparison's host and its cancel, a piece request's cancel, the door, and the
-- Companion's citations. So before its first delete the function locks every parent such a
-- writer adds to or changes, in the order those writers take them: the project plane's key
-- (0127), the world's projects, their items, its entry, its versions, each state row before its
-- previews, its piece requests, its signal comparisons' starts and then their runs; then it
-- erases the societies (0183's order); then the world's door grants; and last the registration
-- itself, which every world table references, so that from there no row can be added under the
-- world. Each such writer waits for the erasure and then finds its parent gone, or the erasure
-- waits for it. A row lock needs UPDATE on a column of its table: workspace_id, which no body
-- writes.
--
-- WORKSPACES ERASED BEFORE THIS MIGRATION. A workspace tombstone written before it erased none
-- of these rows, since no trigger did then. Here every workspace with an effective workspace
-- tombstone loses them, as that tombstone's trigger below now takes them. No byte of them is in
-- the object store, so no purge job is due.

begin;

select pg_advisory_xact_lock(119622309);

-- A removed request's outstanding monetary obligation and batch cancellation survive without
-- its world, request document or content digest. Existing measured decisions are copied exactly;
-- otherwise the worker first withdraws the GPU entry and decides against the durable ledger.
create table piece_erasure_settlement (
  workspace_id uuid not null,
  piece_request_id uuid not null,
  reservation_id uuid not null,
  reservation_authority_id uuid not null,
  reservation_holder text not null
    check (reservation_holder ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  piece_batch_id uuid not null,
  worst_case_usd numeric(14,8) not null check (worst_case_usd >= 0),
  basis text check (basis in ('reported', 'unknown', 'not_sent')),
  usd numeric(14,8) check (usd >= 0 and usd <= worst_case_usd),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, piece_request_id),
  check ((basis is null) = (usd is null)),
  check (basis <> 'not_sent' or usd = 0)
);
comment on table piece_erasure_settlement is
  'Content-free cancellation and monetary recovery after a piece request is erased. The worker '
  'withdraws its batch before deciding unknown spend or releasing proven unsent work. Completed '
  'receipts retain identities and amounts only; no world key, request text or content digest.';
alter table piece_erasure_settlement enable row level security;
alter table piece_erasure_settlement force row level security;
create policy ws_isolation on piece_erasure_settlement
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
create trigger tg_piece_erasure_settlement_append_only before update or delete
  on piece_erasure_settlement for each row execute function tg_reconstruction_privacy_append_only();

create table piece_erasure_settlement_event (
  workspace_id uuid not null,
  piece_request_id uuid not null,
  kind text not null check (kind in ('withdrawn', 'decided', 'settled')),
  basis text check (basis in ('reported', 'unknown', 'not_sent')),
  usd numeric(14,8) check (usd >= 0),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, piece_request_id, kind),
  foreign key (workspace_id,piece_request_id)
    references piece_erasure_settlement (workspace_id,piece_request_id),
  check ((kind = 'decided') = (basis is not null)),
  check ((basis is null) = (usd is null)),
  check (basis <> 'not_sent' or usd = 0)
);
comment on table piece_erasure_settlement_event is
  'Append-only progress for an erased request''s obligation: GPU withdrawal before a monetary '
  'decision, then settlement. Separate receipts preserve exact decisions across backup restore.';
alter table piece_erasure_settlement_event enable row level security;
alter table piece_erasure_settlement_event force row level security;
create policy ws_isolation on piece_erasure_settlement_event
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on piece_erasure_settlement
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert
  on piece_erasure_settlement_event
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

create function tg_piece_erasure_settlement_event() returns trigger
language plpgsql as $fn$
declare
  obligation piece_erasure_settlement%rowtype;
begin
  if tg_op <> 'INSERT' then
    raise exception 'an erasure settlement receipt is never changed' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  select * into obligation from piece_erasure_settlement
   where workspace_id = new.workspace_id and piece_request_id = new.piece_request_id;
  if not found then
    raise exception 'an erasure progress receipt names its obligation' using errcode = '23514';
  end if;
  if new.kind = 'decided' then
    if not exists (select 1 from piece_erasure_settlement_event
                    where workspace_id = new.workspace_id
                      and piece_request_id = new.piece_request_id and kind = 'withdrawn')
       or new.usd > obligation.worst_case_usd
       or (obligation.basis is not null
           and (new.basis,new.usd) is distinct from (obligation.basis,obligation.usd)) then
      raise exception 'an erased request is decided after withdrawal, preserving its measurement'
        using errcode = '23514';
    end if;
  elsif new.kind = 'settled' and not exists (
    select 1 from piece_erasure_settlement_event where workspace_id = new.workspace_id
      and piece_request_id = new.piece_request_id and kind = 'decided') then
    raise exception 'an erased request is decided before it is settled' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_piece_erasure_settlement_event before insert or update or delete
  on piece_erasure_settlement_event for each row execute function tg_piece_erasure_settlement_event();

-- --------------------------------------------------------------------------------------------
-- 1. Only the erasure deletes a world's records.
-- --------------------------------------------------------------------------------------------

create function tg_world_record_erased_whole() returns trigger
language plpgsql as $fn$
begin
  if current_user = 'exulanica_definer' then
    return old;
  end if;
  raise exception '% is deleted only when its world is erased whole', tg_table_name
    using errcode = '23514';
end $fn$;

comment on function tg_world_record_erased_whole() is
  'Refuses a delete of a world''s record by anybody but the definers'' owner, which deletes them '
  'in world_erase_rows and with a workspace''s kept kinds.';

-- Each table's guard keeps the events it guards besides delete: the trigger is made again with the
-- same name, function and events, but delete.
do $$
declare
  t record;
begin
  for t in
    select * from (values
      ('companion_answer_simulation_citation',
       'tg_companion_answer_simulation_citation_append_only',
       'update', 'tg_companion_memory_append_only'),
      ('companion_answer_simulation_label',
       'tg_companion_answer_simulation_label_append_only',
       'update', 'tg_companion_memory_append_only'),
      ('door_delivery', 'door_delivery_append_only', 'update', 'tg_door_append_only'),
      ('door_grant', 'door_grant_append_only', 'update', 'tg_door_append_only'),
      ('door_grant_revision', 'door_grant_revision_append_only', 'update', 'tg_door_append_only'),
      ('door_grant_revocation',
       'door_grant_revocation_append_only',
       'update', 'tg_door_append_only'),
      ('door_presence', 'tg_door_presence_change', 'update', 'tg_door_presence_change'),
      ('door_secret', 'tg_door_secret_change', 'insert or update', 'tg_door_secret_change'),
      ('door_visitor_gone', 'door_visitor_gone_append_only', 'update', 'tg_door_append_only'),
      ('saved_world_source_attachment',
       'tg_saved_world_source_attachment_append_only',
       'update', 'tg_saved_world_source_attachment_append_only'),
      ('saved_world_source_attachment_operation',
       'tg_saved_world_source_attachment_operation_append_only',
       'update', 'tg_saved_world_source_attachment_append_only'),
      ('saved_world_source_current_membership',
       'tg_saved_world_source_current_membership_guard',
       'insert or update', 'tg_saved_world_source_current_membership_guard'),
      ('saved_world_source_detach',
       'tg_saved_world_source_detach_append_only',
       'update', 'tg_saved_world_source_membership_event_append_only'),
      ('saved_world_source_detach_operation',
       'tg_saved_world_source_detach_operation_append_only',
       'update', 'tg_saved_world_source_membership_event_append_only'),
      ('signal_comparison',
       'signal_comparison_append_only',
       'update', 'tg_signal_comparison_append_only'),
      ('signal_comparison_decision',
       'signal_comparison_decision_append_only',
       'update', 'tg_signal_comparison_append_only'),
      ('signal_comparison_outcome',
       'signal_comparison_outcome_append_only',
       'update', 'tg_signal_comparison_append_only'),
      ('signal_comparison_run',
       'signal_comparison_run_append_only',
       'update', 'tg_signal_comparison_append_only'),
      ('signal_comparison_start',
       'tg_signal_comparison_start_guard',
       'update', 'tg_signal_comparison_start_guard'),
      ('world_alternate_version_edit',
       'tg_world_alternate_version_edit_append_only',
       'update', 'tg_world_alternate_append_only'),
      ('world_generation_receipt',
       'tg_world_generation_receipt_append_only',
       'update', 'tg_reconstruction_privacy_append_only'),
      ('world_identity',
       'tg_world_identity_append_only',
       'update', 'tg_reconstruction_privacy_append_only'),
      ('world_interaction_policy_audit_event',
       'tg_world_interaction_policy_audit_event_append_only',
       'update', 'tg_interaction_append_only'),
      ('world_interaction_policy_version',
       'tg_world_interaction_policy_version_append_only',
       'update', 'tg_interaction_append_only'),
      ('world_kind_version',
       'tg_world_kind_version_append_only',
       'update', 'tg_reconstruction_privacy_append_only'),
      ('world_package_export',
       'tg_world_package_export_append_only',
       'update', 'tg_world_package_export_append_only'),
      ('world_project_binding',
       'tg_world_project_binding_append_only',
       'update', 'tg_world_project_append_only'),
      ('world_project_item_source',
       'tg_world_project_item_source_append_only',
       'update', 'tg_world_project_append_only'),
      ('world_region_style_version',
       'tg_world_region_style_version_append_only',
       'update', 'tg_world_append_only'),
      ('world_structure_audit_event',
       'tg_world_structure_audit_event_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_dependency',
       'tg_world_structure_dependency_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_element_identity',
       'tg_world_structure_element_identity_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_invalidation',
       'tg_world_structure_invalidation_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_placement_migration',
       'tg_world_structure_placement_migration_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_snapshot',
       'tg_world_structure_snapshot_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_snapshot_element',
       'tg_world_structure_snapshot_element_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_structure_snapshot_region',
       'tg_world_structure_snapshot_region_append_only',
       'update', 'tg_world_structure_append_only'),
      ('world_style_audit_event',
       'tg_world_style_audit_event_append_only',
       'update', 'tg_world_append_only'),
      ('world_style_version',
       'tg_world_style_version_append_only',
       'update', 'tg_world_append_only'),
      ('world_thing_look',
       'tg_world_thing_look_append_only',
       'update', 'tg_world_thing_look_append_only'),
      ('world_topology_contract',
       'tg_world_topology_contract_append_only',
       'update', 'tg_world_append_only'),
      ('world_topology_region',
       'tg_world_topology_region_append_only',
       'update', 'tg_world_append_only'),
      ('world_topology_source',
       'tg_world_topology_source_append_only',
       'update', 'tg_world_append_only'),
      ('world_traffic_signal_choice',
       'world_traffic_signal_choice_append_only',
       'update', 'tg_world_traffic_signal_append_only'),
      ('world_traffic_signal_decision',
       'world_traffic_signal_decision_append_only',
       'update', 'tg_world_traffic_signal_append_only'),
      ('world_traffic_signal_decision_request',
       'world_traffic_signal_decision_request_append_only',
       'update', 'tg_world_traffic_signal_append_only'),
      ('world_traffic_signal_segment',
       'world_traffic_signal_segment_append_only',
       'update', 'tg_world_traffic_signal_append_only')
    ) as guards(tab, name, events, fn)
  loop
    execute format('drop trigger %I on %I', t.name, t.tab);
    execute format('create trigger %I before %s on %I for each row execute function %I()',
                   t.name, t.events, t.tab, t.fn);
  end loop;
end $$;

-- These guarded delete alone, and the new guard takes it.
drop trigger tg_world_alternate_version_no_delete on world_alternate_version;
drop trigger tg_world_project_no_delete on world_project;
drop trigger tg_world_project_item_no_delete on world_project_item;
drop trigger tg_world_project_item_revision_no_delete on world_project_item_revision;
drop trigger tg_world_project_share_no_delete on world_project_share;
drop function tg_world_alternate_version_no_delete();

-- The new guard, on every table the erasure deletes from but world_minds_budget.
do $$
declare
  t text;
begin
  foreach t in array array[
    'companion_answer_simulation_citation', 'companion_answer_simulation_label', 'door_delivery',
    'door_grant', 'door_grant_revision', 'door_grant_revocation', 'door_presence', 'door_secret',
    'door_visitor_gone', 'piece_look_step', 'piece_request', 'piece_settlement',
    'saved_world_entry', 'saved_world_source_attachment',
    'saved_world_source_attachment_operation', 'saved_world_source_current_membership',
    'saved_world_source_detach', 'saved_world_source_detach_operation', 'signal_comparison',
    'signal_comparison_decision', 'signal_comparison_outcome', 'signal_comparison_run',
    'signal_comparison_start', 'world_alternate_element_override',
    'world_alternate_environment_instance', 'world_alternate_object',
    'world_alternate_point_map_instance', 'world_alternate_thing', 'world_alternate_version',
    'world_alternate_version_edit', 'world_generation_receipt', 'world_identity',
    'world_interaction_policy_audit_event', 'world_interaction_policy_preview',
    'world_interaction_policy_proposal', 'world_interaction_policy_state',
    'world_interaction_policy_version', 'world_kind_version', 'world_package_export',
    'world_project', 'world_project_binding', 'world_project_item', 'world_project_item_revision',
    'world_project_item_source', 'world_project_share', 'world_region_style_version',
    'world_structure_audit_event', 'world_structure_dependency',
    'world_structure_element_identity', 'world_structure_invalidation',
    'world_structure_placement_migration', 'world_structure_preview', 'world_structure_snapshot',
    'world_structure_snapshot_element', 'world_structure_snapshot_region',
    'world_structure_state', 'world_style_audit_event', 'world_style_preview',
    'world_style_proposal', 'world_style_state', 'world_style_version', 'world_thing_look',
    'world_topology_contract', 'world_topology_region', 'world_topology_source',
    'world_traffic_signal_choice', 'world_traffic_signal_decision',
    'world_traffic_signal_decision_request', 'world_traffic_signal_segment'
  ] loop
    execute format('create trigger tg_world_record_erased_whole before delete on %I '
                   'for each row execute function tg_world_record_erased_whole()', t);
  end loop;
end $$;

-- An erasure's record outlives the world it names.
alter table society_erasure drop constraint society_erasure_world_is_registered;

comment on table society_erasure is
  'A workspace''s erasure of one society of a world, naming the society, its world version and '
  'the society tombstone written with it; its trigger deletes every row that records the '
  'society, and a restore carries it. It names its world by id and outlives it. Appended; never '
  'updated or deleted.';

-- --------------------------------------------------------------------------------------------
-- 2. The erasure.
-- --------------------------------------------------------------------------------------------

-- Every row of one world, children first, in the workspace the session is in.
create function world_erase_rows(p_workspace uuid, p_world text) returns void
language plpgsql security definer as $fn$
declare
  v_society uuid;
begin
  perform assert_workspace_context(p_workspace);
  -- Every parent a writer without the workspace lock adds to or changes, before the first
  -- delete, in the order those writers take them (LOCKS).
  perform pg_advisory_xact_lock(hashtextextended('world_project:' || p_workspace::text, 0));
  perform 1 from world_project x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.project_id for update;
  perform 1 from world_project_item x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.item_id for update;
  perform 1 from saved_world_entry x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.entry_id for update;
  perform 1 from world_alternate_version x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.version_id for update;
  perform 1 from world_style_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_style_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from world_structure_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_structure_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from world_interaction_policy_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_interaction_policy_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from piece_request x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.piece_request_id for update;
  perform 1 from signal_comparison_start x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.comparison_id for update;
  perform 1 from signal_comparison_run x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.run_id for update;
  -- The world's societies, each whole and with its own locks (0183).
  for v_society in
    select s.society_id from world_society s
     where s.workspace_id = p_workspace and s.world_id = p_world
     order by s.society_id
  loop
    perform society_erase_rows(p_workspace, v_society);
  end loop;
  perform 1 from door_grant x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.grant_id for update;
  -- Every world table references the registration: from here no row is added under the world.
  perform 1 from world_identity x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  insert into piece_erasure_settlement
    (workspace_id,piece_request_id,reservation_id,reservation_authority_id,reservation_holder,
     piece_batch_id,worst_case_usd,basis,usd)
    select p.workspace_id,p.piece_request_id,p.reservation_id,p.reservation_authority_id,
           p.reservation_holder,p.piece_batch_id,p.worst_case_usd,s.basis,s.usd
      from piece_request p left join piece_settlement s
        on s.workspace_id = p.workspace_id and s.piece_request_id = p.piece_request_id
     where p.workspace_id = p_workspace and p.world_id = p_world
       and p.reservation_id is not null and s.settled_at is null
    on conflict (workspace_id,piece_request_id) do nothing;
  -- Every table that names the world, in the order its foreign keys allow.
  -- Layer 0.
  -- A label is the name or the spot a placeholder stood for in a Companion answer, and has no
  -- key to a world (0127): the labels of the answers that cite this world, and any that names
  -- one of its versions.
  delete from companion_answer_simulation_label x
   where x.workspace_id = p_workspace
     and (x.answer_id in (select c.answer_id from companion_answer_simulation_citation c
                           where c.workspace_id = p_workspace and c.world_id = p_world)
          or x.version_id in (select k.version_id from world_alternate_version k
                               where k.workspace_id = p_workspace and k.world_id = p_world));
  delete from companion_answer_simulation_citation x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from comparison_cancellation x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from comparison_run_start x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from door_answer x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_crossing_binding x
   using door_crossing c
   where x.workspace_id = p_workspace and c.workspace_id = p_workspace
     and c.society_id = x.society_id and c.crossing_id = x.crossing_id
     and c.grant_id in (select k.grant_id from door_grant k
                         where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_delivery x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_grant_revision x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_grant_revocation x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_presence x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_secret x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_visitor_gone x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_look_step x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from piece_output x
   where x.workspace_id = p_workspace
     and x.piece_request_id in (select k.piece_request_id from piece_request k
                              where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_settlement x
   where x.workspace_id = p_workspace
     and x.piece_request_id in (select k.piece_request_id from piece_request k
                              where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_current_membership x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_detach x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from signal_comparison_outcome x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from signal_comparison_start x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_hour x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_outcome x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_replay x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_start x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_checkpoint x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from society_experiment_outcome x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_alternate_element_override x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_environment_instance x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_object x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_point_map_instance x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_version_edit x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_character_appearance_revision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock_event x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock_traffic_minute x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_crossing_occupancy x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_generation_receipt x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_audit_event x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_state x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_minds_budget x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_package_export x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_binding x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_item_revision x
   where x.workspace_id = p_workspace
     and x.item_id in (select k.item_id from world_project_item k
                     where k.workspace_id = p_workspace and k.world_id = p_world);
  -- A source link names its own item and, where it was copied from one, that item too; either
  -- may be this world's.
  delete from world_project_item_source x
   where x.workspace_id = p_workspace
     and (x.item_id in (select k.item_id from world_project_item k
                         where k.workspace_id = p_workspace and k.world_id = p_world)
          or x.source_item_id in (select k.item_id from world_project_item k
                                   where k.workspace_id = p_workspace and k.world_id = p_world));
  delete from world_project_share x
   where x.workspace_id = p_workspace
     and x.project_id in (select k.project_id from world_project k
                        where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_region_style_version x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_society_model_choice x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_society_person_answer x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_audit_event x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_dependency x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_invalidation x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_placement_migration x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_state x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_audit_event x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_state x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_thing_look x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_source x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_segment x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 1.
  delete from door_ask x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_crossing x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_request x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from saved_world_source_attachment x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_detach_operation x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison_run x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_run x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_attempt x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_alternate_thing x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_version x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_item x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_preview x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_snapshot_element x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_preview x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_region x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_decision_request x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 2.
  delete from door_grant x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from saved_world_source_attachment_operation x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_definition x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_proposal x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_element_identity x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_snapshot_region x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_choice x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 3.
  delete from saved_world_entry x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 4.
  delete from world_society x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 5.
  delete from world_alternate_version x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 6.
  delete from world_structure_snapshot x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_version x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 7.
  delete from world_style_proposal x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_contract x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 8.
  delete from world_identity x where x.workspace_id = p_workspace and x.world_id = p_world;
end $fn$;

comment on function world_erase_rows(uuid, text) is
  'Every row of one world, children first: its societies, what names the world in every table, '
  'and its registration last. Runs as exulanica_definer, in the session''s own workspace; for '
  'the erasure triggers alone.';

-- A workspace tombstone erases every world the workspace holds, and then the kinds it kept,
-- which are no one world's.
create function tg_world_erases_on_tombstone() returns trigger
language plpgsql security definer as $fn$
declare
  v_world text;
begin
  if new.scope::text <> 'workspace' then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  for v_world in
    select w.world_id from world_identity w where w.workspace_id = new.workspace_id
     order by w.world_id
  loop
    perform world_erase_rows(new.workspace_id, v_world);
  end loop;
  delete from world_kind_version x where x.workspace_id = new.workspace_id;
  return new;
end $fn$;

comment on function tg_world_erases_on_tombstone() is
  'A workspace tombstone''s erasure of every world the workspace holds, at once, and of the '
  'kinds it kept. Runs as exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_world_erases_on_tombstone
  after insert on tombstone
  for each row execute function tg_world_erases_on_tombstone();

-- --------------------------------------------------------------------------------------------
-- 3. Workspaces erased before this migration (above).
-- --------------------------------------------------------------------------------------------

-- These statements read every workspace: row_security is off and FORCE is lifted on each table
-- they touch, so filtering would raise rather than skip a row, and every guard that refuses a
-- delete is disabled for the deletes alone, whichever migration made it. Children first: the
-- tables world_erase_rows deletes from and those of each society, in one order.
-- Flush each foreign-key check at its statement, before the table's guards are restored.
-- Deferred constraint-trigger events would otherwise prevent ALTER TABLE on a populated table.
-- The sweep deletes children before parents, so every intermediate statement satisfies its keys.
set constraints all immediate;
set local row_security = off;
alter table tombstone no force row level security;
-- Preserve obligations before the historical sweep removes their source rows. These tables
-- all force RLS; lift it for the schema owner's cross-workspace backfill and restore it at once.
alter table piece_request no force row level security;
alter table piece_settlement no force row level security;
alter table piece_erasure_settlement no force row level security;
  insert into piece_erasure_settlement
    (workspace_id,piece_request_id,reservation_id,reservation_authority_id,reservation_holder,
     piece_batch_id,worst_case_usd,basis,usd)
    select p.workspace_id,p.piece_request_id,p.reservation_id,p.reservation_authority_id,
           p.reservation_holder,p.piece_batch_id,p.worst_case_usd,s.basis,s.usd
      from piece_request p left join piece_settlement s
        on s.workspace_id = p.workspace_id and s.piece_request_id = p.piece_request_id
     where exists (select 1 from tombstone t where t.workspace_id = p.workspace_id
                      and t.scope::text = 'workspace' and t.effective_at <= now())
       and p.reservation_id is not null and s.settled_at is null
    on conflict (workspace_id,piece_request_id) do nothing;
alter table piece_request force row level security;
alter table piece_settlement force row level security;
alter table piece_erasure_settlement force row level security;
do $$
declare
  t text;
  g text;
  v_guards text[];
  v_forced boolean;
begin
  foreach t in array array[
    'companion_answer_simulation_label', 'world_kind_version',
    'companion_answer_simulation_citation', 'comparison_cancellation', 'comparison_run_start',
    'door_answer', 'door_crossing_binding', 'door_delivery', 'door_grant_revision',
    'door_grant_revocation', 'door_presence', 'door_secret', 'door_visitor_gone',
    'piece_look_step', 'piece_output', 'piece_settlement',
    'saved_world_source_current_membership', 'saved_world_source_detach',
    'signal_comparison_decision', 'signal_comparison_outcome', 'signal_comparison_start',
    'society_comparison_decision', 'society_comparison_hour', 'society_comparison_outcome',
    'society_comparison_replay', 'society_comparison_start', 'society_experiment_checkpoint',
    'society_experiment_outcome', 'world_alternate_element_override',
    'world_alternate_environment_instance', 'world_alternate_object',
    'world_alternate_point_map_instance', 'world_alternate_version_edit',
    'world_character_appearance_revision', 'world_clock', 'world_clock_event',
    'world_clock_traffic_minute', 'world_crossing_occupancy', 'world_generation_receipt',
    'world_interaction_policy_audit_event', 'world_interaction_policy_state',
    'world_minds_budget', 'world_package_export', 'world_project_binding',
    'world_project_item_revision', 'world_project_item_source', 'world_project_share',
    'world_region_style_version', 'world_society_control_event', 'world_society_model_choice',
    'world_society_person_answer', 'world_society_presence', 'world_society_transition_action',
    'world_society_transition_decision', 'world_structure_audit_event',
    'world_structure_dependency', 'world_structure_invalidation',
    'world_structure_placement_migration', 'world_structure_state', 'world_style_audit_event',
    'world_style_state', 'world_thing_look', 'world_topology_source',
    'world_traffic_signal_decision', 'world_traffic_signal_segment', 'door_ask', 'door_crossing',
    'piece_request', 'saved_world_source_attachment', 'saved_world_source_detach_operation',
    'signal_comparison_run', 'society_comparison_run', 'society_experiment_attempt',
    'world_alternate_thing', 'world_interaction_policy_preview',
    'world_interaction_policy_version', 'world_project_item', 'world_society_action_request',
    'world_society_control', 'world_society_decision', 'world_society_event',
    'world_society_transition', 'world_structure_preview', 'world_structure_snapshot_element',
    'world_style_preview', 'world_topology_region', 'world_traffic_signal_decision_request',
    'door_grant', 'saved_world_source_attachment_operation', 'signal_comparison',
    'society_comparison', 'society_experiment_definition', 'world_interaction_policy_proposal',
    'world_project', 'world_society_decision_request', 'world_structure_element_identity',
    'world_structure_snapshot_region', 'world_traffic_signal_choice', 'saved_world_entry',
    'world_society_input', 'world_society', 'world_alternate_version', 'world_structure_snapshot',
    'world_style_version', 'world_style_proposal', 'world_topology_contract', 'world_identity'
  ] loop
    select c.relforcerowsecurity into v_forced from pg_class c
     where c.oid = format('%I.%I', current_schema(), t)::regclass;
    if v_forced then
      execute format('alter table %I no force row level security', t);
    end if;
    select coalesce(array_agg(tg.tgname order by tg.tgname), '{}') into v_guards
      from pg_trigger tg
     where tg.tgrelid = format('%I.%I', current_schema(), t)::regclass
       and not tg.tgisinternal and tg.tgenabled <> 'D'
       and (tg.tgtype & 2) <> 0 and (tg.tgtype & 8) <> 0;
    foreach g in array v_guards loop
      execute format('alter table %I disable trigger %I', t, g);
    end loop;
    execute format(
      'delete from %I x where exists (select 1 from tombstone tb '
      'where tb.workspace_id = x.workspace_id and tb.scope = ''workspace'' '
      'and tb.effective_at <= now())', t);
    foreach g in array v_guards loop
      execute format('alter table %I enable trigger %I', t, g);
    end loop;
    if v_forced then
      execute format('alter table %I force row level security', t);
    end if;
  end loop;
end $$;
alter table tombstone force row level security;
set local row_security = on;

-- --------------------------------------------------------------------------------------------
-- 4. The two definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ begin
  execute format('alter function world_erase_rows(uuid, text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_world_erases_on_tombstone() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function world_erase_rows(uuid, text) from public;
revoke all on function tg_world_erases_on_tombstone() from public;

-- The deletes and the reads they make. The society tables' and piece_output's are 0182's and
-- 0175's grants; world_minds_budget's is the migration's that lets the definer delete it.
grant select, delete on
  companion_answer_simulation_citation, companion_answer_simulation_label, door_delivery,
  door_grant, door_grant_revision, door_grant_revocation, door_presence, door_secret,
  door_visitor_gone, piece_look_step, piece_request, piece_settlement, saved_world_entry,
  saved_world_source_attachment, saved_world_source_attachment_operation,
  saved_world_source_current_membership, saved_world_source_detach,
  saved_world_source_detach_operation, signal_comparison, signal_comparison_decision,
  signal_comparison_outcome, signal_comparison_run, signal_comparison_start,
  world_alternate_element_override, world_alternate_environment_instance, world_alternate_object,
  world_alternate_point_map_instance, world_alternate_thing, world_alternate_version,
  world_alternate_version_edit, world_generation_receipt, world_identity,
  world_interaction_policy_audit_event, world_interaction_policy_preview,
  world_interaction_policy_proposal, world_interaction_policy_state,
  world_interaction_policy_version, world_kind_version, world_package_export, world_project,
  world_project_binding, world_project_item, world_project_item_revision,
  world_project_item_source, world_project_share, world_region_style_version,
  world_structure_audit_event, world_structure_dependency, world_structure_element_identity,
  world_structure_invalidation, world_structure_placement_migration, world_structure_preview,
  world_structure_snapshot, world_structure_snapshot_element, world_structure_snapshot_region,
  world_structure_state, world_style_audit_event, world_style_preview, world_style_proposal,
  world_style_state, world_style_version, world_thing_look, world_topology_contract,
  world_topology_region, world_topology_source, world_traffic_signal_choice,
  world_traffic_signal_decision, world_traffic_signal_decision_request,
  world_traffic_signal_segment
  to exulanica_definer;
grant select, insert on piece_erasure_settlement to exulanica_definer;
do $$ declare r text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on piece_erasure_settlement to %I', r);
      execute format('grant select, insert on piece_erasure_settlement_event to %I', r);
    end if;
  end loop;
  if exists (select 1 from pg_roles where rolname = 'exulanica_ro') then
    grant select on piece_erasure_settlement, piece_erasure_settlement_event to exulanica_ro;
  end if;
end $$;

-- A row lock needs UPDATE on a column of its table: workspace_id, which no body writes. The
-- owner already updates a project and its items (0127), so those two need no more.
grant update (workspace_id) on saved_world_entry, world_alternate_version, world_style_state,
  world_style_preview, world_structure_state, world_structure_preview,
  world_interaction_policy_state, world_interaction_policy_preview, piece_request,
  signal_comparison_start, signal_comparison_run, door_grant, world_identity
  to exulanica_definer;
alter function world_erase_rows(uuid, text) owner to exulanica_definer;
alter function tg_world_erases_on_tombstone() owner to exulanica_definer;

commit;
