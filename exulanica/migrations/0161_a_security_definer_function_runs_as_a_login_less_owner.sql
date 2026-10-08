-- A SECURITY DEFINER function runs as a login-less owner that is neither superuser nor BYPASSRLS.
--
-- Every migration runs as the bootstrap owner, which compose.yaml makes a superuser, and a function
-- a migration creates belongs to it. Each SECURITY DEFINER function therefore ran with every
-- privilege in the cluster: past row-level security, able to read any database, run COPY TO PROGRAM
-- and create roles. A mistake in one body was a mistake made as a superuser.
--
-- From here every SECURITY DEFINER function in the schema belongs to exulanica_definer: NOLOGIN,
-- NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION and NOINHERIT, a member of no
-- role and granted to none. It holds USAGE on the schema, the table privileges below (each line
-- names the functions whose bodies need it) and EXECUTE on the internal spending steps those
-- bodies call. It owns no table, so row-level security binds it: the workspace isolation policies
-- name no role and apply to it as to the runtime. Every definer that touches a workspace's rows
-- asserts or compares the workspace context first, and none reads another workspace's rows or a
-- row with no workspace (0155 replaced the last that did), so none needs a policy of its own.
--
-- A role belongs to the server, not the database: the first migration on a server creates it and
-- every later one finds it. One found wider than above (an attribute, a membership or a member) is
-- refused, not narrowed: functions handed to it would run with whatever it was given, and a
-- server whose role was widened by hand needs its administrator. exulanica-db checks the same,
-- every definer's owner and search path, and the role's privileges against the set below, at each
-- deployment (exulanica.db.definer_role), because a migration that drops and creates a definer,
-- or a restore that loads one without its owner, hands it back to the migrating role, and one
-- that strips or recreates a table here takes its grants away.
--
-- Each definer's search path is pinned pg_catalog first and pg_temp last, so a bare built-in name
-- in a body cannot resolve to an object planted in the schema.
--
-- Five triggers let only a member of a table's owner write the table (0065, 0072, 0074, 0076,
-- 0131). Inside a definer the current user is the definer's owner, so each now also admits
-- exulanica_definer. What that role may write is what its grants allow, and of the five tables it
-- writes only baked_tile (record_baked_tile_bake, 0144). The test stays inline in each trigger, in
-- catalog functions alone, because pg_restore loads rows under an empty search path.

begin;
select pg_advisory_xact_lock(119622309);

do $role$
declare
  wider text;
begin
  if not exists (select 1 from pg_roles where rolname = current_user and rolsuper) then
    raise exception 'this migration creates exulanica_definer and hands it the SECURITY DEFINER '
                    'functions; run it as a superuser, as compose.yaml''s database owner is'
      using errcode = '42501';
  end if;
  begin
    create role exulanica_definer
      nologin nosuperuser nobypassrls nocreatedb nocreaterole noreplication noinherit;
  exception when duplicate_object or unique_violation then
    -- Another database on this server made it first; it is checked below like any found role.
    null;
  end;
  select string_agg(found.what, ', ' order by found.what) into wider from (
    select 'can log in' as what from pg_roles
     where rolname = 'exulanica_definer' and rolcanlogin
    union all select 'is a superuser' from pg_roles
     where rolname = 'exulanica_definer' and rolsuper
    union all select 'bypasses row-level security' from pg_roles
     where rolname = 'exulanica_definer' and rolbypassrls
    union all select 'can create databases' from pg_roles
     where rolname = 'exulanica_definer' and rolcreatedb
    union all select 'can create roles' from pg_roles
     where rolname = 'exulanica_definer' and rolcreaterole
    union all select 'can replicate' from pg_roles
     where rolname = 'exulanica_definer' and rolreplication
    union all select 'inherits' from pg_roles
     where rolname = 'exulanica_definer' and rolinherit
    union all select 'is a member of ' || granted.rolname
      from pg_auth_members m
      join pg_roles granted on granted.oid = m.roleid
      join pg_roles me on me.oid = m.member
     where me.rolname = 'exulanica_definer'
    union all select 'is granted to ' || member.rolname
      from pg_auth_members m
      join pg_roles member on member.oid = m.member
      join pg_roles me on me.oid = m.roleid
     where me.rolname = 'exulanica_definer'
  ) found;
  if wider is not null then
    raise exception 'exulanica_definer % on this server; it owns SECURITY DEFINER functions only '
                    'as a narrow role, so an administrator must narrow it first', wider
      using errcode = '42501';
  end if;
  execute format('grant usage on schema %I to exulanica_definer', current_schema());
