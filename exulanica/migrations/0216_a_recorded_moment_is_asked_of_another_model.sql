-- 0216_a_recorded_moment_is_asked_of_another_model.sql
-- The same recorded moment, asked of another model, and kept beside the answer the world used.
--
-- A recorded decision request (0055) holds what a character was told and the options it had, and
-- its one receipt is the answer the society took up. A person may ask another model the identical
-- request: the same context and options, sent by the same role under the same terms, so the
-- messages the first model read are proved again by their digest before anything is sent. Each
-- such ask is a row here: the model asked, by its own answering mechanism; the digest of what it
-- was sent, and of what the first model was sent; the spending bound it was asked under; and its
-- answer as a live answer is recorded (status, reason, the proposal it chose and the provider's
-- record of the calls, their tokens, cost and latency). An ask is never applied: nothing here is
-- read by a society's minute, its inputs or its transitions.
--
-- WHO ASKED, AND OVER WHAT. Rows are appended and never changed. Each names the request it asks
-- again and the actor who asked; an idempotency key, where given, names one ask per actor.
--
-- ERASURE. An ask is a record of its society: deleted only by the definers' owner, in
-- society_erase_rows, which a society's erasure, its world's and a workspace's tombstone run. The
-- function is made again here with one statement more, deleting the asks before the requests
-- they name; its name, signature, owner and grants stay as they were, and its search path, which a
-- replacement clears, is set again as 0183 set it. A writer of an ask takes the request's key
-- share by its foreign key, so it waits for, or fails against, the erasure's lock on the request.
begin;
select pg_advisory_xact_lock(119622309);

create table world_society_decision_ask (
  workspace_id    uuid not null,
  society_id      uuid not null,
  request_id      uuid not null,
  ask_id          uuid not null default uuidv7(),
  asked_by        uuid not null,
  idempotency_key uuid,
  provider        text not null check (provider ~ '^[a-z][a-z0-9_]{0,63}$'),
  model_id        text not null check (char_length(model_id) between 1 and 200),
  mechanism       text not null check (mechanism ~ '^[a-z][a-z0-9_]{0,63}$'),
  prompt_version  text not null check (char_length(prompt_version) between 1 and 100),
  -- What this ask sent, and what the first model was sent, each as the role's first messages.
  messages_sha256         text not null check (messages_sha256 ~ '^[0-9a-f]{64}$'),
  request_messages_sha256 text not null check (request_messages_sha256 ~ '^[0-9a-f]{64}$'),
  bound_id        uuid,
  bound_usd       numeric(12, 8) not null check (bound_usd > 0 and bound_usd <= 0.1),
  status          text not null check (status in ('accepted', 'rejected', 'unavailable')),
  reason          text not null check (reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  -- The answer as a live ask returns it: {status, reason, proposal, provider}.
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  asked_at        timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, ask_id),
  constraint world_society_decision_ask_once unique (workspace_id, society_id, asked_by, idempotency_key),
  foreign key (workspace_id, society_id, request_id)
    references world_society_decision_request (workspace_id, society_id, request_id),
  check (document->>'status' is not distinct from status),
  check (document->>'reason' is not distinct from reason),
  check ((jsonb_typeof(document->'proposal') in ('object', 'null')) is true),
  check ((jsonb_typeof(document->'provider') in ('object', 'null')) is true)
);

create index world_society_decision_ask_request
  on world_society_decision_ask (workspace_id, society_id, request_id, asked_at);

comment on table world_society_decision_ask is
  'Another model asked a recorded decision request again, by the same role under the same terms, '
  'and its answer kept beside the receipt the society took up; never applied. Appended; deleted '
  'only with its society.';

create trigger tg_world_society_decision_ask_append_only
  before update on world_society_decision_ask
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_society_record_erased_whole
  before delete on world_society_decision_ask
  for each row execute function tg_society_record_erased_whole();
alter table world_society_decision_ask enable row level security;
alter table world_society_decision_ask force row level security;
create policy ws_isolation on world_society_decision_ask
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

-- The erasure's read and delete of the asks; the rest of its grants are 0182's and 0183's.
grant select, delete on world_society_decision_ask to exulanica_definer;

commit;
