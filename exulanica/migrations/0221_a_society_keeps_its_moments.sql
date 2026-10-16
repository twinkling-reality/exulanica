-- 0221_a_society_keeps_its_moments.sql
-- What a world's characters did that a person would tell, kept as the minute that made it is kept.
--
-- A moment is formed from a society's own records by a versioned data rule
-- (exulanica/world/society-moment-rules.v1.json): a line said to someone (the first between two
-- characters is a meeting), a line said to everyone near, a decision to go somewhere or to leave,
-- following someone, a thing handed over. The society repository writes a minute's moments in the
-- same transaction as the minute (exulanica/world/society_moments.py), and a back-fill writes the
-- moments of minutes played before, through the replay. A moment's id is derived from its version,
-- its rule and the event it is anchored on, so both name it the same way and a second write of it is
-- nothing.
--
-- WHAT A MOMENT HOLDS. Its kind, its minute, the events it was formed from, the decision that made
-- it where one did, its subjects, and a document: who decided (a kind and, for a model, its provider
-- and id), the placed thing it happened by, the thing handed, and its scene (each person's position,
-- last path, action and partner as the live drawing reads them). No words of anyone's: a line said is
-- kept once, in its event, and the read joins it from there.
--
-- ERASURE. A moment is a record of its society: appended, never changed, and deleted only by the
-- definers' owner in society_erase_rows, which a society's erasure, its world's and a workspace's
-- tombstone run. The function is made again here with one statement more, deleting the moments
-- before the events they are anchored on; its name, signature, owner and grants stay as they were,
-- and its search path, which a replacement clears, is set again as 0183 set it.
begin;
select pg_advisory_xact_lock(119622309);

create table world_society_moment (
  workspace_id    uuid not null,
  moment_id       uuid not null,
  society_id      uuid not null,
  version_id      uuid not null,
  tick            integer not null check (tick >= 0),
  kind            text not null check (kind ~ '^[a-z][a-z_]{0,63}$'),
  rule_version    text not null check (char_length(rule_version) between 1 and 100),
  anchor_event_id uuid not null,
  event_ids       uuid[] not null check (cardinality(event_ids) between 1 and 16),
  request_id      uuid,
  subjects        uuid[] not null check (cardinality(subjects) between 1 and 8),
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, moment_id),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  foreign key (workspace_id, society_id, anchor_event_id)
    references world_society_event (workspace_id, society_id, event_id)
);

create index world_society_moment_minute
  on world_society_moment (workspace_id, society_id, tick, moment_id);
create index world_society_moment_kind
  on world_society_moment (workspace_id, society_id, kind, tick);

comment on table world_society_moment is
  'What a society''s characters did that a person would tell, formed by a versioned rule from its '
  'events and written with the minute that made it; no words of anyone''s. Appended; deleted only '
  'with its society.';

create trigger tg_world_society_moment_append_only
  before update on world_society_moment
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_society_record_erased_whole
  before delete on world_society_moment
  for each row execute function tg_society_record_erased_whole();
alter table world_society_moment enable row level security;
alter table world_society_moment force row level security;
create policy ws_isolation on world_society_moment
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

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
  delete from world_society_decision_ask x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_decision x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_decision_request x
   where x.workspace_id = p_workspace and x.society_id = p_society;
  delete from world_society_moment x
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

do $$ begin
  execute format('alter function society_erase_rows(uuid, uuid) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;

-- The erasure's read and delete of the moments; the rest of its grants are 0182's and 0183's.
grant select, delete on world_society_moment to exulanica_definer;

commit;
