-- Workspace-scoped reusable environment sources and their immutable derived assets.
begin;
select pg_advisory_xact_lock(119622309);

create function environment_rights_valid(p_rights jsonb) returns boolean
language sql immutable as $fn$
  select jsonb_typeof(p_rights)='object'
    and p_rights ?& array[
      'display','extract','index','persist','modify','compose','export','model_processing'
    ]
    and (select count(*) from jsonb_object_keys(p_rights))=8
    and not exists (
      select 1 from jsonb_each(p_rights) e where jsonb_typeof(e.value)<>'boolean'
    );
$fn$;

create table environment_source_admission (
  workspace_id uuid not null,
  admission_id uuid not null default uuidv7(),
  place_id uuid not null,
  provider_key text not null check(provider_key=btrim(provider_key) and provider_key<>''),
  provider_original_id text not null
    check(provider_original_id=btrim(provider_original_id) and provider_original_id<>''),
  provider_revision text not null
    check(provider_revision=btrim(provider_revision) and provider_revision<>''),
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  source_path text not null check(source_path=btrim(source_path) and source_path<>''),
  member_path text,
  media_type text not null check(media_type ~ '^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$'),
  byte_size bigint not null check(byte_size>=0),
  geographic_frame jsonb not null,
  geographic_bounds jsonb not null,
  operation_rights jsonb not null check(environment_rights_valid(operation_rights)),
  attribution text not null check(attribution=btrim(attribution) and attribution<>''),
  modification_notice text not null
    check(modification_notice=btrim(modification_notice) and modification_notice<>''),
  receipt_record jsonb not null,
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  admitted_by uuid not null,
  admitted_at timestamptz not null default now(),
  withdrawn_at timestamptz,
  primary key(workspace_id,admission_id),
  unique(workspace_id,provider_key,provider_original_id,provider_revision),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id),
  check(member_path is null or (member_path=btrim(member_path) and member_path<>'')),
  check(withdrawn_at is null or withdrawn_at>=admitted_at),
  check(jsonb_typeof(geographic_frame)='object' and jsonb_typeof(geographic_bounds)='object'),
  check(receipt_record->>'profile'='exulanica.environment-source-admission/v1'),
  check(receipt_record->>'admission_id'=admission_id::text),
  check(receipt_record->>'place_id'=place_id::text),
  check(receipt_record->>'source_sha256'=encode(source_sha256,'hex')),
  check(receipt_record->>'byte_size'=byte_size::text),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
create index environment_source_place_idx
  on environment_source_admission(workspace_id,place_id);

