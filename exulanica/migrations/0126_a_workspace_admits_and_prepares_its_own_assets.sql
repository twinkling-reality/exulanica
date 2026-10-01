-- 0126_a_workspace_admits_and_prepares_its_own_assets.sql
-- A person admits their own static 3D object to their workspace, it is prepared, and a placed
-- object can pin the prepared bytes without the object becoming global content.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- Until now every placed object named a row of `world_reviewed_asset`, a global catalog that
-- migrations fill, the runtime roles only read, and whose licence check admits CC0 alone. A
-- person's own object is none of those things, so it is held here, per workspace, and is never a
-- global row. `docs/workspace-asset-admission.md` is the contract; what follows records the shape.
--
-- THE SHAPE CHOSEN.
--
--   workspace_asset              one admission, immutable: the person's declaration (canonical
--                                bytes, the same document as jsonb, and the digest over the bytes),
--                                the exact input bytes' digest and size, the declared unit and the
--                                declared rights. The server's use policy is recorded beside it.
--   workspace_asset_withdrawal   the person ending an admission, append-only, once. Final.
--   workspace_preparation        one preparation by one pinned preparer of pinned inputs: an
--                                admission's bytes, or a character recipe of a served family
--                                revision. A lease queue in the 0016 and 0066 shape, then the
--                                output's digest and the receipt that says exactly how it was made.
--                                The one preparation queue: static assets and saved characters
--                                both use it, and each preparer is registered in code.
--   workspace_preparation_request
--                                every request that put a preparation in the queue, counted
--                                against the workspace's quota.
--   workspace_asset_blob         every object in the workspace's own store namespace, recorded
--                                before its bytes are written, so deletion finds every one.
--
-- WITHDRAWAL HIDES; IT DOES NOT ERASE. A withdrawn admission and every preparation of it are
-- unreadable the moment the withdrawal commits (`tombstone_blocks_workspace_asset`), pending
-- preparations are cancelled, and no new placement may pin it. Its bytes stay in the workspace's
-- namespace until the workspace is erased, as 0066 decided for a withdrawn material recipe.
-- Erasing one admission's bytes sooner is later work, through the one purge machinery.
--
-- ERASURE RUNS THROUGH THE ONE MACHINERY. `purge_job.target_kind` gains `workspace_asset`, whose
-- `target_ref` is a namespace object's hex digest. A workspace tombstone cancels every pending
-- preparation and enqueues every recorded namespace object; `workspace_asset_purge_is_authorized`
-- is the destroy question; `tombstone_purge_is_complete` counts an unpurged object as work left.
-- Capture and person tombstones do not reach these rows: nothing here is derived from a photograph.
--
-- THE WRITE AND THE ERASURE ARE SERIALISED as 0066 serialises bakes: a namespace object is
-- recorded before its bytes are written, under a session lock on the object the purger also takes,
-- and every tombstone insert takes the workspace lifecycle lock every write here takes.
--
-- A PLACED OBJECT MAY PIN A PREPARATION. `world_alternate_object.workspace_preparation_id` names
-- the preparation whose output the object draws; the object's `asset_sha256` is that output. The
-- reviewed catalog's foreign key moves onto a stored generated column that is the digest when no
-- preparation is pinned and null when one is, so every existing row keeps exactly its old
-- constraint, and a pinned row is held instead by a composite key to the preparation's
-- `(workspace_id, preparation_id, output_sha256)`. A binding trigger refuses writing a new pin
-- unless the preparation is placeable now, in the shape of 0050 and 0088's environment binding:
-- insertion and the revival of an undone addition are checked, and every other update keeps the
-- binding exactly as it was, so a withdrawn object can still be removed and its edits undone. (The
-- object repository refuses moving one, which is placing it again, before any row is written.)
--
-- WHAT THIS DELIBERATELY DOES NOT DO. It stores no float. It adds no tombstone scope. It adds no
-- world_id to the new tables, because an admission belongs to a workspace, not to a world. It does
-- not make any row global and it grants nothing to another workspace.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The admission.
-- --------------------------------------------------------------------------------------------

