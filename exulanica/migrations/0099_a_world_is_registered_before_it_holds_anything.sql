-- 0099_a_world_is_registered_before_it_holds_anything.sql
-- A world is a registered identity with a kind, owned by one workspace, before any world table
-- holds a row for it.
--
-- Every world table has keyed its rows by (workspace_id, world_id) since 0017, so storage has
-- always held any number of worlds. What it never held was the world itself: a world existed
-- because some table had a row naming it, and it came into existence as a side effect of the first
-- write that did. Nothing recorded what kind of world it was, who owned it, where it came from or
-- when, and nothing could refuse a world the account was not allowed to have, because there was no
-- moment of creation to refuse.
--
-- world_identity is that moment. One row per world, appended once and never changed:
--
--   kind        what the world is. 'personal-source' is composed from the workspace's own
--               photographs and other personal sources; 'authored-starter' is a
--               source-independent authored world that starts empty. The list is stated once in
--               exulanica/world/worlds.py and held equal to this CHECK by tests/test_worlds.py.
--   provenance  how the row came to be: the policy version a creation was checked against, or
--               the stored fact a backfilled row's kind was read from.
--   created_by  the actor who created it; null only for a world that existed before this
--               migration and was registered by it.
--
-- How many worlds of a kind a workspace may hold is a versioned policy the server checks at
-- creation (exulanica/world/world-count-policy.v1.json), not a constraint here, so changing the
-- number is a new policy version rather than a migration.
--
-- EVERY WORLD TABLE names its world through a foreign key to world_identity. The tables are read
-- from the catalog, not listed here: every base table in this schema with a world_id column. A
-- table that reached its world only through nullable columns (an export whose structure, style and
-- interaction pointers are all null names a world_id no key checks) is anchored the same way as
-- the rest. A world table a later migration adds declares the same key, and tests/test_worlds.py
-- fails on one that does not.
--
-- ONE WORLD TABLE HOLDS ROWS THAT NAME NO WORLD. world_package_export is the ledger of every signed
-- package, and a training dataset export (0039; the rows whose training_terms is set) keeps its
-- dataset package id in world_id: such a row exports a dataset, not a world. That table's key
-- reads named_world_id instead, a stored generated column equal to world_id on a row that exports a
-- world and null on a dataset export, which a foreign key does not check, and the backfill
-- registers no dataset package as a world. The table and the predicate true of its world rows are
-- stated once, in migration_0099_world_rows below.
--
-- THE BACKFILL registers every world any of those tables names. Its kind comes from stored fact,
-- not from the shape of its id: a world whose structural snapshot was committed by the authored
-- starter composer ('authored-starter-world', exulanica/world/starter.py) is an authored starter,
-- and every other world is personal-source, which is what every such world was composed as. A
-- workspace that already holds more personal-source worlds than the policy allows keeps them: the
-- policy governs creation, and a migration does not delete a world.
--
-- world_topology_contract.world_id loses the column default 0017 gave it. A default naming a world
-- is a write that says nothing about which world it meant.
--
-- Forward-only. Dropping world_identity would leave every world table's foreign key naming it;
-- recovery is a restore from backup.

begin;

select pg_advisory_xact_lock(119622309);

create table world_identity (
  workspace_id uuid not null,
  world_id     text not null check (length(world_id) between 1 and 200),
  kind         text not null check (kind in ('personal-source', 'authored-starter')),
  provenance   jsonb not null check (jsonb_typeof(provenance) = 'object'),
  created_by   uuid,
  created_at   timestamptz not null default now(),
  primary key (workspace_id, world_id),
  constraint world_identity_names_its_creator check (
    created_by is not null or provenance->>'origin' = 'backfill')
);

create index world_identity_kind_idx on world_identity (workspace_id, kind, created_at, world_id);

comment on table world_identity is
  'Every world a workspace holds, registered with its kind before any world table names it. '
  'Appended once; never updated or deleted by the runtime.';

-- The world tables, read once from the catalog. world_identity is excluded by name because it is
-- the table they refer to.
create temporary table migration_0099_world_table on commit drop as
select c.relname::text as table_name, c.relforcerowsecurity as forced
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = current_schema()
   and c.relkind = 'r'
   and c.relname <> 'world_identity'
   and exists (
     select 1 from pg_attribute a
      where a.attrelid = c.oid and a.attname = 'world_id' and a.attnum > 0 and not a.attisdropped);

