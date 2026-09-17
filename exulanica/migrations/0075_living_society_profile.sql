-- The living society profile, exulanica-society/v4, over the existing input and transition tables.
-- V4 consumes the same authorized society inputs as v2 and v3 and records the same transition
-- receipts. Its population is sized to its place, so it may hold fewer than 100 people; every
-- earlier profile keeps its original bounds. Stored v1, v2 and v3 rows are not touched.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_engine_version_check;
alter table world_society add constraint world_society_engine_version_check
  check(engine_version in ('exulanica-society/v1','exulanica-society/v2','exulanica-society/v3',
    'exulanica-society/v4'));
alter table world_society drop constraint world_society_population_size_check;
alter table world_society add constraint world_society_population_size_check
  check((engine_version='exulanica-society/v4' and population_size between 1 and 65536)
    or (engine_version<>'exulanica-society/v4' and population_size between 100 and 512));

drop index world_society_event_legacy_unique;
drop index world_society_event_versioned_order_unique;
create unique index world_society_event_legacy_unique
  on world_society_event(workspace_id,society_id,tick,subject_id,event_kind)
  where coalesce(document->>'profile','') not in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4');
create unique index world_society_event_versioned_order_unique
  on world_society_event(workspace_id,society_id,tick,((document->>'order')::bigint))
  where document->>'profile' in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4');

create or replace function tg_world_society_input_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in
      ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4') then
    raise exception 'versioned inputs require a scoped versioned society' using errcode='23514';
  end if;
  if new.document->>'world_id' is distinct from held.world_id or
     new.document->>'version_id' is distinct from held.version_id::text then
    raise exception 'society input belongs to another world version' using errcode='23514';
  end if;
  select coalesce(max(input_seq),0) into latest_seq from world_society_input
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if new.input_seq<>latest_seq+1 then
    raise exception 'society input sequence must be contiguous' using errcode='23514';
  end if;
  return new;
end $fn$;

create or replace function tg_world_society_v2_event_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if not found then
    raise exception 'society event requires a scoped society' using errcode='23514';
  end if;
  if held.engine_version in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4') then
    if new.document->>'profile' is distinct from held.engine_version or
       new.document->>'branch_id' is distinct from held.version_id::text or
       new.document->>'subject_id' is distinct from new.subject_id::text or
       new.document->>'tick' is distinct from new.tick::text or
       new.document->'synthetic' is distinct from 'true'::jsonb or
       coalesce(new.document->>'order','') !~ '^[0-9]+$' or
       jsonb_typeof(new.document->'summary') is distinct from 'string' then
      raise exception 'versioned event identity and order must match its document' using errcode='23514';
    end if;
  elsif new.document->>'profile' in
      ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4') then
    raise exception 'v1 society cannot emit versioned events' using errcode='23514';
  end if;
  return new;
end $fn$;

commit;