create table workspace_asset (
  workspace_id          uuid not null,
  asset_id              uuid not null default uuidv7(),
  content_kind          text not null check (content_kind = 'static_glb'),
  declaration_canonical bytea not null,
  declaration_document  jsonb not null,
  declaration_sha256    bytea not null check (octet_length(declaration_sha256) = 32),
  -- The same declaration and the same bytes: what an identical upload is recognised by.
  admission_sha256      text not null check (admission_sha256 ~ '^[0-9a-f]{64}$'),
  input_sha256          text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  input_byte_size       bigint not null check (input_byte_size between 20 and 33554432),
  unit                  text not null check (unit in ('millimetre', 'centimetre', 'metre')),
  rights_basis          text not null check (rights_basis in ('own_work', 'licensed')),
  licence_id            text check (licence_id in ('CC0-1.0', 'CC-BY-4.0')),
  title                 text not null check (
    char_length(title) between 1 and 200 and title = btrim(title) and title !~ '[[:cntrl:]]'),
  -- The server's decision about what the admission may be used for, never the declaration's.
  use_policy            text not null check (use_policy = 'exulanica.workspace-asset-use/v1'),
  created_by            uuid not null,
  created_at            timestamptz not null default statement_timestamp(),
  primary key (workspace_id, asset_id),
  constraint the_rights_basis_names_its_licence
    check ((rights_basis = 'own_work') = (licence_id is null)),
  constraint the_declaration_digest_is_over_its_bytes
    check (public.digest(declaration_canonical, 'sha256') = declaration_sha256),
  constraint the_declaration_document_is_its_bytes
    check (convert_from(declaration_canonical, 'UTF8')::jsonb = declaration_document),
  constraint the_declaration_columns_are_its_document check (
    declaration_document ->> 'profile' = 'exulanica.workspace-asset-admission/v1'
    and declaration_document ->> 'content_kind' = content_kind
    and declaration_document ->> 'content_sha256' = input_sha256
    and declaration_document -> 'byte_size' = to_jsonb(input_byte_size)
    and declaration_document ->> 'unit' = unit
    and declaration_document ->> 'title' = title
    and declaration_document -> 'rights' ->> 'basis' = rights_basis
    and (declaration_document -> 'rights' ->> 'licence_id') is not distinct from licence_id)
);
create index workspace_asset_admission_idx on workspace_asset (workspace_id, admission_sha256);

create table workspace_asset_withdrawal (
  workspace_id uuid not null,
  asset_id     uuid not null,
  withdrawn_by uuid not null,
  withdrawn_at timestamptz not null default statement_timestamp(),
  -- Once, and final.
  primary key (workspace_id, asset_id),
  foreign key (workspace_id, asset_id) references workspace_asset (workspace_id, asset_id)
);

-- --------------------------------------------------------------------------------------------
-- 2. The namespace inventory.
-- --------------------------------------------------------------------------------------------

create table workspace_asset_blob (
  workspace_id   uuid not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint not null check (byte_size > 0),
  recorded_at    timestamptz not null default statement_timestamp(),
  -- Set by the purger, after the bytes are gone, and only when a tombstone asked for them.
  purged_at      timestamptz,
  primary key (workspace_id, content_sha256)
);

-- --------------------------------------------------------------------------------------------
-- 3. The preparation.
-- --------------------------------------------------------------------------------------------

