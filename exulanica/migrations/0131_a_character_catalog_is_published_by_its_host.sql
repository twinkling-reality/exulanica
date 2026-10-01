-- 0131_a_character_catalog_is_published_by_its_host.sql
-- Character catalogs the host publishes: immutable documents named by digest, retained until the
-- host withdraws them.
--
-- A saved look names the exact family revision it was saved over (migration 0056 keeps the whole
-- family document in every revision). A family revision is derived from a catalog document, and
-- until now the one catalog a host served was the directory it started with, so a changed catalog
-- turned every saved look over a changed body into an unknown revision at once, and nothing could
-- serve two catalogs to two worlds. A publication is the reviewed decision to serve one catalog
-- document; the document is held whole, so every later reader derives the same families from the
-- same bytes, and a look resolves against every publication the host still serves.
--
-- These rows are written by the host's administration command (exulanica-character-catalog), with
-- the owner connection, after every container the document names is a reviewed asset. They are
-- never written by a request and never by a workspace, and the triggers below make that a property.
-- The document is canonical JSON of integers and strings only: exulanica.canonical refuses floats
-- in a digest input, and the reader recomputes catalog_sha256 from the stored document before
-- believing it.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. Publications. Global host data, not tenant rows.
-- --------------------------------------------------------------------------------------------

-- No workspace_id, no row-level security: every workspace reads the same publications and no
-- workspace may own, hide or alter one. (catalog_id, revision) is the document's own identity; a
-- catalog's revisions only increase, so an older revision is never published after a newer one.
-- profile and kind are a closed set the application's adapters handle; a document of any other
-- profile has no reader, so the schema refuses it rather than storing something nothing can draw.
create table character_catalog_publication (
  catalog_sha256 text primary key check (catalog_sha256 ~ '^[0-9a-f]{64}$'),
  catalog_id     text not null check (catalog_id ~ '^[a-z][a-z0-9.-]{0,99}$'),
  profile        text not null check (profile in (
                   'exulanica.character-catalog-bundle/v1',
                   'exulanica.parametric-character-catalog/v1')),
  kind           text not null check (kind in ('layered-people', 'parametric-body')),
  revision       integer not null check (revision >= 1),
  document       jsonb not null check (jsonb_typeof(document) = 'object'),
  producer       text not null check (length(btrim(producer)) between 1 and 200),
  published_at   timestamptz not null default statement_timestamp(),
  unique (catalog_id, revision),
  check ((profile = 'exulanica.character-catalog-bundle/v1') = (kind = 'layered-people'))
);

-- --------------------------------------------------------------------------------------------
-- 2. Withdrawals. Final.
-- --------------------------------------------------------------------------------------------

-- A withdrawn publication is no longer served: its catalog read answers withdrawn, and a saved
-- look whose family only it derived reads as unavailable, with its history intact. Withdrawal
-- destroys nothing; the containers stay reviewed assets, which the importer governs.
create table character_catalog_withdrawal (
  catalog_sha256 text primary key
                 references character_catalog_publication(catalog_sha256),
  reason         text not null check (reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  withdrawn_at   timestamptz not null default statement_timestamp()
);

-- A database restored from a backup taken before a withdrawal would serve the catalog again, so a
-- restore checkpoint carries every withdrawal (kind character_catalog in
-- exulanica/deletion/withdrawals.v2.json), and a sealed checkpoint refuses a new one as it refuses
-- every withdrawal (0107).
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on character_catalog_withdrawal
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- --------------------------------------------------------------------------------------------
-- 3. Only the host writes, only once.
-- --------------------------------------------------------------------------------------------

-- The ownership test is 0065's: provisioning revokes the runtime roles' writes on these tables
-- (exulanica.db.roles.READ_ONLY_TABLES), and this is the second wall for a role handed INSERT by
-- mistake. No role updates or deletes a row: a changed catalog is a new revision, and a withdrawal
-- is a row of its own.
create function tg_character_catalog_is_host_data() returns trigger language plpgsql as $fn$
begin
  if tg_op <> 'INSERT' then
    raise exception '% rows are published once and never rewritten', tg_table_name
      using errcode = 'integrity_constraint_violation';
  end if;
  if not pg_has_role(current_user,
                     (select c.relowner from pg_class c where c.oid = tg_relid),
                     'MEMBER') then
    raise exception '% is written by the host administration command, not by %',
      tg_table_name, current_user
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create trigger tg_character_catalog_publication_is_host_data
  before insert or update or delete on character_catalog_publication
  for each row execute function tg_character_catalog_is_host_data();

create trigger tg_character_catalog_withdrawal_is_host_data
  before insert or update or delete on character_catalog_withdrawal
  for each row execute function tg_character_catalog_is_host_data();

-- A catalog's revisions only increase. Publishing revision 2 after revision 3 would make "the
-- newest publication" disagree with "the latest one published", and every reader of a catalog id
-- decides by revision. Serialised on the catalog id so two publishers cannot both pass.
create function tg_character_catalog_revision_increases() returns trigger language plpgsql as $fn$
declare newest integer;
begin
  perform pg_advisory_xact_lock(hashtextextended('character_catalog:' || new.catalog_id, 880131));
  select max(revision) into newest
    from character_catalog_publication where catalog_id = new.catalog_id;
  if newest is not null and new.revision <= newest then
    raise exception 'character catalog % revision % is not newer than revision %',
      new.catalog_id, new.revision, newest
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_character_catalog_revision_increases
  before insert on character_catalog_publication
  for each row execute function tg_character_catalog_revision_increases();

-- --------------------------------------------------------------------------------------------
-- 4. Read-only for the runtime.
-- --------------------------------------------------------------------------------------------

do $$
declare
  r text;
  t text;
begin
  foreach r in array array['exulanica_app','exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['character_catalog_publication','character_catalog_withdrawal'] loop
        execute format('revoke insert,update,delete on %I from %I', t, r);
        execute format('grant select on %I to %I', t, r);
      end loop;
    end if;
  end loop;
end $$;

commit;
