-- 0098_a_saved_world_s_inhabitants_keep_living.sql
-- A saved world's society survives ordinary edits, and its destinations have room.
--
-- 0094 admitted the first profile a saved world's own ground produces. Under it one turned,
-- scaled, raised or moving object, or any environment placement, made the whole input
-- unavailable, so one ordinary edit emptied the world of inhabitants. The second profile,
-- exulanica.society-input/authored-ground-v2, decides each object on its own: an object the
-- society cannot use loses its own activity and nothing else. Every activity it offers also
-- states the places its occupants stand at, so resting people no longer stand inside one
-- another. A stored authored-ground-v1 input is not touched and keeps replaying as it was
-- written.
--
-- The shape rule 0057 wrote for local records, and 0094 carried to the first authored profile,
-- applies to the second unchanged. The second also names the environment placements it did not
-- read, and that list follows the same rule: bounded, and empty whenever the input as a whole
-- is unavailable, so an unavailable input never names what it could once see.
--
-- The person whose world it is can also send its inhabitants away and bring them back. Either is
-- one recorded minute of the society: a transition with a departed or an arrived event for each
-- person, bound here to the request that asked for it. The row is append-only and names its
-- minute, so a departure is never a deletion and a return is a new arrival rather than an undo:
-- replaying to any minute before the departure still shows everybody who was there.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2')) is true);

alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile'='exulanica.society-input/authored-ground-v2'
      then jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)
    else not (document ? 'unread_placements') end
  );

create table world_society_presence (
  workspace_id uuid not null,
  society_id uuid not null,
  tick bigint not null check(tick>0),
  request_id uuid not null,
  requested_by uuid not null,
  presence text not null check(presence in ('away','here')),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,tick),
  unique(workspace_id,society_id,request_id),
  foreign key(workspace_id,society_id,tick)
    references world_society_transition(workspace_id,society_id,tick),
  check(document->>'profile' is not distinct from 'exulanica.society-presence/v1'),
  check(document->>'request_id' is not distinct from request_id::text),
  check(document->>'requested_by' is not distinct from requested_by::text),
  check(document->>'presence' is not distinct from presence),
  check(document->>'base_tick' is not distinct from (tick-1)::text),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check((document->>'base_state_sha256' ~ '^[0-9a-f]{64}$') is true)
);

-- The minute a request names must be the society's own newest one, taken from the state the
-- request was made against, by an engine that lets its people be sent away.
create function tg_world_society_presence_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; transition world_society_transition%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2') then
    raise exception 'presence requests need a society whose people can be sent away'
      using errcode='23514';
  end if;
  select * into transition from world_society_transition
    where workspace_id=new.workspace_id and society_id=new.society_id and tick=new.tick;
  if not found or held.current_tick<>new.tick
    or new.document->>'branch_id' is distinct from held.version_id::text
    or new.document->>'base_state_sha256' is distinct from transition.previous_state_sha256
  then
    raise exception 'presence request is not bound to the minute it took' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_presence_binding before insert on world_society_presence
  for each row execute function tg_world_society_presence_binding();
create trigger world_society_presence_append_only before update or delete on world_society_presence
  for each row execute function tg_world_society_event_append_only();
alter table world_society_presence enable row level security;
alter table world_society_presence force row level security;
create policy ws_isolation on world_society_presence using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- The runtime appends presence requests and never changes or removes one. Runtime roles that
-- already exist lose the grant here, as 0090 does for its append-only tables; provisioning states
-- the same rule for a role it creates.
do $$
declare r text;
begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke update,delete on world_society_presence from %I', r);
    end if;
  end loop;
end $$;

commit;
