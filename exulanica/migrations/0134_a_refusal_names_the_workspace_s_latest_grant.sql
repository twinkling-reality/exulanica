-- 0134_a_refusal_names_the_workspace_s_latest_grant.sql
-- A spending refusal for a workspace with no live grant names the state of its latest grant.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001. Migrations 0124 and 0133 are
-- landed and stay as they are; this replaces one helper of 0124.
--
-- WHY. spending__refusal_without_grant (0124) said why a workspace holds no live grant for a
-- provider by asking whether ANY of its grants for the provider was revoked before asking whether
-- one had expired. A workspace whose current grant expired after an older grant was revoked was
-- told its allowance was revoked, naming the older grant (found by the acceptance matrix,
-- amendment A-24). Nothing was admitted that should not have been; the reason was wrong. Now the
-- reason is the state of the workspace's latest grant, read in the order spending__live_grant
-- reads grants: its authority revoked, then the grant revoked, then expired. A workspace with no
-- grant, or whose latest grant became live after spending__live_grant looked, is not granted.
--
-- REPLACED from 0124: spending__refusal_without_grant, its signature unchanged. Its callers,
-- spending_admit and spending_open_bound, are unchanged.

begin;
select pg_advisory_xact_lock(119622309);

create or replace function spending__refusal_without_grant(p_workspace uuid, p_provider text)
returns jsonb language plpgsql stable as $fn$
declare
  v_grant spending_grant;
begin
  select g.* into v_grant
    from spending_grant g
    join spending_authority a on a.authority_id = g.authority_id
   where g.workspace_id = p_workspace and g.parent_grant_id is null and a.provider = p_provider
   order by g.created_at desc, g.grant_id desc
   limit 1;
  if not found then
    return spending__refusal('spending_not_granted', 'workspace', null, null, null, null);
  end if;
  if exists (select 1 from spending_authority_revocation v
              where v.authority_id = v_grant.authority_id) then
    return spending__refusal('spending_revoked', 'authority', null, null, null, null);
  end if;
  if exists (select 1 from spending_grant_revocation v
              where v.workspace_id = v_grant.workspace_id and v.grant_id = v_grant.grant_id) then
    return spending__refusal('spending_revoked', 'workspace', null, null, null, null);
  end if;
  if v_grant.valid_until <= statement_timestamp() then
    return spending__refusal('spending_expired', 'workspace', null, null, null, null);
  end if;
  return spending__refusal('spending_not_granted', 'workspace', null, null, null, null);
end $fn$;

-- CREATE OR REPLACE keeps a function's privileges but not its settings: pin its path again, and
-- keep it from PUBLIC.
do $pin$
begin
  execute format('alter function spending__refusal_without_grant(uuid, text) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
  execute 'revoke all on function spending__refusal_without_grant(uuid, text) from public';
end $pin$;

commit;
