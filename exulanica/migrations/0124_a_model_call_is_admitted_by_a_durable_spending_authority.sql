-- 0124_a_model_call_is_admitted_by_a_durable_spending_authority.sql
-- A hosted model call is admitted by a durable spending authority every process shares.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- Before this, the one ceiling on hosted spending was `exulanica.models.budget.BudgetGuard`, held
-- in each process's memory: every process started at zero, two processes each spent a whole
-- ceiling, and a restart replenished it. That guard stays, as each process's safety fuse against
-- a runaway loop. This adds the allowance that is money. `docs/model-spending-contract.md` is the
-- contract; what follows records the shape.
--
-- THE SHAPE.
--
--   spending_authority             one authority an operator issued for one provider; immutable
--   spending_authority_term        its ceiling, call limit and validity by epoch: issued, adjusted,
--                                  reauthorized, or carried back by a restore; append-only, and
--                                  the state's epoch names the current one
--   spending_authority_state       one row per authority: what is committed, the ledger's sequence
--                                  and head digest, and a suspension. The lock root: every write
--                                  that changes what is committed takes this row first
--   spending_authority_revocation  an authority's revocation, append-only
--   spending_grant                 a workspace's grant under an authority, or a bound one piece of
--                                  work opens under a grant; immutable, never larger than what it
--                                  is granted under
--   spending_grant_state           what each grant and bound has committed
--   spending_grant_revocation      a grant's or a bound's revocation, append-only
--   spending_reservation           one admitted attempt: its maximum liability, whether it may have
--                                  left, and how it settled
--   spending_event                 the ledger: one event per write that changes what is committed or
--                                  lets an attempt leave, each digest chained to the one before
--
-- NOTHING IS GRANTED BECAUSE A WORKSPACE EXISTS. Admission needs a live grant an operator gave the
-- workspace under a live authority for the provider. Every admission is checked against the
-- authority, the grant and any bound, so a grant or bound never spends past what it is granted
-- under, and grants together never pass their authority. A grant's own terms are checked against
-- its parent when it is written (tg_spending_grant_within_parent).
--
-- THE RUNTIME WRITES NO SPENDING TABLE. It reads its own workspace's grants, bounds and
-- reservations, row-level security keeping every other workspace's out, and it changes them only
-- through the functions granted to it below: spending_admit, spending_dispatch, spending_settle,
-- spending_open_bound and spending_close_bound, each with its owner's rights, a pinned search path,
-- and a check that it acts for the session's workspace. It reads no authority table and no ledger
-- event: an authority's committed total is every workspace's spending together, and the ledger's
-- sequence counts every workspace's steps. spending_authority_facts states what a workspace needs
-- of an authority (active, suspended, expired, revoked or exhausted) and no amount. Issuing,
-- adjusting, granting, revoking, reconciling and reauthorizing are administrative: those functions
-- run with their caller's rights and refuse a caller without a complete view, and no runtime role
-- may execute them.
--
-- A RESERVATION IS HELD UNTIL IT IS KNOWN. Admission holds the attempt's worst case. Dispatch records,
-- before anything is sent, that the request may now leave; a reservation never dispatched within
-- its authority's dispatch window never left, and it is released. A dispatched reservation keeps
-- its whole liability until its caller settles it by the provider's reported usage, or proves it
-- never left. One whose outcome is unknown (a timeout, an error status, a process that stopped)
-- keeps its maximum liability until an administrator reconciles it with evidence.
--
-- LOCK ORDER. Every write that changes what is committed, and every dispatch, takes its
-- authority's state row with FOR UPDATE before any grant, bound or reservation row. The processes
-- that call these functions take the authority's witness lock before that
-- (exulanica/spending/witness.py). Nothing takes an authority's state row while holding a
-- reservation or a grant, so no two of these writes wait on each other in a cycle. Opening and
-- closing a bound take no state row: they change nothing committed, and a dispatch re-reads a
-- bound's closure under the state row, so nothing admitted under a closed bound leaves.
--
-- RESTORE. The ledger's sequence and head are also written, before each such commit, to a witness
-- kept outside the database's backup domain; a dispatch is on the ledger too, so a restore that
-- loses one is a ledger behind its witness. A function given a witness that disagrees with the
-- ledger refuses, and a disagreement only an operator can resolve suspends the authority until it
-- is reauthorized. NOTHING IS APPENDED TO A LEDGER ITS WITNESS DISAGREES WITH: a settlement is not
-- recorded and keeps its whole liability, a revocation is recorded without an event, and a
-- suspension is kept in the authority's state, so a ledger restored behind its witness stays
-- behind it, and never turns into one that looks diverged or ahead. A database restored behind its
-- witness, live or a custody copy, is reconciled from it (spending_reconcile_restore): what the
-- witness says was committed stays committed. A reauthorization over a witness that may hold
-- spending the ledger lacks discards it only when the operator says so.
--
-- WITHDRAWALS. An authority's or a grant's revocation is a withdrawal a restore must not undo:
-- exulanica/deletion/withdrawals.v2.json carries both tables, and a sealed restore checkpoint
-- refuses them as it refuses every other withdrawal (0107). The ledger's events are excluded
-- there: a revocation event records a revocation row the checkpoint carries.

begin;
select pg_advisory_xact_lock(119622309);

-- 1. The authority --------------------------------------------------------------------------

