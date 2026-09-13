-- Confirmed identity between personal-memory place entities and canonical geometry places,
-- plus a relational projection of the bounded environment feature index.
begin;
select pg_advisory_xact_lock(119622309);

alter table entity
  add constraint entity_workspace_identity_uniq unique(workspace_id,entity_id);

create table place_entity_bridge_decision (
  workspace_id uuid not null,
  decision_id uuid not null default uuidv7(),
  place_id uuid not null,
  entity_id uuid not null,
  decision text not null check(decision in ('confirmed','revoked')),
  supersedes_decision_id uuid,
  decided_by uuid not null,
  reason text,
  decided_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,decision_id),
  unique(workspace_id,supersedes_decision_id),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id),
  foreign key(workspace_id,entity_id) references entity(workspace_id,entity_id),
  foreign key(workspace_id,supersedes_decision_id)
    references place_entity_bridge_decision(workspace_id,decision_id),
  check(place_id<>entity_id),
  check(reason is null or (reason=btrim(reason) and length(reason) between 1 and 1000))
);
create index place_entity_bridge_place_idx
  on place_entity_bridge_decision(workspace_id,place_id,decided_at desc);
create index place_entity_bridge_entity_idx
  on place_entity_bridge_decision(workspace_id,entity_id,decided_at desc);

create view confirmed_place_entity_bridge with (security_invoker=true) as
  select d.workspace_id,d.decision_id,d.place_id,d.entity_id,d.decided_by,d.decided_at
    from place_entity_bridge_decision d
   where d.decision='confirmed'
     and not exists(
       select 1 from place_entity_bridge_decision next
        where next.workspace_id=d.workspace_id
          and next.supersedes_decision_id=d.decision_id
     );

create function tg_place_entity_bridge_decision() returns trigger language plpgsql as $fn$
declare
  entity_record entity%rowtype;
  previous place_entity_bridge_decision%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform 1 from place
    where workspace_id=new.workspace_id and place_id=new.place_id
    for update;
  select * into entity_record from entity
    where workspace_id=new.workspace_id and entity_id=new.entity_id
    for update;
  if not found then
    raise exception 'place bridge entity is unavailable' using errcode='23503';
  end if;
  if entity_record.class<>'place' or entity_record.deleted_at is not null
    or entity_record.merged_into is not null
  then
    raise exception 'place bridge requires a live, unmerged place-class entity'
      using errcode='23514';
  end if;

  if new.supersedes_decision_id is null then
    if new.decision<>'confirmed' or exists(
      select 1 from place_entity_bridge_decision prior
       where prior.workspace_id=new.workspace_id
         and prior.place_id=new.place_id and prior.entity_id=new.entity_id
    ) then
      raise exception 'an initial place bridge decision must be a new confirmation'
        using errcode='23514';
    end if;
  else
    select * into previous from place_entity_bridge_decision
      where workspace_id=new.workspace_id
        and decision_id=new.supersedes_decision_id;
    if not found
      or previous.place_id<>new.place_id
      or previous.entity_id<>new.entity_id
      or previous.decision=new.decision
      or exists(
        select 1 from place_entity_bridge_decision later
         where later.workspace_id=new.workspace_id
           and later.supersedes_decision_id=previous.decision_id
      )
    then
      raise exception 'place bridge decisions must alternate along the current pair history'
        using errcode='23514';
    end if;
  end if;

  if new.decision='revoked' and new.supersedes_decision_id is null then
    raise exception 'place bridge revocation must supersede its confirmation'
      using errcode='23514';
  end if;
  if new.decision='confirmed' and exists(
    select 1 from confirmed_place_entity_bridge active
     where active.workspace_id=new.workspace_id
       and (active.place_id=new.place_id or active.entity_id=new.entity_id)
  ) then
    raise exception 'a place or entity already has a confirmed bridge'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_place_entity_bridge_decision
before insert on place_entity_bridge_decision
for each row execute function tg_place_entity_bridge_decision();

create function tg_place_entity_bridge_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'place bridge decisions are append-only; supersede the current decision'
    using errcode='23514';
end $fn$;
create trigger tg_place_entity_bridge_append_only
before update or delete on place_entity_bridge_decision
for each row execute function tg_place_entity_bridge_append_only();

create table environment_feature_index_entry (
  workspace_id uuid not null,
  publication_id uuid not null,
  admission_id uuid not null,
  place_id uuid not null,
  feature_id text not null check(feature_id ~ '^[0-9a-f]{32}$'),
  provider_feature_id text not null
    check(provider_feature_id=btrim(provider_feature_id) and provider_feature_id<>''),
  feature_kind text not null
    check(feature_kind in (
      'building','terrain','water','vegetation','transportation','structure','object','other'
    )),
  label text,
  render_batch_id integer check(render_batch_id is null or render_batch_id>=0),
  bbox jsonb not null check(jsonb_typeof(bbox)='array'),
  projected_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,publication_id,feature_id),
  foreign key(workspace_id,publication_id)
    references environment_feature_index_publication(workspace_id,publication_id),
  foreign key(workspace_id,admission_id)
    references environment_source_admission(workspace_id,admission_id),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id),
  check(label is null or (label=btrim(label) and length(label) between 1 and 512))
);
create index environment_feature_place_idx
  on environment_feature_index_entry(workspace_id,place_id,feature_id);

create function tg_environment_feature_entry_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists(
    select 1 from environment_feature_index_publication p
    join environment_source_admission s
      on s.workspace_id=p.workspace_id and s.admission_id=p.admission_id
    where p.workspace_id=new.workspace_id
      and p.publication_id=new.publication_id
      and p.admission_id=new.admission_id
      and s.place_id=new.place_id
  ) then
    raise exception 'environment feature projection disagrees with its publication'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_environment_feature_entry_binding
before insert on environment_feature_index_entry
for each row execute function tg_environment_feature_entry_binding();

create function tg_environment_feature_entry_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'environment feature projections are immutable'
    using errcode='23514';
end $fn$;
create trigger tg_environment_feature_entry_append_only
before update or delete on environment_feature_index_entry
for each row execute function tg_environment_feature_entry_append_only();

do $$ declare t text; begin
  foreach t in array array[
    'place_entity_bridge_decision',
    'environment_feature_index_entry'
  ] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t
    );
  end loop;
end $$;

commit;
