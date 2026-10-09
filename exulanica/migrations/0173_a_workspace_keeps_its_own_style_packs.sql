-- 0173_a_workspace_keeps_its_own_style_packs.sql
-- A creator keeps their own style packs in their workspace: each version admitted, checked by a
-- preparation, worn by their worlds while it is ready, withdrawn by them, and erased with the
-- workspace.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- Until now every style pack a world could wear was a committed library pack that the host serves
-- by digest. A person's own pack is none of those: it is held here, per workspace, and is never a
-- library row. `docs/style-pack-contract.md` section 11 is the contract; what follows records the
-- shape.
--
-- THE SHAPE CHOSEN.
--
--   workspace_style_pack_version      one admitted version, immutable: its canonical manifest and
--                                     declaration (each with its digest), the pack id and version,
--                                     the declared rights, the base it is drawn on, and the
--                                     admission receipt. What the creator chose or wrote (the two
--                                     documents, the attribution, the pack ids) a tombstone erases,
--                                     keeping digests and sizes; the receipt becomes a fixed marker.
--   workspace_style_pack_file         every file the manifest lists, by path, digest and size.
--   workspace_style_pack_preparation  the check of the pack's pieces, one per version: a lease
--                                     queue in the 0126 shape, ending ready, failed or cancelled.
--   workspace_style_pack_withdrawal   the creator ending a version, append-only, once. Final.
--   workspace_style_pack_publish_request
--                                     the creator asking for a version to join the shared library,
--                                     with the licence they grant the project. Only a host command
--                                     publishes, and only on such a request.
--   workspace_style_pack_blob         every object in the workspace's style pack namespace,
--                                     recorded before its bytes are written, so deletion finds
--                                     every one; 0126's inventory, for this namespace.
--   workspace_style_pack_attempt_day  a workspace's upload attempts in one UTC day.
--   installation_style_pack_day       the installation's attempts in one UTC day.
--   installation_style_pack_total     the installation's retained style pack bytes, one row, kept
--                                     by the inventory's triggers and read under its row lock, so
--                                     the installation's ceiling is exact.
--
-- WHAT A WORLD MAY WEAR. `workspace_style_pack_wearable` is the one question: the pack is this
-- session's workspace's, its preparation is ready, neither it nor any workspace pack in its base
-- chain is withdrawn or erased, and every file is still held. A world write that names a workspace
-- pack asks it under the asset read lock (0041), and so does every delivery's final read check.
--
-- WITHDRAWAL HIDES; IT DOES NOT ERASE, as 0126's asset withdrawal: a withdrawn version stops being
-- worn or served at once and its pending preparation is cancelled; its bytes stay in the namespace
-- until the workspace is erased. A version another live version of the workspace is drawn on is
-- not withdrawn while that one stands (`style_pack_is_a_base`).
--
-- ERASURE RUNS THROUGH THE ONE MACHINERY. `purge_job.target_kind` gains `workspace_style_pack`,
-- whose `target_ref` is a namespace object's hex digest. A workspace tombstone cancels every
-- pending preparation, erases every uploader text (both documents, every file path, every failure
-- message), and enqueues every recorded namespace object; `workspace_style_pack_purge_is_authorized`
-- is the destroy question; `tombstone_purge_is_complete` counts an unpurged object as work left.
--
-- THE WRITE AND THE ERASURE ARE SERIALISED as 0126 serialises them: every write here takes the
-- workspace lifecycle lock (`workspace_asset_lifecycle_lock`) a tombstone insert already takes,
-- and a namespace object is recorded before its bytes are written, under a session lock the
-- purger also takes.
--
-- WHAT THIS DELIBERATELY DOES NOT DO. It stores no float. It adds no tombstone scope. It does not
-- make any row global except the installation's counters, which hold no workspace's content, and
-- it grants nothing to another workspace. It does not touch the library or a world's style version
-- table: a world names a workspace pack by the same (pack id, version, manifest digest) it names a
-- library pack by, and the host asks the library first, then this workspace.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The version, its files and its preparation.
-- --------------------------------------------------------------------------------------------