create table workspace_preparation (
  workspace_id         uuid not null,
  preparation_id       uuid not null default uuidv7(),
  -- What a preparation reads: an admitted asset's bytes, or a character recipe of a served
  -- family revision, which is the character plane's own input and names no admission.
  input_kind           text not null check (input_kind in ('workspace_asset', 'character_recipe')),
  asset_id             uuid,
  preparer_id          text not null check (preparer_id ~ '^[a-z][a-z0-9.-]*$'),
  preparer_version     integer not null check (preparer_version >= 1),
  parameters_canonical bytea not null,
  parameters_document  jsonb not null,
  parameters_sha256    bytea not null check (octet_length(parameters_sha256) = 32),
  -- The exact inputs pinned, as canonical JSON: an admission's id and input digest, or a
  -- recipe's family revision and preparation identity digests.
  inputs_canonical     bytea not null,
  inputs_document      jsonb not null,
  inputs_sha256        bytea not null check (octet_length(inputs_sha256) = 32),
  -- What makes two requests the same preparation, within one workspace only.
  preparation_key      text not null check (preparation_key ~ '^[0-9a-f]{64}$'),
  state                text not null default 'requested'
    check (state in ('requested', 'running', 'prepared', 'failed', 'cancelled')),
  attempts             integer not null default 0 check (attempts >= 0),
  -- The lease, whole while running and absent otherwise (0016).
  claim_token          uuid,
  claimed_by           text,
  lease_expires_at     timestamptz,
  requested_by         uuid not null,
  requested_at         timestamptz not null default statement_timestamp(),
  -- The output, whole or absent, and once present never changed: a later run of the same
  -- preparation must reproduce these bytes exactly.
  output_sha256        text check (output_sha256 ~ '^[0-9a-f]{64}$'),
  output_byte_size     bigint check (output_byte_size between 20 and 33554432),
  width_mm             integer check (width_mm >= 0),
  height_mm            integer check (height_mm >= 0),
  depth_mm             integer check (depth_mm >= 0),
  placeable            boolean,
  receipt_canonical    bytea,
  receipt_document     jsonb,
  receipt_sha256       bytea check (octet_length(receipt_sha256) = 32),
  prepared_at          timestamptz,
  -- The first ten are any preparation's (quota_exceeded: its output would cross the workspace's
  -- configured retained-bytes limit); the last five are the character preparer's (C7).
  failure_class        text check (failure_class in
    ('invalid_content', 'timed_out', 'unverified_output', 'nondeterministic',
     'input_bytes_missing', 'exhausted', 'cancelled', 'withdrawn', 'deleted', 'quota_exceeded',
     'stale', 'preparer_failed', 'rig_incompatible', 'deformation_invalid', 'over_budget')),
  failure_code         text check (failure_code ~ '^[a-z][a-z_]{0,63}$'),
  failure_message      text check (char_length(failure_message) <= 2000),
  primary key (workspace_id, preparation_id),
  unique (workspace_id, preparation_key),
  -- What a placed object's pin references: this preparation and exactly its output.
  unique (workspace_id, preparation_id, output_sha256),
  foreign key (workspace_id, asset_id) references workspace_asset (workspace_id, asset_id),
  constraint an_asset_preparation_names_its_asset
    check ((input_kind = 'workspace_asset') = (asset_id is not null)),
  constraint a_lease_is_whole_while_running check (
    (state = 'running')
      = (claim_token is not null and claimed_by is not null and lease_expires_at is not null)
    and num_nulls(claim_token, claimed_by, lease_expires_at) in (0, 3)),
  constraint an_output_is_whole_or_absent check (
    num_nulls(output_sha256, output_byte_size, width_mm, height_mm, depth_mm, placeable,
              receipt_canonical, receipt_document, receipt_sha256, prepared_at) in (0, 10)),
  constraint a_prepared_row_holds_its_output
    check (state <> 'prepared' or output_sha256 is not null),
  constraint a_failure_is_named_where_it_happened
    check ((failure_class is not null) = (state in ('failed', 'cancelled'))
           and (failure_message is null or failure_class is not null)
           and (failure_code is null or failure_class is not null)),
  constraint the_parameters_digest_is_over_their_bytes
    check (public.digest(parameters_canonical, 'sha256') = parameters_sha256),
  constraint the_parameters_document_is_their_bytes
    check (convert_from(parameters_canonical, 'UTF8')::jsonb = parameters_document),
  constraint the_inputs_digest_is_over_their_bytes
    check (public.digest(inputs_canonical, 'sha256') = inputs_sha256),
  constraint the_inputs_document_is_their_bytes
    check (convert_from(inputs_canonical, 'UTF8')::jsonb = inputs_document),
  constraint the_receipt_digest_is_over_its_bytes
    check (receipt_canonical is null
           or public.digest(receipt_canonical, 'sha256') = receipt_sha256),
  constraint the_receipt_document_is_its_bytes
    check (receipt_canonical is null
           or convert_from(receipt_canonical, 'UTF8')::jsonb = receipt_document),
  constraint the_receipt_columns_are_its_document check (
    receipt_document is null or (
      receipt_document ->> 'profile' = 'exulanica.workspace-preparation-receipt/v1'
      and (receipt_document ->> 'asset_id') is not distinct from asset_id::text
      and receipt_document -> 'inputs_sha256' = to_jsonb(encode(inputs_sha256, 'hex'))
      and receipt_document -> 'preparer' ->> 'id' = preparer_id
      and receipt_document -> 'preparer' -> 'version' = to_jsonb(preparer_version)
      and receipt_document -> 'output' ->> 'content_sha256' = output_sha256
      and receipt_document -> 'output' -> 'byte_size' = to_jsonb(output_byte_size)
      and receipt_document -> 'parameters_sha256' = to_jsonb(encode(parameters_sha256, 'hex'))))
);
create index workspace_preparation_queue_idx
  on workspace_preparation (state, lease_expires_at, requested_at)
  where state in ('requested', 'running');
create index workspace_preparation_asset_idx
  on workspace_preparation (workspace_id, asset_id);

-- Every request that put a preparation in the queue: the first, a retry after a failure or a
-- cancellation, and a re-run of one whose output bytes went missing all cost the same.
create table workspace_preparation_request (
  workspace_id   uuid not null,
  request_id     uuid not null default uuidv7(),
  preparation_id uuid not null,
  requested_by   uuid not null,
  requested_at   timestamptz not null default statement_timestamp(),
  primary key (workspace_id, request_id),
  foreign key (workspace_id, preparation_id)
    references workspace_preparation (workspace_id, preparation_id)
);
create index workspace_preparation_request_day_idx
  on workspace_preparation_request (workspace_id, requested_at);

