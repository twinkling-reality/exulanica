-- 0180_a_held_piece_is_found_by_an_index.sql
-- A look made of generated pieces, held more cheaply and more strictly: the held clause finds a
-- piece's passed outputs by an index, a generated version is never without its library base, and
-- such a look is never offered to the shared library.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
--   piece_output_held_idx   the held clause of the migration of a workspace look made of generated
--                           pieces (its preparation guard, workspace_style_pack_wearable and the
--                           repository's record) asks for the workspace's passed outputs naming one
--                           digest, per file; piece_output's only index was its key (workspace,
--                           request, variant), so each ask walked every output the workspace holds
--   generated_ids_are_generated_versions
--                           as before, except that a generated version's base is 'library' and
--                           never null: the old test passed a null base_source
--   tg_workspace_style_pack_publish_request_guard
--                           as the migration of a workspace's own style packs wrote it, and it now
--                           also refuses a generated version: its pieces are the generation
--                           worker's, made at a person's request, not a creator's own work to offer
--                           the shared library (docs/style-pack-contract.md section 11.2)

begin;
select pg_advisory_xact_lock(119622309);

create index piece_output_held_idx on piece_output (workspace_id, piece_sha256) where within;

alter table workspace_style_pack_version drop constraint generated_ids_are_generated_versions;
alter table workspace_style_pack_version
  add constraint generated_ids_are_generated_versions
    check ((erased_at is not null or (pack_id ~ '^generated\.') = (origin = 'generated'))
           and (origin <> 'generated' or base_source is not distinct from 'library'));

-- A publish request is the version's creator's, of a ready and unwithdrawn version that is not made
-- of generated pieces, passing on no licence a licensed version did not come under; it changes only
-- by its workspace's erasure.
create or replace function tg_workspace_style_pack_publish_request_guard() returns trigger
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
  select v.created_by, v.rights_basis, v.licence_id, v.licence_attribution, v.origin into version
    from workspace_style_pack_version v
   where v.workspace_id = new.workspace_id and v.manifest_sha256 = new.manifest_sha256;
  if version.created_by is distinct from new.requested_by then
    raise exception 'only the creator of a style pack version asks for it to be published'
      using errcode = 'insufficient_privilege';
  end if;
  if version.origin = 'generated' then
    raise exception 'publish_generated_look: a look made of generated pieces is not offered to the '
                    'shared library'
      using errcode = 'check_violation';
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

commit;