create table workspace_style_pack_version (
  workspace_id          uuid not null,
  manifest_sha256       text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  -- A creator's own namespace: never the project's.
  pack_id               text not null check (
    pack_id ~ '^[a-z][a-z0-9-]{0,31}(\.[a-z][a-z0-9-]{0,31}){1,3}$'
    and pack_id !~ '^exulanica\.'),
  version               integer not null check (version between 1 and 1000000),
  -- The documents, as admitted; null once the workspace is erased (with erased_at).
  manifest_canonical    bytea,
  manifest_byte_size    integer not null check (manifest_byte_size between 2 and 262144),
  declaration_canonical bytea,
  declaration_sha256    bytea not null check (octet_length(declaration_sha256) = 32),
  rights_basis          text not null check (rights_basis in ('own_work', 'licensed')),
  licence_id            text not null check (
    licence_id in ('CC0-1.0', 'CC-BY-4.0', 'LicenseRef-Exulanica-Own-Work')),
  -- The attribution a licensed CC-BY version came under; null otherwise and once erased.
  licence_attribution   text check (char_length(licence_attribution) between 1 and 400),
  -- The pack it is drawn on: a library version, or a version of this workspace's own.
  base_source           text check (base_source in ('library', 'workspace')),
  base_pack_id          text check (
    base_pack_id ~ '^[a-z][a-z0-9-]{0,31}(\.[a-z][a-z0-9-]{0,31}){1,3}$'),
  base_version          integer check (base_version between 1 and 1000000),
  base_manifest_sha256  text check (base_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  file_count            integer not null check (file_count between 0 and 512),
  file_byte_size        bigint not null check (file_byte_size between 0 and 67108864),
  preview_sha256        text check (preview_sha256 ~ '^[0-9a-f]{64}$'),
  -- What the admission checked, each check and its verdict, and the readers' versions; a fixed
  -- marker once erased.
  receipt_document      jsonb not null check (octet_length(receipt_document::text) <= 65536),
  -- The manifest's, the declaration's and the receipt's bytes together, as admitted: what the
  -- version holds in the database until its workspace is erased, counted in both byte totals.
  documents_byte_size   integer not null default 1 check (documents_byte_size > 0),
  -- The server's decision about what the version may be used for, never the declaration's.
  use_policy            text not null check (use_policy = 'exulanica.workspace-style-pack-use/v1'),
  created_by            uuid not null,
  created_at            timestamptz not null default statement_timestamp(),
  erased_at             timestamptz,
  primary key (workspace_id, manifest_sha256),
  -- The "erased." ids are the erasure's: a live version never holds one nor names one as any base,
  -- library or workspace, and an erased one always holds one, so no id a creator chooses can meet
  -- the id an erasure writes (the identity index below).
  constraint erased_ids_are_the_erasures
    check ((erased_at is not null) = (pack_id ~ '^erased\.')
           and (erased_at is not null or base_pack_id !~ '^erased\.')),
  constraint a_base_is_whole_or_absent
    check (num_nulls(base_source, base_pack_id, base_version, base_manifest_sha256) in (0, 4)),
  constraint a_workspace_base_is_a_workspace_pack
    check (base_source is distinct from 'workspace' or base_pack_id !~ '^exulanica\.'),
  constraint own_work_is_its_own_licence
    check ((rights_basis = 'own_work') = (licence_id = 'LicenseRef-Exulanica-Own-Work')),
  constraint an_erased_version_holds_no_document
    check ((erased_at is null) = (manifest_canonical is not null)
           and (erased_at is null) = (declaration_canonical is not null)),
  constraint the_manifest_digest_is_over_its_bytes
    check (manifest_canonical is null
           or encode(public.digest(manifest_canonical, 'sha256'), 'hex') = manifest_sha256),
  constraint the_manifest_size_is_its_bytes
    check (manifest_canonical is null or octet_length(manifest_canonical) = manifest_byte_size),
  constraint the_declaration_digest_is_over_its_bytes
    check (declaration_canonical is null
           or public.digest(declaration_canonical, 'sha256') = declaration_sha256),
  constraint a_declaration_is_bounded
    check (declaration_canonical is null or octet_length(declaration_canonical) <= 65536),
  constraint a_cc_by_version_names_its_attribution
    check (erased_at is not null
           or (licence_id = 'CC-BY-4.0') = (licence_attribution is not null)),
  constraint an_erased_version_holds_no_attribution
    check (erased_at is null or licence_attribution is null)
);
-- A pack id and version name one live version of a workspace. Erased rows are left out: the
-- erasure rewrites every id in one statement, and a unique key checked row by row would meet an
-- id the statement had not yet rewritten.
create unique index workspace_style_pack_version_identity
  on workspace_style_pack_version (workspace_id, pack_id, version)
  where erased_at is null;
create index workspace_style_pack_version_base_idx
  on workspace_style_pack_version (workspace_id, base_manifest_sha256)
  where base_source = 'workspace';

create table workspace_style_pack_file (
  workspace_id    uuid not null,
  manifest_sha256 text not null,
  ordinal         integer not null check (ordinal between 0 and 511),
  -- The manifest's path for the file; null once the workspace is erased.
  path            text check (char_length(path) between 1 and 300),
  content_sha256  text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size       bigint not null check (byte_size between 1 and 67108864),
  media_type      text not null check (
    media_type in ('model/gltf-binary', 'image/jpeg', 'image/png', 'image/webp')),
  primary key (workspace_id, manifest_sha256, ordinal),
  foreign key (workspace_id, manifest_sha256)
    references workspace_style_pack_version (workspace_id, manifest_sha256)
);
create index workspace_style_pack_file_content_idx
  on workspace_style_pack_file (workspace_id, content_sha256);

create table workspace_style_pack_preparation (
  workspace_id     uuid not null,
  manifest_sha256  text not null,
  state            text not null default 'requested'
    check (state in ('requested', 'running', 'ready', 'failed', 'cancelled')),
  attempts         integer not null default 0 check (attempts >= 0),
  -- The lease, whole while running and absent otherwise (0016).
  claim_token      uuid,
  claimed_by       text,
  lease_expires_at timestamptz,
  requested_at     timestamptz not null default statement_timestamp(),
  -- What the check found, once it ends: the per-piece measures, and for a failure its class.
  report_document  jsonb check (octet_length(report_document::text) <= 65536),
  finished_at      timestamptz,
  -- interrupted: the check's time bound or its worker stopped it, and a repeat may ask again;
  -- refused: the pieces broke a rule, which the same bytes always will; base_unavailable: a pack
  -- in its base chain was withdrawn or is not ready; withdrawn and deleted: it was cancelled.
  failure_class    text check (failure_class in
    ('interrupted', 'refused', 'base_unavailable', 'withdrawn', 'deleted')),
  -- What the check said, for its creator; null once the workspace is erased.
  failure_message  text check (char_length(failure_message) <= 2000),
  primary key (workspace_id, manifest_sha256),
  foreign key (workspace_id, manifest_sha256)
    references workspace_style_pack_version (workspace_id, manifest_sha256),
  constraint a_style_pack_lease_is_whole_while_running check (
    (state = 'running')
      = (claim_token is not null and claimed_by is not null and lease_expires_at is not null)
    and num_nulls(claim_token, claimed_by, lease_expires_at) in (0, 3)),
  constraint a_style_pack_failure_is_named
    check ((failure_class is not null) = (state in ('failed', 'cancelled'))
           and (failure_message is null or failure_class is not null)),
  constraint a_finished_check_says_when
    check ((finished_at is not null) = (state in ('ready', 'failed', 'cancelled')))
);
create index workspace_style_pack_preparation_queue_idx
  on workspace_style_pack_preparation (state, lease_expires_at, requested_at)
  where state in ('requested', 'running');

create table workspace_style_pack_withdrawal (
  workspace_id    uuid not null,
  manifest_sha256 text not null,
  withdrawn_by    uuid not null,
  withdrawn_at    timestamptz not null default statement_timestamp(),
  -- Once, and final.
  primary key (workspace_id, manifest_sha256),
  foreign key (workspace_id, manifest_sha256)
    references workspace_style_pack_version (workspace_id, manifest_sha256)
);

-- The creator's request that a version join the shared library, with the licence they grant the
-- project. A licensed version can pass on only the licence it came under; own work may grant
-- either. The attribution and statement are the creator's words, erased with the workspace.
create table workspace_style_pack_publish_request (
  workspace_id    uuid not null,
  request_id      uuid not null default uuidv7(),
  manifest_sha256 text not null,
  licence_id      text not null check (licence_id in ('CC0-1.0', 'CC-BY-4.0')),
  attribution     text check (char_length(attribution) between 1 and 400),
  statement       text check (char_length(statement) between 1 and 2000),
  requested_by    uuid not null,
  requested_at    timestamptz not null default statement_timestamp(),
  erased_at       timestamptz,
  primary key (workspace_id, request_id),
  foreign key (workspace_id, manifest_sha256)
    references workspace_style_pack_version (workspace_id, manifest_sha256),
  constraint a_publish_licence_names_its_attribution
    check (erased_at is not null or (licence_id = 'CC-BY-4.0') = (attribution is not null)),
  constraint an_erased_request_holds_no_words
    check (erased_at is null or (attribution is null and statement is null))
);

-- --------------------------------------------------------------------------------------------
-- 2. The namespace inventory and the installation's byte total.
-- --------------------------------------------------------------------------------------------

create table workspace_style_pack_blob (
  workspace_id   uuid not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint not null check (byte_size between 1 and 67108864),
  recorded_at    timestamptz not null default statement_timestamp(),
  -- Set by the purger, after the bytes are gone, and only when a tombstone asked for them.
  purged_at      timestamptz,
  primary key (workspace_id, content_sha256)
);

-- One row: every workspace's unpurged style pack bytes together. Written only by the inventory's
-- and the versions' trigger, a workspace tombstone's trigger and the byte check, definers run as
-- exulanica_definer (0161), and read by the admission's byte check under its row lock, so two
-- uploads in different workspaces cannot both take the last of the ceiling. The trigger and the
-- byte check make the row when it is missing.
create table installation_style_pack_total (
  singleton      boolean primary key default true check (singleton),
  retained_bytes bigint not null default 0 check (retained_bytes >= 0)
);
insert into installation_style_pack_total (singleton, retained_bytes) values (true, 0);

-- --------------------------------------------------------------------------------------------
-- 3. Attempts, per workspace and per installation, each one UTC day.
-- --------------------------------------------------------------------------------------------

create table workspace_style_pack_attempt_day (
  workspace_id uuid not null,
  attempt_day  date not null,
  attempts     integer not null check (attempts > 0),
  primary key (workspace_id, attempt_day)
);

create table installation_style_pack_day (
  attempt_day date primary key,
  attempts    integer not null check (attempts > 0)
);

-- --------------------------------------------------------------------------------------------
-- 4. What blocks a version, and what a world may wear.
-- --------------------------------------------------------------------------------------------

-- A version is unreadable once its workspace is erased or its creator withdrew it. A missing
-- version fails closed, which also covers a session that declared no workspace. VOLATILE, for the
-- fresh snapshot 0024 explains.
create function tombstone_blocks_workspace_style_pack(p_workspace uuid, p_manifest text)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from workspace_style_pack_version v
                 where v.workspace_id = p_workspace and v.manifest_sha256 = p_manifest)
    or exists (select 1 from tombstone t
                where t.workspace_id = p_workspace
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp())
    or exists (select 1 from workspace_style_pack_withdrawal w
                where w.workspace_id = p_workspace and w.manifest_sha256 = p_manifest);
