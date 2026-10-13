-- Observer projection follows the supported things state family. No stored row changes.
begin;
select pg_advisory_xact_lock(119622309);

create or replace function participant_scope()
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
    and s.engine_version in ('exulanica-society/v7')
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


commit;
