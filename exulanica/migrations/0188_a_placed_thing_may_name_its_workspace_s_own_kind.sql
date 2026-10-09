-- 0188_a_placed_thing_may_name_its_workspace_s_own_kind.sql
-- A thing placed in a version may name a kind its workspace keeps, by the kind's digest alone.
--
-- 0152 records a placed thing's kind as a shipped kind by key, version and digest. A workspace also
-- keeps kinds of its own (0159: a creature drafted from a person's words), which a world names only
-- by the SHA-256 of the kind's document, never by a key a person's words made, as 0167 names a
-- workspace's own look. So a placed thing now states where its kind comes from (kind_source):
-- 'shipped', named by key, version and digest as before, or 'workspace', named by its digest
-- alone, its key and version left null. Whether the workspace still holds that kind, and whether
-- it was erased after the thing was placed, is read whenever the thing is read
-- (exulanica/world/object_repository.py): a thing whose kind is gone stays, as a version's things
-- always do, and is drawn, moved and carried into a society nowhere. No foreign key names the kind,
-- so erasing a creature (0172's thing_erasure) is never held up by a world that placed it.
--
-- What a placed thing is never changes after it is placed: 0152's binding trigger compares every
-- column but the pose, the removal and the undo, so it holds kind_source fixed as it holds the
-- kind, with no change here. Every stored thing names a shipped kind, so it reads 'shipped';
-- nothing stored is rewritten.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_thing
  add column kind_source text not null default 'shipped'
    check (kind_source in ('shipped', 'workspace'));

alter table world_alternate_thing alter column kind drop not null;
alter table world_alternate_thing alter column kind_version drop not null;

-- A shipped kind is named by key and version beside its digest; a workspace's by its digest alone.
alter table world_alternate_thing add constraint world_alternate_thing_names_its_kind_source check (
  ((kind_source = 'shipped') = (kind is not null and kind_version is not null)
   and (kind_source = 'workspace') = (kind is null and kind_version is null)) is true
);

comment on table world_alternate_thing is
  'A thing an author placed in an authored version, by a shipped kind''s key, version and digest '
  'or by the digest of a kind its workspace keeps, at the kind''s own size. What it looks like '
  'and what it does are not stored here.';

commit;