$fn$;

comment on function tombstone_blocks_workspace_style_pack(uuid, text) is
  'Is this style pack version unreadable: its workspace erased or the version withdrawn. Fails '
  'closed.';

-- The version and every workspace version in its base chain, nearest first. A chain is at most
-- eight versions deep: the admission refuses a deeper one, and this stops there whatever it finds.
create function workspace_style_pack_chain(p_workspace uuid, p_manifest text)
returns table (manifest_sha256 text, depth integer)
language sql stable as $fn$
  with recursive chain(manifest_sha256, depth) as (
    select p_manifest, 0
    union all
    select v.base_manifest_sha256, c.depth + 1
      from chain c
      join workspace_style_pack_version v
        on v.workspace_id = p_workspace and v.manifest_sha256 = c.manifest_sha256
     where v.base_source = 'workspace' and c.depth < 8
  )
  select manifest_sha256, depth from chain;
$fn$;

-- May a world wear this version now, and may its files be served: this session's workspace, the
-- version and every workspace version in its base chain ready, none withdrawn, the workspace not
-- erased, and every file each lists still held. The world write and the delivery's final check ask
-- it under the asset read lock (0041).
create function workspace_style_pack_wearable(p_workspace uuid, p_manifest text)
returns boolean
language sql volatile as $fn$
  select p_workspace = current_workspace()
    and not exists (
      select 1 from workspace_style_pack_chain(p_workspace, p_manifest) c
       where c.depth = 8
          or tombstone_blocks_workspace_style_pack(p_workspace, c.manifest_sha256)
          or not exists (select 1 from workspace_style_pack_preparation p
                          where p.workspace_id = p_workspace
                            and p.manifest_sha256 = c.manifest_sha256
                            and p.state = 'ready')
          or exists (select 1 from workspace_style_pack_file f
                      where f.workspace_id = p_workspace
                        and f.manifest_sha256 = c.manifest_sha256
                        and not exists (select 1 from workspace_style_pack_blob b
                                         where b.workspace_id = f.workspace_id
                                           and b.content_sha256 = f.content_sha256
                                           and b.purged_at is null)));
