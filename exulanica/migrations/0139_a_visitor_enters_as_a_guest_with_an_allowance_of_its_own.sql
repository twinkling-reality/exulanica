-- A visitor enters as a guest, with a workspace and an allowance of their own.
--
-- The public server lets a person in without an operator: one request makes a user with no
-- identity, a workspace, a membership in the new role `guest` and a browser session, in one
-- transaction on the account role (exulanica/api/account_repository.py). Three things here make
-- that safe to leave open:
--
--   1. A day's entries are counted in the database (`account_guest_day`), in the entry's own
--      transaction, against a limit the server states; a full day refuses rather than admits.
--   2. A guest session names the entry it came from (`account_guest_entry`), as a Google session
--      names its login attempt: a session row names exactly one of the two.
--   3. The allowance is a step of the durable spending authority's ledger, like an admission, not
--      an administrative grant: `spending_grant_guest` grants a workspace exactly the figures of
--      the authority's live guest policy, once, and returns the witness advance the runtime
--      writes, so the ledger and the witness move together. It accepts no figure from its caller,
--      refuses a workspace that already holds a grant under the authority, grants at most the
--      policy's number of workspaces in a UTC day (counted under the authority's state row lock,
--      which it takes before reading the policy), and is executable by the runtime role alone.
--      The policy is the operator's (`spending_set_guest_policy`, `spending_withdraw_guest_policy`,
--      an administrator's). A policy set before the authority's latest restore reconciliation or
--      reauthorization grants nothing until set again: a restore can bring back one that ended.
--
-- A session also gains `seen_at`, the last minute it was used, moved forward only: a guest's town
-- plays while somebody is watching it, and a guest workspace nobody has seen for a while is
-- disabled, not deleted. Nothing here deletes an account row; 0058's rule stands.

begin;
select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. Accounts: the guest role, a day's entries, a session's origin and its last use.
-- --------------------------------------------------------------------------------------------

alter table account_membership drop constraint account_membership_membership_role_check;
alter table account_membership add constraint account_membership_membership_role_check
  check (membership_role in ('owner', 'guest'));

create table account_guest_entry (
  entry_id     uuid primary key,
  user_id      uuid not null unique references account_user(user_id),
  workspace_id uuid not null references account_workspace(workspace_id),
  entry_day    date not null,
  created_at   timestamptz not null default now()
);

create table account_guest_day (
  entry_day date primary key,
  entries   integer not null check (entries > 0)
);

alter table account_browser_session alter column login_state_sha256 drop not null;
alter table account_browser_session
  add column guest_entry_id uuid unique references account_guest_entry(entry_id),
  add column seen_at timestamptz;
alter table account_browser_session add constraint account_browser_session_has_one_origin
  check ((login_state_sha256 is null) <> (guest_entry_id is null));

-- 0058's rule, with what this migration adds: a guest entry never changes; a day's count only
-- rises; a session's `seen_at` only moves forward, beside its set-once `revoked_at`.
create or replace function tg_account_immutable() returns trigger language plpgsql as $fn$
declare mutable text[];
begin
  if tg_op='DELETE' then
    raise exception 'account identities and session audit rows are retained' using errcode='23514';
  end if;
  if tg_table_name = 'account_guest_day' then
    if new.entry_day is distinct from old.entry_day or new.entries < old.entries then
      raise exception 'a day''s guest entries only rise' using errcode='23514';
    end if;
    return new;
  end if;
  mutable := case tg_table_name
    when 'account_user' then array['disabled_at']
    when 'account_workspace' then array['disabled_at']
    when 'account_membership' then array['revoked_at']
    when 'account_browser_session' then array['revoked_at', 'seen_at']
    else array[]::text[] end;
  if cardinality(mutable) = 0 or (to_jsonb(new) - mutable) is distinct from (to_jsonb(old) - mutable)
      or (to_jsonb(old)->mutable[1] <> 'null'::jsonb
          and to_jsonb(new)->mutable[1] is distinct from to_jsonb(old)->mutable[1]) then
    raise exception 'account bindings are immutable; disabling is irreversible here' using errcode='23514';
  end if;
  -- Nested, not joined with AND: a record's field is resolved when its expression runs, and the
  -- other tables have no seen_at.
  if tg_table_name = 'account_browser_session' then
    if old.seen_at is not null and (new.seen_at is null or new.seen_at < old.seen_at) then
      raise exception 'a session''s last use only moves forward' using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;
revoke all on function tg_account_immutable() from public;

do $$ declare t text; begin
  foreach t in array array['account_guest_entry', 'account_guest_day'] loop
    execute format('create trigger account_immutable before update or delete on %I '
      'for each row execute function tg_account_immutable()', t);
    execute format('revoke all privileges on table %I from public', t);
  end loop;