-- --------------------------------------------------------------------------------------------
-- 4. What blocks an admission, the lock every write takes, and what may be placed.
-- --------------------------------------------------------------------------------------------

-- An admission is unreadable once its workspace is erased or its holder withdrew it. A missing
-- admission fails closed, which also covers a session that declared no workspace. VOLATILE, for
-- the fresh snapshot 0024 explains.
create function tombstone_blocks_workspace_asset(p_workspace uuid, p_asset uuid)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from workspace_asset a
                 where a.workspace_id = p_workspace and a.asset_id = p_asset)
    or exists (select 1 from tombstone t
                where t.workspace_id = p_workspace
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp())
    or exists (select 1 from workspace_asset_withdrawal w
                where w.workspace_id = p_workspace and w.asset_id = p_asset);
$fn$;

comment on function tombstone_blocks_workspace_asset(uuid, uuid) is
  'Is this admission unreadable: its workspace erased or the admission withdrawn. Fails closed.';

-- A preparation of an admission is blocked exactly when its admission is. One that names no
-- admission (a character recipe) is blocked when its workspace is erased; whether its recipe is
-- still served is its own preparer's question, asked when it records (``stale``).
create function tombstone_blocks_workspace_preparation(p_workspace uuid, p_asset uuid)
returns boolean
language sql volatile as $fn$
  select case
    when p_asset is not null then tombstone_blocks_workspace_asset(p_workspace, p_asset)
    else exists (select 1 from tombstone t
                  where t.workspace_id = p_workspace
                    and t.scope = 'workspace'
                    and t.effective_at <= clock_timestamp())
  end;
$fn$;

-- The per-workspace bounds, stated once: the guards below enforce them and the API reports them.
-- Declared bounds, not measured capacity.
create function workspace_asset_limits(
  out assets integer, out input_bytes bigint, out requests_per_day integer,
  out pending_at_once integer
)
language sql immutable as $fn$
  select 64, 536870912::bigint, 64, 8;
$fn$;

-- Which count bound a new admission (p_admission) or a request that queues a run would meet now,
-- by its name, or null: the counts the admission and request guards below refuse on, asked before
-- writing, for a capability read. The guards stay the authority, and also refuse what this cannot
-- see in advance: the byte total, and two requests racing for the last place.
create function workspace_asset_spent(p_workspace uuid, p_admission boolean)
returns text
language sql volatile as $fn$
  with bound as (select * from workspace_asset_limits())
  select case
    when p_admission
         and (select count(*) from workspace_asset a
               where a.workspace_id = p_workspace
                 and not exists (select 1 from workspace_asset_withdrawal w
                                  where w.workspace_id = a.workspace_id
                                    and w.asset_id = a.asset_id))
             >= (select assets from bound) then 'assets'
    when (select count(*) from workspace_preparation_request r
           where r.workspace_id = p_workspace
             and r.requested_at > statement_timestamp() - interval '1 day')
         >= (select requests_per_day from bound) then 'requests_per_day'
    when (select count(*) from workspace_preparation p
           where p.workspace_id = p_workspace and p.state in ('requested', 'running'))
         >= (select pending_at_once from bound) then 'pending_at_once'
  end;
$fn$;

-- The lock a tombstone, a withdrawal and every write here take, so none commits around another.
create function workspace_asset_lifecycle_lock(p_workspace uuid) returns void
language sql volatile as $fn$
  select pg_advisory_xact_lock(
    hashtextextended('workspace-asset-lifecycle:' || p_workspace::text, 0));
$fn$;

-- Whether a placed object may pin this preparation's output now: this session's workspace, the
-- preparation's output recorded as this digest, placeable and not purged, its admission neither
-- withdrawn nor erased. It reads rows and never the preparation's state: an output is written once,
-- and a run that reproduces missing bytes does not make a placed object's source withdrawn. A new
-- placement asks more first (prepared, bytes present); this is the rights question a pin keeps.
create function workspace_asset_placeable(
  p_workspace uuid, p_preparation uuid, p_output text
) returns boolean
language sql volatile as $fn$
  select p_workspace = current_workspace() and exists (
    select 1
      from workspace_preparation p
      join workspace_asset_blob b on b.workspace_id = p.workspace_id
                                 and b.content_sha256 = p.output_sha256
     where p.workspace_id = p_workspace
       and p.preparation_id = p_preparation
       and p.output_sha256 = p_output
       and p.input_kind = 'workspace_asset'
       and p.placeable
       and b.purged_at is null
       and not tombstone_blocks_workspace_asset(p.workspace_id, p.asset_id));
$fn$;

