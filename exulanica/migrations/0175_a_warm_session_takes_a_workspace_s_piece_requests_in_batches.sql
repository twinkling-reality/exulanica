-- 0175_a_warm_session_takes_a_workspace_s_piece_requests_in_batches.sql
-- A warm session the operator registers takes a workspace's piece requests in batches.
--
-- The operator starts a generation session on their own Nebius AI Cloud account for a stated window
-- and registers it here; the generation worker (exulanica/generation) writes each workspace's
-- waiting requests into the session's queue as one batch, follows it, and records what it made.
--
-- generation_session, the operator's register of a session: its record (canonical bytes and
-- digest), route, code archive, components (the pinned models), container, the compute catalog key
-- it is priced by, the Nebius job id, who registered it and when, the window's end, and its close.
-- Installation data, not a workspace's: written only by a member of the table's owner (the
-- operator's command, as 0131's host data), never by the runtime, which reads it. A registration
-- never changes except its one close.
--
-- piece_batch, one queue entry, named in the bucket by its own id (so two identical jobs are two
-- entries): the session it went to (the register's id), the job record (canonical bytes and
-- digest), when it was queued, the instant after which no session takes it (not_after), when it was
-- claimed and ended, and its state: queued, then done, refused (the session refused the entry, or
-- it was never sent, with the code) or expired (no session took it before not_after, or a session
-- took it and never said it had ended). The job never changes; progress moves forward only.
--
-- piece_request gains what the worker writes when it queues a request: the batch, and the spending
-- reservation it admitted for the request (its id, authority and holder, so a settlement after a
-- restart names the reservation it admitted). Each is written once, with the step to queued, and
-- the batch must be one of the workspace's. No foreign key names the batch, so a request that ended
-- keeps its digest-only record when its workspace's batches are erased.
--
-- generated_piece, the installation's index of the generated pieces it keeps: one row per cache
-- key (the request's digest, the pinned models' digest and the post-process version) and variant,
-- with the receipt and the piece's digest and size. Catalog content only (the shared store's write
-- path checks it), no workspace's: no workspace column, no row-level security, never updated, and
-- never erased by a workspace's deletion, as the pieces it names are not. A request every variant of
-- which is here is answered from it, with no GPU run and no charge.
--
-- piece_output, one item a request was answered with: the variant, the receipt (canonical bytes and
-- digest), the piece's digest, its cache key, and whether it passed every check (the over list
-- otherwise); the batch that made it, or none when the request was answered from generated_piece.
-- Every output names a generated_piece row. Appended once, never changed. The piece's bytes are in
-- the shared generated-pieces namespace, which holds catalog content only and no workspace's
-- erasure reaches.
--
-- piece_settlement, each queued request's spending settlement: decided with the batch's end (what
-- its items measured, at most its reservation; not_sent when nothing reached a session; unknown when
-- a session took it and never said it ended, or the workspace was deleted while it was queued) and
-- marked settled when the spending authority took it, so a settlement a crash or a lock timeout
-- interrupted is retried. A finished request never changes, so this is its own table. It holds ids,
-- a basis and an amount, no text, and is kept after the workspace's deletion so its reservation is
-- still settled.
--
-- ERASURE. A workspace tombstone deletes the workspace's piece_output and piece_batch rows (a
-- SECURITY DEFINER trigger function, owned by exulanica_definer as 0161 requires, holding DELETE
-- on those two tables and nothing else here), keyed on the tombstone's own columns so a replayed
-- tombstone reaches the same rows; the piece request migration's trigger already cancels the
-- requests. piece_settlement is kept, so a cancelled request's reservation is still settled, and
-- generated_piece is never erased. None of these rows holds a person's text: catalog keys,
-- digests, instants and numbers.
--
-- piece_batch and piece_output are under forced row-level security keyed on the workspace.
begin;
select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The operator's register of sessions
-- --------------------------------------------------------------------------------------------