end $$;

-- As 0058 does for its tables: no grant a provisioner's default privileges gave survives, for any
-- grantee. `exulanica-db` grants the account role what it needs (exulanica/db/account_roles.py).
do $$ declare held record; begin
  for held in select distinct c.relname, a.grantee from pg_class c
    join pg_namespace n on n.oid = c.relnamespace,
    lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    where n.nspname = current_schema()
      and c.relname in ('account_guest_entry', 'account_guest_day') and a.grantee <> c.relowner
  loop
    execute format('revoke all privileges on table %I from %s cascade', held.relname,
      case when held.grantee = 0 then 'PUBLIC' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 2. Spending: the operator's guest policy, and the one runtime step that grants by it.
-- --------------------------------------------------------------------------------------------

create table spending_guest_policy (
  policy_id      uuid primary key default uuidv7(),
  authority_id   uuid not null references spending_authority(authority_id),
  ceiling_usd    numeric(20, 8) not null check (ceiling_usd > 0),
  max_calls      integer not null check (max_calls > 0),
  valid_for      interval not null check (valid_for > interval '0' and valid_for <= interval '31 days'),
  -- How many workspaces the policy grants in one UTC day, counted under the authority's state
  -- row lock, so the database bounds a day's guest grants whatever process asks for them.
  grants_per_day integer not null check (grants_per_day between 1 and 1000000),
  created_by     text not null check (created_by ~ '^[a-z0-9:._-]{1,64}$'),
  reason         text not null check (length(reason) between 1 and 500),
  created_at     timestamptz not null default statement_timestamp(),
  -- When the policy stopped granting, and why: replaced by another, or withdrawn by the operator
  -- (no guest is granted anything under the authority until another is set).
  ended_at       timestamptz,
  ended_as       text check (ended_as in ('replaced', 'withdrawn')),
  check ((ended_at is null) = (ended_as is null))
);
create unique index spending_guest_policy_one_live on spending_guest_policy (authority_id)
  where ended_at is null;
-- What a grant asks of the ledger: whether the authority was reconciled after a restore, or
-- reauthorized, since the policy was set. A small index: only those two kinds of event.
create index spending_event_restore_or_reauthorize on spending_event (authority_id, created_at)
  where kind in ('restore_reconciled', 'reauthorized');

create function tg_spending_guest_policy_terms() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a guest policy is retained' using errcode = '23514';
  end if;
  if (to_jsonb(new) - 'ended_at' - 'ended_as') is distinct from (to_jsonb(old) - 'ended_at' - 'ended_as')
     or (old.ended_at is not null
         and (new.ended_at, new.ended_as) is distinct from (old.ended_at, old.ended_as)) then
    raise exception 'a guest policy''s terms never change; set another, which replaces it'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_guest_policy_terms before update or delete on spending_guest_policy
  for each row execute function tg_spending_guest_policy_terms();

-- Every body below names its tables, types and functions with this schema, so its pinned search
-- path is never what a name resolves through.
do $create$
begin
  -- The operator's: set the authority's guest policy, marking the one it replaces. Administrators
  -- only, as every operator step (spending__require_admin).
  execute format($body$
create function %1$I.spending_set_guest_policy(
  p_authority_id uuid, p_ceiling_usd numeric, p_max_calls integer, p_valid_for interval,
  p_grants_per_day integer, p_created_by text, p_reason text
) returns jsonb language plpgsql as $fn$
declare
  v_policy uuid;
begin
  perform %1$I.spending__require_admin();
  if not exists (select 1 from %1$I.spending_authority a where a.authority_id = p_authority_id) then
    raise exception 'no such authority' using errcode = '22023';
  end if;
  perform 1 from %1$I.spending_authority_state s where s.authority_id = p_authority_id for update;
  update %1$I.spending_guest_policy
     set ended_at = pg_catalog.statement_timestamp(), ended_as = 'replaced'
   where authority_id = p_authority_id and ended_at is null;
  insert into %1$I.spending_guest_policy (authority_id, ceiling_usd, max_calls, valid_for,
                                          grants_per_day, created_by, reason)
  values (p_authority_id, pg_catalog.round(p_ceiling_usd, 8), p_max_calls, p_valid_for,
          p_grants_per_day, p_created_by, p_reason)
  returning policy_id into v_policy;
  return pg_catalog.jsonb_build_object('outcome', 'set', 'policy_id', v_policy::text);
end $fn$
$body$, current_schema());

  -- The operator's: withdraw the authority's live guest policy, so no guest is granted anything
  -- under it until another is set. A guest already granted keeps that grant, which the operator
  -- revokes as any grant.
  execute format($body$
create function %1$I.spending_withdraw_guest_policy(
  p_authority_id uuid, p_withdrawn_by text, p_reason text
) returns jsonb language plpgsql as $fn$
declare
  v_policy uuid;
begin
  perform %1$I.spending__require_admin();
  perform 1 from %1$I.spending_authority_state s where s.authority_id = p_authority_id for update;
  update %1$I.spending_guest_policy
     set ended_at = pg_catalog.statement_timestamp(), ended_as = 'withdrawn'
   where authority_id = p_authority_id and ended_at is null
  returning policy_id into v_policy;
  if v_policy is null then
    return pg_catalog.jsonb_build_object('outcome', 'none_live');
  end if;
  return pg_catalog.jsonb_build_object('outcome', 'withdrawn', 'policy_id', v_policy::text,
                                       'withdrawn_by', p_withdrawn_by, 'reason', p_reason);
end $fn$
$body$, current_schema());

  -- Which authority a provider's live guest policy is under, so the runtime can take that
  -- authority's witness lock before it asks for a grant. Names an id, never an amount.
  execute format($body$
create function %1$I.spending_guest_policy_authority(p_provider text) returns uuid
language sql stable security definer as $fn$
  select p.authority_id from %1$I.spending_guest_policy p
    join %1$I.spending_authority a on a.authority_id = p.authority_id
   where a.provider = p_provider and p.ended_at is null
   order by p.created_at desc limit 1
$fn$
$body$, current_schema());

  -- The runtime step. In the workspace's own context (assert_workspace_context), for a workspace
  -- that holds no grant from this authority: the live policy's figures, valid for the policy's
  -- period or the authority's term, whichever ends first; appended to the ledger as `granted` with
  -- its basis; the witness advance returned. The authority's state row is locked before the
  -- policy is read, so a grant racing a replacement takes the policy that stands after it. Asked
  -- again for a workspace this policy already granted, it answers that grant and moves nothing.
  -- Refused: no live policy; a policy set before the authority's latest restore reconciliation or
  -- reauthorization (a restore can bring back a policy the operator replaced or withdrew, so one
  -- is restated after it); the policy's grants of the day spent; and an admission's refusals.
  execute format($body$
create function %1$I.spending_grant_guest(
  p_workspace_id uuid, p_provider text, p_authority_id uuid, p_actor text, p_witness jsonb
) returns jsonb language plpgsql security definer as $fn$
declare
  v_now timestamptz := pg_catalog.statement_timestamp();
  v_day_start timestamptz;
  v_policy %1$I.spending_guest_policy;
  v_authority %1$I.spending_authority;
  v_state %1$I.spending_authority_state;
  v_term %1$I.spending_authority_term;
  v_verdict text;
  v_existing %1$I.spending_grant;
  v_grant uuid;
  v_until timestamptz;
  v_reason text;
  v_today integer;
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
  if exists (select 1 from %1$I.spending_event e
              where e.authority_id = v_authority.authority_id
                and e.kind in ('restore_reconciled', 'reauthorized')
                and e.created_at > v_policy.created_at) then
    return pg_catalog.jsonb_build_object('outcome', 'refused',
                                         'reason', 'guest_policy_needs_restating');
  end if;
  v_reason := 'guest policy ' || v_policy.policy_id::text;
  -- The workspace's grants from this authority, read in its own context. One this policy made is
  -- answered again; any other refuses: a guest's allowance is never added to an allowance it
  -- already holds under the same authority.
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
  -- The policy's grants of this UTC day, counted under the state row lock held above.
  v_day_start := pg_catalog.date_trunc('day', v_now at time zone 'UTC') at time zone 'UTC';
  select pg_catalog.count(*) into v_today from %1$I.spending_grant g
   where g.authority_id = v_authority.authority_id and g.reason = v_reason
     and g.created_at >= v_day_start;
  if v_today >= v_policy.grants_per_day then
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

-- Owner rights, pinned paths, PUBLIC revoked, as every spending function (0124 section 10).
do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('spending_set_guest_policy', 'spending_withdraw_guest_policy',
                         'spending_guest_policy_authority', 'spending_grant_guest',
                         'tg_spending_guest_policy_terms')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- No role but the owner holds anything on the policy, whatever a provisioner's default privileges
-- gave; the runtime reaches it only through the two functions provisioning grants it.
do $$ declare held record; begin
  for held in select distinct a.grantee from pg_class c
    join pg_namespace n on n.oid = c.relnamespace,
    lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    where n.nspname = current_schema() and c.relname = 'spending_guest_policy'
      and a.grantee <> c.relowner
  loop
    execute format('revoke all privileges on table spending_guest_policy from %s',
      case when held.grantee = 0 then 'public' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

commit;