end $role$;

-- What the bodies read and write. caption_vector_purge_is_authorized and
-- caption_vector_purge_is_complete (0044), material_bake_purge_is_authorized (0066) and
-- workspace_asset_purge_is_authorized (0126) read:
grant select on tombstone, tombstone_embedding_target, person_derivative_dependency, embedding,
                material_bake, material_recipe, material_recipe_source
   to exulanica_definer;
-- tg_saved_world_source_attachment_moves_membership and
-- tg_saved_world_source_detach_moves_membership (0090):
grant select on saved_world_source_attachment_operation to exulanica_definer;
grant select, insert, update on saved_world_source_current_membership to exulanica_definer;
-- tg_sealed_checkpoint_refuses_withdrawals (0107):
grant select on restore_control to exulanica_definer;
-- tg_world_project_withdraws_its_items, tg_world_project_item_erases_on_withdrawal,
-- tg_companion_answers_withdraw_project_items and tg_tombstone_withdraws_project_context (0127),
-- and the lifecycle triggers their updates fire:
grant select, update on world_project, world_project_item, world_project_item_revision,
                        world_project_share
   to exulanica_definer;
grant select on world_project_item_source to exulanica_definer;
-- spending_authority_facts, spending_admit, spending_dispatch, spending_settle,
-- spending_open_bound and spending_close_bound (0124, 0133), spending_grant_guest,
-- spending_guest_policy_authority and tg_spending_event_ends_guest_policies (0139, 0155), and
-- tg_spending_grant_within_parent, which a grant they insert fires:
grant select on spending_authority, spending_authority_term, spending_authority_revocation
   to exulanica_definer;
grant select, update on spending_authority_state, spending_guest_policy to exulanica_definer;
grant select, insert on spending_grant, spending_grant_revocation to exulanica_definer;
grant select, insert, update on spending_grant_state, spending_reservation,
                                spending_guest_policy_day
   to exulanica_definer;
grant insert on spending_event to exulanica_definer;
-- door_prune (0149, replaced in place by 0157), which deletes a bounded batch of each by time:
grant select, delete on door_redemption_refusal, door_secret to exulanica_definer;
-- record_baked_tile_bake (0144):
grant select on baked_tile_stage to exulanica_definer;
grant select, insert, update on baked_tile to exulanica_definer;

-- The internal spending steps the spending definers call. 0124 revoked every spending function
-- from PUBLIC; the owner calls these and nothing else among them.
do $steps$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('spending__append', 'spending__charge', 'spending__live_grant',
                         'spending__refusal', 'spending__refusal_without_grant',
                         'spending__release_stale', 'spending__verdict', 'spending__witness',
                         'spending__witness_authority', 'spending__witness_position')
  loop
    execute format('grant execute on function %s to exulanica_definer', f.signature);
  end loop;
end $steps$;

-- Every SECURITY DEFINER function in the schema, found rather than listed, so none is missed. A
-- later migration's create or replace keeps the owner; a new definer must be handed over by its
-- own migration (exulanica-db refuses a deployment otherwise).
do $owners$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace and p.prosecdef
  loop
    execute format('alter routine %s owner to exulanica_definer', f.signature);
  end loop;
end $owners$;

-- Every definer's search path puts pg_catalog first, so a built-in type, function or operator a
-- body names bare is the built-in and never an object of the same name in the schema; pg_temp
-- stays last, so no temporary object shadows anything. door_prune (0149, 0157) and
-- record_baked_tile_bake (0144) already pin pg_catalog, pg_temp with schema-qualified names and
-- keep that; the 0155 guest definers already put pg_catalog first. The rest put the schema first.
do $paths$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace and p.prosecdef
       and not exists (select 1 from unnest(p.proconfig) c
                        where c ~ '^search_path=pg_catalog,(.*,)? *pg_temp$')
  loop
    execute format('alter routine %s set search_path = pg_catalog, %I, pg_temp',
                   f.signature, current_schema());
  end loop;
end $paths$;

-- The five owner-written guards. Each body is its migration's, except the test of who writes.
create or replace function tg_world_texture_set_is_migration_data() returns trigger
language plpgsql as $fn$
begin
  if tg_op <> 'INSERT' then
    raise exception
      'world_texture_set rows are pinned digests; a rebake is a new version in a new migration'
      using errcode = 'integrity_constraint_violation';
  end if;
  if not (pg_has_role(current_user,
                      (select c.relowner from pg_class c where c.oid = tg_relid),
                      'MEMBER')
          or current_user = 'exulanica_definer') then
    raise exception 'world_texture_set is written by migrations, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create or replace function tg_baked_tile_guard() returns trigger language plpgsql as $fn$
