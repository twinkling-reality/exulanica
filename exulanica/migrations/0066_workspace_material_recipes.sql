-- 0066_workspace_material_recipes.sql
-- A workspace holds its own material recipes and their bakes, and deletion reaches both.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- 0065 pinned the published library: eight sets, every one a maker applied to a recipe, and every
-- recipe an object with a digest. This is the personal half. A person varies a recipe (a darker
-- mortar, a longer brick), the Companion proposes one from a description, and later a recipe may
-- be derived from the person's own photographs. Each is a row here, and each can be baked into a
-- container that belongs to that workspace alone. `docs/texture-package.md` section 14 is the
-- design; what follows records the shape.
--
-- THE SHAPE CHOSEN.
--
--   material_recipe             one recipe, immutable: its canonical bytes, the same document as
--                               jsonb, and the digest over the bytes, as 0063 holds a verdict;
--                               the maker it names; where it came from; the person's own label,
--                               which is outside every digest
--   material_recipe_source      the capture ids a photo-derived recipe was derived from, one row
--                               each, so a deletion cascade reaches through them, exactly as
--                               `place_record_member` and `reconstruction_scene_member` are rows
--   material_recipe_withdrawal  a person removing a recipe they hold, append-only, once
--   material_bake               the one container baked from a recipe: a lease queue in the 0016
--                               shape, then the bytes' digest and the receipt that says how they
--                               were made
--
-- REMOVING A RECIPE IS AN AUTHORED CHANGE, NOT AN ERASURE. A tombstone erases personal data, and
-- `tombstone_scope` is an enum that 0024 and 0038 both declined to widen. A recipe a person
-- authored is not personal data about anyone, so removing it is a row in
-- `material_recipe_withdrawal`: the recipe and its bake become unreadable the moment it commits,
-- through `tombstone_blocks_material_recipe` and `tombstone_blocks_material_bake`, and the row is
-- kept as history. Its bake's bytes are NOT destroyed by it. They are a cache a recipe reproduces
-- exactly, reclaimed when the workspace is erased; a sweep that reclaims them sooner is a named
-- follow-up, and it must run through the one purge machinery when it is built. When the edit lane
-- lands, removing a recipe becomes one of its operations and can be undone; this table is the
-- record that operation will write, and nothing here builds undo.
--
-- ERASURE RUNS THROUGH THE ONE MACHINERY, and never beside it. 0044 put caption vectors into
-- `purge_job` and `tombstone_purge_is_complete` rather than next to them, because a second byte
-- path is one a deletion can miss. This does the same for bakes:
--
--   *  `purge_job.target_kind` gains `material_bake`. Its `target_ref` is the container's content
--      hash, as for an artifact.
--   *  A workspace tombstone enqueues every bake the workspace holds. A capture tombstone enqueues
--      the bakes of photo-derived recipes that name the capture, and a person withdrawal the
--      bakes of photo-derived recipes a confirmed identity decision ties to that person, through
--      `person_derivative_dependency`, as 0030 does for every other derivative. Both also cancel
--      any bake still pending.
--   *  `material_bake_purge_is_authorized` is the destroy question, a narrow capability in the
--      shape of `caption_vector_purge_is_authorized`. Bake bytes live in a store namespace of
--      their own, one per workspace (`exulanica.store.namespaces`), so the question never needs
--      another workspace's rows.
--   *  `tombstone_purge_is_complete` counts an unpurged bake as work left, and a workspace
--      tombstone is not complete while any bake in the workspace still has bytes.
--   *  `exulanica/deletion/restore.py` replays the jobs a checkpoint names and checks the bytes
--      are gone from the namespace.
--
-- THE WRITE AND THE ERASURE ARE SERIALISED, in two places. A bake is recorded before its bytes
-- are written, under a session lock on the object that the purger also takes
-- (`exulanica.world.material_bakes`), which is the ingest path's `committed_writes` order: a crash
-- leaves a row whose bytes are missing, never bytes no row names. And every tombstone insert takes
-- a per-workspace lock that the bake guard also takes, the 0044 lifecycle lock, so a tombstone
-- either sees a finished bake and enqueues it or commits first and the bake is refused.
--
-- PHOTO-DERIVED RECIPES ARE INERT. No personal photograph reaches a recipe until the personal
-- model right (migration 0073) exists. Two triggers, `tg_material_recipe_awaits_model_right`
-- and `tg_material_recipe_source_awaits_model_right`, refuse every such row and do nothing
-- else, and are named to fire before every other guard on their tables, so the refusal is always
-- theirs. The migration that follows 0073 replaces exactly those two and nothing more. Everything
-- a photo-derived recipe needs when it arrives is already here and already tested with those two
-- set aside: its sources, its person dependencies, its blocking and its erasure.
--
-- A BAKE IS A COMPUTE AMPLIFIER. `material_bake_quota` bounds how many bakes one workspace may
-- request in a day and how many may wait at once, and the request guard refuses past either.
--
-- WHAT THIS DELIBERATELY DOES NOT DO. It stores no float. Nothing that reaches a digest carries a
-- clock: `created_at`, `requested_at` and `baked_at` are facts about the write. It adds no
-- tombstone scope. It does not decide which surface a recipe dresses, which is the grammar's
-- material stage. It does not publish anything: a workspace bake is under its own licence id,
-- which the published manifest and every export refuse.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The recipe.
-- --------------------------------------------------------------------------------------------