create table generation_session (
  generation_session_id uuid primary key default uuidv7(),
  session_canonical text not null check (char_length(session_canonical) between 2 and 4096),
  session_sha256 text not null check (session_sha256 ~ '^[0-9a-f]{64}$'),
  route text not null check (route ~ '^[A-Z]$'),
  code_sha256 text not null check (code_sha256 ~ '^[0-9a-f]{64}$'),
  components_sha256 text not null check (components_sha256 ~ '^[0-9a-f]{64}$'),
  container text not null check (container ~ '^sha256:[0-9a-f]{64}$'),
  compute_key text not null check (compute_key ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
  provider_job_id text not null check (provider_job_id ~ '^[A-Za-z0-9-]{1,128}$'),
  opened_by text not null check (char_length(opened_by) between 1 and 200),
  opened_at timestamptz not null default statement_timestamp(),
  window_ends_at timestamptz not null,
  closed_at timestamptz,
  close_reason text check (close_reason is null or close_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  gpu_run_sha256 text check (gpu_run_sha256 is null or gpu_run_sha256 ~ '^[0-9a-f]{64}$'),
  constraint generation_session_digest_is_its_bytes
    check (encode(sha256(convert_to(session_canonical, 'UTF8')), 'hex') = session_sha256),
  constraint generation_session_window
    check (window_ends_at > opened_at and window_ends_at <= opened_at + interval '24 hours'),
  constraint generation_session_closed
    check ((closed_at is null) = (close_reason is null)
           and (gpu_run_sha256 is null or closed_at is not null))
);
create index generation_session_open on generation_session (window_ends_at)
  where closed_at is null;

create function tg_generation_session_is_host_data() returns trigger language plpgsql as $fn$
begin
  if not pg_has_role(current_user,
                     (select c.relowner from pg_class c where c.oid = tg_relid),
                     'MEMBER') then
    raise exception 'generation_session is written by the operator''s command, not by %',
      current_user using errcode = 'insufficient_privilege';
  end if;
  if tg_op = 'DELETE' then
    raise exception 'a registered generation session is never removed'
      using errcode = 'integrity_constraint_violation';
  end if;
  if tg_op = 'UPDATE' then
    if old.closed_at is not null then
      raise exception 'a closed generation session never changes'
        using errcode = 'integrity_constraint_violation';
    end if;
    if (to_jsonb(new) - array['closed_at', 'close_reason', 'gpu_run_sha256'])
       is distinct from (to_jsonb(old) - array['closed_at', 'close_reason', 'gpu_run_sha256']) then
      raise exception 'a generation session changes only by its close'
        using errcode = 'integrity_constraint_violation';
    end if;
  end if;
  return new;
end $fn$;
create trigger tg_generation_session_is_host_data
  before insert or update or delete on generation_session
  for each row execute function tg_generation_session_is_host_data();

-- --------------------------------------------------------------------------------------------
-- 2. Batches: one queue entry each
-- --------------------------------------------------------------------------------------------

create table piece_batch (
  workspace_id uuid not null,
  piece_batch_id uuid not null default uuidv7(),
  -- The register's id, not a foreign key: a workspace's rows travel (a judge seed, an export)
  -- without the installation's register of sessions.
  generation_session_id uuid not null,
  job_canonical text not null check (char_length(job_canonical) between 2 and 1048576),
  job_sha256 text not null check (job_sha256 ~ '^[0-9a-f]{64}$'),
  state text not null default 'queued'
    check (state in ('queued', 'done', 'refused', 'expired')),
  refusal text check (refusal is null or refusal ~ '^[a-z][a-z0-9_]{0,63}$'),
  queued_at timestamptz not null default statement_timestamp(),
  not_after timestamptz not null,
  claimed_at timestamptz,
  ended_at timestamptz,
  primary key (workspace_id, piece_batch_id),
  constraint piece_batch_digest_is_its_bytes
    check (encode(sha256(convert_to(job_canonical, 'UTF8')), 'hex') = job_sha256),
  constraint piece_batch_ended check ((state = 'queued') = (ended_at is null)),
  constraint piece_batch_refusal_named check ((state = 'refused') = (refusal is not null)),
  -- A session's clock and this server's may differ by up to two minutes; past that, an instant
  -- before the batch was queued is not this batch's.
  constraint piece_batch_instants
    check (not_after > queued_at
           and (claimed_at is null or claimed_at >= queued_at - interval '2 minutes')
           and (ended_at is null or ended_at >= queued_at - interval '2 minutes'))
);
create index piece_batch_open on piece_batch (workspace_id, generation_session_id)
  where state = 'queued';

create function tg_piece_batch_progress() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id and t.scope = 'workspace') then
      perform tombstone_refuse('piece_batch');
    end if;
    if new.state <> 'queued' or new.claimed_at is not null then
      raise exception 'a piece batch starts queued' using errcode = '23514';
    end if;
    return new;
  end if;
  if old.state <> 'queued' then
    raise exception 'an ended piece batch never changes' using errcode = '23514';
  end if;
  if new.workspace_id <> old.workspace_id or new.piece_batch_id <> old.piece_batch_id
     or new.generation_session_id <> old.generation_session_id
     or new.job_canonical <> old.job_canonical or new.job_sha256 <> old.job_sha256
     or new.queued_at <> old.queued_at or new.not_after <> old.not_after
     or (old.claimed_at is not null and new.claimed_at is distinct from old.claimed_at) then
    raise exception 'a piece batch''s progress moves, not its job' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_piece_batch_progress before insert or update on piece_batch
  for each row execute function tg_piece_batch_progress();

-- --------------------------------------------------------------------------------------------
-- 3. What the worker writes on a request when it queues it
-- --------------------------------------------------------------------------------------------

alter table piece_request
  add column piece_batch_id uuid,
  add column reservation_id uuid,
  add column reservation_authority_id uuid,
  add column reservation_holder text
    check (reservation_holder is null or char_length(reservation_holder) between 1 and 200),
  add constraint piece_request_reservation_whole
    check ((reservation_id is null) = (reservation_authority_id is null)
           and (reservation_id is null) = (reservation_holder is null)),
  -- A request answered from generated_piece moves to queued and to its end in one transaction with
  -- no batch and no reservation; one a session serves names both.
  add constraint piece_request_batch_when_taken
    check ((piece_batch_id is null) = (reservation_id is null));

-- The batch and the reservation are written once, with the step from requested to queued, and the
-- batch is one of the workspace's own.
create function tg_piece_request_queue_step() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    if new.piece_batch_id is not null or new.reservation_id is not null then
      raise exception 'a piece request is asked before it is queued' using errcode = '23514';
    end if;
    return new;
  end if;
  if old.piece_batch_id is not null then
    if new.piece_batch_id is distinct from old.piece_batch_id
       or new.reservation_id is distinct from old.reservation_id
       or new.reservation_authority_id is distinct from old.reservation_authority_id
       or new.reservation_holder is distinct from old.reservation_holder then
      raise exception 'a queued piece request names its batch and reservation once'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if new.piece_batch_id is not null then
    if old.state <> 'requested' or new.state <> 'queued' then
      raise exception 'a piece request names its batch with the step to queued'
        using errcode = '23514';
    end if;
    if not exists (select 1 from piece_batch b
                    where b.workspace_id = new.workspace_id
                      and b.piece_batch_id = new.piece_batch_id and b.state = 'queued') then
      raise exception 'a piece request is queued into one of its workspace''s open batches'
        using errcode = '23514';
    end if;
  end if;
  return new;
end $fn$;
create trigger tg_piece_request_queue_step before insert or update on piece_request
  for each row execute function tg_piece_request_queue_step();

-- --------------------------------------------------------------------------------------------
-- 4. Outputs: one item a session made
-- --------------------------------------------------------------------------------------------

create table generated_piece (
  cache_key text not null check (cache_key ~ '^[0-9a-f]{64}$'),
  variant integer not null check (variant between 0 and 15),
  request_sha256 text not null check (request_sha256 ~ '^[0-9a-f]{64}$'),
  components_sha256 text not null check (components_sha256 ~ '^[0-9a-f]{64}$'),
  postprocess_version text not null check (postprocess_version ~ '^[a-z0-9.-]+/v[0-9]+$'),
  receipt_canonical text not null check (char_length(receipt_canonical) between 2 and 65536),
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  piece_sha256 text not null check (piece_sha256 ~ '^[0-9a-f]{64}$'),
  piece_bytes integer not null check (piece_bytes > 0),
  within boolean not null,
  over_checks text[] not null default '{}',
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (cache_key, variant),
  constraint generated_piece_digest_is_its_bytes
    check (encode(sha256(convert_to(receipt_canonical, 'UTF8')), 'hex') = receipt_sha256),
  constraint generated_piece_verdict check (within = (cardinality(over_checks) = 0))
);

create function tg_generated_piece_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    return new;
  end if;
  raise exception 'a generated piece is recorded once, never changed or removed'
    using errcode = '23514';
end $fn$;
create trigger tg_generated_piece_append_only before insert or update or delete on generated_piece
  for each row execute function tg_generated_piece_append_only();

create table piece_output (
  workspace_id uuid not null,
  piece_request_id uuid not null,
  variant integer not null check (variant between 0 and 15),
  piece_batch_id uuid,
  cache_key text not null check (cache_key ~ '^[0-9a-f]{64}$'),
  receipt_canonical text not null check (char_length(receipt_canonical) between 2 and 65536),
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  piece_sha256 text not null check (piece_sha256 ~ '^[0-9a-f]{64}$'),
  within boolean not null,
  over_checks text[] not null default '{}',
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, piece_request_id, variant),
  foreign key (workspace_id, piece_request_id)
    references piece_request (workspace_id, piece_request_id),
  foreign key (workspace_id, piece_batch_id) references piece_batch (workspace_id, piece_batch_id),
  foreign key (cache_key, variant) references generated_piece (cache_key, variant),
  constraint piece_output_digest_is_its_bytes
    check (encode(sha256(convert_to(receipt_canonical, 'UTF8')), 'hex') = receipt_sha256),
  constraint piece_output_verdict
    check (within = (cardinality(over_checks) = 0))
);