$fn$;

comment on function workspace_style_pack_wearable(uuid, text) is
  'May a world wear this workspace style pack version, and may its files be served, now. Ask it '
  'under the asset read lock.';

-- The per-workspace bounds, stated once: the guards below enforce them and the API reports them.
-- Declared bounds, not measured capacity.
create function workspace_style_pack_limits(
  out live_versions integer, out pack_bytes bigint, out pending_at_once integer
)
language sql immutable as $fn$
  select 16, 268435456::bigint, 4;
$fn$;

-- --------------------------------------------------------------------------------------------
-- 5. Guards.
-- --------------------------------------------------------------------------------------------

create function tg_workspace_style_pack_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

-- Whether this workspace has been erased: the condition every write here refuses.
create function workspace_style_pack_workspace_erased(p_workspace uuid) returns boolean
language sql volatile as $fn$
  select exists (select 1 from tombstone t
                  where t.workspace_id = p_workspace
                    and t.scope = 'workspace'
                    and t.effective_at <= clock_timestamp());
$fn$;

-- A version: immutable but for its erasure, refused once the workspace is erased, bounded per
-- workspace, and drawn on a base this workspace may wear when it is one of its own.
create function tg_workspace_style_pack_version_guard() returns trigger
language plpgsql as $fn$
declare
  live integer;
  live_bytes bigint;
  bound record;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    -- The one update a version receives: its workspace's erasure clearing everything the creator
    -- chose or wrote (both documents, the attribution, the pack ids) and the receipt.
    if (to_jsonb(new) - 'manifest_canonical' - 'declaration_canonical' - 'erased_at'
          - 'pack_id' - 'base_pack_id' - 'receipt_document' - 'licence_attribution')
         is distinct from
       (to_jsonb(old) - 'manifest_canonical' - 'declaration_canonical' - 'erased_at'
          - 'pack_id' - 'base_pack_id' - 'receipt_document' - 'licence_attribution')
       or old.erased_at is not null or new.erased_at is null
       or not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a style pack version is never rewritten; it is erased with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  if workspace_style_pack_workspace_erased(new.workspace_id) then
    perform tombstone_refuse('workspace_style_pack_version');
  end if;
  if new.erased_at is not null then
    raise exception 'a style pack version arrives with its documents'
      using errcode = 'check_violation';
  end if;
  new.documents_byte_size := new.manifest_byte_size + octet_length(new.declaration_canonical)
                             + octet_length(new.receipt_document::text);
  select * into bound from workspace_style_pack_limits();
  select count(*), coalesce(sum(v.file_byte_size + v.documents_byte_size), 0)
    into live, live_bytes
    from workspace_style_pack_version v
   where v.workspace_id = new.workspace_id
     and not exists (select 1 from workspace_style_pack_withdrawal w
                      where w.workspace_id = v.workspace_id
                        and w.manifest_sha256 = v.manifest_sha256)
     and not exists (select 1 from workspace_style_pack_preparation p
                      where p.workspace_id = v.workspace_id
                        and p.manifest_sha256 = v.manifest_sha256
                        and p.state in ('failed', 'cancelled')
                        and p.failure_class is distinct from 'interrupted');
  if live >= bound.live_versions then
    raise exception 'this workspace holds % style pack versions, its limit', live
      using errcode = 'program_limit_exceeded';
  end if;
  if live_bytes + new.file_byte_size + new.documents_byte_size > bound.pack_bytes then
    raise exception 'this workspace''s style packs would exceed % bytes', bound.pack_bytes
      using errcode = 'program_limit_exceeded';
  end if;
  if new.base_source = 'workspace' and workspace_style_pack_wearable(
       new.workspace_id, new.base_manifest_sha256) is not true then
    raise exception 'a style pack is drawn only on a workspace pack that may be worn now'
      using errcode = 'check_violation';
  end if;
  if new.base_source = 'workspace' and not exists (
       select 1 from workspace_style_pack_version b
        where b.workspace_id = new.workspace_id
          and b.manifest_sha256 = new.base_manifest_sha256
          and b.pack_id = new.base_pack_id
          and b.version = new.base_version) then
    raise exception 'a workspace base is named by its own pack id, version and digest'
      using errcode = 'check_violation';
  end if;
  -- A chain is at most eight versions deep, this one included.
  if new.base_source = 'workspace' and exists (
       select 1 from workspace_style_pack_chain(new.workspace_id, new.base_manifest_sha256) c
        where c.depth >= 7) then
    raise exception 'a style pack is drawn on a chain at most eight versions deep'
      using errcode = 'check_violation';
  end if;
  new.created_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_workspace_style_pack_version_guard
  before insert or update on workspace_style_pack_version
  for each row execute function tg_workspace_style_pack_version_guard();
create trigger tg_workspace_style_pack_version_no_delete
  before delete on workspace_style_pack_version
  for each row execute function tg_workspace_style_pack_append_only();

-- A file row: written with its version, and changed only by its workspace's erasure clearing its
-- path.
create function tg_workspace_style_pack_file_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    if (to_jsonb(new) - 'path') is distinct from (to_jsonb(old) - 'path')
       or old.path is null or new.path is not null
       or not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a style pack file is never rewritten; its path is erased with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  if workspace_style_pack_workspace_erased(new.workspace_id) then
    perform tombstone_refuse('workspace_style_pack_file');
  end if;
  if new.path is null then
    raise exception 'a style pack file arrives with its path' using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_workspace_style_pack_file_guard
  before insert or update on workspace_style_pack_file
  for each row execute function tg_workspace_style_pack_file_guard();
