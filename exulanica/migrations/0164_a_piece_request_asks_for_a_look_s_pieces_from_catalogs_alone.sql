-- 0164_a_piece_request_asks_for_a_look_s_pieces_from_catalogs_alone.sql
-- A piece request asks a GPU for new pieces of a world's look, from catalog words alone.
--
-- A person or the Companion asks for pieces of a world's look for some thing kinds
-- (exulanica/generation). Each kind becomes one request: the shipped kind version and its digest,
-- the committed style pack version and its manifest digest, the look role the piece dresses, how
-- many variants, and the request document itself (exulanica.generated-asset-request/v2) as
-- canonical JSON with its digest. Its words come from catalogs only (a measured recipe
-- description, or the kind's look role), so a request holds no text a person typed, and every
-- request is catalog content, shared by any workspace asking the same thing.
--
-- WHAT A REQUEST IS FOR. The world it names is the one whose look takes each passed piece in as it
-- arrives: asking is the consent to that, and each piece can be taken back. The work runs on a GPU
-- session the operator starts; until one takes the request it waits as requested. A request moves
-- from requested to queued (a session's queue holds it) and ends made, refused (every variant
-- failed a check), failed or cancelled; a person may cancel one still requested. A finished
-- request never changes, and what was asked never changes at all.
--
-- MONEY. The request states its worst case in US dollars at the GPU's listed rate (the piece
-- compute catalog); the worker that queues it admits that amount under the workspace's
-- nebius_ai_cloud_gpu grant, dispatches and settles it from the measured milliseconds. Nothing is
-- reserved here: a reservation lapses within ten minutes, and a request may wait hours.
--
-- LIMITS. piece_request_limits() states how many requests a workspace may make in a day and hold
-- open at once; the insert trigger counts under the workspace's own key, so two concurrent asks
-- cannot both pass the last place. The same open request (one world, one request digest) is held
-- once: asking again is answered with the request already waiting. An ask under a caller's key
-- is recorded (piece_ask) with every request it answered with, so the key answers the same
-- requests again, and a key whose ask made none is still bound to that ask.
--
-- ORDER. The store takes the workspace's lock (880024) before anything else, so an ask and a
-- workspace tombstone never interleave: one waits for the other, or the tombstone is refused and
-- sent again (0137).
--
-- ERASURE. A workspace tombstone cancels every open request of the workspace (failure
-- workspace_deleted), so no session makes a piece for a deleted workspace, and the workspace takes
-- no new request. The trigger runs as the tombstone's writer, which may update the table, keyed on
-- the tombstone's own columns, so a replayed tombstone reaches the same rows. The rows hold no
-- person's text, only catalog keys, digests and numbers.
--
-- WHAT THIS DELIBERATELY DOES NOT DO. Sessions, batches, outputs, stored pieces and their purge
-- arrive with the worker that writes them. A person's own words for a piece are not taken.
--
-- Under forced row-level security keyed on the workspace.
begin;
select pg_advisory_xact_lock(119622309);

create function piece_request_limits(out per_day integer, out open_at_once integer)
language sql immutable as $fn$
  select 64, 32;
$fn$;
do $pin$ begin
  execute format('alter function piece_request_limits() set search_path = %I, pg_catalog, pg_temp',
                 current_schema());
end $pin$;

