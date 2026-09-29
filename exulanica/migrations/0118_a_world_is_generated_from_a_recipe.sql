-- 0118_a_world_is_generated_from_a_recipe.sql
-- A world the server generates from a reviewed recipe, the receipt that says how, and the
-- society input a world that states its own walking surfaces produces.
--
-- A third kind of world. A person chooses a recipe from the world recipe catalog
-- (assets/catalogs/world-recipes) and the server generates the world through the same path
-- POST /world-generation/worlds takes (exulanica/grammar/specified.py): the seed is drawn from the
-- recipe and the world's own identity, trying the recipe's stated candidates in order. The kind
-- CHECK 0099 wrote admits it, and a saved entry may say its world was generated.
--
-- world_generation_receipt holds what the generation was: the recipe and its specification, the
-- grammar and its descriptor digest, the candidate kept and why each earlier one was refused, the
-- seed and the generation's own output digest. The world's structural snapshot names the receipt
-- by its SHA-256 in every generated element's streaming key, so the snapshot's digest binds the
-- receipt, and a reader regenerates the records from it and holds them to the output digest. A
-- receipt is appended once and never changed or deleted, with the refusal 0029 gives every
-- receipt; it belongs to a registered world (world_generation_receipt_world_is_registered), and
-- row-level security keeps it inside its workspace.
--
-- exulanica.society-input/walking-surfaces-v1 is the input a world that states its own walking
-- surfaces produces: the purposeful society walks the footways, corners, crossings and doors the
-- world's records state rather than a lattice over a declared square, and the input records the
-- population its ground's rule derived from the world's own premises. It records the purposeful
-- routine it was composed under, as authored-ground-v3 does, and its unread placements. The
-- earlier profiles' rules are unchanged.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_identity drop constraint world_identity_kind_check;
alter table world_identity add constraint world_identity_kind_check
  check (kind in ('personal-source', 'authored-starter', 'generated'));

alter table saved_world_entry drop constraint saved_world_entry_source_kind_check;
alter table saved_world_entry add constraint saved_world_entry_source_kind_check
  check (source_kind in ('personal', 'authored', 'generated'));

create table world_generation_receipt (
  workspace_id   uuid not null,
  world_id       text not null,
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  receipt        jsonb not null check (jsonb_typeof(receipt) = 'object'),
  created_by     uuid not null,
  created_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, receipt_sha256),
  constraint world_generation_receipt_world_is_registered foreign key (workspace_id, world_id)
    references world_identity (workspace_id, world_id),
  constraint world_generation_receipt_names_its_world check (
    (receipt->>'world_id' = world_id) is true),
  constraint world_generation_receipt_states_its_generation check (
    (receipt->>'profile' = 'exulanica.generated-world/v1'
      and jsonb_typeof(receipt->'recipe') = 'object'
      and jsonb_typeof(receipt->'specification') = 'object'
      and receipt->>'seed' ~ '^[0-9a-f]{64}$'
      and receipt->>'output_digest' ~ '^[0-9a-f]{64}$'
      and jsonb_typeof(receipt->'tiles') = 'array'
      and jsonb_array_length(receipt->'tiles') between 1 and 256) is true)
);

comment on table world_generation_receipt is
  'How a generated world was generated: its recipe, specification, seed and output digest. '
  'Appended once; never updated or deleted by the runtime.';

create trigger tg_world_generation_receipt_append_only
before update or delete on world_generation_receipt
for each row execute function tg_reconstruction_privacy_append_only();

alter table world_generation_receipt enable row level security;
alter table world_generation_receipt force row level security;
create policy ws_isolation on world_generation_receipt
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- Grants for roles that already exist. Provisioning applies the same shape through
-- exulanica.db.roles, where the receipt is insert-only.
do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on world_generation_receipt to %I', r);
      if r in ('exulanica_app','orimera_app') then
        execute format('grant insert on world_generation_receipt to %I', r);
        execute format('revoke update,delete on world_generation_receipt from %I', r);
      else
        execute format('revoke insert,update,delete on world_generation_receipt from %I', r);
      end if;
    end if;
  end loop;
end $$;

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3',
     'exulanica.society-input/walking-surfaces-v1')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/walking-surfaces-v1')
      then (jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)) is true
    else not (document ? 'unread_placements') end
  );

alter table world_society_input drop constraint world_society_input_routine_check;
alter table world_society_input add constraint world_society_input_routine_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/walking-surfaces-v1')
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

-- Only the walking-surfaces input records the population its ground's rule derived, and it
-- always does: exactly a rule's name and a whole size from 0 to 512, as the planner's validator
-- states them; the size is zero for a world whose premises offer no home (its society is refused
-- by name when it is created, not here).
alter table world_society_input add constraint world_society_input_population_check
  check (
    case when document->>'profile'='exulanica.society-input/walking-surfaces-v1'
      then (jsonb_typeof(document->'population')='object'
        and ((document->'population') - 'rule' - 'size') = '{}'::jsonb
        and jsonb_typeof(document->'population'->'rule')='string'
        and length(document->'population'->>'rule') between 1 and 1000
        and case when jsonb_typeof(document->'population'->'size')='number'
              then (document->'population'->>'size') ~ '^[0-9]+$'
                and (document->'population'->>'size')::numeric between 0 and 512
              else false end) is true
    else not (document ? 'population') end
  );

commit;
