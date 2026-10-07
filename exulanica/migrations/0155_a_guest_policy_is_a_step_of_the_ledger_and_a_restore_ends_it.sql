-- A guest policy is a step of the spending ledger, and a restore or a reauthorization ends it.
--
-- 0139 made the guest policy an operator's row beside the ledger. Three things followed that a
-- public server cannot keep:
--
--   1. Setting or withdrawing a policy moved neither the ledger nor its witness, so a restore that
--      lost only a policy change left the ledger in step with its witness: nothing suspended,
--      nothing was reconciled, and the replaced policy granted again. Both are now ledger steps
--      (`guest_policy_set`, `guest_policy_ended`) taken under the witness lock, as an adjustment
--      is: a restore that loses one leaves the ledger behind its witness, the authority suspends,
--      and its reconciliation is the restore's.
--   2. spending_grant_guest decided whether a policy predated a restore by reading spending_event,
--      and counted the day's grants in spending_grant. Both tables force row-level security, so
--      only an owner that bypasses it saw other workspaces' rows or the authority's own events;
--      under any other owner the day never filled and a restored policy granted. Now nothing is
--      read past row-level security: a trigger on spending_event ends every live policy of an
--      authority when it is reconciled after a restore or reauthorized, and the day's count is a
--      row of its own (`spending_guest_policy_day`), written under the state row lock.
--   3. A policy's end now records who ended it and why.
--
-- The definers' search path puts pg_catalog first, so a built-in type or operator their bodies use
-- bare always resolves to the catalog's; the schema follows for the unpinned helpers they call
-- (assert_workspace_context reads current_workspace() by its bare name). Every name the bodies use
-- themselves is qualified (0139).

begin;
select pg_advisory_xact_lock(119622309);

alter table spending_event drop constraint spending_event_kind_check;
alter table spending_event add constraint spending_event_kind_check check (kind in (
  'issued', 'adjusted', 'granted', 'authority_revoked', 'grant_revoked', 'admitted',
  'dispatched', 'settled', 'released', 'expired', 'reconciled', 'restore_reconciled',
  'reauthorized', 'guest_policy_set', 'guest_policy_ended'));

alter table spending_guest_policy drop constraint spending_guest_policy_ended_as_check;
alter table spending_guest_policy
  add column ended_by     text check (ended_by ~ '^[a-z0-9:._-]{1,64}$'),
  add column ended_reason text check (length(ended_reason) between 1 and 500),
  add constraint spending_guest_policy_ended_as_check
    check (ended_as in ('replaced', 'withdrawn', 'restored', 'reauthorized')),
  add constraint spending_guest_policy_ended_with_its_reason
    check ((ended_at is null) = (ended_by is null) and (ended_at is null) = (ended_reason is null))
    not valid;
-- A policy ended under 0139 has no recorded person or reason; one ended from here on has both.
update spending_guest_policy set ended_by = 'unrecorded', ended_reason = 'ended before 0155'
 where ended_at is not null and ended_by is null;
alter table spending_guest_policy validate constraint spending_guest_policy_ended_with_its_reason;

create or replace function tg_spending_guest_policy_terms() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a guest policy is retained' using errcode = '23514';
  end if;
  if (to_jsonb(new) - 'ended_at' - 'ended_as' - 'ended_by' - 'ended_reason')
       is distinct from (to_jsonb(old) - 'ended_at' - 'ended_as' - 'ended_by' - 'ended_reason')
     or (old.ended_at is not null
         and (new.ended_at, new.ended_as, new.ended_by, new.ended_reason)
           is distinct from (old.ended_at, old.ended_as, old.ended_by, old.ended_reason)) then
    raise exception 'a guest policy''s terms never change; set another, which replaces it'
      using errcode = '23514';
  end if;
  return new;
end $fn$;

-- How many workspaces a policy granted in one UTC day. No row-level security: it names no
-- workspace, and spending_grant_guest reads and writes it under the authority's state row lock
-- whoever owns the function. Only the owner holds anything on it.
create table spending_guest_policy_day (
  policy_id uuid not null references spending_guest_policy(policy_id),
  grant_day date not null,
  grants    integer not null check (grants >= 1),
  primary key (policy_id, grant_day)
);