create table material_recipe (
  workspace_id     uuid not null,
  recipe_id        uuid not null default uuidv7(),
  -- Who made it. `authored`: a person set the controls. `proposed`: the Companion suggested it
  -- from words. `photo_derived`: a model read the person's photographs, and until 0073 no row
  -- may say so.
  origin           text not null check (origin in ('authored', 'proposed', 'photo_derived')),
  maker_id         text not null check (maker_id ~ '^[a-z][a-z0-9.-]*$'),
  maker_version    integer not null check (maker_version >= 1),
  -- The published maker manifest the recipe was checked against, as
  -- `exulanica.world.texture_assets.PUBLISHED_MAKER_MANIFESTS` names it.
  maker_sha256     bytea not null check (octet_length(maker_sha256) = 32),
  recipe_canonical bytea not null,
  recipe_document  jsonb not null,
  recipe_sha256    bytea not null check (octet_length(recipe_sha256) = 32),
  -- The published set it was varied from, when it was.
  based_on_set_id  text,
  based_on_version integer,
  -- How many photographs a photo-derived recipe names. Zero for the other two.
  source_count     integer not null default 0 check (source_count >= 0),
  -- The person's own name for it. Outside every digest, and never in a container.
  label            text check (
    label is null
    or (char_length(label) between 1 and 200
        and label = btrim(label)
        and label !~ '[[:cntrl:]]')),
  created_by       uuid not null,
  created_at       timestamptz not null default statement_timestamp(),
  primary key (workspace_id, recipe_id),
  foreign key (based_on_set_id, based_on_version)
    references world_texture_set (set_id, version),
  constraint a_based_on_set_is_whole_or_absent
    check (num_nulls(based_on_set_id, based_on_version) in (0, 2)),
  constraint the_recipe_digest_is_over_its_bytes
    check (public.digest(recipe_canonical, 'sha256') = recipe_sha256),
  constraint the_recipe_document_is_its_bytes
    check (convert_from(recipe_canonical, 'UTF8')::jsonb = recipe_document),
  constraint the_recipe_columns_are_its_document check (
    recipe_document ->> 'profile' = 'exulanica.texture-recipe/v1'
    and recipe_document -> 'maker' ->> 'id' = maker_id
    and recipe_document -> 'maker' -> 'version' = to_jsonb(maker_version)),
  constraint only_a_photo_derived_recipe_names_photographs
    check ((origin = 'photo_derived') = (source_count >= 1))
);
create index material_recipe_digest_idx on material_recipe (workspace_id, recipe_sha256);

create table material_recipe_source (
  workspace_id uuid not null,
  recipe_id    uuid not null,
  capture_id   uuid not null,
  ordinal      integer not null check (ordinal >= 0),
  primary key (workspace_id, recipe_id, capture_id),
  unique (workspace_id, recipe_id, ordinal),
  foreign key (workspace_id, recipe_id) references material_recipe (workspace_id, recipe_id),
  foreign key (workspace_id, capture_id) references capture (workspace_id, capture_id)
);
-- "Which recipes name this capture", asked by the predicate and the cascade below.
create index material_recipe_source_capture_idx
  on material_recipe_source (workspace_id, capture_id, recipe_id);

create table material_recipe_withdrawal (
  workspace_id uuid not null,
  recipe_id    uuid not null,
  withdrawn_by uuid not null,
  withdrawn_at timestamptz not null default statement_timestamp(),
  -- Once. A withdrawn recipe stays withdrawn until the edit lane gives removal an undo.
  primary key (workspace_id, recipe_id),
  foreign key (workspace_id, recipe_id) references material_recipe (workspace_id, recipe_id)
);

-- --------------------------------------------------------------------------------------------
-- 2. The bake.
-- --------------------------------------------------------------------------------------------