comment on function workspace_asset_placeable(uuid, uuid, text) is
  'May a placed object pin this preparation''s output now. The binding trigger asks it; the '
  'object repository asks the same question first, so the two answer alike.';

-- --------------------------------------------------------------------------------------------
-- 5. Guards.
-- --------------------------------------------------------------------------------------------

create function tg_workspace_asset_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

-- The admission: immutable, refused once the workspace is erased, and bounded per workspace.
create function tg_workspace_asset_guard() returns trigger
language plpgsql as $fn$
declare
  live integer;
  live_bytes bigint;
  bound record;
begin
  perform assert_workspace_context(new.workspace_id);
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  select * into bound from workspace_asset_limits();
  if exists (select 1 from tombstone t
              where t.workspace_id = new.workspace_id
                and t.scope = 'workspace'
                and t.effective_at <= clock_timestamp()) then
    perform tombstone_refuse('workspace_asset');
  end if;
  select count(*), coalesce(sum(a.input_byte_size), 0) into live, live_bytes
    from workspace_asset a
   where a.workspace_id = new.workspace_id
     and not exists (select 1 from workspace_asset_withdrawal w
                      where w.workspace_id = a.workspace_id and w.asset_id = a.asset_id);
  if live >= bound.assets then
    raise exception 'this workspace holds % admitted assets, its limit', live
      using errcode = 'program_limit_exceeded';
  end if;
  if live_bytes + new.input_byte_size > bound.input_bytes then
    raise exception 'this workspace''s admitted assets would exceed % bytes', bound.input_bytes
      using errcode = 'program_limit_exceeded';
  end if;
  new.created_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_workspace_asset_guard
  before insert on workspace_asset
  for each row execute function tg_workspace_asset_guard();
create trigger tg_workspace_asset_append_only
  before update or delete on workspace_asset
  for each row execute function tg_workspace_asset_append_only();

-- A withdrawal names an admission in this workspace, is serialised with the preparation that might
-- finish beside it, and cancels whatever preparation of it has not finished.
create function tg_workspace_asset_withdrawal_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  -- withdrawn_at is the column default's for a new withdrawal and the carried row's own when a
  -- restore writes one again (the restore withdrawal catalog), as 0066's recipe withdrawal is.
  return new;
end $fn$;

create trigger tg_workspace_asset_withdrawal_guard
  before insert on workspace_asset_withdrawal
  for each row execute function tg_workspace_asset_withdrawal_guard();

create function tg_workspace_asset_withdrawal_cancels() returns trigger
language plpgsql as $fn$
begin
  update workspace_preparation p
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'withdrawn', failure_code = null,
         failure_message = 'the admission was withdrawn'
   where p.workspace_id = new.workspace_id
     and p.asset_id = new.asset_id
     and p.state in ('requested', 'running', 'failed');
  return null;
end $fn$;

create trigger tg_workspace_asset_withdrawal_cancels
  after insert on workspace_asset_withdrawal
  for each row execute function tg_workspace_asset_withdrawal_cancels();

-- A namespace object is recorded under the lifecycle lock and never after the workspace is erased.
create function tg_workspace_asset_blob_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.purged_at is not null then
      raise exception 'a namespace object arrives unpurged'
        using errcode = 'check_violation';
    end if;
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp()) then
      perform tombstone_refuse('workspace_asset_blob');
    end if;
    new.recorded_at := statement_timestamp();
    return new;
  end if;
  if old.purged_at is not null then
    if new is distinct from old then
      raise exception 'a purged namespace object does not change again'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'purged_at') is distinct from (to_jsonb(old) - 'purged_at')
     or new.purged_at is null then
    raise exception 'only the purger writes a namespace object, and only its purge'
      using errcode = 'check_violation';
  end if;
  if not exists (
       select 1 from purge_job pj
        where pj.workspace_id = new.workspace_id
          and pj.target_kind = 'workspace_asset'
          and pj.target_ref = new.content_sha256
          and workspace_asset_purge_is_authorized(new.workspace_id, pj.tombstone_id,
                                                  new.content_sha256)) then
    raise exception 'a namespace object is marked purged only when a tombstone asked for it'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

-- The preparation: its states, its fixed identity, its write-once output, and its source's state.
create function tg_workspace_preparation_guard() returns trigger
language plpgsql as $fn$
declare
  own_input text;