create function tg_spending_guest_policy_day_rises() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' or new.policy_id is distinct from old.policy_id
     or new.grant_day is distinct from old.grant_day or new.grants < old.grants then
    raise exception 'a guest policy''s day of grants only rises' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_guest_policy_day_rises before update or delete
  on spending_guest_policy_day for each row execute function tg_spending_guest_policy_day_rises();

do $create$
begin
  -- The operator's: set the authority's guest policy, ending the one it replaces, as a step of
  -- the ledger under the witness lock (spending__admin_lock), refused while the authority is
  -- suspended: a restore is reconciled before a policy is set again.
  execute format($body$
create or replace function %1$I.spending_set_guest_policy(
  p_authority_id uuid, p_ceiling_usd numeric, p_max_calls integer, p_valid_for interval,
  p_grants_per_day integer, p_created_by text, p_reason text, p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_state %1$I.spending_authority_state := %1$I.spending__admin_lock(p_authority_id, p_witness);
  v_policy uuid;
  v_ended uuid;
begin
  perform %1$I.spending__require_admin();
  if v_state.suspended_reason is not null then
    raise exception 'the authority is suspended (%%): reconcile or reauthorize it first',
      v_state.suspended_reason using errcode = '55000';
  end if;
  update %1$I.spending_guest_policy
     set ended_at = pg_catalog.statement_timestamp(), ended_as = 'replaced',
         ended_by = p_created_by, ended_reason = 'replaced: ' || p_reason
   where authority_id = p_authority_id and ended_at is null
  returning policy_id into v_ended;
  insert into %1$I.spending_guest_policy (authority_id, ceiling_usd, max_calls, valid_for,
                                          grants_per_day, created_by, reason)
  values (p_authority_id, pg_catalog.round(p_ceiling_usd, 8), p_max_calls, p_valid_for,
          p_grants_per_day, p_created_by, p_reason)
  returning policy_id into v_policy;
  perform %1$I.spending__append(p_authority_id, null, 'guest_policy_set',
    pg_catalog.jsonb_build_object(
      'policy_id', v_policy::text, 'replaced', v_ended::text,
      'ceiling_usd', pg_catalog.round(p_ceiling_usd, 8)::text, 'max_calls', p_max_calls,
      'valid_for', p_valid_for::text, 'grants_per_day', p_grants_per_day, 'by', p_created_by));
  return pg_catalog.jsonb_build_object('outcome', 'set', 'policy_id', v_policy::text,
    'witness', pg_catalog.jsonb_build_object(
      'authority', %1$I.spending__witness_authority(p_authority_id, v_state.head_sha256)));
end $fn$
$body$, current_schema());

  -- The operator's: end the authority's live guest policy with no other, as a step of the ledger.
  execute format($body$
create or replace function %1$I.spending_withdraw_guest_policy(
  p_authority_id uuid, p_withdrawn_by text, p_reason text, p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_state %1$I.spending_authority_state := %1$I.spending__admin_lock(p_authority_id, p_witness);
  v_policy uuid;
begin
  perform %1$I.spending__require_admin();
  update %1$I.spending_guest_policy
     set ended_at = pg_catalog.statement_timestamp(), ended_as = 'withdrawn',
         ended_by = p_withdrawn_by, ended_reason = p_reason
   where authority_id = p_authority_id and ended_at is null
  returning policy_id into v_policy;
  if v_policy is null then
    return pg_catalog.jsonb_build_object('outcome', 'none_live');
  end if;
  perform %1$I.spending__append(p_authority_id, null, 'guest_policy_ended',
    pg_catalog.jsonb_build_object('policy_id', v_policy::text, 'ended_as', 'withdrawn',
                                  'by', p_withdrawn_by));
  return pg_catalog.jsonb_build_object('outcome', 'withdrawn', 'policy_id', v_policy::text,
    'witness', pg_catalog.jsonb_build_object(
      'authority', %1$I.spending__witness_authority(p_authority_id, v_state.head_sha256)));
end $fn$
$body$, current_schema());

  -- The ledger ends a policy: when an authority is reconciled after a restore, or reauthorized,
  -- every live policy of it ends, so a restored database never grants under a policy it brought
  -- back. The row is written whoever inserted the event; the function runs with its owner's
  -- rights so the runtime, which never sets a policy, need hold nothing on the table.
  execute format($body$
create function %1$I.tg_spending_event_ends_guest_policies() returns trigger
language plpgsql security definer as $fn$
begin
  update %1$I.spending_guest_policy
     set ended_at = pg_catalog.statement_timestamp(),
         ended_as = case new.kind when 'restore_reconciled' then 'restored' else 'reauthorized' end,
         ended_by = 'ledger',
         ended_reason = 'the authority was ' ||
           case new.kind when 'restore_reconciled' then 'reconciled after a restore'
                         else 'reauthorized' end
           || '; set the guest policy again'
   where authority_id = new.authority_id and ended_at is null;
  return null;
end $fn$
$body$, current_schema());

  -- The runtime step, as 0139's, with two changes: no read of spending_event (a policy that is
  -- live is valid, the trigger above ends the rest), and the day's grants counted in
  -- spending_guest_policy_day under the state row lock.
  execute format($body$
create or replace function %1$I.spending_grant_guest(
  p_workspace_id uuid, p_provider text, p_authority_id uuid, p_actor text, p_witness jsonb
) returns jsonb language plpgsql security definer as $fn$
declare
  v_now timestamptz := pg_catalog.statement_timestamp();
  v_policy %1$I.spending_guest_policy;
  v_authority %1$I.spending_authority;
  v_state %1$I.spending_authority_state;
  v_term %1$I.spending_authority_term;
  v_verdict text;
  v_existing %1$I.spending_grant;
  v_grant uuid;
  v_until timestamptz;
  v_reason text;
  v_counted integer;
begin
  perform %1$I.assert_workspace_context(p_workspace_id);
  select * into v_authority from %1$I.spending_authority a
   where a.authority_id = p_authority_id and a.provider = p_provider;
  if not found then
    return pg_catalog.jsonb_build_object('outcome', 'refused', 'reason', 'no_guest_policy');
  end if;
  select * into v_state from %1$I.spending_authority_state s
   where s.authority_id = v_authority.authority_id for update;
  select p.* into v_policy from %1$I.spending_guest_policy p
    join %1$I.spending_authority a on a.authority_id = p.authority_id
   where a.provider = p_provider and p.ended_at is null
   order by p.created_at desc limit 1;
  if not found then
    return pg_catalog.jsonb_build_object('outcome', 'refused', 'reason', 'no_guest_policy');
  end if;
  if v_policy.authority_id is distinct from v_authority.authority_id then
    return pg_catalog.jsonb_build_object('outcome', 'authority_changed',
                                         'authority_id', v_policy.authority_id::text);
  end if;
  v_reason := 'guest policy ' || v_policy.policy_id::text;
  select g.* into v_existing from %1$I.spending_grant g
   where g.workspace_id = p_workspace_id and g.authority_id = v_authority.authority_id
     and g.parent_grant_id is null
   order by g.created_at desc limit 1;
  if found then
    if v_existing.reason = v_reason then
      return pg_catalog.jsonb_build_object('outcome', 'granted',
                                           'grant_id', v_existing.grant_id::text,
                                           'repeated', true);
    end if;
    return pg_catalog.jsonb_build_object('outcome', 'refused', 'reason', 'workspace_holds_a_grant');
  end if;
  if v_state.suspended_reason is not null then
    return %1$I.spending__refusal('spending_suspended', 'authority', v_state.suspended_reason,
                                  null, null, null);
  end if;
  v_verdict := %1$I.spending__verdict(v_authority.authority_id, v_authority.witnessed,
                                      v_state.sequence, v_state.head_sha256, p_witness);
  if v_verdict in ('witness_not_configured', 'ledger_behind_witness',
                   'witness_directory_mismatch') then
    return %1$I.spending__refusal('spending_suspended', 'authority', v_verdict,
                                  null, null, null);
  elsif v_verdict is not null then
    update %1$I.spending_authority_state s set suspended_reason = v_verdict, suspended_at = v_now
     where s.authority_id = v_authority.authority_id;
    return %1$I.spending__refusal('spending_suspended', 'authority', v_verdict,
                                  null, null, null);
  end if;
  if exists (select 1 from %1$I.spending_authority_revocation v
              where v.authority_id = v_authority.authority_id) then
    return %1$I.spending__refusal('spending_revoked', 'authority', null, null, null, null);
  end if;
  select * into v_term from %1$I.spending_authority_term t
   where t.authority_id = v_authority.authority_id and t.epoch = v_state.epoch;
  if v_term.valid_until <= v_now then
    return %1$I.spending__refusal('spending_expired', 'authority', null, null, null, null);
  end if;
  -- The policy's grants of this UTC day: one more, unless the day is full. Under the state row
  -- lock held above, and in a row no row-level security hides.
  insert into %1$I.spending_guest_policy_day as d (policy_id, grant_day, grants)
  values (v_policy.policy_id, (v_now at time zone 'UTC')::date, 1)
  on conflict (policy_id, grant_day) do update set grants = d.grants + 1
   where d.grants < v_policy.grants_per_day
  returning d.grants into v_counted;
  if v_counted is null then
    return pg_catalog.jsonb_build_object('outcome', 'refused', 'reason', 'guest_grants_exhausted');
  end if;
  v_until := least(v_now + v_policy.valid_for, v_term.valid_until);
  insert into %1$I.spending_grant (workspace_id, authority_id, ceiling_usd, max_calls, valid_until,
                                   created_by, reason)
  values (p_workspace_id, v_authority.authority_id,
          least(v_policy.ceiling_usd, v_term.ceiling_usd),
          least(v_policy.max_calls, v_term.max_calls), v_until, p_actor, v_reason)
  returning grant_id into v_grant;
  insert into %1$I.spending_grant_state (workspace_id, grant_id) values (p_workspace_id, v_grant);
  perform %1$I.spending__append(v_authority.authority_id, p_workspace_id, 'granted',
    pg_catalog.jsonb_build_object(
      'grant_id', v_grant::text,
      'ceiling_usd', pg_catalog.round(least(v_policy.ceiling_usd, v_term.ceiling_usd), 8)::text,
      'max_calls', least(v_policy.max_calls, v_term.max_calls), 'valid_until', v_until,
      'basis', 'guest_policy', 'policy_id', v_policy.policy_id::text));
  return pg_catalog.jsonb_build_object('outcome', 'granted', 'grant_id', v_grant::text,
    'witness', %1$I.spending__witness(v_authority.authority_id, v_state.head_sha256, p_workspace_id,
                                      array[v_grant]));
end $fn$
$body$, current_schema());
end $create$;

create trigger tg_spending_event_ends_guest_policies after insert on spending_event
  for each row when (new.kind in ('restore_reconciled', 'reauthorized'))
  execute function tg_spending_event_ends_guest_policies();

-- The old signatures of the operator steps take no witness: drop them so only the ledger's remain.
drop function spending_set_guest_policy(uuid, numeric, integer, interval, integer, text, text);
drop function spending_withdraw_guest_policy(uuid, text, text);

do $pin$
declare
  f record;
begin
  -- The two definers the runtime calls, and the event trigger's: pg_catalog first, then the schema
  -- for the helpers they call.
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('spending_grant_guest', 'spending_guest_policy_authority')
  loop
    execute format('alter function %s set search_path = pg_catalog, %I, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
  -- The operator steps and the triggers keep 0139's path, schema first; none is a definer but the
  -- event trigger's function, whose body names every object with its schema.
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('spending_set_guest_policy', 'spending_withdraw_guest_policy',
                         'tg_spending_guest_policy_terms', 'tg_spending_guest_policy_day_rises')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname = 'tg_spending_event_ends_guest_policies'
  loop
    execute format('alter function %s set search_path = pg_catalog, %I, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- No role but the owner holds anything on the day's counts, whatever default privileges gave.
do $$ declare held record; begin
  for held in select distinct a.grantee from pg_class c
    join pg_namespace n on n.oid = c.relnamespace,
    lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    where n.nspname = current_schema() and c.relname = 'spending_guest_policy_day'
      and a.grantee <> c.relowner
  loop
    execute format('revoke all privileges on table spending_guest_policy_day from %s',
      case when held.grantee = 0 then 'public' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

commit;