create table material_bake (
  workspace_id      uuid not null,
  bake_id           uuid not null default uuidv7(),
  recipe_id         uuid not null,
  -- The set id the container states: `ws.` and the recipe id's 32 hex digits. Version 1 always,
  -- because a recipe is immutable and so is its container.
  set_id            text not null,
  state             text not null default 'requested'
    check (state in ('requested', 'running', 'baked', 'failed', 'cancelled')),
  attempts          integer not null default 0 check (attempts >= 0),
  -- The lease, whole while running and absent otherwise. The 0016 shape: a claimant is believed
  -- until `lease_expires_at`, and every write of its own names its token.
  claim_token       uuid,
  claimed_by        text,
  lease_expires_at  timestamptz,
  requested_by      uuid not null,
  requested_at      timestamptz not null default statement_timestamp(),
  -- The bake, whole or absent, and once present never changed: a later bake of the same recipe
  -- must reproduce these bytes exactly.
  content_sha256    bytea check (octet_length(content_sha256) = 32),
  byte_size         bigint check (byte_size > 0),
  receipt_canonical bytea,
  receipt_document  jsonb,
  receipt_sha256    bytea check (octet_length(receipt_sha256) = 32),
  baked_at          timestamptz,
  failure_class     text check (failure_class in
    ('invalid_recipe', 'bake_failed', 'timed_out', 'over_memory', 'unverified_output',
     'nondeterministic', 'withdrawn', 'exhausted')),
  failure_message   text check (char_length(failure_message) <= 2000),
  -- Set by the purger, after the bytes are gone, and only for a bake a tombstone asked for.
  purged_at         timestamptz,
  primary key (workspace_id, bake_id),
  unique (workspace_id, recipe_id),
  foreign key (workspace_id, recipe_id) references material_recipe (workspace_id, recipe_id),
  constraint the_set_id_names_the_recipe
    check (set_id = 'ws.' || replace(recipe_id::text, '-', '')),
  constraint a_lease_is_whole_while_running check (
    (state = 'running')
      = (claim_token is not null and claimed_by is not null and lease_expires_at is not null)
    and num_nulls(claim_token, claimed_by, lease_expires_at) in (0, 3)),
  constraint a_bake_is_whole_or_absent check (
    num_nulls(content_sha256, byte_size, receipt_canonical, receipt_document, receipt_sha256,
              baked_at) in (0, 6)),
  constraint a_baked_row_holds_its_bake
    check (state <> 'baked' or content_sha256 is not null),
  constraint a_failure_is_named_where_it_happened
    check ((failure_class is not null) = (state in ('failed', 'cancelled'))
           and (failure_message is null or failure_class is not null)),
  constraint only_bytes_are_purged
    check (purged_at is null or content_sha256 is not null),
  constraint the_receipt_digest_is_over_its_bytes
    check (receipt_canonical is null
           or public.digest(receipt_canonical, 'sha256') = receipt_sha256),
  constraint the_receipt_document_is_its_bytes
    check (receipt_canonical is null
           or convert_from(receipt_canonical, 'UTF8')::jsonb = receipt_document),
  constraint the_receipt_columns_are_its_document check (
    receipt_document is null or (
      receipt_document ->> 'profile' = 'exulanica.workspace-texture-bake-receipt/v1'
      and receipt_document ->> 'set_id' = set_id
      and receipt_document -> 'version' = '1'::jsonb
      and receipt_document ->> 'content_sha256' = encode(content_sha256, 'hex')
      and receipt_document -> 'byte_size' = to_jsonb(byte_size)))
);
-- One container per recipe, and within a workspace one bake per container: the set id is part of
-- the header, so two recipes never bake to the same bytes, and the purge question below relies on
-- a content hash naming one bake.
create unique index material_bake_content_idx
  on material_bake (workspace_id, content_sha256) where content_sha256 is not null;
create index material_bake_queue_idx
  on material_bake (state, lease_expires_at, requested_at)
  where state in ('requested', 'running');

-- --------------------------------------------------------------------------------------------
-- 3. The quota.
-- --------------------------------------------------------------------------------------------

-- One row per workspace, declared by an operator the way 0062 declares a tile ceiling. A
-- workspace without a row gets the defaults in `material_bake_quota_for`, so a new workspace is
-- bounded from its first request rather than unbounded until somebody remembers.
create table material_bake_quota (
  workspace_id     uuid primary key,
  requests_per_day integer not null check (requests_per_day between 0 and 100000),
  pending_at_once  integer not null check (pending_at_once between 0 and 1000),
  declared_by      uuid not null,
  declared_at      timestamptz not null default statement_timestamp()
);

create function tg_material_bake_quota_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' and new.workspace_id is distinct from old.workspace_id then
    raise exception 'a bake quota belongs to one workspace for good'
      using errcode = 'check_violation';
  end if;
  new.declared_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_material_bake_quota_guard
  before insert or update on material_bake_quota
  for each row execute function tg_material_bake_quota_guard();