begin
  perform assert_workspace_context(new.workspace_id);

  if tg_op = 'INSERT' then
    if new.state <> 'requested' or new.attempts <> 0 or new.output_sha256 is not null then
      raise exception 'a preparation arrives requested, unattempted and empty'
        using errcode = 'check_violation';
    end if;
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_preparation(new.workspace_id, new.asset_id) then
      perform tombstone_refuse('workspace_preparation');
    end if;
    new.requested_at := statement_timestamp();
    return new;
  end if;

  if (new.workspace_id, new.preparation_id, new.input_kind, new.asset_id, new.preparer_id,
      new.preparer_version, new.parameters_canonical, new.parameters_sha256,
      new.inputs_canonical, new.inputs_sha256, new.preparation_key, new.requested_by,
      new.requested_at)
     is distinct from (old.workspace_id, old.preparation_id, old.input_kind, old.asset_id,
                       old.preparer_id, old.preparer_version, old.parameters_canonical,
                       old.parameters_sha256, old.inputs_canonical, old.inputs_sha256,
                       old.preparation_key, old.requested_by, old.requested_at) then
    raise exception 'a preparation''s identity and request are fixed'
      using errcode = 'check_violation';
  end if;
  if old.output_sha256 is not null
     and (new.output_sha256, new.output_byte_size, new.width_mm, new.height_mm, new.depth_mm,
          new.placeable, new.receipt_canonical, new.receipt_sha256, new.prepared_at)
         is distinct from (old.output_sha256, old.output_byte_size, old.width_mm, old.height_mm,
                           old.depth_mm, old.placeable, old.receipt_canonical, old.receipt_sha256,
                           old.prepared_at) then
    raise exception 'a preparation''s output is fixed once recorded; a later run must '
                    'reproduce it'
      using errcode = 'check_violation';
  end if;

  if new.state is distinct from old.state then
    if not (
         (old.state = 'requested' and new.state in ('running', 'cancelled'))
      or (old.state = 'running' and new.state in ('running', 'prepared', 'failed', 'cancelled'))
      or (old.state = 'failed' and new.state in ('requested', 'cancelled'))
      or (old.state = 'cancelled' and new.state = 'requested')
      or (old.state = 'prepared' and new.state = 'requested')) then
      raise exception 'a preparation does not move from % to %', old.state, new.state
        using errcode = 'check_violation';
    end if;
  end if;

  if new.state in ('requested', 'running', 'prepared')
     and (new.state is distinct from old.state
          or new.claim_token is distinct from old.claim_token
          or new.output_sha256 is distinct from old.output_sha256) then
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_preparation(new.workspace_id, new.asset_id) then
      perform tombstone_refuse('workspace_preparation');
    end if;
  end if;

  if new.state = 'prepared' and old.state <> 'prepared' then
    if new.input_kind = 'workspace_asset' then
      select a.input_sha256 into own_input from workspace_asset a
       where a.workspace_id = new.workspace_id and a.asset_id = new.asset_id;
      if new.receipt_document -> 'input' ->> 'content_sha256' is distinct from own_input then
        raise exception 'the receipt describes another input than this preparation''s admission'
          using errcode = 'check_violation';
      end if;
    end if;
    if not exists (select 1 from workspace_asset_blob b
                    where b.workspace_id = new.workspace_id
                      and b.content_sha256 = new.output_sha256
                      and b.purged_at is null) then
      raise exception 'a prepared output is recorded in the namespace inventory first'
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_workspace_preparation_guard
  before insert or update on workspace_preparation
  for each row execute function tg_workspace_preparation_guard();
create trigger tg_workspace_preparation_no_delete
  before delete on workspace_preparation
  for each row execute function tg_workspace_asset_append_only();

-- Every request that puts a preparation in the queue is counted, and refused past the quota.
create function tg_workspace_preparation_request_guard() returns trigger
language plpgsql as $fn$
declare
  spent integer;
  waiting integer;
  bound record;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended('workspace-asset-preparation-quota:' || new.workspace_id::text, 0));
  select * into bound from workspace_asset_limits();
  if not exists (select 1 from workspace_preparation p
                  where p.workspace_id = new.workspace_id
                    and p.preparation_id = new.preparation_id
                    and p.state = 'requested') then
    raise exception 'a preparation request names a preparation that is not waiting'
      using errcode = 'check_violation';
  end if;
  select count(*) into spent from workspace_preparation_request r
   where r.workspace_id = new.workspace_id
     and r.requested_at > statement_timestamp() - interval '1 day';
  if spent >= bound.requests_per_day then
    raise exception 'this workspace has requested % preparations in the last day, its limit',
      spent
      using errcode = 'program_limit_exceeded';
  end if;
  select count(*) into waiting from workspace_preparation p
   where p.workspace_id = new.workspace_id and p.state in ('requested', 'running');
  if waiting > bound.pending_at_once then
    raise exception 'this workspace already has % preparations waiting, its limit', waiting - 1
      using errcode = 'program_limit_exceeded';
  end if;
  new.requested_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_workspace_preparation_request_guard
  before insert on workspace_preparation_request
  for each row execute function tg_workspace_preparation_request_guard();