create trigger tg_workspace_style_pack_file_no_delete
  before delete on workspace_style_pack_file
  for each row execute function tg_workspace_style_pack_append_only();

-- The preparation: its states, its fixed identity, and its version's state. Becoming ready asks
-- the base chain again, under the lifecycle lock, so a base withdrawn while the check ran makes it
-- fail rather than serve a withdrawn base's files.
create function tg_workspace_style_pack_preparation_guard() returns trigger
language plpgsql as $fn$
declare
  waiting integer;
  bound record;
  base text;
begin
  perform assert_workspace_context(new.workspace_id);

  if tg_op = 'INSERT' then
    if new.state <> 'requested' or new.attempts <> 0 or new.report_document is not null then
      raise exception 'a style pack preparation arrives requested, unattempted and empty'
        using errcode = 'check_violation';
    end if;
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_style_pack(new.workspace_id, new.manifest_sha256) then
      perform tombstone_refuse('workspace_style_pack_preparation');
    end if;
    select * into bound from workspace_style_pack_limits();
    select count(*) into waiting from workspace_style_pack_preparation p
     where p.workspace_id = new.workspace_id and p.state in ('requested', 'running');
    if waiting >= bound.pending_at_once then
      raise exception 'this workspace already has % style pack checks waiting, its limit', waiting
        using errcode = 'program_limit_exceeded';
    end if;
    new.requested_at := statement_timestamp();
    return new;
  end if;

  if (new.workspace_id, new.manifest_sha256) is distinct from (old.workspace_id, old.manifest_sha256)
  then
    raise exception 'a style pack preparation''s version is fixed'
      using errcode = 'check_violation';
  end if;
  -- An erasure clears what the check said and found, and changes nothing else.
  if (old.failure_message is not null or old.report_document is not null)
     and new.failure_message is null and new.report_document is null
     and (to_jsonb(new) - 'failure_message' - 'report_document')
         = (to_jsonb(old) - 'failure_message' - 'report_document') then
    if not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a check''s message is erased only with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if old.state = 'ready' then
    raise exception 'a ready style pack stays ready; withdrawing it is a withdrawal'
      using errcode = 'check_violation';
  end if;
  if new.state is distinct from old.state then
    if not (
         (old.state = 'requested' and new.state in ('running', 'cancelled'))
      or (old.state = 'running' and new.state in ('running', 'ready', 'failed', 'cancelled'))
      or (old.state = 'failed' and old.failure_class = 'interrupted'
          and new.state in ('requested', 'cancelled'))) then
      raise exception 'a style pack preparation does not move from % to %', old.state, new.state
        using errcode = 'check_violation';
    end if;
  end if;
  -- A finished check's ending is what it found: no write turns a refusal into an interruption.
  if new.state = old.state and old.state in ('failed', 'cancelled')
     and (new.failure_class, new.failure_message, new.report_document, new.finished_at)
         is distinct from
         (old.failure_class, old.failure_message, old.report_document, old.finished_at) then
    raise exception 'a finished style pack check keeps how it ended'
      using errcode = 'check_violation';
  end if;
  -- A check asked again waits within the same bound as a new one.
  if new.state = 'requested' and old.state <> 'requested' then
    select * into bound from workspace_style_pack_limits();
    select count(*) into waiting from workspace_style_pack_preparation p
     where p.workspace_id = new.workspace_id and p.state in ('requested', 'running')
       and p.manifest_sha256 <> new.manifest_sha256;
    if waiting >= bound.pending_at_once then
      raise exception 'this workspace already has % style pack checks waiting, its limit', waiting
        using errcode = 'program_limit_exceeded';
    end if;
  end if;
  if new.state in ('requested', 'running', 'ready')
     and (new.state is distinct from old.state or new.claim_token is distinct from old.claim_token)
  then
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_style_pack(new.workspace_id, new.manifest_sha256) then
      perform tombstone_refuse('workspace_style_pack_preparation');
    end if;
  end if;
  if new.state = 'ready' and old.state <> 'ready' then
    select v.base_manifest_sha256 into base from workspace_style_pack_version v
     where v.workspace_id = new.workspace_id and v.manifest_sha256 = new.manifest_sha256
       and v.base_source = 'workspace';
    if base is not null and workspace_style_pack_wearable(new.workspace_id, base) is not true then
      raise exception 'a style pack becomes ready only while its base may be worn'
        using errcode = 'check_violation';
    end if;
    if exists (select 1 from workspace_style_pack_file f
                where f.workspace_id = new.workspace_id
                  and f.manifest_sha256 = new.manifest_sha256
                  and not exists (select 1 from workspace_style_pack_blob b
                                   where b.workspace_id = f.workspace_id
                                     and b.content_sha256 = f.content_sha256
                                     and b.purged_at is null)) then
      raise exception 'a style pack becomes ready only with every file recorded in the inventory'
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_workspace_style_pack_preparation_guard
  before insert or update on workspace_style_pack_preparation
  for each row execute function tg_workspace_style_pack_preparation_guard();
create trigger tg_workspace_style_pack_preparation_no_delete
  before delete on workspace_style_pack_preparation
  for each row execute function tg_workspace_style_pack_append_only();

-- A withdrawal names a version of this workspace, is serialised with the preparation that might
-- finish beside it, and is refused while a live version of the workspace is drawn on it.
create function tg_workspace_style_pack_withdrawal_guard() returns trigger
language plpgsql as $fn$
declare
  dependents text;