-- Every request that reached the queue, append-only: a first request, a retry of a failed bake,
-- and a re-bake of one whose bytes went missing all cost the same.
create table material_bake_request (
  workspace_id uuid not null,
  request_id   uuid not null default uuidv7(),
  bake_id      uuid not null,
  requested_by uuid not null,
  requested_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, request_id),
  foreign key (workspace_id, bake_id) references material_bake (workspace_id, bake_id)
);
create index material_bake_request_day_idx
  on material_bake_request (workspace_id, requested_at);

create function material_bake_quota_for(p_workspace uuid, out requests_per_day integer,
                                        out pending_at_once integer)
language sql stable as $fn$
  select coalesce((select q.requests_per_day from material_bake_quota q
                    where q.workspace_id = p_workspace), 64),
         coalesce((select q.pending_at_once from material_bake_quota q
                    where q.workspace_id = p_workspace), 8);
$fn$;

-- --------------------------------------------------------------------------------------------
-- 4. What blocks a recipe, and so its bake.
-- --------------------------------------------------------------------------------------------

-- A recipe is unreadable once its workspace is erased or its holder withdrew it, and a
-- photo-derived recipe also once any of its photographs is deleted or withdrawn, or any person a
-- confirmed decision found in them withdraws: ANY and not ALL, as for a scene, because a recipe
-- read from four photographs is not a claim about the three that are left. A missing recipe, and
-- a photo-derived recipe with no sources, fail closed, which also covers a session that declared
-- no workspace and so sees no rows. VOLATILE, for the fresh snapshot 0024 explains.
create function tombstone_blocks_material_recipe(p_workspace uuid, p_recipe uuid)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from material_recipe r
                 where r.workspace_id = p_workspace and r.recipe_id = p_recipe)
    or exists (select 1 from tombstone t
                where t.workspace_id = p_workspace
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp())
    or exists (select 1 from material_recipe_withdrawal w
                where w.workspace_id = p_workspace and w.recipe_id = p_recipe)
    or exists (
      select 1 from material_recipe r
       where r.workspace_id = p_workspace
         and r.recipe_id = p_recipe
         and r.origin = 'photo_derived'
         and (not exists (select 1 from material_recipe_source s
                           where s.workspace_id = r.workspace_id and s.recipe_id = r.recipe_id)
              or exists (
                select 1 from material_recipe_source s
                  join capture c on c.workspace_id = s.workspace_id
                                and c.capture_id = s.capture_id
                 where s.workspace_id = r.workspace_id
                   and s.recipe_id = r.recipe_id
                   and (c.deleted_at is not null
                        or tombstone_blocks_capture(p_workspace, s.capture_id)
                        or person_withdrawal_blocks_capture(p_workspace, s.capture_id)))
              or exists (
                select 1 from person_derivative_dependency d
                 where d.workspace_id = r.workspace_id
                   and d.target_kind = 'material_recipe'
                   and d.target_id = r.recipe_id
                   and tombstone_blocks_entity(p_workspace, d.entity_id))));
$fn$;

comment on function tombstone_blocks_material_recipe(uuid, uuid) is
  'Is this recipe unreadable: its workspace erased, the recipe withdrawn, or, for a '
  'photo-derived recipe, any source photograph or any person in them withdrawn. Fails closed.';

create function tombstone_blocks_material_bake(p_workspace uuid, p_bake uuid)
returns boolean
language sql volatile as $fn$
  select coalesce(
    (select tombstone_blocks_material_recipe(b.workspace_id, b.recipe_id)
       from material_bake b
      where b.workspace_id = p_workspace and b.bake_id = p_bake),
    true);
$fn$;

comment on function tombstone_blocks_material_bake(uuid, uuid) is
  'A bake is unreadable exactly when its recipe is. Fails closed on a missing bake.';

-- The lock a tombstone and a bake both take, so neither can commit around the other. The 0044
-- lifecycle lock, in its own key space.
create function material_bake_lifecycle_lock(p_workspace uuid) returns void
language sql volatile as $fn$
  select pg_advisory_xact_lock(
    hashtextextended('material-bake-lifecycle:' || p_workspace::text, 0));
$fn$;

-- --------------------------------------------------------------------------------------------
-- 5. The recipe's guards.
-- --------------------------------------------------------------------------------------------

create function tg_material_recipe_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op <> 'INSERT' then
    raise exception 'a material recipe is immutable; a changed recipe is a new recipe'
      using errcode = 'integrity_constraint_violation';
  end if;
  perform material_bake_lifecycle_lock(new.workspace_id);
  if exists (select 1 from tombstone t
              where t.workspace_id = new.workspace_id
                and t.scope = 'workspace'
                and t.effective_at <= clock_timestamp()) then
    perform tombstone_refuse('material_recipe');
  end if;
  return new;
end $fn$;

create trigger tg_material_recipe_guard
  before insert or update on material_recipe
  for each row execute function tg_material_recipe_guard();

