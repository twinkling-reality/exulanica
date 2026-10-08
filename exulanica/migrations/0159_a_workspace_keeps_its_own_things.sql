-- 0159_a_workspace_keeps_its_own_things.sql
-- A workspace keeps the things it made or admitted as the documents they were read as: a body
-- recipe drafted from a person's words, the body plan built from it, a thing kind, and a look
-- with its container, held by digest.
--
-- WHAT IS KEPT. Each row is a document a reader in exulanica/things passed before it was written
-- (read_body_recipe, read_body_plan, read_thing_kind, read_look), with the SHA-256 of its
-- canonical JSON. A database cannot run those readers, so the application reads each document at
-- its digest before it writes (exulanica/world/thing_store.py), and these tables hold the shape,
-- hold each version fixed and keep it inside its workspace. A version is appended once and never
-- changed or deleted, with the refusal 0029 gives every receipt; an edit is a new version. The
-- things the product ships are files under assets/ and are never rows here, and no row takes a
-- shipped key (the application refuses it, as a shipped key resolves first). A recipe keeps the
-- digest of the words it was drafted from, never the words. A kind of a drafted plan names the
-- plan's digest in its document, and its row holds the same digest.
--
-- A LOOK'S CONTAINER is held by digest in the workspace's own "looks" namespace of the
-- content-addressed store (exulanica/store/namespaces.py). Its row states the container's digest
-- and length as its document names them, its profile, which follows from the look's kind (a
-- skinned look is read as a skinned glTF, any other as a static one), and what the container's
-- reader measured. Its licence is read from the document's origin record by generated columns, one
-- source, and a share-alike licence is refused here, as export refuses it, without the credit it
-- asks: the attribution, the authors and the licence's address.
--
-- A LOOK IS WITHDRAWN by a row of its own naming the version and its digest, never by an update: a
-- choice that names a withdrawn look stays (choices are appended, 0156), and every read passes the
-- look by unless it asks for withdrawn looks. A withdrawal is carried by a restore
-- (exulanica/deletion/withdrawals.v2.json), so a restore from an older backup never serves again a
-- look its workspace withdrew, and a sealed restore checkpoint refuses new ones (0107).
--
-- Row-level security keeps every row inside its workspace. None of these tables names a world or
-- a version: they are a workspace's own library, which every world of the workspace may draw on.
-- The caps per workspace are the application's (exulanica/world/thing_store.py), checked under the
-- workspace's lock before each insert.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

create table body_recipe_version (
  workspace_id    uuid not null,
  sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  words_sha256    text check (words_sha256 ~ '^[0-9a-f]{64}$'),
  created_by      uuid not null,
  created_at      timestamptz not null default statement_timestamp(),
  primary key (workspace_id, sha256),
  constraint body_recipe_version_is_a_recipe check (
    (document->>'profile' = 'exulanica.body-recipe/v1') is true)
);

create table body_plan_version (
  workspace_id    uuid not null,
  key             text not null check (key ~ '^[a-z][a-z0-9_]{0,63}$'),
  version         integer not null check (version between 1 and 9999),
  sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  recipe_sha256   text not null,
  created_by      uuid not null,
  created_at      timestamptz not null default statement_timestamp(),
  primary key (workspace_id, key, version),
  constraint body_plan_version_is_one_document unique (workspace_id, sha256),
  foreign key (workspace_id, recipe_sha256)
    references body_recipe_version (workspace_id, sha256),
  constraint body_plan_version_names_itself check (
    (document->>'profile' = 'exulanica.body-plan/v1'
      and document->>'key' = key
      and document->>'version' = version::text) is true)
);

create table thing_kind_version (
  workspace_id    uuid not null,
  key             text not null check (key ~ '^[a-z][a-z0-9_]{0,47}$'),
  version         integer not null check (version between 1 and 9999),
  sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  -- The plan's name as the kind's document gives it. A drafted plan is this workspace's row, by
  -- the digest the document names beside it; a shipped plan has no row here and no digest.
  plan            text not null check (length(plan) between 3 and 128),
  plan_sha256     text,
  created_by      uuid not null,
  created_at      timestamptz not null default statement_timestamp(),
  primary key (workspace_id, key, version),
  constraint thing_kind_version_is_one_document unique (workspace_id, sha256),
  foreign key (workspace_id, plan_sha256) references body_plan_version (workspace_id, sha256),
  constraint thing_kind_version_names_itself check (
    (document->>'profile' = 'exulanica.thing-kind/v1'
      and document->>'kind' = key
      and document->>'version' = version::text
      and document->'body'->>'plan' = plan) is true),
  constraint thing_kind_version_names_its_plan check (
    plan_sha256 is not distinct from document->'body'->>'plan_sha256')
);

