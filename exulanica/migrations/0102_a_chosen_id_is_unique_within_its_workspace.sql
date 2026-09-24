-- 0102_a_chosen_id_is_unique_within_its_workspace.sql
-- An id a caller chooses is unique within its workspace, never across workspaces.
--
-- Three ids reach the database as the caller wrote them: a place's (POST
-- /environment-resources/places), a style proposal's (POST /world/styles/previews) and an
-- interaction policy proposal's (POST /world/interactions/previews). Each was the whole primary key
-- of its table, and a primary key is enforced against every row, including the rows row-level
-- security hides. So a caller naming an id another workspace had used was refused (409
-- place_frame_conflict, 422 invalid_style_data, and a 500 from the unhandled violation) where a
-- fresh id was accepted, and the answer told a stranger that the id existed in somebody else's
-- account.
--
-- Each table is keyed by its workspace instead, which is how everything that refers to it already
-- names it: every foreign key to place names (workspace_id, place_id), and every foreign key to a
-- proposal names (workspace_id, world_id, proposal_id). No id changes and no row is rewritten.
--
-- place: its unique (workspace_id, place_id), which the foreign keys reference, becomes the primary
-- key. PostgreSQL cannot promote a constraint other constraints depend on, so each foreign key that
-- references place is dropped and added again from the definition the catalogue holds for it,
-- under its own name, and adding it checks it against every row. A foreign key naming place_id
-- alone would have nothing to reference afterwards, so adding it again would stop the migration
-- rather than leave a reference unchecked.
--
-- The two proposal tables: the primary key becomes (workspace_id, proposal_id). A proposal id stays
-- unique across the worlds of one workspace, as it was, so the owner reusing one is refused by name
-- as before; the (workspace_id, world_id, proposal_id) unique the foreign keys name is unchanged.
begin;
select pg_advisory_xact_lock(119622309);

do $migration$
declare
  referencing record;
  kept jsonb := '[]'::jsonb;
  unique_name text;
begin
  for referencing in
    select c.conrelid::regclass::text as table_name,
           c.conname as constraint_name,
           pg_get_constraintdef(c.oid) as definition
      from pg_constraint c
     where c.contype = 'f'
       and c.confrelid = 'place'::regclass
       and c.conparentid = 0
     order by 1, 2
  loop
    kept := kept || jsonb_build_object(
      'table_name', referencing.table_name,
      'constraint_name', referencing.constraint_name,
      'definition', referencing.definition
    );
    execute format(
      'alter table %s drop constraint %I', referencing.table_name, referencing.constraint_name
    );
  end loop;

  select c.conname into strict unique_name
    from pg_constraint c
   where c.conrelid = 'place'::regclass
     and c.contype = 'u'
     and c.conkey = array[
       (select attnum from pg_attribute where attrelid = 'place'::regclass and attname = 'workspace_id'),
       (select attnum from pg_attribute where attrelid = 'place'::regclass and attname = 'place_id')
     ]::int2[];
  execute format('alter table place drop constraint %I', unique_name);
  alter table place drop constraint place_pkey;
  alter table place add constraint place_pkey primary key (workspace_id, place_id);

  for referencing in
    select * from jsonb_to_recordset(kept) as k(table_name text, constraint_name text, definition text)
  loop
    execute format(
      'alter table %s add constraint %I %s',
      referencing.table_name, referencing.constraint_name, referencing.definition
    );
  end loop;
end
$migration$;

alter table world_style_proposal drop constraint world_style_proposal_pkey;
alter table world_style_proposal
  add constraint world_style_proposal_pkey primary key (workspace_id, proposal_id);

alter table world_interaction_policy_proposal drop constraint world_interaction_policy_proposal_pkey;
alter table world_interaction_policy_proposal
  add constraint world_interaction_policy_proposal_pkey primary key (workspace_id, proposal_id);

commit;