-- The first of the two triggers the migration after 0073 replaces. It refuses and does nothing
-- else, deliberately, so that replacing it changes nothing but this.
create function tg_material_recipe_awaits_model_right() returns trigger
language plpgsql as $fn$
begin
  if new.origin = 'photo_derived' then
    raise exception 'a photo-derived recipe needs the personal model right, which does not exist '
                    'yet; no personal photograph may reach a recipe before it does'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create trigger tg_material_recipe_awaits_model_right
  before insert on material_recipe
  for each row execute function tg_material_recipe_awaits_model_right();

-- At commit, a photo-derived recipe names exactly the photographs it declared. Deferred because
-- the sources reference the recipe and so arrive after it.
create function tg_material_recipe_complete() returns trigger
language plpgsql as $fn$
declare
  held integer;
begin
  perform assert_workspace_context(new.workspace_id);
  select count(*) into held from material_recipe_source s
   where s.workspace_id = new.workspace_id and s.recipe_id = new.recipe_id;
  if held <> new.source_count then
    raise exception 'material recipe % names % photographs and declares %',
      new.recipe_id, held, new.source_count
      using errcode = 'check_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_material_recipe_complete
  after insert on material_recipe
  deferrable initially deferred
  for each row execute function tg_material_recipe_complete();

-- The second of the two.
create function tg_material_recipe_source_awaits_model_right() returns trigger
language plpgsql as $fn$
begin
  raise exception 'a recipe source names a personal photograph, and the personal model right '
                  'that would allow it does not exist yet'
    using errcode = 'insufficient_privilege';
end $fn$;

create trigger tg_material_recipe_source_awaits_model_right
  before insert on material_recipe_source
  for each row execute function tg_material_recipe_source_awaits_model_right();

-- A source is a live photograph nobody has withdrawn, of a photo-derived recipe, within the
-- count it declared. The shape of `tg_place_record_member_live`.
create function tg_material_recipe_source_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from material_recipe r
                  where r.workspace_id = new.workspace_id
                    and r.recipe_id = new.recipe_id
                    and r.origin = 'photo_derived') then
    raise exception 'only a photo-derived recipe names photographs'
      using errcode = 'check_violation';
  end if;
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id
                    and c.deleted_at is null) then
    raise exception 'a recipe source names an absent or deleted photograph'
      using errcode = 'foreign_key_violation';
  end if;
  if tombstone_blocks_capture(new.workspace_id, new.capture_id)
     or person_withdrawal_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('material_recipe_source');
  end if;
  if (select count(*) from material_recipe_source s
       where s.workspace_id = new.workspace_id and s.recipe_id = new.recipe_id)
     >= (select r.source_count from material_recipe r
          where r.workspace_id = new.workspace_id and r.recipe_id = new.recipe_id) then
    raise exception 'material recipe % already names every photograph it declared', new.recipe_id
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_material_recipe_source_live
  before insert on material_recipe_source
  for each row execute function tg_material_recipe_source_live();

-- A withdrawal names a recipe in this workspace, is serialised with the bake that might finish
-- beside it, and cancels whatever bake of it is still waiting.
create function tg_material_recipe_withdrawal_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform material_bake_lifecycle_lock(new.workspace_id);
  return new;
end $fn$;

create trigger tg_material_recipe_withdrawal_guard
  before insert on material_recipe_withdrawal
  for each row execute function tg_material_recipe_withdrawal_guard();

create function tg_material_recipe_withdrawal_cancels() returns trigger
language plpgsql as $fn$
begin
  update material_bake b
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'withdrawn', failure_message = 'the recipe was withdrawn'
   where b.workspace_id = new.workspace_id
     and b.recipe_id = new.recipe_id
     and b.state in ('requested', 'running', 'failed');
  return null;
end $fn$;

create trigger tg_material_recipe_withdrawal_cancels
  after insert on material_recipe_withdrawal
  for each row execute function tg_material_recipe_withdrawal_cancels();

-- --------------------------------------------------------------------------------------------
-- 6. The bake's guard: its states, its immutable half, and who may mark it purged.
-- --------------------------------------------------------------------------------------------

