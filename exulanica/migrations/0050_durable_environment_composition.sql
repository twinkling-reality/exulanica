-- Durable environment selections placed in authored alternate versions.
begin;
select pg_advisory_xact_lock(119622309);

create table world_alternate_environment_instance (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  instance_id text not null
    check(instance_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),
  admission_id uuid not null,
  render_asset_id uuid not null,
  publication_id uuid,
  selection_kind text not null check(selection_kind in ('whole_asset','feature')),
  feature_id text,
  render_batch_id integer,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  source_receipt_sha256 bytea not null check(octet_length(source_receipt_sha256)=32),
  render_sha256 bytea not null check(octet_length(render_sha256)=32),
  render_receipt_sha256 bytea not null check(octet_length(render_receipt_sha256)=32),
  index_sha256 bytea check(index_sha256 is null or octet_length(index_sha256)=32),
  index_receipt_sha256 bytea
    check(index_receipt_sha256 is null or octet_length(index_receipt_sha256)=32),
  publication_receipt_sha256 bytea
    check(publication_receipt_sha256 is null or octet_length(publication_receipt_sha256)=32),
  source_place_id uuid not null,
  source_frame jsonb not null check(jsonb_typeof(source_frame)='object'),
  source_bounds jsonb not null check(jsonb_typeof(source_bounds)='object'),
  source_anchor jsonb not null check(jsonb_typeof(source_anchor)='object'),
  region_id text not null check(length(region_id) between 1 and 500),
  x_mm bigint not null check(abs(x_mm)<=1000000000),
  y_mm bigint not null check(abs(y_mm)<=1000000000),
  z_mm bigint not null check(abs(z_mm)<=1000000000),
  yaw_microradians bigint not null check(yaw_microradians between 0 and 6283185),
  scale_milli bigint not null check(scale_milli between 1 and 1000000),
  origin_kind text not null check(origin_kind='authored'),
  origin_role text not null check(origin_role in ('fictional','personal')),
  removed boolean not null default false,
  created_edit_id uuid not null,
  last_edit_id uuid not null,
  primary key(workspace_id,world_id,version_id,instance_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,admission_id)
    references environment_source_admission(workspace_id,admission_id),
  foreign key(workspace_id,render_asset_id)
    references derived_environment_asset(workspace_id,asset_id),
  foreign key(workspace_id,publication_id)
    references environment_feature_index_publication(workspace_id,publication_id),
  constraint world_environment_selection_complete check(
    (selection_kind='whole_asset' and publication_id is null and feature_id is null
      and render_batch_id is null and index_sha256 is null
      and index_receipt_sha256 is null and publication_receipt_sha256 is null)
    or
    (selection_kind='feature' and publication_id is not null
      and feature_id ~ '^[0-9a-f]{32}$' and render_batch_id is not null
      and index_sha256 is not null and index_receipt_sha256 is not null
      and publication_receipt_sha256 is not null)
  )
);

create function tg_world_environment_binding() returns trigger language plpgsql as $fn$
declare
  source_record environment_source_admission%rowtype;
  render_record derived_environment_asset%rowtype;
  publication_record environment_feature_index_publication%rowtype;
  current_publication_id uuid;
begin
  if tg_op='UPDATE' then
    if (to_jsonb(new)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'last_edit_id')
       is distinct from
       (to_jsonb(old)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'last_edit_id')
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

create trigger tg_world_environment_binding
before insert or update on world_alternate_environment_instance
for each row execute function tg_world_environment_binding();

alter table world_alternate_environment_instance enable row level security;
alter table world_alternate_environment_instance force row level security;
create policy ws_isolation on world_alternate_environment_instance
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

alter table world_alternate_version_edit
  add column environment_instance_id text;
alter table world_alternate_version_edit
  drop constraint world_alternate_version_edit_kind_check;
alter table world_alternate_version_edit
  add constraint world_alternate_version_edit_kind_check check(
    kind in ('add_object','move_object','remove_object',
             'suppress_element','transform_element',
             'add_environment','move_environment','remove_environment','undo')
  );
alter table world_alternate_version_edit
  drop constraint world_alternate_edit_names_its_subject;
alter table world_alternate_version_edit
  add constraint world_alternate_edit_names_its_subject check(
    (kind in ('add_object','move_object','remove_object')
      and object_id is not null and element_id is null and environment_instance_id is null)
    or
    (kind in ('suppress_element','transform_element')
      and element_id is not null and object_id is null and environment_instance_id is null)
    or
    (kind in ('add_environment','move_environment','remove_environment')
      and environment_instance_id is not null and object_id is null and element_id is null)
    or kind='undo'
  );

create index world_alternate_environment_live_idx
  on world_alternate_environment_instance(workspace_id,world_id,version_id)
  where not removed;

commit;
