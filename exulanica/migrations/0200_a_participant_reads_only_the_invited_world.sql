-- A read-only role receives explicit projected views, never a host workspace table.
begin;
select pg_advisory_xact_lock(119622309);
do $$ begin
  if not exists(select 1 from pg_roles where rolname='exulanica_participant') then
    create role exulanica_participant nologin noinherit nosuperuser nobypassrls nocreatedb nocreaterole;
  end if;
  execute format('grant usage on schema %I to exulanica_participant',current_schema());
end $$;

create function participant_scope()
returns table(workspace_id uuid,grant_id uuid,world_id text,version_id uuid,society_id uuid)
language sql stable security definer as $fn$
  select g.workspace_id,g.grant_id,g.world_id,r.version_id,s.society_id
  from world_grant g
  join lateral (select x.version_id,x.expires_at,x.document from world_grant_revision x
    where x.workspace_id=g.workspace_id and x.grant_id=g.grant_id
    order by x.grant_seq desc limit 1) r on true
  join world_grant_entry e on e.workspace_id=g.workspace_id and e.grant_id=g.grant_id
  join world_grant_principal p on p.workspace_id=g.workspace_id and p.grant_id=g.grant_id
  join world_identity w on w.workspace_id=g.workspace_id and w.world_id=g.world_id
  join world_alternate_version v on v.workspace_id=g.workspace_id and v.world_id=g.world_id
    and v.version_id=r.version_id
  join world_society s on s.workspace_id=g.workspace_id and s.world_id=g.world_id
    and s.version_id=r.version_id
  where g.workspace_id=current_workspace()
    and g.grant_id::text=nullif(current_setting('exulanica.participant_grant',true),'')
    and p.principal_sha256=nullif(current_setting('exulanica.participant_principal',true),'')
    and e.used_at is not null and e.revoked_at is null and r.expires_at>statement_timestamp()
    and w.kind in ('authored-starter','generated')
    and s.engine_version in ('exulanica-society/v6','exulanica-society/v7')
    and r.document->'role'->>'key'='observer'
    and not exists(select 1 from world_grant_revocation x
      where x.workspace_id=g.workspace_id and x.grant_id=g.grant_id)
    and not exists(select 1 from world_grant_departure x
      where x.workspace_id=g.workspace_id and x.grant_id=g.grant_id)
$fn$;
do $$ begin
  execute format('alter function participant_scope() set search_path=pg_catalog,%I,pg_temp',
                 current_schema());
end $$;
revoke all on function participant_scope() from public;
alter function participant_scope() owner to exulanica_definer;
grant execute on function participant_scope() to exulanica_participant;

-- Views remain owned by the migration's schema owner; exulanica_definer owns routines only.
-- Each view binds every base row to participant_scope. The barrier keeps caller predicates
-- outside this projection. The application additionally projects JSON before serving it.
create view participant_world with(security_barrier=true) as
  select v.version_id,v.world_id,v.source_snapshot_id,v.edit_seq,v.state_sha256,w.kind
  from participant_scope() p join world_alternate_version v
    on v.workspace_id=p.workspace_id and v.world_id=p.world_id and v.version_id=p.version_id
  join world_identity w on w.workspace_id=p.workspace_id and w.world_id=p.world_id;
create view participant_objects with(security_barrier=true) as
  select o.object_id,o.asset_sha256,o.region_id,o.x_mm,o.y_mm,o.z_mm,
    o.yaw_microradians,o.scale_milli
  from participant_scope() p join world_alternate_object o
    on o.workspace_id=p.workspace_id and o.world_id=p.world_id and o.version_id=p.version_id
  where not o.removed and o.origin_role='fictional';
create view participant_things with(security_barrier=true) as
  select t.thing_id,t.kind_source,t.kind,t.kind_version,encode(t.kind_sha256,'hex') as kind_sha256,
    t.region_id,t.x_mm,t.y_mm,t.z_mm,t.yaw_microradians
  from participant_scope() p join world_alternate_thing t
    on t.workspace_id=p.workspace_id and t.world_id=p.world_id and t.version_id=p.version_id
  where not t.removed and t.origin_role='fictional';
create view participant_society with(security_barrier=true) as
  select s.society_id,s.engine_version,s.current_tick,s.tick_seconds,
    jsonb_build_object('inhabitants',coalesce((
      select jsonb_agg(jsonb_build_object(
        'id',i->'id',
        'kind',case when i->'kind'->>'source'='workspace'
          then jsonb_build_object('source','workspace','sha256',i->'kind'->'sha256')
          else jsonb_build_object('kind',i->'kind'->'kind','version',i->'kind'->'version',
                                 'sha256',i->'kind'->'sha256') end,
        'location',jsonb_build_object('indoors',coalesce(i->'location'->'indoors','false'::jsonb)),
        'position_mm',case when i->'location'->'indoors'='true'::jsonb then 'null'::jsonb
                          else i->'position_mm' end,
        'motion_path_mm',case when i->'location'->'indoors'='true'::jsonb then '[]'::jsonb
                             else i->'motion_path_mm' end))
      from jsonb_array_elements(s.state->'inhabitants') i), '[]'::jsonb)) as state,
    s.state_sha256
  from participant_scope() p join world_society s
    on s.workspace_id=p.workspace_id and s.society_id=p.society_id;
create view participant_clock with(security_barrier=true) as
  select c.mode,c.speed,c.base_tick_interval_ms,c.next_due_at
  from participant_scope() p join world_society_control c
    on c.workspace_id=p.workspace_id and c.society_id=p.society_id;
create view participant_choices with(security_barrier=true) as
  select c.choice_seq,
    jsonb_build_object('subjects',c.document->'subjects','since_tick',c.document->'since_tick',
      'ended',c.document->'ended',
      'decider',case
        when c.document->'decider'->>'kind'='model' then
          jsonb_build_object('kind','model','provider',c.document->'decider'->'provider',
                             'model_id',c.document->'decider'->'model_id')
        when c.document->'decider'->>'kind' in ('routine','person','external') then
          jsonb_build_object('kind',c.document->'decider'->>'kind')
        when c.document->'model' is not null and c.document->'model'<>'null'::jsonb then
          jsonb_build_object('kind','model','provider',c.document->'model'->'provider',
                             'model_id',c.document->'model'->'model_id')
        else jsonb_build_object('kind','routine') end) as document
  from participant_scope() p join world_society_model_choice c
    on c.workspace_id=p.workspace_id and c.society_id=p.society_id;

grant select on participant_world,participant_objects,participant_things,participant_society,
  participant_clock,participant_choices to exulanica_participant;
-- Membership allows an explicit SET ROLE and never inherits participant authority implicitly.
do $$ begin
  if exists(select 1 from pg_roles where rolname='exulanica_app') then
    grant exulanica_participant to exulanica_app with inherit false;
  end if;
end $$;
commit;