-- Whether a tombstone may destroy these bytes from its workspace's namespace.
--
-- A workspace tombstone may destroy anything in the namespace, whether or not a row still names
-- it: the namespace is the workspace's alone, and all of it goes. A capture or person tombstone
-- may destroy a bake only when its scope reaches that bake's photo-derived recipe, so a forged job
-- cannot reach an authored bake. It may also destroy bytes no bake row names at all. The one way
-- such bytes exist is a restore: a database backed up before the bake was recorded, beside a
-- namespace that still holds it. There, the sealed checkpoint that named the job is the authority,
-- as it is for a blob; without this, the replay could never finish and the bytes would stay.
create function material_bake_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_content bytea
) returns boolean
language sql volatile security definer as $fn$
  select p_workspace = current_workspace() and p_content is not null and exists (
    select 1
      from tombstone t
     where t.workspace_id = p_workspace
       and t.tombstone_id = p_tombstone
       and t.effective_at <= now()
       and (t.scope = 'workspace'
            or (t.scope in ('capture', 'entity') and (
                  not exists (select 1 from material_bake b
                               where b.workspace_id = p_workspace
                                 and b.content_sha256 = p_content)
                  or exists (
                    select 1
                      from material_bake b
                      join material_recipe r on r.workspace_id = b.workspace_id
                                            and r.recipe_id = b.recipe_id
                     where b.workspace_id = p_workspace
                       and b.content_sha256 = p_content
                       and r.origin = 'photo_derived'
                       and ((t.scope = 'capture' and exists (
                               select 1 from material_recipe_source s
                                where s.workspace_id = r.workspace_id
                                  and s.recipe_id = r.recipe_id
                                  and s.capture_id = t.capture_id))
                            or (t.scope = 'entity' and exists (
                               select 1 from person_derivative_dependency d
                                where d.workspace_id = r.workspace_id
                                  and d.entity_id = t.entity_id
                                  and d.target_kind = 'material_recipe'
                                  and d.target_id = r.recipe_id))))))));
$fn$;

comment on function material_bake_purge_is_authorized(uuid, uuid, bytea) is
  'May this tombstone destroy these bytes from its workspace''s namespace: it is effective, in '
  'this session''s workspace, and it is a workspace tombstone, or its scope reaches the bake''s '
  'photo-derived recipe, or no bake row names the bytes (a restore). For the purge role.';

do $$ begin
  execute format('alter function material_bake_purge_is_authorized(uuid,uuid,bytea) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $$;
revoke all on function material_bake_purge_is_authorized(uuid, uuid, bytea) from public;

create function tg_material_bake_guard() returns trigger
language plpgsql as $fn$
declare
  own_recipe bytea;
  own_maker  bytea;
begin
  perform assert_workspace_context(new.workspace_id);

  if tg_op = 'INSERT' then
    if new.state <> 'requested' or new.attempts <> 0 or new.content_sha256 is not null
       or new.purged_at is not null then
      raise exception 'a bake arrives requested, unattempted and empty'
        using errcode = 'check_violation';
    end if;
    perform material_bake_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_material_recipe(new.workspace_id, new.recipe_id) then
      perform tombstone_refuse('material_bake');
    end if;
    return new;
  end if;

  if (new.workspace_id, new.bake_id, new.recipe_id, new.set_id, new.requested_by,
      new.requested_at)
     is distinct from (old.workspace_id, old.bake_id, old.recipe_id, old.set_id,
                       old.requested_by, old.requested_at) then
    raise exception 'a bake''s identity and request are fixed'
      using errcode = 'check_violation';
  end if;
  if old.content_sha256 is not null
     and (new.content_sha256, new.byte_size, new.receipt_canonical, new.receipt_sha256,
          new.baked_at)
         is distinct from (old.content_sha256, old.byte_size, old.receipt_canonical,
                           old.receipt_sha256, old.baked_at) then
    raise exception 'a bake''s bytes are fixed once recorded; a later bake must reproduce them'
      using errcode = 'check_violation';
  end if;
  if old.purged_at is not null then
    if new is distinct from old then
      raise exception 'a purged bake does not change again'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;

  -- Marking the bytes gone, and nothing else, is the purger's write, and it is allowed only for a
  -- bake a tombstone asked to have destroyed. Blocked is the expected state here.
  if new.purged_at is not null then
    if (to_jsonb(new) - 'purged_at') is distinct from (to_jsonb(old) - 'purged_at') then
      raise exception 'marking a bake purged changes nothing else'
        using errcode = 'check_violation';
    end if;
    if not exists (
         select 1 from purge_job pj
          where pj.workspace_id = new.workspace_id
            and pj.target_kind = 'material_bake'
            and pj.target_ref = encode(new.content_sha256, 'hex')
            and material_bake_purge_is_authorized(new.workspace_id, pj.tombstone_id,
                                                  new.content_sha256)) then
      raise exception 'a bake is marked purged only when a tombstone asked for its bytes'
        using errcode = 'insufficient_privilege';
    end if;
    return new;
  end if;

  if new.state is distinct from old.state then
    if not (
         (old.state = 'requested' and new.state in ('running', 'cancelled'))
      or (old.state = 'running' and new.state in ('running', 'baked', 'failed', 'cancelled'))
      or (old.state = 'failed' and new.state in ('requested', 'cancelled'))
      or (old.state = 'baked' and new.state = 'requested')) then
      raise exception 'a bake does not move from % to %', old.state, new.state
        using errcode = 'check_violation';
    end if;
  end if;

  if new.state in ('requested', 'running', 'baked')
     and (new.state is distinct from old.state
          or new.claim_token is distinct from old.claim_token
          or new.content_sha256 is distinct from old.content_sha256) then
    perform material_bake_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_material_recipe(new.workspace_id, new.recipe_id) then
      perform tombstone_refuse('material_bake');
    end if;
  end if;

  if new.state = 'baked' and old.state <> 'baked' then
    select r.recipe_sha256, r.maker_sha256 into own_recipe, own_maker
      from material_recipe r
     where r.workspace_id = new.workspace_id and r.recipe_id = new.recipe_id;
    if new.receipt_document ->> 'recipe_sha256' is distinct from encode(own_recipe, 'hex')
       or new.receipt_document ->> 'maker_sha256' is distinct from encode(own_maker, 'hex') then
      raise exception 'the receipt describes another recipe or maker than this bake''s'
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_material_bake_guard
  before insert or update on material_bake
  for each row execute function tg_material_bake_guard();

-- Every request that puts a bake in the queue is counted, and refused past the workspace's quota.
create function tg_material_bake_request_guard() returns trigger
language plpgsql as $fn$
declare
  quota record;
  spent integer;
  waiting integer;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended('material-bake-quota:' || new.workspace_id::text, 0));
  if not exists (select 1 from material_bake b
                  where b.workspace_id = new.workspace_id
                    and b.bake_id = new.bake_id
                    and b.state = 'requested') then
    raise exception 'a bake request names a bake that is not waiting'
      using errcode = 'check_violation';
  end if;
  select * into quota from material_bake_quota_for(new.workspace_id);
  select count(*) into spent from material_bake_request r
   where r.workspace_id = new.workspace_id
     and r.requested_at > statement_timestamp() - interval '1 day';
  if spent >= quota.requests_per_day then
    raise exception 'this workspace has requested % bakes in the last day, its limit', spent
      using errcode = 'program_limit_exceeded';
  end if;
  select count(*) into waiting from material_bake b
   where b.workspace_id = new.workspace_id and b.state in ('requested', 'running');
  if waiting > quota.pending_at_once then
    raise exception 'this workspace already has % bakes waiting, its limit', waiting - 1
      using errcode = 'program_limit_exceeded';
  end if;
  new.requested_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_material_bake_request_guard
  before insert on material_bake_request
  for each row execute function tg_material_bake_request_guard();