begin
  perform assert_workspace_context(new.workspace_id);
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  -- A restore writes a carried withdrawal again before any tombstone (the restore withdrawal
  -- catalog), in withdrawn_at order, through carry_style_pack_withdrawal: a dependent withdrawn
  -- before its base is replayed first, and an unfinished dependent the restored database still
  -- holds is cancelled as base_unavailable before this row is written, so this guard holds.
  select string_agg(v.pack_id || ' version ' || v.version, ', ' order by v.pack_id, v.version)
    into dependents
    from workspace_style_pack_version v
    join workspace_style_pack_preparation p
      on p.workspace_id = v.workspace_id and p.manifest_sha256 = v.manifest_sha256
   where v.workspace_id = new.workspace_id
     and v.base_source = 'workspace'
     and v.base_manifest_sha256 = new.manifest_sha256
     and (p.state in ('requested', 'running', 'ready')
          or (p.state = 'failed' and p.failure_class = 'interrupted'))
     and not exists (select 1 from workspace_style_pack_withdrawal w
                      where w.workspace_id = v.workspace_id
                        and w.manifest_sha256 = v.manifest_sha256);
  if dependents is not null then
    raise exception 'style_pack_is_a_base: drawn on by %', dependents
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_workspace_style_pack_withdrawal_guard
  before insert on workspace_style_pack_withdrawal
  for each row execute function tg_workspace_style_pack_withdrawal_guard();

create function tg_workspace_style_pack_withdrawal_cancels() returns trigger
language plpgsql as $fn$
begin
  update workspace_style_pack_preparation p
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'withdrawn', failure_message = null, finished_at = statement_timestamp()
   where p.workspace_id = new.workspace_id
     and p.manifest_sha256 = new.manifest_sha256
     and (p.state in ('requested', 'running')
          or (p.state = 'failed' and p.failure_class = 'interrupted'));
  return null;
end $fn$;

create trigger tg_workspace_style_pack_withdrawal_cancels
  after insert on workspace_style_pack_withdrawal
  for each row execute function tg_workspace_style_pack_withdrawal_cancels();

create trigger tg_workspace_style_pack_withdrawal_append_only
  before update or delete on workspace_style_pack_withdrawal
  for each row execute function tg_workspace_style_pack_append_only();

-- A publish request is the version's creator's, of a ready and unwithdrawn version, passing on no
-- licence a licensed version did not come under; it changes only by its workspace's erasure.
create function tg_workspace_style_pack_publish_request_guard() returns trigger
language plpgsql as $fn$
declare
  version record;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    if (to_jsonb(new) - 'attribution' - 'statement' - 'erased_at')
         is distinct from (to_jsonb(old) - 'attribution' - 'statement' - 'erased_at')
       or old.erased_at is not null or new.erased_at is null
       or not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a publish request is never rewritten; it is erased with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  if new.erased_at is not null then
    raise exception 'a publish request arrives with its words' using errcode = 'check_violation';
  end if;
  select v.created_by, v.rights_basis, v.licence_id, v.licence_attribution into version
    from workspace_style_pack_version v
   where v.workspace_id = new.workspace_id and v.manifest_sha256 = new.manifest_sha256;
  if version.created_by is distinct from new.requested_by then
    raise exception 'only the creator of a style pack version asks for it to be published'
      using errcode = 'insufficient_privilege';
  end if;
  if workspace_style_pack_wearable(new.workspace_id, new.manifest_sha256) is not true then
    raise exception 'a style pack version is published only while it may be worn'
      using errcode = 'check_violation';
  end if;
  if version.rights_basis = 'licensed'
     and (version.licence_id <> new.licence_id
          or version.licence_attribution is distinct from new.attribution) then
    raise exception 'publish_licence_not_held: a licensed pack passes on only its own licence and '
                    'attribution'
      using errcode = 'check_violation';
  end if;
  new.requested_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_workspace_style_pack_publish_request_guard
  before insert or update on workspace_style_pack_publish_request
  for each row execute function tg_workspace_style_pack_publish_request_guard();
create trigger tg_workspace_style_pack_publish_request_no_delete
  before delete on workspace_style_pack_publish_request
  for each row execute function tg_workspace_style_pack_append_only();

-- --------------------------------------------------------------------------------------------
-- 6. The inventory, the installation's total, and the attempt counters.
-- --------------------------------------------------------------------------------------------

