-- 0213_a_placed_being_keeps_an_owner_written_character.sql
-- Who a placed being is, as the world's owner writes it: a name, a few words about it, or both.
--
-- A CHARACTER IS WRITTEN BESIDE A THING, NEVER IN IT. What a being is and does is its kind's and the
-- society's. Who it is, for whoever decides for it, is fiction its world's owner writes. So a
-- character lives here, beside the placed thing (0152), as a look choice does (0156), and reaches a
-- society only through the society's input, and only a society whose first input records the
-- character module (exulanica-ability/character/v1): the application copies the newest character of
-- each placed being into such a society's next input (exulanica/api/society_runtime.py). Nothing
-- derives one from a photograph, a kind's description or a person.
--
-- WHAT IS WRITTEN. An optional name of 1 to 40 characters and an optional text about the being of 1 to
-- 300, each with no white space at either end. A record holding neither clears the character. The
-- application holds each to the line rule and refuses any name the account holder saved
-- (exulanica/world/thing_characters.py); this table holds the bounds a database can state.
--
-- WHO WROTE IT, AND OVER WHAT. Records are appended and never changed: the newest per thing is its
-- character, and the history stays. Each names the actor who wrote it and the record it replaced
-- (base_revision, null for the first). Only the newest may be replaced: a record naming an older one
-- is refused, and of two writers that read the same one, the unique index keeps the first to commit.
--
-- ERASURE. A world's records are deleted with the world: world_erase_rows (0195), which a world's
-- erasure (0197) and a workspace's tombstone run, is made again here with one statement more,
-- deleting them beside the world's look choices, before the things and versions they name. Its
-- name, signature, owner, path and grants stay as they were (0183's way of replacing a definer).

begin;
select pg_advisory_xact_lock(119622309);

create table world_thing_character (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  revision bigint generated always as identity,
  placed_id text not null check(placed_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),
  name text check(
    name is null
    or (char_length(name) between 1 and 40 and name !~ '^[[:space:]]|[[:space:]]$')
  ),
  about text check(
    about is null
    or (char_length(about) between 1 and 300 and about !~ '^[[:space:]]|[[:space:]]$')
  ),
  base_revision bigint check(base_revision is null or base_revision >= 1),
  actor uuid not null,
  written_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,revision),
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,world_id,version_id,placed_id)
    references world_alternate_thing(workspace_id,world_id,version_id,thing_id)
);

-- One record replaces any one record, so two writers that read the same newest record cannot both
-- append after it.
create unique index world_thing_character_one_successor
  on world_thing_character(workspace_id,world_id,version_id,placed_id,coalesce(base_revision,0));

-- The newest record per thing, read by a version.
create index world_thing_character_latest
  on world_thing_character(workspace_id,world_id,version_id,placed_id,revision desc);

create function tg_world_thing_character_binding() returns trigger language plpgsql as $fn$
declare
  newest bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select max(c.revision) into newest from world_thing_character c
   where c.workspace_id=new.workspace_id and c.world_id=new.world_id
     and c.version_id=new.version_id and c.placed_id=new.placed_id;
  if new.base_revision is distinct from newest then
    raise exception 'a character replaces the newest one written for its thing'
      using errcode='23514';
  end if;
  return new;
end $fn$;

create trigger tg_world_thing_character_binding
before insert on world_thing_character
for each row execute function tg_world_thing_character_binding();

create function tg_world_thing_character_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'a character is appended and never changed' using errcode='23514';
end $fn$;

create trigger tg_world_thing_character_append_only
before update on world_thing_character
for each row execute function tg_world_thing_character_append_only();

-- Deleted only by the definers' owner, when its world is erased whole (0195's rule).
create trigger tg_world_record_erased_whole
before delete on world_thing_character
for each row execute function tg_world_record_erased_whole();

alter table world_thing_character enable row level security;
alter table world_thing_character force row level security;
create policy ws_isolation on world_thing_character
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

create or replace function world_erase_rows(p_workspace uuid, p_world text) returns void
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
  delete from world_thing_character x
   where x.workspace_id = p_workspace and x.world_id = p_world;
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

do $$ begin
  execute format('alter function world_erase_rows(uuid, text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function world_erase_rows(uuid, text) from public;
grant select, delete on world_thing_character to exulanica_definer;
alter function world_erase_rows(uuid, text) owner to exulanica_definer;

commit;