create function tg_piece_output_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    return new;
  end if;
  raise exception 'a piece output is recorded once and never changed' using errcode = '23514';
end $fn$;
create trigger tg_piece_output_append_only before insert or update on piece_output
  for each row execute function tg_piece_output_append_only();

create table piece_settlement (
  workspace_id uuid not null,
  piece_request_id uuid not null,
  reservation_id uuid not null,
  basis text not null check (basis in ('reported', 'unknown', 'not_sent')),
  usd numeric(14, 8) not null check (usd >= 0),
  decided_at timestamptz not null default statement_timestamp(),
  settled_at timestamptz,
  primary key (workspace_id, piece_request_id),
  foreign key (workspace_id, piece_request_id)
    references piece_request (workspace_id, piece_request_id),
  constraint piece_settlement_not_sent_is_free check (basis <> 'not_sent' or usd = 0)
);
create index piece_settlement_open on piece_settlement (workspace_id) where settled_at is null;

-- Decided once, settled once: only settled_at moves, from null to an instant.
create function tg_piece_settlement_once() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.settled_at is not null then
      raise exception 'a piece settlement is decided before it is settled' using errcode = '23514';
    end if;
    if not exists (select 1 from piece_request p
                    where p.workspace_id = new.workspace_id
                      and p.piece_request_id = new.piece_request_id
                      and p.reservation_id = new.reservation_id) then
      raise exception 'a piece settlement names its request''s own reservation'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if old.settled_at is not null or new.settled_at is null
     or (to_jsonb(new) - 'settled_at') is distinct from (to_jsonb(old) - 'settled_at') then
    raise exception 'a piece settlement is settled once and never changes'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_piece_settlement_once before insert or update on piece_settlement
  for each row execute function tg_piece_settlement_once();