-- The world tables whose rows do not all name a world, each with the predicate true of the rows
-- that do. A table absent here names a world on every row.
create temporary table migration_0099_world_rows (
  table_name    text primary key,
  names_a_world text not null
) on commit drop;
insert into migration_0099_world_rows (table_name, names_a_world) values
  ('world_package_export', 'training_terms is null');

do $$
begin
  if (select count(*) from migration_0099_world_table) = 0 then
    raise exception '0099 found no world table in schema %; the catalog read is wrong',
      current_schema();
  end if;
  if exists (select 1 from migration_0099_world_rows r
              where not exists (select 1 from migration_0099_world_table w
                                 where w.table_name = r.table_name)) then
    raise exception '0099 names a world table schema % does not hold', current_schema();
  end if;
end $$;

-- The backfill reads every workspace. A migration role subject to row-level security would read
-- nothing under FORCE with no workspace set and register no world, and the foreign keys below
-- would then refuse the migration. Lifting FORCE on the tables read, for these statements only,
-- exempts the owner; row_security=off turns any remaining filtering into an error instead of an
-- empty result. 0090 reads its backfill the same way. FORCE is restored on exactly the tables that
-- had it.
set local row_security = off;
do $$
declare t text;
begin
  for t in select table_name from migration_0099_world_table where forced order by table_name loop
    execute format('alter table %I no force row level security', t);
  end loop;
end $$;

do $$
declare
  t text;
  rows_naming text;
  named text := '';
begin
  for t, rows_naming in
    select w.table_name, coalesce(r.names_a_world, 'true')
      from migration_0099_world_table w
      left join migration_0099_world_rows r on r.table_name = w.table_name
     order by w.table_name
  loop
    named := named || case when named = '' then '' else ' union ' end
      || format('select workspace_id, world_id from %I where %s', t, rows_naming);
  end loop;
  execute format($sql$
    insert into world_identity (workspace_id, world_id, kind, provenance, created_by)
    select found.workspace_id,
           found.world_id,
           case when starter.world_id is not null then 'authored-starter'
                else 'personal-source' end,
           jsonb_build_object(
             'origin', 'backfill',
             'migration', '0099_a_world_is_registered_before_it_holds_anything',
             'kind_from', case when starter.world_id is not null
                               then 'structural snapshot composer authored-starter-world'
                               else 'no snapshot committed by the authored starter composer' end),
           null
      from (%s) found
      left join (
        select distinct workspace_id, world_id from world_structure_snapshot
         where composer_key = 'authored-starter-world'
      ) starter on starter.workspace_id = found.workspace_id and starter.world_id = found.world_id
  $sql$, named);
end $$;

do $$
declare t text;
begin
  for t in select table_name from migration_0099_world_table where forced order by table_name loop
    execute format('alter table %I force row level security', t);
  end loop;
end $$;
set local row_security = on;

alter table world_topology_contract alter column world_id drop default;

-- A table whose rows do not all name a world is keyed through named_world_id, stored so that the
-- key can read it.
do $$
declare
  t text;
  rows_naming text;
  key_column text;
begin
  for t, rows_naming in
    select w.table_name, r.names_a_world
      from migration_0099_world_table w
      left join migration_0099_world_rows r on r.table_name = w.table_name
     order by w.table_name
  loop
    key_column := 'world_id';
    if rows_naming is not null then
      key_column := 'named_world_id';
      execute format(
        'alter table %I add column %I text generated always as '
        '(case when %s then world_id end) stored',
        t, key_column, rows_naming);
    end if;
    execute format(
      'alter table %I add constraint %I foreign key (workspace_id, %I) '
      'references world_identity (workspace_id, world_id)',
      t, t || '_world_is_registered', key_column);
  end loop;
end $$;

-- Appended, never changed and never deleted, with the refusal 0029 gives every receipt.
create trigger tg_world_identity_append_only
before update or delete on world_identity
for each row execute function tg_reconstruction_privacy_append_only();

alter table world_identity enable row level security;
alter table world_identity force row level security;
create policy ws_isolation on world_identity
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- Grants for roles that already exist. Provisioning applies the same shape through
-- exulanica.db.roles, where world_identity is insert-only.
do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on world_identity to %I', r);
      if r in ('exulanica_app','orimera_app') then
        execute format('grant insert on world_identity to %I', r);
        execute format('revoke update,delete on world_identity from %I', r);
      else
        execute format('revoke insert,update,delete on world_identity from %I', r);
      end if;
    end if;
  end loop;
end $$;

commit;
