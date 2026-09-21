-- Retain undone source-element overrides and environment additions as explicit projection state.
-- The runtime role deliberately has no DELETE privilege.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_element_override
  add column addition_undone boolean not null default false;

comment on column world_alternate_element_override.addition_undone is
  'True only when an undo edit reversed the first override represented by this projection row. Readers omit the row while the row and edit log retain exact history.';

alter table world_alternate_environment_instance
  add column addition_undone boolean not null default false,
  add constraint world_alternate_environment_undone_addition_is_removed check (
    not addition_undone or (removed and created_edit_id <> last_edit_id)
  );

comment on column world_alternate_environment_instance.addition_undone is
  'True only when an undo edit reversed the addition that created this projection row. Readers omit the row while the immutable source binding and edit log retain exact history.';

-- A same-ID re-add may replace a retained undone environment row, but it must pass the same
-- current authorization and lineage checks as a new insertion. All other updates retain the
-- immutable source-binding rule.
create or replace function tg_world_environment_binding() returns trigger language plpgsql as $fn$
declare
  source_record environment_source_admission%rowtype;
  render_record derived_environment_asset%rowtype;
  publication_record environment_feature_index_publication%rowtype;
  current_publication_id uuid;
begin
  if tg_op='UPDATE' and not (old.addition_undone and not new.addition_undone) then
    if (to_jsonb(new)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'last_edit_id' - 'addition_undone')
       is distinct from
       (to_jsonb(old)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'last_edit_id' - 'addition_undone')
    then
      raise exception 'environment instance source binding is immutable'
        using errcode='23514';
    end if;
    return new;
  end if;

  select * into source_record from environment_source_admission
    where workspace_id=new.workspace_id and admission_id=new.admission_id;
  select * into render_record from derived_environment_asset
    where workspace_id=new.workspace_id and asset_id=new.render_asset_id;
  if source_record.admission_id is null or render_record.asset_id is null
    or render_record.admission_id<>new.admission_id
    or source_record.place_id<>new.source_place_id
    or source_record.source_sha256<>new.source_sha256
    or source_record.receipt_sha256<>new.source_receipt_sha256
    or render_record.source_sha256<>new.source_sha256
    or render_record.content_sha256<>new.render_sha256
    or render_record.receipt_sha256<>new.render_receipt_sha256
    or source_record.geographic_frame<>new.source_frame
    or (new.selection_kind='whole_asset'
      and source_record.geographic_bounds<>new.source_bounds)
    or not environment_resource_allows(
      new.workspace_id,'source',new.admission_id,'compose',statement_timestamp())
    or not environment_resource_allows(
      new.workspace_id,'asset',new.render_asset_id,'compose',statement_timestamp())
  then
    raise exception 'environment instance source binding is unavailable, changed, or denied'
      using errcode='23514';
  end if;

  if new.selection_kind='feature' then
    select * into publication_record from environment_feature_index_publication
      where workspace_id=new.workspace_id and publication_id=new.publication_id;
    select publication_id into current_publication_id
      from environment_feature_index_publication
      where workspace_id=new.workspace_id and admission_id=new.admission_id
      order by published_at desc,publication_id desc limit 1;
    if publication_record.publication_id is null
      or publication_record.publication_id<>current_publication_id
      or publication_record.admission_id<>new.admission_id
      or publication_record.render_asset_id<>new.render_asset_id
      or publication_record.source_sha256<>new.source_sha256
      or publication_record.source_receipt_sha256<>new.source_receipt_sha256
      or publication_record.render_sha256<>new.render_sha256
      or publication_record.render_receipt_sha256<>new.render_receipt_sha256
      or publication_record.index_sha256<>new.index_sha256
      or publication_record.index_receipt_sha256<>new.index_receipt_sha256
      or publication_record.receipt_sha256<>new.publication_receipt_sha256
      or not environment_resource_allows(
        new.workspace_id,'asset',publication_record.index_asset_id,
        'compose',statement_timestamp())
      or not environment_resource_allows(
        new.workspace_id,'source',new.admission_id,'index',statement_timestamp())
      or not environment_resource_allows(
        new.workspace_id,'asset',new.render_asset_id,'index',statement_timestamp())
      or not environment_resource_allows(
        new.workspace_id,'asset',publication_record.index_asset_id,
        'index',statement_timestamp())
    then
      raise exception 'environment feature selection is stale, changed, or denied'
        using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;

commit;