create table spending_authority (
  authority_id uuid primary key,
  provider text not null check (provider ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
  -- Whether every change to what it commits is written to a witness outside the database. An
  -- authority issued without one has no restore protection, and status says so.
  witnessed boolean not null,
  -- How long an admitted attempt may wait to be dispatched before it is released as never sent.
  dispatch_seconds integer not null default 60 check (dispatch_seconds between 1 and 600),
  -- An operator's label, never a name, an address or a key: lower case, no spaces, no @.
  issued_by text not null check (issued_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason text not null check (char_length(reason) between 1 and 500),
  created_at timestamptz not null default statement_timestamp()
);

create table spending_authority_term (
  authority_id uuid not null references spending_authority (authority_id),
  epoch integer not null check (epoch >= 1),
  ceiling_usd numeric(20, 8) not null check (ceiling_usd > 0),
  max_calls integer not null check (max_calls > 0),
  valid_until timestamptz not null,
  basis text not null check (basis in ('issued', 'adjusted', 'reauthorized', 'restored')),
  issued_by text not null check (issued_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason text not null check (char_length(reason) between 1 and 500),
  created_at timestamptz not null default statement_timestamp(),
  primary key (authority_id, epoch)
);

create table spending_authority_state (
  authority_id uuid primary key references spending_authority (authority_id),
  epoch integer not null,
  committed_usd numeric(20, 8) not null default 0 check (committed_usd >= 0),
  committed_calls integer not null default 0 check (committed_calls >= 0),
  sequence bigint not null default 0 check (sequence >= 0),
  head_sha256 bytea not null check (octet_length(head_sha256) = 32),
  suspended_reason text check (suspended_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  suspended_at timestamptz,
  check ((suspended_reason is null) = (suspended_at is null)),
  foreign key (authority_id, epoch) references spending_authority_term (authority_id, epoch)
);

create table spending_authority_revocation (
  authority_id uuid primary key references spending_authority (authority_id),
  revoked_at timestamptz not null default statement_timestamp(),
  revoked_by text not null check (revoked_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason text not null check (char_length(reason) between 1 and 500)
);

-- 2. Grants and bounds ----------------------------------------------------------------------

create table spending_grant (
  workspace_id uuid not null,
  grant_id uuid not null default uuidv7(),
  authority_id uuid not null references spending_authority (authority_id),
  -- Null for a workspace's grant under the authority; a bound names the grant it is opened under.
  parent_grant_id uuid,
  -- The key a bound is opened by, unique in its workspace, so opening it again finds it.
  bound_key text check (bound_key ~ '^[a-z0-9][a-z0-9:._/-]{0,127}$'),
  ceiling_usd numeric(20, 8) not null check (ceiling_usd > 0),
  max_calls integer not null check (max_calls > 0),
  valid_until timestamptz not null,
  created_by text not null check (created_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason text not null check (char_length(reason) between 1 and 500),
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id),
  foreign key (workspace_id, parent_grant_id) references spending_grant (workspace_id, grant_id),
  unique (workspace_id, bound_key),
  check ((parent_grant_id is null) = (bound_key is null))
);
create index spending_grant_by_authority on spending_grant (authority_id, workspace_id);

create table spending_grant_state (
  workspace_id uuid not null,
  grant_id uuid not null,
  committed_usd numeric(20, 8) not null default 0 check (committed_usd >= 0),
  committed_calls integer not null default 0 check (committed_calls >= 0),
  primary key (workspace_id, grant_id),
  foreign key (workspace_id, grant_id) references spending_grant (workspace_id, grant_id)
);

create table spending_grant_revocation (
  workspace_id uuid not null,
  grant_id uuid not null,
  revoked_at timestamptz not null default statement_timestamp(),
  revoked_by text not null check (revoked_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason text not null check (char_length(reason) between 1 and 500),
  primary key (workspace_id, grant_id),
  foreign key (workspace_id, grant_id) references spending_grant (workspace_id, grant_id)
);

-- 3. Reservations ---------------------------------------------------------------------------

create table spending_reservation (
  workspace_id uuid not null,
  reservation_id uuid not null default uuidv7(),
  -- The attempt's idempotency key: admitting the same key again never holds a second liability.
  request_key text not null check (request_key ~ '^[A-Za-z0-9][A-Za-z0-9:._/#=-]{0,199}$'),
  authority_id uuid not null references spending_authority (authority_id),
  grant_id uuid not null,
  bound_id uuid,
  epoch integer not null,
  provider text not null check (provider ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
  model_id text not null check (char_length(model_id) between 1 and 200),
  role text not null check (role ~ '^[a-z][a-z0-9_.-]{0,63}$'),
  -- The attempt's worst case, held from admission until it settles.
  reserved_usd numeric(20, 8) not null check (reserved_usd >= 0),
  state text not null
    check (state in ('admitted', 'dispatched', 'settled', 'released', 'unknown', 'reconciled')),
  -- What it settled at: the priced report, zero when it never left, its whole liability when its
  -- outcome is unknown, or what an administrator reconciled it to.
  settled_usd numeric(20, 8) check (settled_usd >= 0),
  cost_basis text check (cost_basis in ('reported', 'not_sent', 'unknown', 'reconciled')),
  prompt_tokens integer check (prompt_tokens >= 0),
  completion_tokens integer check (completion_tokens >= 0),
  -- The process that admitted it, by a label with no host or account in it.
  holder text not null check (holder ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  admitted_at timestamptz not null default statement_timestamp(),
  dispatch_by timestamptz not null,
  dispatched_at timestamptz,
  settled_at timestamptz,
  -- History a restore carried: it never settles, releases or reconciles again.
  frozen boolean not null default false,
  reconciliation jsonb,
  primary key (workspace_id, reservation_id),
  unique (workspace_id, request_key),
  foreign key (workspace_id, grant_id) references spending_grant (workspace_id, grant_id),
  foreign key (workspace_id, bound_id) references spending_grant (workspace_id, grant_id),
  foreign key (authority_id, epoch) references spending_authority_term (authority_id, epoch),
  check (
    case state
      when 'admitted' then dispatched_at is null and settled_at is null and settled_usd is null
        and cost_basis is null
      when 'dispatched' then dispatched_at is not null and settled_at is null
        and settled_usd is null and cost_basis is null
      when 'settled' then dispatched_at is not null and settled_at is not null
        and settled_usd is not null and cost_basis = 'reported'
      when 'released' then settled_at is not null and settled_usd = 0 and cost_basis = 'not_sent'
      when 'unknown' then dispatched_at is not null and settled_at is not null
        and settled_usd >= reserved_usd and cost_basis = 'unknown'
      when 'reconciled' then settled_at is not null and settled_usd is not null
        and cost_basis = 'reconciled' and reconciliation is not null
    end
  )
);
-- Admission releases its workspace's reservations that were never dispatched in time.
create index spending_reservation_admitted
  on spending_reservation (workspace_id, authority_id, dispatch_by) where state = 'admitted';
-- Status and reconciliation read what may have been billed and is not yet known.
create index spending_reservation_unresolved
  on spending_reservation (workspace_id, authority_id, dispatched_at)
  where state in ('dispatched', 'unknown');

-- 4. The ledger -----------------------------------------------------------------------------

create table spending_event (
  authority_id uuid not null references spending_authority (authority_id),
  sequence bigint not null check (sequence >= 1),
  -- The workspace an event is about; none for an event about the authority itself.
  workspace_id uuid,
  kind text not null check (kind in (
    'issued', 'adjusted', 'granted', 'authority_revoked', 'grant_revoked', 'admitted',
    'dispatched', 'settled', 'released', 'expired', 'reconciled', 'restore_reconciled',
    'reauthorized')),
  body jsonb not null,
  previous_sha256 bytea not null check (octet_length(previous_sha256) = 32),
  sha256 bytea not null check (octet_length(sha256) = 32),
  created_at timestamptz not null default statement_timestamp(),
  primary key (authority_id, sequence)
);

-- 5. What never changes, and how what does may change ----------------------------------------

create function tg_spending_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception '% is append-only: a spending record is never changed or removed', tg_table_name
    using errcode = '23514';
end $fn$;
create trigger tg_spending_append_only before update or delete on spending_authority
  for each row execute function tg_spending_append_only();
create trigger tg_spending_append_only before update or delete on spending_authority_term
  for each row execute function tg_spending_append_only();
create trigger tg_spending_append_only before update or delete on spending_authority_revocation
  for each row execute function tg_spending_append_only();
create trigger tg_spending_append_only before update or delete on spending_grant
  for each row execute function tg_spending_append_only();
create trigger tg_spending_append_only before update or delete on spending_grant_revocation
  for each row execute function tg_spending_append_only();
create trigger tg_spending_append_only before update or delete on spending_event
  for each row execute function tg_spending_append_only();

create function tg_spending_authority_state_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'an authority''s state is never removed' using errcode = '23514';
  end if;
  if new.authority_id <> old.authority_id or new.sequence < old.sequence then
    raise exception 'an authority''s state keeps its identity and its ledger never runs backwards'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_authority_state_guard before update or delete
  on spending_authority_state for each row execute function tg_spending_authority_state_guard();

create function tg_spending_grant_state_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a grant''s state is never removed' using errcode = '23514';
  end if;
  if (new.workspace_id, new.grant_id) is distinct from (old.workspace_id, old.grant_id) then
    raise exception 'a grant''s state keeps its identity' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_grant_state_guard before update or delete
  on spending_grant_state for each row execute function tg_spending_grant_state_guard();

create function tg_spending_reservation_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a reservation is never removed' using errcode = '23514';
  end if;
  if (new.workspace_id, new.reservation_id, new.request_key, new.provider)
       is distinct from (old.workspace_id, old.reservation_id, old.request_key, old.provider)
     or (old.frozen and not new.frozen) then
    raise exception 'a reservation keeps its identity, and a frozen one stays frozen'
      using errcode = '23514';
  end if;
  if old.frozen and (new.state, new.settled_usd, new.reserved_usd)
       is distinct from (old.state, old.settled_usd, old.reserved_usd) then
    raise exception 'a frozen reservation is history a restore carried: it never settles again'
      using errcode = '23514';
  end if;
  if new.state <> old.state and (old.state, new.state) not in (
       ('admitted', 'dispatched'), ('admitted', 'released'), ('dispatched', 'settled'),
       ('dispatched', 'unknown'), ('dispatched', 'released'), ('dispatched', 'reconciled'),
       ('unknown', 'reconciled'), ('released', 'admitted')) then
    raise exception 'a reservation cannot move from % to %', old.state, new.state
      using errcode = '23514';
  end if;
  if not (old.state = 'released' and new.state = 'admitted')
     and (new.reserved_usd, new.authority_id, new.grant_id, new.bound_id, new.epoch, new.model_id,
          new.role, new.holder, new.admitted_at, new.dispatch_by)
       is distinct from (old.reserved_usd, old.authority_id, old.grant_id, old.bound_id, old.epoch,
          old.model_id, old.role, old.holder, old.admitted_at, old.dispatch_by) then
    raise exception 'a reservation''s liability and scope change only when it is admitted again'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_reservation_guard before update or delete
  on spending_reservation for each row execute function tg_spending_reservation_guard();

-- A grant is never larger than what it is granted under: a workspace's grant than its authority's
-- current terms, a bound than the grant it is opened under.
create function tg_spending_grant_within_parent() returns trigger language plpgsql as $fn$
declare
  v_ceiling numeric;
  v_calls integer;
  v_until timestamptz;
  v_parent record;
begin
  if new.parent_grant_id is null then
    select t.ceiling_usd, t.max_calls, t.valid_until into v_ceiling, v_calls, v_until
      from spending_authority_state s
      join spending_authority_term t on t.authority_id = s.authority_id and t.epoch = s.epoch
     where s.authority_id = new.authority_id;
    if not found then
      raise exception 'a grant names an authority with no terms' using errcode = '23503';
    end if;
  else
    select g.authority_id, g.parent_grant_id, g.ceiling_usd, g.max_calls, g.valid_until
      into v_parent
      from spending_grant g
     where g.workspace_id = new.workspace_id and g.grant_id = new.parent_grant_id;
    if not found or v_parent.parent_grant_id is not null
       or v_parent.authority_id <> new.authority_id then
      raise exception 'a bound is opened under a workspace''s grant of the same authority'
        using errcode = '23514';
    end if;
    v_ceiling := v_parent.ceiling_usd;
    v_calls := v_parent.max_calls;
    v_until := v_parent.valid_until;
  end if;
  if new.ceiling_usd > v_ceiling or new.max_calls > v_calls or new.valid_until > v_until then
    raise exception 'a grant is never larger than what it is granted under: USD %, % calls, until %',
      v_ceiling, v_calls, v_until using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_spending_grant_within_parent before insert on spending_grant
  for each row execute function tg_spending_grant_within_parent();

-- A sealed restore checkpoint refuses a revocation as it refuses every withdrawal (0107).
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on spending_authority_revocation
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on spending_grant_revocation
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- 6. Row-level security ---------------------------------------------------------------------
-- A workspace reads its own grants, reservations and events. The authority tables hold no
-- workspace's rows. An event about the authority itself names no workspace, so only an
-- administrative complete view reads it.
do $$ declare t text; begin
  foreach t in array array['spending_grant', 'spending_grant_state', 'spending_grant_revocation',
                           'spending_reservation', 'spending_event'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
                   'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- 7. The ledger's helpers -------------------------------------------------------------------

create function spending__genesis(p_authority uuid) returns bytea
language sql immutable as $fn$
  select sha256(convert_to('exulanica.spending-ledger/v1:' || p_authority::text, 'UTF8'))
$fn$;

-- One event on the authority's chain. The caller holds the authority's state row.
create function spending__append(p_authority uuid, p_workspace uuid, p_kind text, p_body jsonb)
returns bigint language plpgsql as $fn$
declare
  v_sequence bigint;
  v_head bytea;
  v_next bytea;
begin
  select s.sequence, s.head_sha256 into v_sequence, v_head
    from spending_authority_state s where s.authority_id = p_authority;
  v_next := sha256(v_head || convert_to(p_kind || ':' || p_body::text, 'UTF8'));
  insert into spending_event (authority_id, sequence, workspace_id, kind, body, previous_sha256,
                              sha256)
  values (p_authority, v_sequence + 1, p_workspace, p_kind, p_body, v_head, v_next);
  update spending_authority_state s set sequence = v_sequence + 1, head_sha256 = v_next
   where s.authority_id = p_authority;
  return v_sequence + 1;
end $fn$;

-- Adds to what the authority, the grant and any bound have committed.
create function spending__charge(
  p_authority uuid, p_workspace uuid, p_grant uuid, p_bound uuid, p_usd numeric, p_calls integer
) returns void language plpgsql as $fn$
begin
  update spending_authority_state s
     set committed_usd = s.committed_usd + p_usd, committed_calls = s.committed_calls + p_calls
   where s.authority_id = p_authority;
  update spending_grant_state g
     set committed_usd = g.committed_usd + p_usd, committed_calls = g.committed_calls + p_calls
   where g.workspace_id = p_workspace and g.grant_id = p_grant;
  if p_bound is not null then
    update spending_grant_state g
       set committed_usd = g.committed_usd + p_usd, committed_calls = g.committed_calls + p_calls
     where g.workspace_id = p_workspace and g.grant_id = p_bound;
  end if;
end $fn$;

-- Releases admitted reservations whose dispatch window passed: they never left. One workspace's,
-- or every workspace's for an administrator (p_workspace null). The caller holds the state row.
create function spending__release_stale(p_authority uuid, p_workspace uuid, p_limit integer)
returns table (o_workspace uuid, o_reservation uuid, o_grant uuid, o_usd numeric)
language plpgsql as $fn$
declare
  r record;
begin
  for r in
    select x.workspace_id, x.reservation_id, x.grant_id, x.bound_id, x.reserved_usd
      from spending_reservation x
     where x.authority_id = p_authority
       and (p_workspace is null or x.workspace_id = p_workspace)
       and x.state = 'admitted' and not x.frozen and x.dispatch_by <= statement_timestamp()
     order by x.dispatch_by, x.reservation_id
     limit p_limit
       for update skip locked
  loop
    update spending_reservation x
       set state = 'released', cost_basis = 'not_sent', settled_usd = 0,
           settled_at = statement_timestamp()
     where x.workspace_id = r.workspace_id and x.reservation_id = r.reservation_id;
    perform spending__charge(p_authority, r.workspace_id, r.grant_id, r.bound_id,
                             -r.reserved_usd, -1);
    o_workspace := r.workspace_id;
    o_reservation := r.reservation_id;
    o_grant := r.grant_id;
    o_usd := r.reserved_usd;
    return next;
  end loop;
end $fn$;

create function spending__refusal(
  p_reason text, p_scope text, p_detail text, p_limit text, p_committed text, p_requested text
) returns jsonb language sql immutable as $fn$
  select jsonb_strip_nulls(jsonb_build_object(
    'outcome', 'refused', 'reason', p_reason, 'scope', p_scope, 'detail', p_detail,
    'limit', p_limit, 'committed', p_committed, 'requested', p_requested))
$fn$;

-- Why a workspace holds no live grant for a provider, as precisely as its grants say.
create function spending__refusal_without_grant(p_workspace uuid, p_provider text)
returns jsonb language plpgsql stable as $fn$
begin
  if exists (
    select 1 from spending_grant g
      join spending_authority a on a.authority_id = g.authority_id
      join spending_authority_revocation v on v.authority_id = g.authority_id
     where g.workspace_id = p_workspace and g.parent_grant_id is null and a.provider = p_provider
  ) then
    return spending__refusal('spending_revoked', 'authority', null, null, null, null);
  end if;
  if exists (
    select 1 from spending_grant g
      join spending_authority a on a.authority_id = g.authority_id
      join spending_grant_revocation v
        on v.workspace_id = g.workspace_id and v.grant_id = g.grant_id
     where g.workspace_id = p_workspace and g.parent_grant_id is null and a.provider = p_provider
  ) then
    return spending__refusal('spending_revoked', 'workspace', null, null, null, null);
  end if;
  if exists (
    select 1 from spending_grant g
      join spending_authority a on a.authority_id = g.authority_id
     where g.workspace_id = p_workspace and g.parent_grant_id is null and a.provider = p_provider
  ) then
    return spending__refusal('spending_expired', 'workspace', null, null, null, null);
  end if;
  return spending__refusal('spending_not_granted', 'workspace', null, null, null, null);
end $fn$;

-- Where a witness, live or a copy, stands against the ledger: `agrees` (or holds one step whose
-- commit never happened), `ahead` (the ledger lacks steps it records), `behind`, or `diverged`;
-- `absent`, `unreadable` or `foreign` (another authority's) when nothing of this authority's can
-- be compared.
create function spending__witness_position(
  p_authority uuid, p_sequence bigint, p_head bytea, p_witness jsonb
) returns text language plpgsql immutable as $fn$
declare
  v_status text := p_witness->>'status';
  v_sequence bigint;
  v_head bytea;
  v_previous bytea;
  v_confirmed boolean;
begin
  if p_witness is null or v_status = 'absent' then
    return 'absent';
  end if;
  if v_status is distinct from 'live' and v_status is distinct from 'copy' then
    return 'unreadable';
  end if;
  if (p_witness->>'authority_id') is distinct from p_authority::text then
    return 'foreign';
  end if;
  v_sequence := (p_witness->>'sequence')::bigint;
  v_head := decode(p_witness->>'head_sha256', 'hex');
  v_previous := decode(p_witness->>'previous_sha256', 'hex');
  v_confirmed := coalesce((p_witness->>'confirmed')::boolean, false);
  if v_sequence = p_sequence and v_head = p_head then
    return 'agrees';
  end if;
  if v_sequence = p_sequence + 1 and not v_confirmed then
    -- Written before a commit that did not happen: that step never took effect.
    return case when v_previous = p_head then 'agrees' else 'diverged' end;
  end if;
  if v_sequence > p_sequence then
    return 'ahead';
  end if;
  if v_sequence < p_sequence then
    return 'behind';
  end if;
  -- The same sequence with another head, or a record missing either.
  return 'diverged';
end $fn$;

-- Whether the witness a process read agrees with the ledger: null when it does, else why not.
-- `witness_not_configured` and `ledger_behind_witness` refuse each admission until they change;
-- every other answer suspends the authority until an operator reauthorizes it. A copy is never
-- agreement: the live witness it stands in for may have been further ahead.
create function spending__verdict(
  p_authority uuid, p_witnessed boolean, p_sequence bigint, p_head bytea, p_witness jsonb
) returns text language plpgsql immutable as $fn$
declare
  v_position text;
begin
  if not p_witnessed then
    return null;
  end if;
  if p_witness is null then
    return 'witness_not_configured';
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

-- What a witness records of an authority after this transaction.
create function spending__witness_authority(p_authority uuid, p_previous bytea)
returns jsonb language sql stable as $fn$
  select jsonb_build_object(
    'authority_id', s.authority_id::text,
    'epoch', s.epoch,
    'sequence', s.sequence,
    'head_sha256', encode(s.head_sha256, 'hex'),
    'previous_sha256', encode(p_previous, 'hex'),
    'committed_usd', s.committed_usd::text,
    'committed_calls', s.committed_calls,
    'terms', jsonb_build_object(
      'ceiling_usd', t.ceiling_usd::text, 'max_calls', t.max_calls,
      'valid_until', t.valid_until))
    from spending_authority_state s
    join spending_authority_term t on t.authority_id = s.authority_id and t.epoch = s.epoch
   where s.authority_id = p_authority
$fn$;

-- The witness's advance after a runtime write: the authority, and the workspace's grants it touched.
create function spending__witness(
  p_authority uuid, p_previous bytea, p_workspace uuid, p_grants uuid[]
) returns jsonb language sql stable as $fn$
  select jsonb_build_object(
    'authority', spending__witness_authority(p_authority, p_previous),
    'grants', coalesce((
      select jsonb_agg(jsonb_build_object(
               'key', gs.workspace_id::text || '/' || gs.grant_id::text,
               'committed_usd', gs.committed_usd::text,
               'committed_calls', gs.committed_calls) order by gs.grant_id)
        from spending_grant_state gs
        join spending_grant g on g.workspace_id = gs.workspace_id and g.grant_id = gs.grant_id
       where gs.workspace_id = p_workspace and gs.grant_id = any(p_grants)
         and g.parent_grant_id is null), '[]'::jsonb))
$fn$;

-- Everything a witness records of an authority, for writing one whole: after issuing,
-- reauthorizing or reconciling a restore. Read with an administrative complete view.
create function spending__witness_full(p_authority uuid, p_previous bytea)
returns jsonb language sql stable as $fn$
  select jsonb_build_object(
    'authority', spending__witness_authority(p_authority, p_previous),
    'grants', coalesce((
      select jsonb_agg(jsonb_build_object(
               'key', gs.workspace_id::text || '/' || gs.grant_id::text,
               'committed_usd', gs.committed_usd::text,
               'committed_calls', gs.committed_calls) order by gs.workspace_id, gs.grant_id)
        from spending_grant_state gs
        join spending_grant g on g.workspace_id = gs.workspace_id and g.grant_id = gs.grant_id
       where g.authority_id = p_authority and g.parent_grant_id is null), '[]'::jsonb),
    'revoked', coalesce((
      select jsonb_agg(k order by k) from (
        select 'authority:' || v.authority_id::text as k
          from spending_authority_revocation v where v.authority_id = p_authority
        union all
        select 'grant:' || v.workspace_id::text || '/' || v.grant_id::text
          from spending_grant_revocation v
          join spending_grant g on g.workspace_id = v.workspace_id and g.grant_id = v.grant_id
         where g.authority_id = p_authority and g.parent_grant_id is null) keys), '[]'::jsonb),
    'full', true)
$fn$;

-- The workspace's live grant for a provider: not revoked, not past its validity, under an
-- authority not revoked. Nothing here grants anything.
create function spending__live_grant(p_workspace uuid, p_provider text)
returns setof spending_grant language sql stable as $fn$
  select g.*
    from spending_grant g
    join spending_authority a on a.authority_id = g.authority_id
   where g.workspace_id = p_workspace and g.parent_grant_id is null and a.provider = p_provider
     and g.valid_until > statement_timestamp()
     and not exists (select 1 from spending_grant_revocation v
                      where v.workspace_id = g.workspace_id and v.grant_id = g.grant_id)
     and not exists (select 1 from spending_authority_revocation v
                      where v.authority_id = g.authority_id)
   order by g.created_at desc, g.grant_id desc
   limit 1
$fn$;

create function spending__require_admin() returns void language plpgsql stable as $fn$
begin
  if not exists (select 1 from pg_roles
                  where rolname = current_user and (rolsuper or rolbypassrls)) then
    raise exception 'spending administration requires an administrative complete view'
      using errcode = '42501';
  end if;
end $fn$;

-- 8. What the runtime may call --------------------------------------------------------------

-- What a workspace, or an installation's facts, may know of each authority: its provider, whether
-- a witness protects it, its epoch and validity, and whether it is suspended (and why), revoked
-- or exhausted. Never an amount: what an authority committed is every workspace's together.
create function spending_authority_facts()
returns table (
  authority_id uuid, provider text, witnessed boolean, epoch integer, valid_until timestamptz,
  suspended_reason text, revoked boolean, exhausted boolean, created_at timestamptz
) language sql stable security definer as $fn$
  select a.authority_id, a.provider, a.witnessed, s.epoch, t.valid_until, s.suspended_reason,
         exists (select 1 from spending_authority_revocation v
                  where v.authority_id = a.authority_id),
         s.committed_usd >= t.ceiling_usd or s.committed_calls >= t.max_calls,
         a.created_at
    from spending_authority a
    join spending_authority_state s on s.authority_id = a.authority_id
    join spending_authority_term t on t.authority_id = s.authority_id and t.epoch = s.epoch
$fn$;

-- Admit one attempt, or refuse it. Returns a document: outcome admitted, refused or
-- authority_changed (the caller locked another authority's witness; it locks this one and asks
-- again), and the witness's advance whenever this changed what is committed.
create function spending_admit(
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
  if v_verdict in ('witness_not_configured', 'ledger_behind_witness') then
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

-- Record, before the request is sent, that it may now leave. Refuses one past its dispatch window,
-- one under a suspended, revoked or expired authority, grant or bound, one another attempt holds,
-- and any while the witness disagrees with the ledger. Changes nothing that is committed, and is
-- on the ledger and the witness all the same: a restore that lost this marker would otherwise
-- agree with its witness and release, as never sent, an attempt that may have been billed.
create function spending_dispatch(
  p_workspace_id uuid, p_reservation_id uuid, p_holder text, p_witness jsonb
) returns jsonb language plpgsql security definer as $fn$
declare
  v_now timestamptz := statement_timestamp();
  v_authority spending_authority;
  v_authority_id uuid;
  v_state spending_authority_state;
  v_term spending_authority_term;
  v_grant spending_grant;
  v_bound spending_grant;
  v_verdict text;
  r spending_reservation;
begin
  perform assert_workspace_context(p_workspace_id);
  if p_holder is null then
    raise exception 'a dispatch names the attempt that holds it' using errcode = '22023';
  end if;
  select x.authority_id into v_authority_id from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
  if not found then
    return spending__refusal('spending_unavailable', 'workspace', 'reservation_unknown',
                             null, null, null);
  end if;
  select * into v_authority from spending_authority a where a.authority_id = v_authority_id;
  select * into v_state from spending_authority_state s
   where s.authority_id = v_authority_id for update;
  select * into r from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id for update;
  if r.frozen or r.state in ('dispatched', 'unknown') then
    return spending__refusal('duplicate_request_unknown', 'workspace', null, null, null, null);
  end if;
  if r.state in ('settled', 'reconciled') then
    return spending__refusal('duplicate_request_settled', 'workspace', null, null, null, null);
  end if;
  if r.state = 'released' or r.dispatch_by <= v_now then
    return spending__refusal('spending_unavailable', 'workspace', 'dispatch_window_passed',
                             null, null, null);
  end if;
  if r.holder is distinct from p_holder then
    return spending__refusal('duplicate_request_in_flight', 'workspace', null, null, null, null);
  end if;
  if v_state.suspended_reason is not null then
    return spending__refusal('spending_suspended', 'authority', v_state.suspended_reason,
                             null, null, null);
  end if;
  v_verdict := spending__verdict(v_authority_id, v_authority.witnessed, v_state.sequence,
                                 v_state.head_sha256, p_witness);
  if v_verdict is not null then
    return spending__refusal('spending_suspended', 'authority', v_verdict, null, null, null);
  end if;
  select * into v_term from spending_authority_term t
   where t.authority_id = v_authority_id and t.epoch = v_state.epoch;
  if v_term.valid_until <= v_now then
    return spending__refusal('spending_expired', 'authority', null, null, null, null);
  end if;
  if exists (select 1 from spending_authority_revocation v where v.authority_id = v_authority_id)
  then
    return spending__refusal('spending_revoked', 'authority', null, null, null, null);
  end if;
  select * into v_grant from spending_grant g
   where g.workspace_id = p_workspace_id and g.grant_id = r.grant_id;
  if exists (select 1 from spending_grant_revocation v
              where v.workspace_id = p_workspace_id and v.grant_id = r.grant_id) then
    return spending__refusal('spending_revoked', 'workspace', null, null, null, null);
  end if;
  if v_grant.valid_until <= v_now then
    return spending__refusal('spending_expired', 'workspace', null, null, null, null);
  end if;
  if r.bound_id is not null then
    select * into v_bound from spending_grant g
     where g.workspace_id = p_workspace_id and g.grant_id = r.bound_id;
    if exists (select 1 from spending_grant_revocation v
                where v.workspace_id = p_workspace_id and v.grant_id = r.bound_id) then
      return spending__refusal('spending_revoked', 'bound', null, null, null, null);
    end if;
    if v_bound.valid_until <= v_now then
      return spending__refusal('spending_expired', 'bound', null, null, null, null);
    end if;
  end if;
  update spending_reservation x set state = 'dispatched', dispatched_at = v_now
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
  perform spending__append(v_authority_id, p_workspace_id, 'dispatched',
                           jsonb_build_object('reservation_id', p_reservation_id::text));
  if not v_authority.witnessed then
    return jsonb_build_object('outcome', 'dispatched');
  end if;
  return jsonb_build_object('outcome', 'dispatched',
    'witness', spending__witness(v_authority_id, v_state.head_sha256, p_workspace_id,
                               '{}'::uuid[]));
end $fn$;

-- Settle one attempt: by the provider's reported usage (reported), as having left with its
-- outcome unknown (unknown: its whole liability stays), or as never having left (not_sent: its
-- liability and its call are returned). Only the attempt that holds it settles it. Recorded only
-- while the witness agrees with the ledger, and the witness advances with it; otherwise nothing
-- changes (witness_disagrees) and the attempt keeps its whole liability, which a restore's
-- reconciliation or an operator's then accounts for.
create function spending_settle(
  p_workspace_id uuid, p_reservation_id uuid, p_holder text, p_basis text, p_usd numeric,
  p_prompt_tokens integer, p_completion_tokens integer, p_witness jsonb
) returns jsonb language plpgsql security definer as $fn$
declare
  v_now timestamptz := statement_timestamp();
  v_authority_id uuid;
  v_authority spending_authority;
  v_state spending_authority_state;
  v_verdict text;
  v_head bytea;
  v_liability numeric;
  v_delta numeric;
  v_calls integer := 0;
  v_kind text;
  r spending_reservation;
begin
  perform assert_workspace_context(p_workspace_id);
  if p_basis is null or p_basis not in ('reported', 'unknown', 'not_sent') then
    raise exception 'a settlement is reported, unknown or not_sent' using errcode = '22023';
  end if;
  if p_usd is null or p_usd < 0 then
    raise exception 'a settlement is a non-negative amount' using errcode = '22023';
  end if;
  if p_holder is null then
    raise exception 'a settlement names the attempt that holds it' using errcode = '22023';
  end if;
  select x.authority_id into v_authority_id from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
  if not found then
    return jsonb_build_object('outcome', 'reservation_unknown');
  end if;
  select * into v_authority from spending_authority a where a.authority_id = v_authority_id;
  select * into v_state from spending_authority_state s
   where s.authority_id = v_authority_id for update;
  v_head := v_state.head_sha256;
  v_verdict := spending__verdict(v_authority_id, v_authority.witnessed, v_state.sequence,
                                 v_state.head_sha256, p_witness);
  if v_verdict is not null then
    return jsonb_build_object('outcome', 'witness_disagrees', 'detail', v_verdict);
  end if;
  select * into r from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id for update;
  if r.frozen then
    return jsonb_build_object('outcome', 'frozen');
  end if;
  if r.holder is distinct from p_holder then
    return jsonb_build_object('outcome', 'not_holder');
  end if;
  if p_basis = 'not_sent' then
    if r.state not in ('admitted', 'dispatched') then
      return jsonb_build_object('outcome', 'not_open', 'state', r.state);
    end if;
    update spending_reservation x
       set state = 'released', cost_basis = 'not_sent', settled_usd = 0, settled_at = v_now
     where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
    v_liability := 0;
    v_delta := -r.reserved_usd;
    v_calls := -1;
    v_kind := 'released';
  else
    if r.state <> 'dispatched' then
      return jsonb_build_object('outcome', 'not_open', 'state', r.state);
    end if;
    if p_basis = 'reported' then
      v_liability := round(p_usd, 8);
      update spending_reservation x
         set state = 'settled', cost_basis = 'reported', settled_usd = v_liability,
             prompt_tokens = p_prompt_tokens, completion_tokens = p_completion_tokens,
             settled_at = v_now
       where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
    else
      v_liability := greatest(r.reserved_usd, round(p_usd, 8));
      update spending_reservation x
         set state = 'unknown', cost_basis = 'unknown', settled_usd = v_liability,
             settled_at = v_now
       where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
    end if;
    v_delta := v_liability - r.reserved_usd;
    v_kind := 'settled';
  end if;
  perform spending__charge(v_authority_id, p_workspace_id, r.grant_id, r.bound_id, v_delta,
                           v_calls);
  perform spending__append(v_authority_id, p_workspace_id, v_kind, jsonb_build_object(
    'reservation_id', r.reservation_id::text,
    'basis', p_basis,
    'usd', v_liability::text,
    'delta', v_delta::text,
    -- A report above the reservation is recorded as it is, and named: the estimate was wrong.
    'over_reservation', p_basis = 'reported' and v_delta > 0));
  if v_authority.witnessed then
    return jsonb_build_object('outcome', 'settled',
      'witness', spending__witness(v_authority_id, v_head, p_workspace_id, array[r.grant_id]));
  end if;
  return jsonb_build_object('outcome', 'settled');
end $fn$;

-- Open a bound for one piece of work under the workspace's live grant for a provider, or find the
-- one this key already opened. A bound larger than its grant is refused, never shrunk.
create function spending_open_bound(
  p_workspace_id uuid, p_provider text, p_bound_key text, p_ceiling_usd numeric,
  p_max_calls integer, p_valid_until timestamptz, p_created_by text, p_reason text
) returns jsonb language plpgsql security definer as $fn$
declare
  v_grant spending_grant;
  v_existing spending_grant;
  v_bound uuid;
begin
  perform assert_workspace_context(p_workspace_id);
  select * into v_grant from spending__live_grant(p_workspace_id, p_provider);
  if not found then
    return spending__refusal_without_grant(p_workspace_id, p_provider);
  end if;
  select * into v_existing from spending_grant g
   where g.workspace_id = p_workspace_id and g.bound_key = p_bound_key;
  if found then
    if v_existing.parent_grant_id = v_grant.grant_id and v_existing.ceiling_usd = p_ceiling_usd
       and v_existing.max_calls = p_max_calls and v_existing.valid_until = p_valid_until then
      return jsonb_build_object('outcome', 'opened', 'repeated', true,
                                'bound_id', v_existing.grant_id::text);
    end if;
    raise exception 'bound key % already names a bound with other terms', p_bound_key
      using errcode = '23505';
  end if;
  if p_ceiling_usd > v_grant.ceiling_usd or p_max_calls > v_grant.max_calls
     or p_valid_until > v_grant.valid_until then
    return spending__refusal('spending_limit_reached', 'workspace', 'bound_exceeds_grant',
                             v_grant.ceiling_usd::text, null, p_ceiling_usd::text);
  end if;
  insert into spending_grant (workspace_id, authority_id, parent_grant_id, bound_key, ceiling_usd,
                              max_calls, valid_until, created_by, reason)
  values (p_workspace_id, v_grant.authority_id, v_grant.grant_id, p_bound_key, p_ceiling_usd,
          p_max_calls, p_valid_until, p_created_by, p_reason)
  returning grant_id into v_bound;
  insert into spending_grant_state (workspace_id, grant_id) values (p_workspace_id, v_bound);
  return jsonb_build_object('outcome', 'opened', 'repeated', false, 'bound_id', v_bound::text);
end $fn$;

-- Close a bound: nothing more is admitted or dispatched under it; what it admitted settles as
-- before. A closure changes nothing committed, so it takes no state row and is not on the ledger:
-- a dispatch reads it under the state row. Bounds are not in the witness; a restore's
-- reconciliation closes every bound the restored database holds open.
create function spending_close_bound(
  p_workspace_id uuid, p_bound_id uuid, p_closed_by text, p_reason text
) returns jsonb language plpgsql security definer as $fn$
declare
  v_bound spending_grant;
begin
  perform assert_workspace_context(p_workspace_id);
  select * into v_bound from spending_grant g
   where g.workspace_id = p_workspace_id and g.grant_id = p_bound_id;
  if not found or v_bound.parent_grant_id is null then
    raise exception 'only a bound is closed this way' using errcode = '22023';
  end if;
  insert into spending_grant_revocation (workspace_id, grant_id, revoked_by, reason)
  values (p_workspace_id, p_bound_id, p_closed_by, p_reason)
  on conflict (workspace_id, grant_id) do nothing;
  return jsonb_build_object('outcome', 'closed', 'repeated', not found);
end $fn$;

-- 9. What only an administrator may call ----------------------------------------------------
-- Each runs with its caller's rights and refuses a caller without a complete view. The caller
-- holds the authority's witness lock and passes the witness it read.

create function spending_issue(
  p_authority_id uuid, p_provider text, p_ceiling_usd numeric, p_max_calls integer,
  p_valid_until timestamptz, p_dispatch_seconds integer, p_witnessed boolean, p_issued_by text,
  p_reason text
) returns jsonb language plpgsql as $fn$
declare
  v_head bytea := spending__genesis(p_authority_id);
begin
  perform spending__require_admin();
  if p_valid_until <= statement_timestamp() then
    raise exception 'an authority is valid for some time from now' using errcode = '22023';
  end if;
  insert into spending_authority (authority_id, provider, witnessed, dispatch_seconds, issued_by,
                                  reason)
  values (p_authority_id, p_provider, p_witnessed, p_dispatch_seconds, p_issued_by, p_reason);
  insert into spending_authority_term (authority_id, epoch, ceiling_usd, max_calls, valid_until,
                                       basis, issued_by, reason)
  values (p_authority_id, 1, p_ceiling_usd, p_max_calls, p_valid_until, 'issued', p_issued_by,
          p_reason);
  insert into spending_authority_state (authority_id, epoch, head_sha256)
  values (p_authority_id, 1, v_head);
  perform 1 from spending_authority_state s where s.authority_id = p_authority_id for update;
  perform spending__append(p_authority_id, null, 'issued', jsonb_build_object(
    'provider', p_provider, 'ceiling_usd', round(p_ceiling_usd, 8)::text,
    'max_calls', p_max_calls, 'valid_until', p_valid_until, 'witnessed', p_witnessed,
    'dispatch_seconds', p_dispatch_seconds));
  return jsonb_build_object('outcome', 'issued', 'authority_id', p_authority_id::text,
                            'witness', spending__witness_full(p_authority_id, v_head));
end $fn$;

-- The authority's state row, locked, after checking the witness agrees with its ledger.
create function spending__admin_lock(p_authority uuid, p_witness jsonb)
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
  return v_state;
end $fn$;

create function spending_adjust(
  p_authority_id uuid, p_ceiling_usd numeric, p_max_calls integer, p_valid_until timestamptz,
  p_issued_by text, p_reason text, p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_state spending_authority_state := spending__admin_lock(p_authority_id, p_witness);
  v_epoch integer;
begin
  if v_state.suspended_reason is not null then
    raise exception 'the authority is suspended (%): reauthorize it', v_state.suspended_reason
      using errcode = '55000';
  end if;
  select max(t.epoch) + 1 into v_epoch from spending_authority_term t
   where t.authority_id = p_authority_id;
  insert into spending_authority_term (authority_id, epoch, ceiling_usd, max_calls, valid_until,
                                       basis, issued_by, reason)
  values (p_authority_id, v_epoch, p_ceiling_usd, p_max_calls, p_valid_until, 'adjusted',
          p_issued_by, p_reason);
  update spending_authority_state s set epoch = v_epoch where s.authority_id = p_authority_id;
  perform spending__append(p_authority_id, null, 'adjusted', jsonb_build_object(
    'epoch', v_epoch, 'ceiling_usd', round(p_ceiling_usd, 8)::text, 'max_calls', p_max_calls,
    'valid_until', p_valid_until));
  return jsonb_build_object('outcome', 'adjusted', 'epoch', v_epoch,
    'witness', jsonb_build_object(
      'authority', spending__witness_authority(p_authority_id, v_state.head_sha256)));
end $fn$;

-- Grant a workspace an allowance under an authority. A workspace holds one live grant per provider.
create function spending_grant_workspace(
  p_authority_id uuid, p_workspace_id uuid, p_ceiling_usd numeric, p_max_calls integer,
  p_valid_until timestamptz, p_created_by text, p_reason text, p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_state spending_authority_state := spending__admin_lock(p_authority_id, p_witness);
  v_provider text;
  v_grant uuid;
begin
  if v_state.suspended_reason is not null then
    raise exception 'the authority is suspended (%): reauthorize it', v_state.suspended_reason
      using errcode = '55000';
  end if;
  if exists (select 1 from spending_authority_revocation v where v.authority_id = p_authority_id)
  then
    raise exception 'the authority is revoked' using errcode = '55000';
  end if;
  select a.provider into v_provider from spending_authority a where a.authority_id = p_authority_id;
  if exists (select 1 from spending__live_grant(p_workspace_id, v_provider)) then
    raise exception 'the workspace already holds a live grant for %: revoke it first', v_provider
      using errcode = '23505';
  end if;
  insert into spending_grant (workspace_id, authority_id, ceiling_usd, max_calls, valid_until,
                              created_by, reason)
  values (p_workspace_id, p_authority_id, p_ceiling_usd, p_max_calls, p_valid_until,
          p_created_by, p_reason)
  returning grant_id into v_grant;
  insert into spending_grant_state (workspace_id, grant_id) values (p_workspace_id, v_grant);
  perform spending__append(p_authority_id, p_workspace_id, 'granted', jsonb_build_object(
    'grant_id', v_grant::text, 'ceiling_usd', round(p_ceiling_usd, 8)::text,
    'max_calls', p_max_calls, 'valid_until', p_valid_until));
  return jsonb_build_object('outcome', 'granted', 'grant_id', v_grant::text,
    'witness', spending__witness(p_authority_id, v_state.head_sha256, p_workspace_id,
                                 array[v_grant]));
end $fn$;

-- Revoke an authority (p_grant_id null) or one of its grants or bounds. Always possible: while the
-- witness disagrees with the ledger the revocation is recorded as its row alone, with no ledger
-- event and no witness advance, so the disagreement stays as it was; the restore's reconciliation
-- or the reauthorization that resolves it writes the witness whole, revocations included.
create function spending_revoke(
  p_authority_id uuid, p_workspace_id uuid, p_grant_id uuid, p_revoked_by text, p_reason text,
  p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_authority spending_authority;
  v_state spending_authority_state;
  v_verdict text;
  v_key text;
  v_grant spending_grant;
begin
  perform spending__require_admin();
  select * into v_authority from spending_authority a where a.authority_id = p_authority_id;
  if not found then
    raise exception 'no spending authority %', p_authority_id using errcode = '22023';
  end if;
  select * into v_state from spending_authority_state s
   where s.authority_id = p_authority_id for update;
  v_verdict := spending__verdict(p_authority_id, v_authority.witnessed, v_state.sequence,
                                 v_state.head_sha256, p_witness);
  if p_grant_id is null then
    insert into spending_authority_revocation (authority_id, revoked_by, reason)
    values (p_authority_id, p_revoked_by, p_reason)
    on conflict (authority_id) do nothing;
    if not found then
      return jsonb_build_object('outcome', 'already');
    end if;
    v_key := 'authority:' || p_authority_id::text;
    if v_verdict is null then
      perform spending__append(p_authority_id, null, 'authority_revoked',
                               jsonb_build_object('reason', p_reason));
    end if;
  else
    select * into v_grant from spending_grant g
     where g.workspace_id = p_workspace_id and g.grant_id = p_grant_id
       and g.authority_id = p_authority_id;
    if not found then
      raise exception 'no grant % of this authority in that workspace', p_grant_id
        using errcode = '22023';
    end if;
    insert into spending_grant_revocation (workspace_id, grant_id, revoked_by, reason)
    values (p_workspace_id, p_grant_id, p_revoked_by, p_reason)
    on conflict (workspace_id, grant_id) do nothing;
    if not found then
      return jsonb_build_object('outcome', 'already');
    end if;
    if v_grant.parent_grant_id is null then
      v_key := 'grant:' || p_workspace_id::text || '/' || p_grant_id::text;
    end if;
    if v_verdict is null then
      perform spending__append(p_authority_id, p_workspace_id, 'grant_revoked',
        jsonb_build_object('grant_id', p_grant_id::text,
                           'bound', v_grant.parent_grant_id is not null, 'reason', p_reason));
    end if;
  end if;
  if v_verdict is not null then
    return jsonb_build_object('outcome', 'revoked', 'ledger_event', false, 'detail', v_verdict);
  end if;
  if not v_authority.witnessed then
    return jsonb_build_object('outcome', 'revoked', 'ledger_event', true);
  end if;
  return jsonb_build_object('outcome', 'revoked', 'ledger_event', true,
    'witness', jsonb_build_object(
      'authority', spending__witness_authority(p_authority_id, v_state.head_sha256),
      'revoked', v_key));
end $fn$;

-- Reconcile one attempt whose outcome is unknown, or which was dispatched and never settled, to
-- the amount an operator's evidence shows. p_evidence: source and reference labels, observed_at.
create function spending_reconcile(
  p_workspace_id uuid, p_reservation_id uuid, p_usd numeric, p_evidence jsonb,
  p_reconciled_by text, p_witness jsonb
) returns jsonb language plpgsql as $fn$
declare
  v_authority_id uuid;
  v_state spending_authority_state;
  v_liability numeric;
  v_usd numeric := round(p_usd, 8);
  r spending_reservation;
begin
  perform spending__require_admin();
  if p_usd is null or p_usd < 0 then
    raise exception 'a reconciled amount is non-negative' using errcode = '22023';
  end if;
  if jsonb_typeof(p_evidence) is distinct from 'object'
     or coalesce(p_evidence->>'source', '') !~ '^[a-z0-9][a-z0-9:._-]{0,95}$'
     or coalesce(p_evidence->>'reference', '') !~ '^[A-Za-z0-9][A-Za-z0-9:._/#=-]{0,199}$'
     or (p_evidence->>'observed_at') is null
     or (select count(*) from jsonb_object_keys(p_evidence)) <> 3
     or coalesce(p_reconciled_by, '') !~ '^[a-z0-9][a-z0-9:._-]{0,95}$' then
    raise exception 'evidence names its source, a reference and when it was observed, and nothing else'
      using errcode = '22023';
  end if;
  perform (p_evidence->>'observed_at')::timestamptz;
  select x.authority_id into v_authority_id from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
  if not found then
    raise exception 'no reservation % in that workspace', p_reservation_id using errcode = '22023';
  end if;
  v_state := spending__admin_lock(v_authority_id, p_witness);
  select * into r from spending_reservation x
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id for update;
  if r.frozen then
    raise exception 'a frozen reservation is history a restore carried and is not reconciled'
      using errcode = '55000';
  end if;
  if r.state = 'unknown' then
    v_liability := r.settled_usd;
  elsif r.state = 'dispatched' then
    v_liability := r.reserved_usd;
  else
    raise exception 'only an unknown or unsettled dispatched attempt is reconciled, not a % one',
      r.state using errcode = '55000';
  end if;
  update spending_reservation x
     set state = 'reconciled', cost_basis = 'reconciled', settled_usd = v_usd,
         settled_at = statement_timestamp(),
         reconciliation = jsonb_build_object('by', p_reconciled_by, 'evidence', p_evidence,
                                             'previous_liability', v_liability::text)
   where x.workspace_id = p_workspace_id and x.reservation_id = p_reservation_id;
  perform spending__charge(v_authority_id, p_workspace_id, r.grant_id, r.bound_id,
                           v_usd - v_liability, 0);
  perform spending__append(v_authority_id, p_workspace_id, 'reconciled', jsonb_build_object(
    'reservation_id', p_reservation_id::text, 'usd', v_usd::text,
    'previous_liability', v_liability::text, 'evidence', p_evidence));
  return jsonb_build_object('outcome', 'reconciled',
    'witness', spending__witness(v_authority_id, v_state.head_sha256, p_workspace_id,
                                 array[r.grant_id]));
end $fn$;

-- Release every workspace's attempts that were admitted and never dispatched in time.
create function spending_expire(p_authority_id uuid, p_limit integer, p_witness jsonb)
returns jsonb language plpgsql as $fn$
declare
  v_state spending_authority_state := spending__admin_lock(p_authority_id, p_witness);
  v_expired jsonb := '[]'::jsonb;
  v_grants jsonb := '[]'::jsonb;
  r record;
begin
  for r in select * from spending__release_stale(p_authority_id, null, p_limit) loop
    v_expired := v_expired || jsonb_build_array(r.o_reservation::text);
  end loop;
  if jsonb_array_length(v_expired) = 0 then
    return jsonb_build_object('outcome', 'none');
  end if;
  perform spending__append(p_authority_id, null, 'expired',
                           jsonb_build_object('expired', v_expired));
  return jsonb_build_object('outcome', 'expired', 'count', jsonb_array_length(v_expired),
    'witness', spending__witness_full(p_authority_id, v_state.head_sha256));
end $fn$;

-- Carry a restored ledger forward to its witness, live or a custody copy. What the witness says was
-- committed stays committed, for the authority and for each workspace grant. A witness whose last
-- step is unconfirmed keeps the step before it (`prior`): that step may never have committed, so
-- the carry takes the larger amounts of the two, every revocation of either, and the tighter terms.
-- Every attempt the restored ledger still holds open is frozen, since its later outcome is already
-- in what the witness carries; every bound it holds open is closed, since bounds are not in the
-- witness and a restored one would offer its spent allowance again; the witness's terms and
-- revocations are written again; the ledger continues from the witness's head. A copy may be
-- older than the live witness it stands in for, so after one the authority stays suspended until
-- an operator reauthorizes it.
create function spending_reconcile_restore(
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
  update spending_authority_state s
     set sequence = (p_witness->>'sequence')::bigint, head_sha256 = v_head
   where s.authority_id = p_authority_id;
  perform spending__append(p_authority_id, null, 'restore_reconciled', jsonb_build_object(
    'from_sequence', v_state.sequence, 'witness_sequence', (p_witness->>'sequence')::bigint,
    'witness_head', p_witness->>'head_sha256', 'carried_usd', v_carry_usd::text,
    'carried_calls', v_carry_calls, 'frozen', v_frozen, 'closed_bounds', v_closed,
    'revocations', v_revocations, 'from_copy', v_copy, 'unconfirmed', v_prior is not null,
    'reason', p_reason));
  return jsonb_build_object('outcome', 'reconciled', 'carried_usd', v_carry_usd::text,
    'carried_calls', v_carry_calls, 'frozen', v_frozen, 'closed_bounds', v_closed,
    'revocations', v_revocations, 'from_copy', v_copy,
    'witness', spending__witness_full(p_authority_id, v_head));
end $fn$;

-- An operator's explicit, bounded reauthorization: a new epoch with the terms given, which clears a
-- suspension, after which the witness is written whole from the ledger. A witness, live or a copy,
-- that may hold spending the ledger lacks (ahead of it, diverged from it, or another authority's)
-- is discarded only when the operator says so: spending_reconcile_restore carries one that is
-- ahead instead. A missing or unreadable witness holds nothing to keep, and this is the explicit
-- decision that it does not.
create function spending_reauthorize(
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
  update spending_authority_state s
     set epoch = v_epoch, suspended_reason = null, suspended_at = null
   where s.authority_id = p_authority_id;
  perform spending__append(p_authority_id, null, 'reauthorized', jsonb_build_object(
    'epoch', v_epoch, 'ceiling_usd', round(p_ceiling_usd, 8)::text, 'max_calls', p_max_calls,
    'valid_until', p_valid_until, 'suspended', v_state.suspended_reason, 'verdict', v_verdict,
    'witness_position', v_position,
    'discarded_witness', coalesce(coalesce(p_discard_witness, false)
                                  and v_position in ('ahead', 'diverged', 'foreign'), false)));
  return jsonb_build_object('outcome', 'reauthorized', 'epoch', v_epoch,
    'witness', spending__witness_full(p_authority_id, v_state.head_sha256));
end $fn$;

-- Whether every event of an authority is chained to the one before it. A restore's
-- reconciliation continues from the witness's head, so the chain resumes from that head there.
create function spending_verify_chain(p_authority_id uuid) returns jsonb
language plpgsql stable as $fn$
declare
  v_expected bytea := spending__genesis(p_authority_id);
  v_sequence bigint := 0;
  v_count bigint := 0;
  e spending_event;
begin
  perform spending__require_admin();
  for e in select * from spending_event x where x.authority_id = p_authority_id
            order by x.sequence loop
    if e.kind = 'restore_reconciled' then
      if e.previous_sha256 is distinct from decode(e.body->>'witness_head', 'hex')
         or e.sequence <> (e.body->>'witness_sequence')::bigint + 1 then
        return jsonb_build_object('verified', v_count, 'first_bad_sequence', e.sequence);
      end if;
    elsif e.sequence <> v_sequence + 1 or e.previous_sha256 is distinct from v_expected then
      return jsonb_build_object('verified', v_count, 'first_bad_sequence', e.sequence);
    end if;
    if e.sha256 is distinct from
       sha256(e.previous_sha256 || convert_to(e.kind || ':' || e.body::text, 'UTF8')) then
      return jsonb_build_object('verified', v_count, 'first_bad_sequence', e.sequence);
    end if;
    v_expected := e.sha256;
    v_sequence := e.sequence;
    v_count := v_count + 1;
  end loop;
  return jsonb_build_object('verified', v_count, 'first_bad_sequence', null);
end $fn$;

-- 10. Owner rights, pinned paths and grants -------------------------------------------------

do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and (p.proname like 'spending\_%' or p.proname like 'tg\_spending\_%')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- What a role that is not the owner holds on these tables. A provisioner's default privileges
-- give the runtime INSERT and UPDATE on every table a migration creates, and the read-only role
-- SELECT. The migration takes back what it does not mean, as 0058 does for the account tables, for
-- every grantee whatever its name, so the gap does not wait for the next provisioning: no role but
-- the owner writes a spending table, and none reads an authority table or the ledger.
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
           then 'revoke insert, update, delete, truncate, references, trigger on table %I from %s'
           else 'revoke all privileges on table %I from %s' end,
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