begin
  if not (pg_has_role(current_user,
                      (select c.relowner from pg_class c where c.oid = tg_relid),
                      'MEMBER')
          or current_user = 'exulanica_definer') then
    raise exception 'a baked tile is published by the offline bake, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  if tg_op = 'INSERT' then
    if new.state <> 'baked' then
      raise exception 'a baked tile is stored in the baked state' using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if new.baked_tile_id is distinct from old.baked_tile_id
     or new.tile_inputs_digest is distinct from old.tile_inputs_digest
     or new.container_sha256 is distinct from old.container_sha256
     or new.container_bytes is distinct from old.container_bytes
     or new.document_sha256 is distinct from old.document_sha256
     or new.store_namespace is distinct from old.store_namespace
     or new.render_batch_sha256 is distinct from old.render_batch_sha256
     or new.nav_envelope_sha256 is distinct from old.nav_envelope_sha256
     or new.baked_at is distinct from old.baked_at then
    raise exception 'a baked tile is what it was baked as; rebake under a new key'
      using errcode = 'check_violation';
  end if;
  if old.state = 'nondeterminism_detected' then
    raise exception 'a tile that baked twice into different bytes stays that way'
      using errcode = 'check_violation';
  end if;
  if new.state <> 'nondeterminism_detected' then
    raise exception 'the only change a stored tile takes is a detected fault'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create or replace function tg_tombstone_is_written_once() returns trigger
language plpgsql as $fn$
declare
  v_owner oid;
begin
  -- Every column but one, compared whole, so a column added later is covered without an edit.
  if (to_jsonb(new) - 'purge_completed_at') is distinct from
     (to_jsonb(old) - 'purge_completed_at') then
    raise exception 'a tombstone is written once; only its purge completion may change'
      using errcode = '23514';
  end if;
  if new.purge_completed_at is distinct from old.purge_completed_at then
    select c.relowner into v_owner from pg_class c where c.oid = tg_relid;
    if not (
      pg_has_role(current_user, v_owner, 'MEMBER')
      or current_user = 'exulanica_definer'
      or exists (select 1 from pg_roles r
                 where r.rolname = current_user and (r.rolsuper or r.rolbypassrls))
      or (has_column_privilege(current_user, tg_relid, 'purge_completed_at', 'UPDATE')
          and not has_table_privilege(current_user, tg_relid, 'UPDATE')
          and not has_table_privilege(current_user, tg_relid, 'INSERT'))
    ) then
      raise exception 'only the purge worker or an administrator records a purge completion'
        using errcode = '42501';
    end if;
  end if;
  return new;
end $fn$;

comment on function tg_tombstone_is_written_once() is
  'A tombstone changes only in purge_completed_at, and only for its owner, the definer owner, an '
  'administrator, or a role holding UPDATE on that column alone.';

create or replace function tg_world_texture_set_class_is_migration_data() returns trigger
language plpgsql as $fn$
declare
  pinned jsonb;
begin
  if tg_op <> 'INSERT' then
    raise exception
      'world_texture_set_class rows state what pinned bytes are; a set that changes is a new version'
      using errcode = 'integrity_constraint_violation';
  end if;
  if not (pg_has_role(current_user,
                      (select c.relowner from pg_class c where c.oid = tg_relid),
                      'MEMBER')
          or current_user = 'exulanica_definer') then
    raise exception 'world_texture_set_class is written by migrations, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  select s.channels into pinned
  from world_texture_set s
  where s.set_id = new.set_id and s.version = new.version;
  if pinned is null or not exists (
    select 1 from jsonb_array_elements(texture_set_layouts(new.container_profile, new.material_class))
      as allowed(layout)
    where allowed.layout = pinned
  ) then
    raise exception 'the channels pinned for % version % are not a layout of % class %',
      new.set_id, new.version, new.container_profile, new.material_class
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create or replace function tg_character_catalog_is_host_data() returns trigger
language plpgsql as $fn$
begin
  if tg_op <> 'INSERT' then
    raise exception '% rows are published once and never rewritten', tg_table_name
      using errcode = 'integrity_constraint_violation';
  end if;
  if not (pg_has_role(current_user,
                      (select c.relowner from pg_class c where c.oid = tg_relid),
                      'MEMBER')
          or current_user = 'exulanica_definer') then
    raise exception '% is written by the host administration command, not by %',
      tg_table_name, current_user
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

commit;
