-- 0133_a_spending_witness_names_its_directory_and_the_strip_is_complete.sql
-- A spending witness names its directory, so a process pointed at another directory is refused
-- alone; and migration 0124's strip of what other roles hold on the spending tables is completed.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001. Migration 0124 is landed and
-- stays as it is; this replaces five of its functions and strips its tables again.
--
-- THE WITNESS DIRECTORY. 0124 compares the witness a process reads with the ledger. A process
-- configured with another directory (a container without the shared volume, a stale path) finds
-- no witness for the authority there, which 0124 reads as a witness lost: the first admission
-- suspends the authority for every process and workspace until an operator reauthorizes it. Now
-- the directory carries a marker with its own identifier (exulanica/spending/witness.py), every
-- witness a process reads names it (`directory_id`, absent where the directory has no marker), and
-- an authority records the directory its witness is kept in (`witness_directory_id`). A process
-- whose directory has no marker, or another one, is refused alone (`witness_directory_mismatch`,
-- like `witness_not_configured`, never a suspension): it cannot prove it reads this authority's
-- witness, so it never spends under it. An authority records its directory at the first operator
-- step whose witness agrees with its ledger (granting, adjusting, reconciling, expiring), and at
-- every reauthorization and restore reconciliation, which an operator makes from the directory the
-- witness is kept in from then on. An authority with no recorded directory is not checked.
--
-- THE STRIP. 0124's strip did not cascade, so a write a grantee had passed on with its grant
-- option made the migration fail rather than take both back, and it left MAINTAIN on the four
-- workspace tables, which lets a holder lock them. This strips again with both, for every grantee
-- that is not the owner whatever its name, and grants again what 0124 grants.
--
-- REPLACED from 0124, each changed only as its comment says: spending__verdict (reads the recorded
-- directory first; stable, since it reads a table), spending__admin_lock (records it),
-- spending_admit (a directory mismatch refuses the process alone), spending_reconcile_restore and
-- spending_reauthorize (record the operator's directory, and name it in their events).

begin;
select pg_advisory_xact_lock(119622309);

-- 1. Where an authority's witness is kept ---------------------------------------------------

alter table spending_authority_state add column witness_directory_id uuid;
comment on column spending_authority_state.witness_directory_id is
  'The identifier of the directory this authority''s witness is kept in, from that directory''s marker; null where none is recorded yet, which is not checked.';

-- 2. The functions that read or record it ---------------------------------------------------

create or replace function spending__verdict(
  p_authority uuid, p_witnessed boolean, p_sequence bigint, p_head bytea, p_witness jsonb
) returns text language plpgsql stable as $fn$
declare
  v_position text;
  v_directory uuid;
begin
  if not p_witnessed then
    return null;
  end if;
  if p_witness is null then
    return 'witness_not_configured';
  end if;
  -- A process whose witness directory is not the one this authority's witness is kept in,
  -- or that cannot show which it is, says nothing about this authority's witness.
  select s.witness_directory_id into v_directory from spending_authority_state s
   where s.authority_id = p_authority;
  if v_directory is not null
     and (p_witness->>'directory_id') is distinct from v_directory::text then
    return 'witness_directory_mismatch';
  end if;
  v_position := spending__witness_position(p_authority, p_sequence, p_head, p_witness);
  if v_position = 'absent' then
    return 'witness_missing';
  end if;
  if v_position = 'unreadable' then
    return 'witness_unreadable';
  end if;
  if v_position = 'foreign' then
    return 'witness_diverged';
  end if;
  if p_witness->>'status' = 'copy' then
    return 'witness_copy_only';
  end if;
  return case v_position
    when 'agrees' then null
    when 'ahead' then 'ledger_behind_witness'
    when 'behind' then 'witness_behind'
    else 'witness_diverged'
  end;
end $fn$;

create or replace function spending__admin_lock(p_authority uuid, p_witness jsonb)
returns spending_authority_state language plpgsql as $fn$
declare
  v_authority spending_authority;
  v_state spending_authority_state;
  v_verdict text;
begin
  perform spending__require_admin();
  select * into v_authority from spending_authority a where a.authority_id = p_authority;
  if not found then
    raise exception 'no spending authority %', p_authority using errcode = '22023';
  end if;
  select * into v_state from spending_authority_state s
   where s.authority_id = p_authority for update;
  v_verdict := spending__verdict(p_authority, v_authority.witnessed, v_state.sequence,
                                 v_state.head_sha256, p_witness);
  if v_verdict is not null then
    raise exception 'the witness disagrees with the ledger (%): reconcile the restore or reauthorize first',
      v_verdict using errcode = '55000';
  end if;
  -- The first operator step whose witness agrees with the ledger records the directory
  -- that witness is kept in.
  if v_authority.witnessed and v_state.witness_directory_id is null
     and (p_witness->>'directory_id') is not null then
    update spending_authority_state s
       set witness_directory_id = (p_witness->>'directory_id')::uuid
     where s.authority_id = p_authority
    returning * into v_state;
  end if;
  return v_state;
end $fn$;

create or replace function spending_admit(
  p_workspace_id uuid, p_authority_id uuid, p_provider text, p_bound_id uuid,
  p_request_key text, p_model_id text, p_role text, p_usd numeric, p_holder text,
  p_witness jsonb
) returns jsonb language plpgsql security definer as $fn$
declare
  v_now timestamptz := statement_timestamp();
  v_grant spending_grant;
  v_authority spending_authority;
  v_state spending_authority_state;
  v_term spending_authority_term;
  v_bound spending_grant;
  v_existing spending_reservation;
  v_grant_state spending_grant_state;
  v_bound_state spending_grant_state;
  v_verdict text;
  v_head bytea;
  v_expired jsonb := '[]'::jsonb;
  v_touched uuid[] := '{}';
  v_result jsonb;
  v_admitted boolean := false;
  v_readmit boolean := false;
  v_reservation uuid;
  v_dispatch_by timestamptz;
  v_usd numeric := round(p_usd, 8);
  r record;
begin
  perform assert_workspace_context(p_workspace_id);
  if p_usd is null or p_usd < 0 or p_usd <> v_usd then
    raise exception 'a reservation is a non-negative amount of at most eight decimal places'
      using errcode = '22023';
  end if;
  if p_holder is null then
    raise exception 'an admission names the attempt that holds it' using errcode = '22023';
  end if;

  select * into v_grant from spending__live_grant(p_workspace_id, p_provider);
  if not found then
    return spending__refusal_without_grant(p_workspace_id, p_provider);
  end if;
  if p_authority_id is distinct from v_grant.authority_id then
    return jsonb_build_object('outcome', 'authority_changed',
                              'authority_id', v_grant.authority_id::text);
  end if;
  select * into v_authority from spending_authority a where a.authority_id = v_grant.authority_id;
  -- The lock root.
  select * into v_state from spending_authority_state s
   where s.authority_id = v_grant.authority_id for update;
  v_head := v_state.head_sha256;
  if v_state.suspended_reason is not null then
    return spending__refusal('spending_suspended', 'authority', v_state.suspended_reason,
                             null, null, null);
  end if;
  v_verdict := spending__verdict(v_authority.authority_id, v_authority.witnessed,
                                 v_state.sequence, v_state.head_sha256, p_witness);
  if v_verdict in ('witness_not_configured', 'ledger_behind_witness',
                   'witness_directory_mismatch') then
    return spending__refusal('spending_suspended', 'authority', v_verdict, null, null, null);
  elsif v_verdict is not null then
    -- Kept in the state row, not on the ledger: an event appended now would move the ledger past
    -- a witness that may be ahead of it, and hide that it was.
    update spending_authority_state s set suspended_reason = v_verdict, suspended_at = v_now
     where s.authority_id = v_authority.authority_id;
    return spending__refusal('spending_suspended', 'authority', v_verdict, null, null, null);
  end if;

  -- Attempts this workspace admitted and never dispatched in time never left, and can no longer
  -- leave: whatever this admission's answer, they are released first.
  for r in select * from spending__release_stale(v_authority.authority_id, p_workspace_id, 100)
  loop
    v_expired := v_expired || jsonb_build_array(r.o_reservation::text);
    v_touched := array_append(v_touched, r.o_grant);
  end loop;
  select * into v_state from spending_authority_state s
   where s.authority_id = v_authority.authority_id;

  <<decide>>
  begin
    select * into v_term from spending_authority_term t
     where t.authority_id = v_authority.authority_id and t.epoch = v_state.epoch;
    if v_term.valid_until <= v_now then
      v_result := spending__refusal('spending_expired', 'authority', null, null, null, null);
      exit decide;
    end if;
    -- A revocation takes this same row, so one committed before it was taken is seen here.
    if exists (select 1 from spending_authority_revocation v
                where v.authority_id = v_authority.authority_id) then
      v_result := spending__refusal('spending_revoked', 'authority', null, null, null, null);
      exit decide;
    end if;
    if exists (select 1 from spending_grant_revocation v
                where v.workspace_id = p_workspace_id and v.grant_id = v_grant.grant_id) then
      v_result := spending__refusal('spending_revoked', 'workspace', null, null, null, null);
      exit decide;
    end if;
    if p_bound_id is not null then
      select * into v_bound from spending_grant g
       where g.workspace_id = p_workspace_id and g.grant_id = p_bound_id;
      if not found or v_bound.parent_grant_id is distinct from v_grant.grant_id then
        v_result := spending__refusal('spending_not_granted', 'bound', 'bound_not_under_grant',
                                      null, null, null);
        exit decide;
      end if;
      if exists (select 1 from spending_grant_revocation v
                  where v.workspace_id = p_workspace_id and v.grant_id = p_bound_id) then
        v_result := spending__refusal('spending_revoked', 'bound', null, null, null, null);
        exit decide;
      end if;
      if v_bound.valid_until <= v_now then
        v_result := spending__refusal('spending_expired', 'bound', null, null, null, null);
        exit decide;
      end if;
    end if;

    select * into v_existing from spending_reservation x
     where x.workspace_id = p_workspace_id and x.request_key = p_request_key for update;
    if found then
      if v_existing.frozen then
        v_result := spending__refusal('duplicate_request_unknown', 'workspace', 'frozen',
                                      null, null, null);
        exit decide;
      end if;
      if v_existing.state = 'admitted' then
        if v_existing.holder = p_holder then
          -- The same process asking again for an admission it already holds.
          v_result := jsonb_build_object(
            'outcome', 'admitted', 'repeated', true,
            'authority_id', v_existing.authority_id::text,
            'reservation_id', v_existing.reservation_id::text,
            'reserved_usd', v_existing.reserved_usd::text,
            'dispatch_by', v_existing.dispatch_by);
        else
          v_result := spending__refusal('duplicate_request_in_flight', 'workspace', null,
                                        null, null, null);
        end if;
        exit decide;
      elsif v_existing.state in ('dispatched', 'unknown') then
        v_result := spending__refusal('duplicate_request_unknown', 'workspace', null,
                                      null, null, null);
        exit decide;
      elsif v_existing.state in ('settled', 'reconciled') then
        v_result := spending__refusal('duplicate_request_settled', 'workspace', null,
                                      null, null, null);
        exit decide;
      end if;
      v_readmit := true;
    end if;

    if v_state.committed_calls + 1 > v_term.max_calls then
      v_result := spending__refusal('spending_limit_reached', 'authority', 'calls',
                                    v_term.max_calls::text, v_state.committed_calls::text, '1');
      exit decide;
    end if;
    if v_state.committed_usd + v_usd > v_term.ceiling_usd then
      v_result := spending__refusal('spending_limit_reached', 'authority', 'usd',
                                    v_term.ceiling_usd::text, v_state.committed_usd::text,
                                    v_usd::text);
      exit decide;
    end if;
    select * into v_grant_state from spending_grant_state gs
     where gs.workspace_id = p_workspace_id and gs.grant_id = v_grant.grant_id for update;
    if v_grant_state.committed_calls + 1 > v_grant.max_calls then
      v_result := spending__refusal('spending_limit_reached', 'workspace', 'calls',
                                    v_grant.max_calls::text, v_grant_state.committed_calls::text,
                                    '1');
      exit decide;
    end if;
    if v_grant_state.committed_usd + v_usd > v_grant.ceiling_usd then
      v_result := spending__refusal('spending_limit_reached', 'workspace', 'usd',
                                    v_grant.ceiling_usd::text, v_grant_state.committed_usd::text,
                                    v_usd::text);
      exit decide;
    end if;
    if p_bound_id is not null then
      select * into v_bound_state from spending_grant_state gs
       where gs.workspace_id = p_workspace_id and gs.grant_id = p_bound_id for update;
      if v_bound_state.committed_calls + 1 > v_bound.max_calls then
        v_result := spending__refusal('spending_limit_reached', 'bound', 'calls',
                                      v_bound.max_calls::text,
                                      v_bound_state.committed_calls::text, '1');
        exit decide;
      end if;
      if v_bound_state.committed_usd + v_usd > v_bound.ceiling_usd then
        v_result := spending__refusal('spending_limit_reached', 'bound', 'usd',
                                      v_bound.ceiling_usd::text,
                                      v_bound_state.committed_usd::text, v_usd::text);
        exit decide;
      end if;
    end if;

    v_dispatch_by := v_now + make_interval(secs => v_authority.dispatch_seconds);
    if v_readmit then
      update spending_reservation x
         set state = 'admitted', reserved_usd = v_usd, authority_id = v_authority.authority_id,
             grant_id = v_grant.grant_id, bound_id = p_bound_id, epoch = v_state.epoch,
             model_id = p_model_id, role = p_role, holder = p_holder, admitted_at = v_now,
             dispatch_by = v_dispatch_by, dispatched_at = null, settled_at = null,
             settled_usd = null, cost_basis = null, prompt_tokens = null,
             completion_tokens = null
       where x.workspace_id = p_workspace_id and x.reservation_id = v_existing.reservation_id;
      v_reservation := v_existing.reservation_id;
    else
      insert into spending_reservation (
        workspace_id, request_key, authority_id, grant_id, bound_id, epoch, provider, model_id,
        role, reserved_usd, state, holder, admitted_at, dispatch_by)
      values (
        p_workspace_id, p_request_key, v_authority.authority_id, v_grant.grant_id, p_bound_id,
        v_state.epoch, p_provider, p_model_id, p_role, v_usd, 'admitted', p_holder, v_now,
        v_dispatch_by)
      returning reservation_id into v_reservation;
    end if;
    perform spending__charge(v_authority.authority_id, p_workspace_id, v_grant.grant_id,
                             p_bound_id, v_usd, 1);
    v_touched := array_append(v_touched, v_grant.grant_id);
    v_admitted := true;
    v_result := jsonb_build_object(
      'outcome', 'admitted', 'repeated', false,
      'authority_id', v_authority.authority_id::text,
      'reservation_id', v_reservation::text,
      'reserved_usd', v_usd::text,
      'dispatch_by', v_dispatch_by);
  end;

  if v_admitted then
    perform spending__append(v_authority.authority_id, p_workspace_id, 'admitted',
      jsonb_build_object('reservation_id', v_reservation::text,
                         'grant_id', v_grant.grant_id::text,
                         'bound_id', p_bound_id::text,
                         'usd', v_usd::text,
                         'model_id', p_model_id,
                         'role', p_role,
                         'readmitted', v_readmit,
                         'expired', v_expired));
  elsif jsonb_array_length(v_expired) > 0 then
    perform spending__append(v_authority.authority_id, p_workspace_id, 'expired',
                             jsonb_build_object('expired', v_expired));
  else
    return v_result;
  end if;
  if not v_authority.witnessed then
    return v_result;
  end if;
  return v_result || jsonb_build_object(
    'witness', spending__witness(v_authority.authority_id, v_head, p_workspace_id, v_touched));
end $fn$;

create or replace function spending_reconcile_restore(
  p_authority_id uuid, p_witness jsonb, p_reconciled_by text, p_reason text
) returns jsonb language plpgsql as $fn$
declare
  v_authority spending_authority;
  v_state spending_authority_state;
  v_term spending_authority_term;
  v_position text;
  v_copy boolean := (p_witness->>'status') = 'copy';
  v_prior jsonb;
  v_usd numeric;
  v_calls integer;
  v_carry_usd numeric;
  v_carry_calls integer;
  v_ceiling numeric;
  v_max_calls integer;
  v_valid_until timestamptz;
  v_frozen integer;
  v_closed integer;
  v_epoch integer;
  v_revocations integer := 0;
  v_head bytea;
  v_workspace uuid;
  v_grant uuid;
  v_key text;
  g record;
begin
  perform spending__require_admin();
  select * into v_authority from spending_authority a where a.authority_id = p_authority_id;
  if not found then
    raise exception 'no spending authority %', p_authority_id using errcode = '22023';
  end if;
  if not v_authority.witnessed then
    raise exception 'an authority without a witness has nothing to reconcile a restore against'
      using errcode = '55000';
  end if;
  select * into v_state from spending_authority_state s
   where s.authority_id = p_authority_id for update;
  v_position := spending__witness_position(p_authority_id, v_state.sequence, v_state.head_sha256,
                                           p_witness);
  if v_position is distinct from 'ahead' then
    raise exception 'nothing to reconcile: the ledger is not behind this witness (%)', v_position
      using errcode = '55000';
  end if;
  if not coalesce((p_witness->>'confirmed')::boolean, false) then
    v_prior := p_witness->'prior';
  end if;

  v_usd := greatest((p_witness->>'committed_usd')::numeric,
                    coalesce((v_prior->>'committed_usd')::numeric, 0));
  v_calls := greatest((p_witness->>'committed_calls')::integer,
                      coalesce((v_prior->>'committed_calls')::integer, 0));
  v_carry_usd := greatest(0, v_usd - v_state.committed_usd);
  v_carry_calls := greatest(0, v_calls - v_state.committed_calls);
  update spending_authority_state s
     set committed_usd = s.committed_usd + v_carry_usd,
         committed_calls = s.committed_calls + v_carry_calls
   where s.authority_id = p_authority_id;
  for g in
    select e.value->>'key' as key,
           max((e.value->>'committed_usd')::numeric) as usd,
           max((e.value->>'committed_calls')::integer) as calls
      from jsonb_array_elements(coalesce(p_witness->'grants', '[]'::jsonb)
                                || coalesce(v_prior->'grants', '[]'::jsonb)) as e (value)
     group by e.value->>'key'
  loop
    v_workspace := split_part(g.key, '/', 1)::uuid;
    v_grant := split_part(g.key, '/', 2)::uuid;
    update spending_grant_state gs
       set committed_usd = greatest(gs.committed_usd, g.usd),
           committed_calls = greatest(gs.committed_calls, g.calls)
     where gs.workspace_id = v_workspace and gs.grant_id = v_grant;
  end loop;
  update spending_reservation x set frozen = true
   where x.authority_id = p_authority_id and not x.frozen
     and x.state in ('admitted', 'dispatched', 'unknown');
  get diagnostics v_frozen = row_count;
  insert into spending_grant_revocation (workspace_id, grant_id, revoked_by, reason)
  select b.workspace_id, b.grant_id, p_reconciled_by,
         'closed by a restore reconciliation: a bound is not in the witness'
    from spending_grant b
   where b.authority_id = p_authority_id and b.parent_grant_id is not null
     and not exists (select 1 from spending_grant_revocation v
                      where v.workspace_id = b.workspace_id and v.grant_id = b.grant_id)
  on conflict (workspace_id, grant_id) do nothing;
  get diagnostics v_closed = row_count;

  v_ceiling := (p_witness->'terms'->>'ceiling_usd')::numeric;
  v_max_calls := (p_witness->'terms'->>'max_calls')::integer;
  v_valid_until := (p_witness->'terms'->>'valid_until')::timestamptz;
  if v_prior->'terms' is not null then
    v_ceiling := least(v_ceiling, (v_prior->'terms'->>'ceiling_usd')::numeric);
    v_max_calls := least(v_max_calls, (v_prior->'terms'->>'max_calls')::integer);
    v_valid_until := least(v_valid_until, (v_prior->'terms'->>'valid_until')::timestamptz);
  end if;
  select * into v_term from spending_authority_term t
   where t.authority_id = p_authority_id and t.epoch = v_state.epoch;
  if (v_ceiling, v_max_calls, v_valid_until)
       is distinct from (v_term.ceiling_usd, v_term.max_calls, v_term.valid_until) then
    select greatest(max(t.epoch), (p_witness->>'epoch')::integer,
                    (v_prior->>'epoch')::integer) + 1 into v_epoch
      from spending_authority_term t where t.authority_id = p_authority_id;
    insert into spending_authority_term (authority_id, epoch, ceiling_usd, max_calls, valid_until,
                                         basis, issued_by, reason)
    values (p_authority_id, v_epoch, v_ceiling, v_max_calls, v_valid_until, 'restored',
            p_reconciled_by, p_reason);
    update spending_authority_state s set epoch = v_epoch where s.authority_id = p_authority_id;
  end if;
  for v_key in
    select distinct k.value
      from jsonb_array_elements_text(coalesce(p_witness->'revoked', '[]'::jsonb)
                                     || coalesce(v_prior->'revoked', '[]'::jsonb)) as k (value)
  loop
    if v_key = 'authority:' || p_authority_id::text then
      insert into spending_authority_revocation (authority_id, revoked_by, reason)
      values (p_authority_id, p_reconciled_by, 'carried from the spending witness')
      on conflict (authority_id) do nothing;
      if found then
        v_revocations := v_revocations + 1;
      end if;
    elsif v_key like 'grant:%' then
      v_workspace := split_part(substr(v_key, 7), '/', 1)::uuid;
      v_grant := split_part(substr(v_key, 7), '/', 2)::uuid;
      if exists (select 1 from spending_grant gr
                  where gr.workspace_id = v_workspace and gr.grant_id = v_grant
                    and gr.authority_id = p_authority_id) then
        insert into spending_grant_revocation (workspace_id, grant_id, revoked_by, reason)
        values (v_workspace, v_grant, p_reconciled_by, 'carried from the spending witness')
        on conflict (workspace_id, grant_id) do nothing;
        if found then
          v_revocations := v_revocations + 1;
        end if;
      end if;
    end if;
  end loop;
  if v_copy then
    update spending_authority_state s
       set suspended_reason = coalesce(s.suspended_reason, 'witness_copy_only'),
           suspended_at = coalesce(s.suspended_at, statement_timestamp())
     where s.authority_id = p_authority_id;
  end if;
  v_head := decode(p_witness->>'head_sha256', 'hex');
  -- The witness is kept, from now on, in the directory the operator reconciled from.
  update spending_authority_state s
     set sequence = (p_witness->>'sequence')::bigint, head_sha256 = v_head,
         witness_directory_id = coalesce((p_witness->>'directory_id')::uuid,
                                         s.witness_directory_id)
   where s.authority_id = p_authority_id;
  perform spending__append(p_authority_id, null, 'restore_reconciled', jsonb_build_object(
    'from_sequence', v_state.sequence, 'witness_sequence', (p_witness->>'sequence')::bigint,
    'witness_head', p_witness->>'head_sha256', 'carried_usd', v_carry_usd::text,
    'carried_calls', v_carry_calls, 'frozen', v_frozen, 'closed_bounds', v_closed,
    'revocations', v_revocations, 'from_copy', v_copy, 'unconfirmed', v_prior is not null,
    'witness_directory_id', p_witness->>'directory_id', 'reason', p_reason));
  return jsonb_build_object('outcome', 'reconciled', 'carried_usd', v_carry_usd::text,
    'carried_calls', v_carry_calls, 'frozen', v_frozen, 'closed_bounds', v_closed,
    'revocations', v_revocations, 'from_copy', v_copy,
    'witness', spending__witness_full(p_authority_id, v_head));
end $fn$;

create or replace function spending_reauthorize(
  p_authority_id uuid, p_ceiling_usd numeric, p_max_calls integer, p_valid_until timestamptz,
  p_issued_by text, p_reason text, p_witness jsonb, p_discard_witness boolean
) returns jsonb language plpgsql as $fn$
declare
  v_authority spending_authority;
  v_state spending_authority_state;
  v_verdict text;
  v_position text;
  v_epoch integer;
begin
  perform spending__require_admin();
  select * into v_authority from spending_authority a where a.authority_id = p_authority_id;
  if not found then
    raise exception 'no spending authority %', p_authority_id using errcode = '22023';
  end if;
  if v_authority.witnessed and p_witness is null then
    raise exception 'a witnessed authority is reauthorized with its witness read, or its absence'
      using errcode = '55000';
  end if;
  select * into v_state from spending_authority_state s
   where s.authority_id = p_authority_id for update;
  v_verdict := spending__verdict(p_authority_id, v_authority.witnessed, v_state.sequence,
                                 v_state.head_sha256, p_witness);
  if v_authority.witnessed then
    v_position := spending__witness_position(p_authority_id, v_state.sequence,
                                             v_state.head_sha256, p_witness);
  end if;
  if v_position in ('ahead', 'diverged', 'foreign')
     and not coalesce(p_discard_witness, false) then
    raise exception 'the witness may hold spending this ledger lacks (%): reconcile the restore, or discard the witness explicitly',
      v_position using errcode = '55000';
  end if;
  if p_valid_until <= statement_timestamp() then
    raise exception 'a reauthorization is valid for some time from now' using errcode = '22023';
  end if;
  select max(t.epoch) + 1 into v_epoch from spending_authority_term t
   where t.authority_id = p_authority_id;
  insert into spending_authority_term (authority_id, epoch, ceiling_usd, max_calls, valid_until,
                                       basis, issued_by, reason)
  values (p_authority_id, v_epoch, p_ceiling_usd, p_max_calls, p_valid_until, 'reauthorized',
          p_issued_by, p_reason);
  -- The witness is written whole into the operator's directory, which is where it is kept
  -- from now on.
  update spending_authority_state s
     set epoch = v_epoch, suspended_reason = null, suspended_at = null,
         witness_directory_id = coalesce((p_witness->>'directory_id')::uuid,
                                         s.witness_directory_id)
   where s.authority_id = p_authority_id;
  perform spending__append(p_authority_id, null, 'reauthorized', jsonb_build_object(
    'epoch', v_epoch, 'ceiling_usd', round(p_ceiling_usd, 8)::text, 'max_calls', p_max_calls,
    'valid_until', p_valid_until, 'suspended', v_state.suspended_reason, 'verdict', v_verdict,
    'witness_position', v_position, 'witness_directory_id', p_witness->>'directory_id',
    'discarded_witness', coalesce(coalesce(p_discard_witness, false)
                                  and v_position in ('ahead', 'diverged', 'foreign'), false)));
  return jsonb_build_object('outcome', 'reauthorized', 'epoch', v_epoch,
    'witness', spending__witness_full(p_authority_id, v_state.head_sha256));
end $fn$;

-- 3. Pinned paths, and what other roles hold -----------------------------------------------

do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('spending__verdict', 'spending__admin_lock', 'spending_admit',
                         'spending_reconcile_restore', 'spending_reauthorize')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- Every write on the four workspace tables, MAINTAIN included, and everything on the authority
-- tables and the ledger, from every grantee that is not the owner, with whatever it passed on.
do $$ declare held record; begin
  for held in
    select distinct c.relname, a.grantee
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace,
      lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
     where n.nspname = current_schema() and a.grantee <> c.relowner
       and c.relname in ('spending_authority', 'spending_authority_term',
                         'spending_authority_state', 'spending_authority_revocation',
                         'spending_grant', 'spending_grant_state', 'spending_grant_revocation',
                         'spending_reservation', 'spending_event')
  loop
    execute format(
      case when held.relname in ('spending_grant', 'spending_grant_state',
                                 'spending_grant_revocation', 'spending_reservation')
           then 'revoke insert, update, delete, truncate, references, trigger, maintain '
                'on table %I from %s cascade'
           else 'revoke all privileges on table %I from %s cascade' end,
      held.relname,
      case when held.grantee = 0 then 'public' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

do $$ declare r text; begin
  foreach r in array array['exulanica_app', 'exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on spending_grant, spending_grant_state, '
                     'spending_grant_revocation, spending_reservation to %I', r);
      execute format('grant execute on function spending_authority_facts() to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant execute on function '
                     'spending_admit(uuid, uuid, text, uuid, text, text, text, numeric, text, jsonb), '
                     'spending_dispatch(uuid, uuid, text, jsonb), '
                     'spending_settle(uuid, uuid, text, text, numeric, integer, integer, jsonb), '
                     'spending_open_bound(uuid, text, text, numeric, integer, timestamptz, text, text), '
                     'spending_close_bound(uuid, uuid, text, text) to %I', r);
    end if;
  end loop;
end $$;

commit;