-- The count is not left to whoever writes the queue: a preparation that entered `requested` in
-- this transaction has a request row written in it too (0066's rule for bakes).
create function tg_workspace_preparation_request_counted() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'UPDATE' and old.state = 'requested' then
    return null;
  end if;
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from workspace_preparation_request r
                  where r.workspace_id = new.workspace_id
                    and r.preparation_id = new.preparation_id
                    and r.requested_at >= transaction_timestamp()) then
    raise exception 'preparation % entered the queue without a request that counts it',
      new.preparation_id
      using errcode = 'check_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_workspace_preparation_request_counted
  after insert or update on workspace_preparation
  deferrable initially deferred
  for each row
  when (new.state = 'requested')
  execute function tg_workspace_preparation_request_counted();

do $$
declare
  t text;
begin
  foreach t in array array['workspace_asset_withdrawal', 'workspace_preparation_request'] loop
    execute format(
      'create trigger %I before update or delete on %I '
      'for each row execute function tg_workspace_asset_append_only()',
      'tg_' || t || '_append_only', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 6. Erasure: the destroy question, the queue, the lock, and completion.
-- --------------------------------------------------------------------------------------------

-- Whether a tombstone may destroy these bytes from its workspace's namespace. Only a workspace
-- tombstone reaches this namespace, and it may destroy anything in it, whether or not a row still
-- names it: the namespace is the workspace's alone, and all of it goes (0066's rule, and its
-- restore case: bytes a restored database no longer names are still the workspace's).
create function workspace_asset_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_content text
) returns boolean
language sql volatile security definer as $fn$
  select p_workspace = current_workspace() and p_content ~ '^[0-9a-f]{64}$' and exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.tombstone_id = p_tombstone
       and t.effective_at <= now()
       and t.scope = 'workspace');
$fn$;

comment on function workspace_asset_purge_is_authorized(uuid, uuid, text) is
  'May this tombstone destroy these bytes from its workspace''s asset namespace: it is effective, '
  'in this session''s workspace, and a workspace tombstone. For the purge role.';

do $$ begin
  execute format('alter function workspace_asset_purge_is_authorized(uuid,uuid,text) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $$;
revoke all on function workspace_asset_purge_is_authorized(uuid, uuid, text) from public;

create trigger tg_workspace_asset_blob_guard
  before insert or update on workspace_asset_blob
  for each row execute function tg_workspace_asset_blob_guard();
create trigger tg_workspace_asset_blob_no_delete
  before delete on workspace_asset_blob
  for each row execute function tg_workspace_asset_append_only();

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake',
                         'workspace_asset'));

create function tg_workspace_asset_lifecycle_lock() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  return new;
end $fn$;

create trigger tg_workspace_asset_lifecycle_lock
  before insert on tombstone
  for each row execute function tg_workspace_asset_lifecycle_lock();

-- Its order among the tombstone's AFTER triggers does not matter: it acts on workspace scope only,
-- and the person withdrawal cascade on entity scope only.
create function tg_workspace_asset_purge_on_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope <> 'workspace' then
    return new;
  end if;
  update workspace_preparation p
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'deleted', failure_code = null,
         failure_message = 'the workspace was erased before the preparation finished'
   where p.workspace_id = new.workspace_id
     and p.state in ('requested', 'running', 'failed');
  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select new.tombstone_id, new.workspace_id, 'workspace_asset', b.content_sha256
    from workspace_asset_blob b
   where b.workspace_id = new.workspace_id
     and b.purged_at is null
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;

create trigger tg_workspace_asset_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_workspace_asset_purge_on_tombstone();