create table derived_environment_asset (
  workspace_id uuid not null,
  asset_id uuid not null default uuidv7(),
  admission_id uuid not null,
  parent_asset_id uuid,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  content_sha256 bytea not null check(octet_length(content_sha256)=32),
  source_member_path text,
  media_type text not null check(media_type ~ '^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$'),
  byte_size bigint not null check(byte_size>=0),
  derivation_kind text not null
    check(derivation_kind=btrim(derivation_kind) and derivation_kind<>''),
  derivation_lineage jsonb not null,
  geographic_frame jsonb not null,
  geographic_bounds jsonb not null,
  operation_rights jsonb not null check(environment_rights_valid(operation_rights)),
  attribution text not null check(attribution=btrim(attribution) and attribution<>''),
  modification_notice text not null
    check(modification_notice=btrim(modification_notice) and modification_notice<>''),
  receipt_record jsonb not null,
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  withdrawn_at timestamptz,
  primary key(workspace_id,asset_id),
  foreign key(workspace_id,admission_id)
    references environment_source_admission(workspace_id,admission_id),
  foreign key(workspace_id,parent_asset_id)
    references derived_environment_asset(workspace_id,asset_id),
  check(source_member_path is null or
    (source_member_path=btrim(source_member_path) and source_member_path<>'')),
  check(withdrawn_at is null or withdrawn_at>=created_at),
  check(jsonb_typeof(derivation_lineage)='object'),
  check(jsonb_typeof(geographic_frame)='object' and jsonb_typeof(geographic_bounds)='object'),
  check(receipt_record->>'profile'='exulanica.derived-environment-asset/v1'),
  check(receipt_record->>'asset_id'=asset_id::text),
  check(receipt_record->>'admission_id'=admission_id::text),
  check(receipt_record->>'source_sha256'=encode(source_sha256,'hex')),
  check(receipt_record->>'content_sha256'=encode(content_sha256,'hex')),
  check(receipt_record->>'byte_size'=byte_size::text),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
create index derived_environment_source_idx
  on derived_environment_asset(workspace_id,admission_id);

do $$ declare t text; begin
  foreach t in array array['environment_source_admission','derived_environment_asset'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
    execute format('create trigger aaa_asset_read_mutation '
      'before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()',t);
  end loop;
end $$;

create function tg_environment_source_receipt() returns trigger language plpgsql as $fn$
begin
  if (select count(*) from jsonb_object_keys(new.receipt_record))<>14
    or (select count(*) from jsonb_object_keys(new.receipt_record->'provider'))<>3
    or new.receipt_record->'provider'->>'key' is distinct from new.provider_key
    or new.receipt_record->'provider'->>'original_id' is distinct from new.provider_original_id
    or new.receipt_record->'provider'->>'revision' is distinct from new.provider_revision
    or new.receipt_record->>'source_path' is distinct from new.source_path
    or new.receipt_record->>'member_path' is distinct from new.member_path
    or new.receipt_record->>'media_type' is distinct from new.media_type
    or new.receipt_record->'geographic_frame' is distinct from new.geographic_frame
    or new.receipt_record->'geographic_bounds' is distinct from new.geographic_bounds
    or new.receipt_record->'operation_rights' is distinct from new.operation_rights
    or new.receipt_record->>'attribution' is distinct from new.attribution
    or new.receipt_record->>'modification_notice' is distinct from new.modification_notice
  then
    raise exception 'environment source receipt disagrees with admitted metadata'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_environment_source_receipt
before insert on environment_source_admission
for each row execute function tg_environment_source_receipt();

create function tg_derived_environment_lineage() returns trigger language plpgsql as $fn$
declare source_digest bytea; parent_record derived_environment_asset%rowtype;
begin
  select source_sha256 into source_digest from environment_source_admission
    where workspace_id=new.workspace_id and admission_id=new.admission_id;
  if source_digest is null or source_digest<>new.source_sha256 then
    raise exception 'derived environment asset source digest disagrees with its admission'
      using errcode='23514';
  end if;
  if new.parent_asset_id is not null then
    select * into parent_record from derived_environment_asset
      where workspace_id=new.workspace_id and asset_id=new.parent_asset_id;
    if not found or parent_record.admission_id<>new.admission_id
      or parent_record.source_sha256<>new.source_sha256 then
      raise exception 'derived environment parent belongs to another source'
        using errcode='23514';
    end if;
  end if;
  if (select count(*) from jsonb_object_keys(new.receipt_record))<>16
    or new.receipt_record->>'parent_asset_id'
       is distinct from (case when new.parent_asset_id is null then null
                              else new.parent_asset_id::text end)
    or new.receipt_record->>'source_member_path' is distinct from new.source_member_path
    or new.receipt_record->>'media_type' is distinct from new.media_type
    or new.receipt_record->>'derivation_kind' is distinct from new.derivation_kind
    or new.receipt_record->'derivation_lineage' is distinct from new.derivation_lineage
    or new.receipt_record->'geographic_frame' is distinct from new.geographic_frame
    or new.receipt_record->'geographic_bounds' is distinct from new.geographic_bounds
    or new.receipt_record->'operation_rights' is distinct from new.operation_rights
    or new.receipt_record->>'attribution' is distinct from new.attribution
    or new.receipt_record->>'modification_notice' is distinct from new.modification_notice
    or jsonb_typeof(new.derivation_lineage->'input_sha256') is distinct from 'array'
    or jsonb_array_length(new.derivation_lineage->'input_sha256')=0
    or coalesce(new.derivation_lineage->>'method','')=''
    or exists(select 1 from jsonb_array_elements_text(
      new.derivation_lineage->'input_sha256') digest_value
      where digest_value !~ '^[0-9a-f]{64}$')
  then
    raise exception 'derived environment receipt or lineage disagrees'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_derived_environment_lineage
before insert on derived_environment_asset
for each row execute function tg_derived_environment_lineage();

create function tg_environment_source_immutable() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'environment source admissions are withdrawn, never deleted'
      using errcode='23514';
  end if;
  if (new.workspace_id,new.admission_id,new.place_id,new.provider_key,new.provider_original_id,
      new.provider_revision,new.source_sha256,new.source_path,new.member_path,new.media_type,
      new.byte_size,new.geographic_frame,new.geographic_bounds,new.attribution,
      new.modification_notice,new.receipt_record,new.receipt_canonical,new.receipt_sha256,
      new.admitted_by,new.admitted_at)
    is distinct from
     (old.workspace_id,old.admission_id,old.place_id,old.provider_key,old.provider_original_id,
      old.provider_revision,old.source_sha256,old.source_path,old.member_path,old.media_type,
      old.byte_size,old.geographic_frame,old.geographic_bounds,old.attribution,
      old.modification_notice,old.receipt_record,old.receipt_canonical,old.receipt_sha256,
      old.admitted_by,old.admitted_at)
    or (old.withdrawn_at is not null and new.withdrawn_at is distinct from old.withdrawn_at)
  then
    raise exception 'environment source identity and receipt are immutable'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_environment_source_immutable
before update or delete on environment_source_admission
for each row execute function tg_environment_source_immutable();

create function tg_derived_environment_asset_immutable() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'derived environment assets are withdrawn, never deleted'
      using errcode='23514';
  end if;
  if (new.workspace_id,new.asset_id,new.admission_id,new.parent_asset_id,new.source_sha256,
      new.content_sha256,new.source_member_path,new.media_type,new.byte_size,new.derivation_kind,
      new.derivation_lineage,new.geographic_frame,new.geographic_bounds,new.attribution,
      new.modification_notice,new.receipt_record,new.receipt_canonical,new.receipt_sha256,
      new.created_by,new.created_at)
    is distinct from
     (old.workspace_id,old.asset_id,old.admission_id,old.parent_asset_id,old.source_sha256,
      old.content_sha256,old.source_member_path,old.media_type,old.byte_size,old.derivation_kind,
      old.derivation_lineage,old.geographic_frame,old.geographic_bounds,old.attribution,
      old.modification_notice,old.receipt_record,old.receipt_canonical,old.receipt_sha256,
      old.created_by,old.created_at)
    or (old.withdrawn_at is not null and new.withdrawn_at is distinct from old.withdrawn_at)
  then
    raise exception 'derived environment asset identity and receipt are immutable'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_derived_environment_asset_immutable
before update or delete on derived_environment_asset
for each row execute function tg_derived_environment_asset_immutable();

create function environment_resource_allows(
  p_workspace uuid,p_kind text,p_resource uuid,p_operation text,p_at timestamptz
) returns boolean language sql stable as $fn$
  select p_workspace=current_workspace()
    and p_operation=any(array[
      'display','extract','index','persist','modify','compose','export','model_processing'
    ])
    and case p_kind
      when 'source' then exists(
        select 1 from environment_source_admission s
        where s.workspace_id=p_workspace and s.admission_id=p_resource
          and s.withdrawn_at is null
          and environment_rights_valid(s.operation_rights)
          and s.operation_rights->>p_operation='true')
      when 'asset' then exists(
        select 1 from derived_environment_asset a
        join environment_source_admission s
          on s.workspace_id=a.workspace_id and s.admission_id=a.admission_id
        where a.workspace_id=p_workspace and a.asset_id=p_resource
          and a.withdrawn_at is null and s.withdrawn_at is null
          and environment_rights_valid(a.operation_rights)
          and environment_rights_valid(s.operation_rights)
          and a.operation_rights->>p_operation='true'
          and s.operation_rights->>p_operation='true')
      else false
    end;
$fn$;

commit;