-- Whether a tombstone may destroy these bytes from its workspace's style pack namespace: only a
-- workspace tombstone reaches it, and it may destroy anything in it (0126's rule).
create function workspace_style_pack_purge_is_authorized(
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

comment on function workspace_style_pack_purge_is_authorized(uuid, uuid, text) is
  'May this tombstone destroy these bytes from its workspace''s style pack namespace: it is '
  'effective, in this session''s workspace, and a workspace tombstone. For the purge role.';

-- A namespace object is recorded under the lifecycle lock and never after the workspace is erased;
-- only the purger marks it purged, and only when a tombstone asked for it (0126's guard).
create function tg_workspace_style_pack_blob_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.purged_at is not null then
      raise exception 'a namespace object arrives unpurged'
        using errcode = 'check_violation';
    end if;
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if workspace_style_pack_workspace_erased(new.workspace_id) then
      perform tombstone_refuse('workspace_style_pack_blob');
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
          and pj.target_kind = 'workspace_style_pack'
          and pj.target_ref = new.content_sha256
          and workspace_style_pack_purge_is_authorized(new.workspace_id, pj.tombstone_id,
                                                       new.content_sha256)) then
    raise exception 'a namespace object is marked purged only when a tombstone asked for it'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create trigger tg_workspace_style_pack_blob_guard
  before insert or update on workspace_style_pack_blob
  for each row execute function tg_workspace_style_pack_blob_guard();
create trigger tg_workspace_style_pack_blob_no_delete
  before delete on workspace_style_pack_blob
  for each row execute function tg_workspace_style_pack_append_only();

-- The installation's total follows the inventory and the versions: an object recorded adds its
-- bytes and an object purged takes them away; a version adds its documents' bytes, which its
-- workspace's erasure takes away. A definer run as exulanica_definer, since no session role may
-- write the total.
create function tg_installation_style_pack_total() returns trigger
language plpgsql security definer as $fn$
begin
  if tg_table_name = 'workspace_style_pack_version' then
    insert into installation_style_pack_total as t (singleton, retained_bytes)
    values (true, new.documents_byte_size)
    on conflict (singleton) do update
      set retained_bytes = t.retained_bytes + new.documents_byte_size;
  elsif tg_op = 'INSERT' then
    insert into installation_style_pack_total as t (singleton, retained_bytes)
    values (true, new.byte_size)
    on conflict (singleton) do update set retained_bytes = t.retained_bytes + new.byte_size;
  elsif old.purged_at is null and new.purged_at is not null then
    update installation_style_pack_total
       set retained_bytes = greatest(retained_bytes - new.byte_size, 0);
  end if;
  return null;
end $fn$;

create trigger tg_installation_style_pack_total
  after insert or update on workspace_style_pack_blob
  for each row execute function tg_installation_style_pack_total();
-- A version's documents count in the total from its insert until its workspace is erased.
create trigger tg_installation_style_pack_documents
  after insert on workspace_style_pack_version
  for each row execute function tg_installation_style_pack_total();

-- Whether this installation may take p_bytes more of style pack bytes under p_ceiling, asked inside
-- the admission's own transaction: the total's row lock is held until it commits, so the next
-- admission anywhere sees these bytes. Answers a verdict and nothing about any workspace.
create function style_pack_installation_bytes_admit(p_bytes bigint, p_ceiling bigint)
returns boolean
language plpgsql volatile security definer as $fn$
declare
  held bigint;
begin
  insert into installation_style_pack_total (singleton, retained_bytes) values (true, 0)
  on conflict (singleton) do nothing;
  select retained_bytes into held from installation_style_pack_total where singleton for update;
  return held + greatest(p_bytes, 0) <= p_ceiling;
end $fn$;

-- One upload attempt counted for this session's workspace and for the installation, each within
-- its day's bound: 'counted', or the bound it met ('workspace_quota', 'installation_quota'), in
-- which case nothing of that bound was counted. The attempt is counted for its workspace before
-- the installation is asked, so an attempt the installation refuses still counts for its
-- workspace, unless a limit is below one, when nothing is counted at all. The workspace comes from
-- the session, never from the caller.
create function style_pack_attempt(p_workspace_limit integer, p_installation_limit integer)
returns text
language plpgsql volatile security definer as $fn$
declare
  workspace uuid := current_workspace();
  today date := (statement_timestamp() at time zone 'UTC')::date;
  counted integer;
begin
  if workspace is null then
    raise exception 'an upload attempt is counted in a workspace session'
      using errcode = 'insufficient_privilege';
  end if;
  -- A limit below one admits nothing, not even a day's first attempt, which the counters' insert
  -- branch would count whatever the limit; nothing is counted then.
  if coalesce(p_workspace_limit, 0) < 1 then
    return 'workspace_quota';
  end if;
  if coalesce(p_installation_limit, 0) < 1 then
    return 'installation_quota';
  end if;
  insert into workspace_style_pack_attempt_day as d (workspace_id, attempt_day, attempts)
  values (workspace, today, 1)
  on conflict (workspace_id, attempt_day) do update set attempts = d.attempts + 1
    where d.attempts < p_workspace_limit
  returning attempts into counted;
  if counted is null then
    return 'workspace_quota';
  end if;
  counted := null;
  insert into installation_style_pack_day as d (attempt_day, attempts) values (today, 1)
  on conflict (attempt_day) do update set attempts = d.attempts + 1
    where d.attempts < p_installation_limit
  returning attempts into counted;
  if counted is null then
    return 'installation_quota';
  end if;
  return 'counted';
end $fn$;

-- The counters only rise, and are never deleted: a day's attempts are what happened.
create function tg_style_pack_attempts_rise() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception '% is never deleted', tg_table_name using errcode = 'check_violation';
  end if;
  if (to_jsonb(new) - 'attempts') is distinct from (to_jsonb(old) - 'attempts')
     or new.attempts < old.attempts then
    raise exception 'a day''s style pack attempts only rise' using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

do $$ declare t text; begin
  foreach t in array array['workspace_style_pack_attempt_day', 'installation_style_pack_day'] loop
    execute format('create trigger tg_style_pack_attempts_rise before update or delete on %I '
      'for each row execute function tg_style_pack_attempts_rise()', t);
  end loop;
end $$;



-- No session role writes the counters or the total directly: the definer functions above do.
-- Their rows hold no workspace's content, so reading them needs no policy.
do $$ declare t text; begin
  foreach t in array array['installation_style_pack_total', 'installation_style_pack_day'] loop
    execute format('revoke all privileges on table %I from public', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 7. Erasure: the queue, the documents, and completion.
-- --------------------------------------------------------------------------------------------

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake',
                         'workspace_asset', 'look', 'workspace_style_pack'));

-- A workspace tombstone cancels every check still to finish, erases every uploader text, and
-- enqueues every recorded namespace object. A definer run as exulanica_definer: the documents and
-- paths are insert-only for every session role, and this is the one update they receive.
create function tg_workspace_style_pack_purge_on_tombstone() returns trigger
language plpgsql security definer as $fn$
declare
  documents bigint;
begin
  if new.scope <> 'workspace' then
    return new;
  end if;
  update workspace_style_pack_preparation p
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'deleted', failure_message = null, finished_at = statement_timestamp()
   where p.workspace_id = new.workspace_id
     and (p.state in ('requested', 'running')
          or (p.state = 'failed' and p.failure_class = 'interrupted'));
  update workspace_style_pack_preparation p
     set failure_message = null, report_document = null
   where p.workspace_id = new.workspace_id
     and (p.failure_message is not null or p.report_document is not null);
  -- The documents leave the installation's total as they leave the database. Only a workspace
  -- holding a live version writes the total's row, which every admission locks until it commits.
  select sum(v.documents_byte_size) into documents from workspace_style_pack_version v
   where v.workspace_id = new.workspace_id and v.erased_at is null;
  if documents is not null then
    update installation_style_pack_total
       set retained_bytes = greatest(retained_bytes - documents, 0);
  end if;
  -- Everything the creator chose or wrote: both documents, the attribution, the pack ids (each
  -- replaced by an id derived from its own digest, so versions stay distinct), and the receipt.
  update workspace_style_pack_version v
     set manifest_canonical = null, declaration_canonical = null, licence_attribution = null,
         pack_id = 'erased.x' || left(v.manifest_sha256, 24),
         base_pack_id = case when v.base_source = 'workspace'
                             then 'erased.x' || left(v.base_manifest_sha256, 24)
                             else v.base_pack_id end,
         receipt_document = '{"erased": true}'::jsonb,
         erased_at = statement_timestamp()
   where v.workspace_id = new.workspace_id and v.erased_at is null;
  update workspace_style_pack_file f
     set path = null
   where f.workspace_id = new.workspace_id and f.path is not null;
  update workspace_style_pack_publish_request r
     set attribution = null, statement = null, erased_at = statement_timestamp()
   where r.workspace_id = new.workspace_id and r.erased_at is null;
  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select new.tombstone_id, new.workspace_id, 'workspace_style_pack', b.content_sha256
    from workspace_style_pack_blob b
   where b.workspace_id = new.workspace_id
     and b.purged_at is null
  -- No conflict target: naming one needs SELECT on the queue, which this owner does not hold; these
  -- rows name a tombstone, so of the queue's uniqueness only (tombstone_id, target_kind, target_ref)
  -- can meet them.
  on conflict do nothing;
  return new;
end $fn$;


create trigger tg_workspace_style_pack_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_workspace_style_pack_purge_on_tombstone();

-- Re-stated from the creature erasure's migration (0126's with its two looks clauses) with two
-- clauses added: a style pack namespace job whose object is not yet marked purged, and, for a
-- workspace tombstone, any style pack namespace object still holding bytes. Everything it asks is
-- asked unchanged.
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
            and w.purged_at is null))
      or (pj.target_kind='look' and exists (select 1 from look_object o
          where o.workspace_id=pj.workspace_id and o.content_sha256=pj.target_ref
            and o.purged_at is null))
      or (pj.target_kind='workspace_style_pack' and exists (
          select 1 from workspace_style_pack_blob s
           where s.workspace_id=pj.workspace_id and s.content_sha256=pj.target_ref
             and s.purged_at is null)))) then
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
                        and w.purged_at is null)
       and not exists (select 1 from look_object o where o.workspace_id=v_workspace
                        and o.purged_at is null)
       and not exists (select 1 from workspace_style_pack_blob s where s.workspace_id=v_workspace
                        and s.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 8. Row-level security, the delivery barrier, and the sealed checkpoint.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['workspace_style_pack_version', 'workspace_style_pack_file',
                           'workspace_style_pack_preparation', 'workspace_style_pack_withdrawal',
                           'workspace_style_pack_blob', 'workspace_style_pack_attempt_day',
                           'workspace_style_pack_publish_request'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

-- A write that changes whether a version or its files may be worn or served waits for, or fails
-- against, a delivery's or a world write's last question in progress (0041).
do $$ declare t text; begin
  foreach t in array array['workspace_style_pack_version', 'workspace_style_pack_file',
                           'workspace_style_pack_preparation', 'workspace_style_pack_withdrawal',
                           'workspace_style_pack_blob'] loop
    execute format('create trigger aaa_asset_read_mutation '
      'before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()', t);
  end loop;
end $$;

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on workspace_style_pack_withdrawal
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- --------------------------------------------------------------------------------------------
-- 9. The definers run as exulanica_definer (migration 0161): login-less, unprivileged, under
--    row-level security, holding exactly what these bodies and the triggers their writes fire use
--    (this migration's entry in exulanica/db/definer_role.py GRANTS_BY_MIGRATION says the same,
--    and its check refuses a difference). pg_catalog first and pg_temp last on each search path;
--    no PUBLIC execute.
-- --------------------------------------------------------------------------------------------

-- tg_workspace_style_pack_purge_on_tombstone erases and cancels these rows; the guards its writes
-- fire read the tombstone.
grant select, update on workspace_style_pack_version, workspace_style_pack_file,
  workspace_style_pack_preparation, workspace_style_pack_publish_request to exulanica_definer;
-- It reads the inventory to queue every object, and queues each as a purge job.
grant select on workspace_style_pack_blob to exulanica_definer;
grant insert on purge_job to exulanica_definer;
-- tg_installation_style_pack_total, style_pack_installation_bytes_admit and style_pack_attempt
-- keep and read the byte total and the two day counters, the total under its row lock.
grant select, insert, update on installation_style_pack_total, installation_style_pack_day,
  workspace_style_pack_attempt_day to exulanica_definer;

do $$ declare f text; begin
  foreach f in array array[
    'workspace_style_pack_purge_is_authorized(uuid,uuid,text)',
    'tg_installation_style_pack_total()',
    'style_pack_installation_bytes_admit(bigint,bigint)',
    'style_pack_attempt(integer,integer)',
    'tg_workspace_style_pack_purge_on_tombstone()'] loop
    execute format('alter routine %s set search_path = pg_catalog, %I, pg_temp',
                   f, current_schema());
    execute format('revoke all on function %s from public', f);
    execute format('alter routine %s owner to exulanica_definer', f);
  end loop;
end $$;

commit;