create table piece_request (
  workspace_id uuid not null,
  piece_request_id uuid not null default uuidv7(),
  requested_by uuid not null,
  world_id text not null,
  kind_key text not null check (kind_key ~ '^[a-z][a-z0-9_]{0,47}$'),
  kind_version integer not null check (kind_version >= 1),
  kind_sha256 text not null check (kind_sha256 ~ '^[0-9a-f]{64}$'),
  pack_id text not null check (pack_id ~ '^[a-z0-9][a-z0-9.-]{0,63}$'),
  pack_version integer not null check (pack_version >= 1),
  pack_manifest_sha256 text not null check (pack_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  look_role text not null check (look_role ~ '^[a-z]+\.[a-z0-9_]{1,63}$'),
  variants integer not null check (variants between 1 and 16),
  request_canonical text not null check (char_length(request_canonical) between 2 and 65536),
  request_sha256 text not null check (request_sha256 ~ '^[0-9a-f]{64}$'),
  cache_scope text not null check (cache_scope = 'catalog'),
  worst_case_usd numeric(14, 8) not null check (worst_case_usd >= 0),
  state text not null default 'requested'
    check (state in ('requested', 'queued', 'made', 'refused', 'failed', 'cancelled')),
  failure text check (failure is null or failure ~ '^[a-z][a-z0-9_]{0,63}$'),
  requested_at timestamptz not null default statement_timestamp(),
  queued_at timestamptz,
  finished_at timestamptz,
  primary key (workspace_id, piece_request_id),
  foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  constraint piece_request_digest_is_its_bytes
    check (encode(sha256(convert_to(request_canonical, 'UTF8')), 'hex') = request_sha256),
  constraint piece_request_queued_when_taken
    check ((state = 'requested') <= (queued_at is null)
           and (state in ('queued', 'made', 'refused')) <= (queued_at is not null)),
  constraint piece_request_finished
    check ((state in ('made', 'refused', 'failed', 'cancelled')) = (finished_at is not null)),
  constraint piece_request_failure_named
    check ((state in ('failed', 'cancelled')) = (failure is not null))
);

create unique index piece_request_open_once on piece_request (workspace_id, world_id, request_sha256)
  where state in ('requested', 'queued');
create index piece_request_recent on piece_request (workspace_id, world_id, requested_at desc);
create index piece_request_day on piece_request (workspace_id, requested_at);
create index piece_request_waiting on piece_request (workspace_id, state, requested_at)
  where state in ('requested', 'queued');

-- What was asked never changes, a finished request never changes, and a request moves forward
-- only: requested to queued, cancelled or failed; queued to made, refused, failed or cancelled (a
-- queued request is cancelled only by its workspace's tombstone; a person cancels one requested).
create function tg_piece_request_progress() returns trigger language plpgsql as $fn$
declare
  v_limits record;
  v_day integer;
  v_open integer;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id and t.scope = 'workspace') then
      perform tombstone_refuse('piece_request');
    end if;
    if new.state <> 'requested' or new.queued_at is not null then
      raise exception 'a piece request starts requested' using errcode = '23514';
    end if;
    -- Asked now: a writer cannot date a request out of the day it counts in.
    new.requested_at := statement_timestamp();
    -- The workspace's own key in this migration's family, so concurrent asks count in turn.
    perform pg_advisory_xact_lock(hashtextextended('piece_request:' || new.workspace_id::text, 880164));
    select * into v_limits from piece_request_limits();
    select count(*) filter (where p.requested_at > statement_timestamp() - interval '1 day'),
           count(*) filter (where p.state in ('requested', 'queued'))
      into v_day, v_open
      from piece_request p
     where p.workspace_id = new.workspace_id;
    if v_day >= v_limits.per_day or v_open >= v_limits.open_at_once then
      raise exception 'a workspace makes at most % piece requests a day and holds % open',
        v_limits.per_day, v_limits.open_at_once using errcode = '54000';
    end if;
    return new;
  end if;
  if old.state in ('made', 'refused', 'failed', 'cancelled') then
    raise exception 'a finished piece request never changes' using errcode = '23514';
  end if;
  if new.workspace_id <> old.workspace_id or new.piece_request_id <> old.piece_request_id
     or new.requested_by <> old.requested_by or new.world_id <> old.world_id
     or new.kind_key <> old.kind_key or new.kind_version <> old.kind_version
     or new.kind_sha256 <> old.kind_sha256 or new.pack_id <> old.pack_id
     or new.pack_version <> old.pack_version
     or new.pack_manifest_sha256 <> old.pack_manifest_sha256 or new.look_role <> old.look_role
     or new.variants <> old.variants or new.request_canonical <> old.request_canonical
     or new.request_sha256 <> old.request_sha256 or new.cache_scope <> old.cache_scope
     or new.worst_case_usd <> old.worst_case_usd or new.requested_at <> old.requested_at then
    raise exception 'a piece request''s progress moves, not what it asked' using errcode = '23514';
  end if;
  if (old.state = 'requested' and new.state not in ('requested', 'queued', 'cancelled', 'failed'))
     or (old.state = 'queued'
         and new.state not in ('queued', 'made', 'refused', 'failed', 'cancelled')) then
    raise exception 'a piece request moves from requested to queued to its end'
      using errcode = '23514';
  end if;
  if old.queued_at is not null and new.queued_at is distinct from old.queued_at then
    raise exception 'a piece request is queued once' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_piece_request_progress before insert or update on piece_request
  for each row execute function tg_piece_request_progress();

-- An ask under a caller's key: the requests it answered with (made then, or already waiting),
-- so the same key answers the same requests again and a key is bound even when the ask made none.
create table piece_ask (
  workspace_id uuid not null,
  requested_by uuid not null,
  request_id uuid not null,
  ask_sha256 text not null check (ask_sha256 ~ '^[0-9a-f]{64}$'),
  piece_request_ids uuid[] not null check (cardinality(piece_request_ids) between 1 and 16),
  asked_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, requested_by, request_id)
);

create function tg_piece_ask_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id and t.scope = 'workspace') then
      perform tombstone_refuse('piece_ask');
    end if;
    new.asked_at := statement_timestamp();
    return new;
  end if;
  raise exception 'an ask is recorded once and never changed' using errcode = '23514';
end $fn$;
create trigger tg_piece_ask_append_only before insert or update on piece_ask
  for each row execute function tg_piece_ask_append_only();

-- A workspace tombstone ends every open request of the workspace. Keyed on the tombstone's own
-- columns, so a replayed tombstone reaches exactly what the original did.
create function tg_tombstone_cancels_piece_requests() returns trigger language plpgsql as $fn$
begin
  if new.scope = 'workspace' then
    update piece_request p
       set state = 'cancelled', failure = 'workspace_deleted', finished_at = new.effective_at
     where p.workspace_id = new.workspace_id and p.state in ('requested', 'queued');
  end if;
  return new;
end $fn$;
create trigger tg_tombstone_cancels_piece_requests
  after insert on tombstone
  for each row execute function tg_tombstone_cancels_piece_requests();

alter table piece_request enable row level security;
alter table piece_request force row level security;
create policy ws_isolation on piece_request
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table piece_ask enable row level security;
alter table piece_ask force row level security;
create policy ws_isolation on piece_ask
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on piece_request to %I', r);
      execute format('grant select, insert on piece_ask to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on piece_request, piece_ask to %I', r);
    end if;
  end loop;
end $$;

commit;