-- Re-stated from 0066 with two clauses added: a namespace job whose object is not yet marked
-- purged, and, for a workspace tombstone, any namespace object still holding bytes. Everything
-- 0066 asks is asked unchanged.
create or replace function tombstone_purge_is_complete(p_tombstone uuid) returns boolean
language plpgsql volatile as $fn$
declare v_scope text; v_workspace uuid;
begin
  select t.scope::text, t.workspace_id into v_scope, v_workspace
    from tombstone t where t.tombstone_id=p_tombstone;
  if v_scope is null then return false; end if;
  if not caption_vector_purge_is_complete(v_workspace, p_tombstone) then return false; end if;
  if exists (
    select 1 from purge_job pj where pj.tombstone_id=p_tombstone and (
      pj.state <> 'done'
      or (pj.target_kind='blob' and exists (select 1 from blob b
          where b.blob_sha256=decode(pj.target_ref,'hex') and b.purged_at is null))
      or (pj.target_kind='artifact' and exists (select 1 from artifact a
          where a.workspace_id=pj.workspace_id and a.content_sha256=decode(pj.target_ref,'hex')
            and a.purged_at is null))
      or (pj.target_kind='embedding' and exists (select 1 from embedding e
          where e.workspace_id=pj.workspace_id and e.embedding_id=pj.target_ref::uuid))
      or (pj.target_kind='material_bake' and exists (select 1 from material_bake m
          where m.workspace_id=pj.workspace_id and m.content_sha256=decode(pj.target_ref,'hex')
            and m.purged_at is null))
      or (pj.target_kind='workspace_asset' and exists (select 1 from workspace_asset_blob w
          where w.workspace_id=pj.workspace_id and w.content_sha256=pj.target_ref
            and w.purged_at is null)))) then
    return false;
  end if;
  if v_scope='workspace' then
    return not exists (select 1 from capture c join blob b on b.blob_sha256=c.blob_sha256
                        where c.workspace_id=v_workspace and b.purged_at is null)
       and not exists (select 1 from artifact a where a.workspace_id=v_workspace
                        and a.content_sha256 is not null and a.purged_at is null)
       and not exists (select 1 from embedding e where e.workspace_id=v_workspace)
       and not exists (select 1 from material_bake m where m.workspace_id=v_workspace
                        and m.content_sha256 is not null and m.purged_at is null)
       and not exists (select 1 from workspace_asset_blob w where w.workspace_id=v_workspace
                        and w.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 7. A placed object may pin a preparation.
-- --------------------------------------------------------------------------------------------

alter table world_alternate_object add column workspace_preparation_id uuid;
-- The reviewed catalog's key, on exactly the rows that name no preparation: every existing row.
alter table world_alternate_object add column reviewed_asset_sha256 text
  generated always as (case when workspace_preparation_id is null then asset_sha256 end) stored;
alter table world_alternate_object drop constraint world_alternate_object_asset_sha256_fkey;
alter table world_alternate_object add constraint world_alternate_object_reviewed_asset_fkey
  foreign key (reviewed_asset_sha256) references world_reviewed_asset (content_sha256);
alter table world_alternate_object add constraint world_alternate_object_workspace_asset_fkey
  foreign key (workspace_id, workspace_preparation_id, asset_sha256)
  references workspace_preparation (workspace_id, preparation_id, output_sha256);
-- A reviewed behaviour is reviewed against a catalog asset; the first workspace profile takes none.
alter table world_alternate_object add constraint world_alternate_object_workspace_asset_behaviour
  check (workspace_preparation_id is null or behaviour_key is null);

-- Insertion and the revival of an undone addition place something, so they ask whether the pinned
-- preparation may be placed now. Every other update keeps the pin and the digest exactly as they
-- were: moving, removing and undoing never re-authorize a withdrawn source (0088's rule).
create function tg_world_object_workspace_asset_binding() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'UPDATE' and not (old.addition_undone and not new.addition_undone) then
    if (new.asset_sha256, new.workspace_preparation_id)
       is distinct from (old.asset_sha256, old.workspace_preparation_id) then
      raise exception 'a placed object''s workspace asset binding is immutable'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if new.workspace_preparation_id is not null
     and workspace_asset_placeable(new.workspace_id, new.workspace_preparation_id,
                                   new.asset_sha256) is not true then
    raise exception 'workspace asset preparation is not placeable: withdrawn, erased, unplaceable '
                    'or not this output'
      using errcode = '23514';
  end if;
  return new;
end $fn$;

create trigger tg_world_object_workspace_asset_binding
  before insert on world_alternate_object
  for each row
  when (new.workspace_preparation_id is not null)
  execute function tg_world_object_workspace_asset_binding();
create trigger tg_world_object_workspace_asset_rebinding
  before update on world_alternate_object
  for each row
  when (new.workspace_preparation_id is not null or old.workspace_preparation_id is not null)
  execute function tg_world_object_workspace_asset_binding();

-- --------------------------------------------------------------------------------------------
-- 8. Row-level security, the delivery barrier, and the sealed checkpoint.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['workspace_asset', 'workspace_asset_withdrawal', 'workspace_asset_blob',
                           'workspace_preparation', 'workspace_preparation_request']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

-- A write that changes whether an admission or its output may be read waits for, or fails
-- against, a delivery or a placement's last question in progress (0041).
do $$ declare t text; begin
  foreach t in array array['workspace_asset', 'workspace_asset_withdrawal', 'workspace_asset_blob',
                           'workspace_preparation'] loop
    execute format('create trigger aaa_asset_read_mutation '
      'before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()', t);
  end loop;
end $$;

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on workspace_asset_withdrawal
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

commit;
