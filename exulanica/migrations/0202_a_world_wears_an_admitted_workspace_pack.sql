-- A world may wear an admitted uploaded pack as well as its generated-piece look.
--
-- 0186 limited appearance history to generated packs because uploaded identities could remain
-- in immutable style rows after their workspace was erased. Since 0195, a workspace tombstone
-- deletes the entire world, including all style versions, previews, proposals and audit rows.
-- 0173 still scrubs uploaded manifests/identifiers and queues their bytes for destruction.
-- A pack withdrawal revokes access without erasing history; its existing restore withdrawal
-- checkpoint remains authoritative. No rows or historical identities are rewritten here.
--
-- Preserve the exact workspace/id/version/digest, erasure and readiness checks. No arbitrary
-- manifest origin or merely requested/failed/withdrawn upload becomes wearable. This is the
-- same invoker trigger, with its existing owner/privileges and schema-qualified search path.

begin;
select pg_advisory_xact_lock(119622309);

create or replace function tg_world_style_version_wears_its_own_pack() returns trigger
language plpgsql as $fn$
begin
  if new.style_pack_source <> 'workspace' then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from workspace_style_pack_version v
                  where v.workspace_id = new.workspace_id
                    and v.manifest_sha256 = new.style_pack_manifest_sha256
                    and v.pack_id = new.style_pack_id
                    and v.version = new.style_pack_version
                    and v.origin in ('uploaded', 'generated')
                    and v.erased_at is null)
     or workspace_style_pack_wearable(new.workspace_id, new.style_pack_manifest_sha256)
          is not true then
    raise exception 'own_pack_not_wearable: a world wears a version of its workspace''s own pack '
                    'only while that version may be worn'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;
do $pin$ begin
  execute format('alter function tg_world_style_version_wears_its_own_pack() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $pin$;

commit;