create table look_version (
  workspace_id       uuid not null,
  key                text not null check (key ~ '^[a-z][a-z0-9-]{0,47}$'),
  version            integer not null check (version between 1 and 9999),
  sha256             text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  document           jsonb not null check (jsonb_typeof(document) = 'object'),
  -- The drafted plan this look is drawn on, by digest; a look on a shipped plan has none.
  plan_sha256        text,
  container_sha256   text generated always as (document->'container'->>'sha256') stored,
  container_bytes    bigint generated always as ((document->'container'->>'bytes')::bigint) stored,
  container_profile  text not null
    check (container_profile in ('exulanica.static-glb/v1', 'exulanica.skinned-glb/v1')),
  admission          jsonb not null check (jsonb_typeof(admission) = 'object'),
  spdx               text generated always as (document->'origin'->'licence'->>'spdx') stored,
  share_alike        boolean generated always as (
    (document->'origin'->'licence'->>'share_alike')::boolean) stored,
  attribution        text generated always as (
    document->'origin'->'licence'->>'attribution') stored,
  licence_url        text generated always as (
    document->'origin'->'licence'->>'licence_url') stored,
  distribution       text generated always as (document->'origin'->>'distribution') stored,
  origin_class       text generated always as (document->'origin'->>'class') stored,
  created_by         uuid not null,
  created_at         timestamptz not null default statement_timestamp(),
  primary key (workspace_id, key, version),
  constraint look_version_is_one_document unique (workspace_id, sha256),
  -- What a withdrawal names: the version and the digest it was kept at.
  constraint look_version_is_one_version unique (workspace_id, key, version, sha256),
  foreign key (workspace_id, plan_sha256) references body_plan_version (workspace_id, sha256),
  constraint look_version_names_itself check (
    (document->>'profile' = 'exulanica.look/v1'
      and document->>'look' = key
      and document->>'version' = version::text
      and container_sha256 ~ '^[0-9a-f]{64}$'
      and container_bytes between 1 and 33554432) is true),
  constraint look_version_reads_its_container_by_its_kind check (
    ((document->>'look_kind' = 'skinned') = (container_profile = 'exulanica.skinned-glb/v1'))
      is true),
  constraint look_version_credits_what_it_shares check (
    (not share_alike
      or (attribution is not null
        and licence_url is not null
        and document->'origin'->'authors'->0 is not null)) is true),
  constraint look_version_states_its_licence check (
    (spdx is not null
      and share_alike is not null
      and distribution in ('public', 'private', 'restricted')
      and origin_class in ('authored', 'drafted', 'generated', 'uploaded', 'imported', 'crossed'))
      is true)
);

create table look_withdrawal (
  workspace_id    uuid not null,
  key             text not null,
  version         integer not null,
  sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  reason          text not null check (length(reason) between 1 and 400),
  withdrawn_by    uuid not null,
  withdrawn_at    timestamptz not null default statement_timestamp(),
  -- Once, and final.
  primary key (workspace_id, key, version),
  foreign key (workspace_id, key, version, sha256)
    references look_version (workspace_id, key, version, sha256)
);

comment on table body_recipe_version is
  'A workspace''s own body recipes, each as drafted and read, with the digest of the words it was '
  'drafted from. Appended once; never updated or deleted by the runtime.';
comment on table body_plan_version is
  'A workspace''s own body plans, each built from a recipe and read. Appended once; never updated '
  'or deleted by the runtime.';
comment on table thing_kind_version is
  'A workspace''s own thing kinds, each version as read; at most 128 versions a workspace. '
  'Appended once; never updated or deleted by the runtime.';
comment on table look_version is
  'A workspace''s own looks, each version as read with its container held by digest in the '
  'workspace''s looks namespace; at most 256 versions a workspace. Appended once; never updated '
  'or deleted by the runtime.';
comment on table look_withdrawal is
  'A workspace''s withdrawal of one of its own looks, carried by a restore. Appended once; never '
  'updated or deleted by the runtime.';

-- A row is written only in its own workspace's context.
create function tg_thing_store_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;

do $$ declare t text; begin
  foreach t in array array[
    'body_recipe_version', 'body_plan_version', 'thing_kind_version', 'look_version',
    'look_withdrawal'
  ] loop
    execute format('create trigger tg_%s_append_only before update or delete on %I '
      'for each row execute function tg_reconstruction_privacy_append_only()', t, t);
    execute format('create trigger tg_%s_binding before insert on %I '
      'for each row execute function tg_thing_store_binding()', t, t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on look_withdrawal
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

commit;