-- --------------------------------------------------------------------------------------------
-- 5. Erasure under the workspace tombstone
-- --------------------------------------------------------------------------------------------

create function tg_tombstone_erases_piece_batches() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope = 'workspace' then
    perform assert_workspace_context(new.workspace_id);
    delete from piece_output o where o.workspace_id = new.workspace_id;
    delete from piece_batch b where b.workspace_id = new.workspace_id;
  end if;
  return new;
end $fn$;
create trigger tg_tombstone_erases_piece_batches
  after insert on tombstone
  for each row execute function tg_tombstone_erases_piece_batches();

do $definer$ begin
  execute format('alter function tg_tombstone_erases_piece_batches() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  revoke all on function tg_tombstone_erases_piece_batches() from public;
  -- 0161: every SECURITY DEFINER function belongs to exulanica_definer, which this function's body
  -- needs to read and delete the two tables below and nothing else.
  alter function tg_tombstone_erases_piece_batches() owner to exulanica_definer;
  grant select, delete on piece_output, piece_batch to exulanica_definer;
end $definer$;

-- --------------------------------------------------------------------------------------------
-- 6. Row-level security and the runtime's grants
-- --------------------------------------------------------------------------------------------

alter table piece_batch enable row level security;
alter table piece_batch force row level security;
create policy ws_isolation on piece_batch
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table piece_output enable row level security;
alter table piece_output force row level security;
create policy ws_isolation on piece_output
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table piece_settlement enable row level security;
alter table piece_settlement force row level security;
create policy ws_isolation on piece_settlement
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on piece_batch to %I', r);
      execute format('grant select, insert on piece_output to %I', r);
      execute format('grant select, insert, update (settled_at) on piece_settlement to %I', r);
      execute format('grant select, insert on generated_piece to %I', r);
      execute format('revoke insert, update, delete on generation_session from %I', r);
      execute format('grant select on generation_session to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on piece_batch, piece_output, piece_settlement, '
                     'generated_piece, generation_session to %I', r);
    end if;
  end loop;
end $$;

commit;
