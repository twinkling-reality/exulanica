-- Immutable current-publication lineage for bounded environment feature catalogs.
begin;
select pg_advisory_xact_lock(119622309);

create table environment_feature_index_publication (
  workspace_id uuid not null,
  publication_id uuid not null default uuidv7(),
  admission_id uuid not null,
  index_asset_id uuid not null,
  render_asset_id uuid not null,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  source_receipt_sha256 bytea not null check(octet_length(source_receipt_sha256)=32),
  index_sha256 bytea not null check(octet_length(index_sha256)=32),
  index_receipt_sha256 bytea not null check(octet_length(index_receipt_sha256)=32),
  render_sha256 bytea not null check(octet_length(render_sha256)=32),
  render_receipt_sha256 bytea not null check(octet_length(render_receipt_sha256)=32),
  receipt_record jsonb not null,
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  published_by uuid not null,
  published_at timestamptz not null default now(),
  primary key(workspace_id,publication_id),
  unique(workspace_id,index_asset_id),
  foreign key(workspace_id,admission_id)
    references environment_source_admission(workspace_id,admission_id),
  foreign key(workspace_id,index_asset_id)
    references derived_environment_asset(workspace_id,asset_id),
  foreign key(workspace_id,render_asset_id)
    references derived_environment_asset(workspace_id,asset_id),
  check(receipt_record->>'profile'='exulanica.environment-feature-index-publication/v1'),
  check(receipt_record->>'publication_id'=publication_id::text),
  check(receipt_record->>'admission_id'=admission_id::text),
  check(receipt_record->>'index_asset_id'=index_asset_id::text),
  check(receipt_record->>'render_asset_id'=render_asset_id::text),
  check(receipt_record->>'source_sha256'=encode(source_sha256,'hex')),
  check(receipt_record->>'source_receipt_sha256'=encode(source_receipt_sha256,'hex')),
  check(receipt_record->>'index_sha256'=encode(index_sha256,'hex')),
  check(receipt_record->>'index_receipt_sha256'=encode(index_receipt_sha256,'hex')),
  check(receipt_record->>'render_sha256'=encode(render_sha256,'hex')),
  check(receipt_record->>'render_receipt_sha256'=encode(render_receipt_sha256,'hex')),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
create index environment_feature_index_current_idx
  on environment_feature_index_publication(
    workspace_id,admission_id,published_at desc,publication_id desc
  );

alter table environment_feature_index_publication enable row level security;
alter table environment_feature_index_publication force row level security;
create policy ws_isolation on environment_feature_index_publication
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());
create trigger aaa_asset_read_mutation
before insert or update or delete on environment_feature_index_publication
for each row execute function tg_asset_read_mutation();

create function tg_environment_feature_index_publication() returns trigger
language plpgsql as $fn$
declare
  source_record environment_source_admission%rowtype;
  index_record derived_environment_asset%rowtype;
  render_record derived_environment_asset%rowtype;
begin
  select * into source_record from environment_source_admission
    where workspace_id=new.workspace_id and admission_id=new.admission_id;
  select * into index_record from derived_environment_asset
    where workspace_id=new.workspace_id and asset_id=new.index_asset_id;
  select * into render_record from derived_environment_asset
    where workspace_id=new.workspace_id and asset_id=new.render_asset_id;
  if source_record.admission_id is null
    or index_record.asset_id is null or render_record.asset_id is null
    or source_record.withdrawn_at is not null
    or index_record.withdrawn_at is not null or render_record.withdrawn_at is not null
    or index_record.admission_id<>new.admission_id
    or render_record.admission_id<>new.admission_id
    or index_record.parent_asset_id<>new.render_asset_id
    or index_record.derivation_kind<>'environment-feature-index'
    or index_record.media_type<>'application/vnd.exulanica.environment-feature-index+json'
    or source_record.source_sha256<>new.source_sha256
    or source_record.receipt_sha256<>new.source_receipt_sha256
    or index_record.content_sha256<>new.index_sha256
    or index_record.receipt_sha256<>new.index_receipt_sha256
    or render_record.content_sha256<>new.render_sha256
    or render_record.receipt_sha256<>new.render_receipt_sha256
    or not environment_resource_allows(
      new.workspace_id,'source',new.admission_id,'index',statement_timestamp())
    or not environment_resource_allows(
      new.workspace_id,'asset',new.index_asset_id,'index',statement_timestamp())
    or not environment_resource_allows(
      new.workspace_id,'asset',new.render_asset_id,'index',statement_timestamp())
  then
    raise exception 'environment feature publication bindings are unavailable or denied'
      using errcode='23514';
  end if;
  if (select count(*) from jsonb_object_keys(new.receipt_record))<>11 then
    raise exception 'environment feature publication receipt is malformed'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_environment_feature_index_publication
before insert on environment_feature_index_publication
for each row execute function tg_environment_feature_index_publication();

create function tg_environment_feature_index_immutable() returns trigger
language plpgsql as $fn$
begin
  raise exception 'environment feature publications are immutable'
    using errcode='23514';
end $fn$;
create trigger tg_environment_feature_index_immutable
before update or delete on environment_feature_index_publication
for each row execute function tg_environment_feature_index_immutable();

commit;