-- --------------------------------------------------------------------------------------------
-- 7. Append-only, in the shape of `tg_place_record_append_only`.
-- --------------------------------------------------------------------------------------------

create function tg_material_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create trigger tg_material_recipe_no_delete
  before delete on material_recipe
  for each row execute function tg_material_append_only();
create trigger tg_material_bake_no_delete
  before delete on material_bake
  for each row execute function tg_material_append_only();

do $$
declare
  t text;
begin
  foreach t in array array['material_recipe_source', 'material_recipe_withdrawal',
                           'material_bake_request'] loop
    execute format(
      'create trigger %I before update or delete on %I '
      'for each row execute function tg_material_append_only()',
      'tg_' || t || '_append_only', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 8. A person's decisions reach a photo-derived recipe, as they reach every other derivative.
-- --------------------------------------------------------------------------------------------

alter table person_derivative_dependency
  drop constraint person_derivative_dependency_target_kind_check;
alter table person_derivative_dependency
  add constraint person_derivative_dependency_target_kind_check check (target_kind in
    ('artifact', 'scene', 'scene_job', 'embedding', 'derived_artifact', 'assertion',
     'material_recipe'));

-- A source photograph carries the people already confirmed in it onto the recipe.
create function tg_record_person_dependencies_from_material_source() returns trigger
language plpgsql as $fn$
begin
  perform record_person_dependency(new.workspace_id, new.capture_id, 'material_recipe',
                                   new.recipe_id);
  return null;
end $fn$;

create trigger tg_record_person_dependencies_from_material_source
  after insert on material_recipe_source
  for each row execute function tg_record_person_dependencies_from_material_source();

-- And a person confirmed later reaches every recipe already read from that photograph.
create function tg_record_material_dependencies_from_link() returns trigger
language plpgsql as $fn$
begin
  if new.state <> 'confirmed' then
    return null;
  end if;
  insert into person_derivative_dependency (
    workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
  select new.workspace_id, new.entity_id, o.occurrence_id, o.capture_id, new.link_id,
         'material_recipe', s.recipe_id
    from occurrence o
    join material_recipe_source s on s.workspace_id = o.workspace_id
                                 and s.capture_id = o.capture_id
   where o.occurrence_id = new.occurrence_id
     and o.workspace_id = new.workspace_id
  on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  return null;
end $fn$;

create trigger tg_record_material_dependencies_from_link
  after insert or update of state on entity_link
  for each row execute function tg_record_material_dependencies_from_link();

-- --------------------------------------------------------------------------------------------
-- 9. Erasure: the queue, the lock, the destroy question's partner, and completion.
-- --------------------------------------------------------------------------------------------

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake'));

create function tg_material_bake_lifecycle_lock() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform material_bake_lifecycle_lock(new.workspace_id);
  return new;
end $fn$;

create trigger tg_material_bake_lifecycle_lock
  before insert on tombstone
  for each row execute function tg_material_bake_lifecycle_lock();

-- Named to sort before `tg_person_withdrawal_cascade`, which fires after it on the same insert,
-- so a person withdrawal's receipt counts the bake jobs this enqueues.
create function tg_material_bake_purge_on_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope not in ('workspace', 'capture', 'entity') then
    return new;
  end if;

  update material_bake b
     set state = 'cancelled', claim_token = null, claimed_by = null, lease_expires_at = null,
         failure_class = 'withdrawn',
         failure_message = 'a deletion reached the recipe before the bake finished'
    from material_recipe r
   where r.workspace_id = b.workspace_id
     and r.recipe_id = b.recipe_id
     and b.workspace_id = new.workspace_id
     and b.state in ('requested', 'running', 'failed')
     and (new.scope = 'workspace'
          or (new.scope = 'capture' and r.origin = 'photo_derived' and exists (
                select 1 from material_recipe_source s
                 where s.workspace_id = r.workspace_id
                   and s.recipe_id = r.recipe_id
                   and s.capture_id = new.capture_id))
          or (new.scope = 'entity' and r.origin = 'photo_derived' and exists (
                select 1 from person_derivative_dependency d
                 where d.workspace_id = r.workspace_id
                   and d.entity_id = new.entity_id
                   and d.target_kind = 'material_recipe'
                   and d.target_id = r.recipe_id)));

  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select distinct new.tombstone_id, new.workspace_id, 'material_bake',
         encode(b.content_sha256, 'hex')
    from material_bake b
    join material_recipe r on r.workspace_id = b.workspace_id and r.recipe_id = b.recipe_id
   where b.workspace_id = new.workspace_id
     and b.content_sha256 is not null
     and b.purged_at is null
     and (new.scope = 'workspace'
          or (new.scope = 'capture' and r.origin = 'photo_derived' and exists (
                select 1 from material_recipe_source s
                 where s.workspace_id = r.workspace_id
                   and s.recipe_id = r.recipe_id
                   and s.capture_id = new.capture_id))
          or (new.scope = 'entity' and r.origin = 'photo_derived' and exists (
                select 1 from person_derivative_dependency d
                 where d.workspace_id = r.workspace_id
                   and d.entity_id = new.entity_id
                   and d.target_kind = 'material_recipe'
                   and d.target_id = r.recipe_id)))
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;

create trigger tg_material_bake_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_material_bake_purge_on_tombstone();

-- Re-stated from 0044 with two clauses added, one per kind of work left: a bake job whose bake is
-- not yet marked purged, and, for a workspace tombstone, any bake in the workspace that still has
-- bytes. Everything 0044 asks is asked unchanged.
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
            and m.purged_at is null)))) then
    return false;
  end if;
  if v_scope='workspace' then
    return not exists (select 1 from capture c join blob b on b.blob_sha256=c.blob_sha256
                        where c.workspace_id=v_workspace and b.purged_at is null)
       and not exists (select 1 from artifact a where a.workspace_id=v_workspace
                        and a.content_sha256 is not null and a.purged_at is null)
       and not exists (select 1 from embedding e where e.workspace_id=v_workspace)
       and not exists (select 1 from material_bake m where m.workspace_id=v_workspace
                        and m.content_sha256 is not null and m.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 10. Row-level security. ENABLE alone is bypassed by the table owner.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['material_recipe', 'material_recipe_source',
                           'material_recipe_withdrawal', 'material_bake',
                           'material_bake_request'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

-- The quota is read by the workspace it bounds and by nobody else.
alter table material_bake_quota enable row level security;
alter table material_bake_quota force row level security;
create policy ws_isolation on material_bake_quota
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- A write that changes whether a recipe or a bake may be read waits for, or fails against, a
-- delivery in progress, as 0041 arranged for every other readable table: a withdrawal cannot slip
-- between a bake's final check and its bytes leaving.
do $$ declare t text; begin
  foreach t in array array['material_recipe', 'material_recipe_source',
                           'material_recipe_withdrawal', 'material_bake'] loop
    execute format('create trigger aaa_asset_read_mutation '
      'before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()', t);
  end loop;
end $$;

commit;
