-- Optional support affinity belongs to the same authored thing and immutable source snapshot.
-- Unbound rows remain entirely null. No authored state, history or published document is rewritten.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_version add constraint world_alternate_version_support_source_key
  unique(workspace_id,world_id,version_id,source_snapshot_id);

alter table world_alternate_thing
  add column support_snapshot_id uuid,
  add column support_receipt_sha256 bytea,
  add column support_network_sha256 bytea,
  add column support_surface_id text,
  add constraint world_alternate_thing_support_shape check (
    (
      support_snapshot_id is null and support_receipt_sha256 is null
      and support_network_sha256 is null and support_surface_id is null
    ) or (
      support_snapshot_id is not null and support_receipt_sha256 is not null
      and support_network_sha256 is not null and support_surface_id is not null
      and octet_length(support_receipt_sha256)=32
      and octet_length(support_network_sha256)=32
      and support_surface_id ~ '^[a-zA-Z0-9][a-zA-Z0-9_:./-]{0,159}$'
    ) is true
  ),
  add constraint world_alternate_thing_support_source_fkey
    foreign key(workspace_id,world_id,version_id,support_snapshot_id)
    references world_alternate_version(workspace_id,world_id,version_id,source_snapshot_id);

comment on column world_alternate_thing.support_snapshot_id is
  'The owning version source snapshot for an explicit support reference. Cleared by an accepted '
  'freeform thing move; removal and undo retain authored binding history. No mesh move constraint.';

-- Support affinity is placement data, mutable together with pose/history. Preserve every
-- identity, kind, origin and creation guard of 0152, including its same-id undone re-add rule.
create or replace function tg_world_thing_binding() returns trigger language plpgsql as $fn$
begin
  if tg_op='UPDATE' and not (old.addition_undone and not new.addition_undone) then
    if (to_jsonb(new)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'removed' - 'addition_undone' - 'last_edit_id'
          - 'support_snapshot_id' - 'support_receipt_sha256'
          - 'support_network_sha256' - 'support_surface_id')
       is distinct from
       (to_jsonb(old)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'removed' - 'addition_undone' - 'last_edit_id'
          - 'support_snapshot_id' - 'support_receipt_sha256'
          - 'support_network_sha256' - 'support_surface_id')
    then
      raise exception 'a placed thing keeps the kind and origin it was placed with'
        using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;

commit;
