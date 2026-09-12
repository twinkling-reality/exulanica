-- Normalized images are derived inputs, never evidence or a substitute for a privacy mask.
begin;
select pg_advisory_xact_lock(119622309);

create table decoded_source (
  workspace_id uuid not null,
  artifact_id uuid not null references artifact(artifact_id),
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  output_sha256 bytea not null check(octet_length(output_sha256)=32),
  receipt_record jsonb not null,
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  primary key(workspace_id,artifact_id),
  check(source_sha256<>output_sha256),
  check(receipt_record->>'profile'='exulanica.decoded-source/v1'),
  check(receipt_record->>'source_sha256'=encode(source_sha256,'hex')),
  check(receipt_record->>'output_sha256'=encode(output_sha256,'hex')),
  check(receipt_record->'decoder'->>'pi-heif'='1.4.0'),
  check(receipt_record->'pixel_grid'->>'orientation'='1'),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
alter table decoded_source enable row level security;
alter table decoded_source force row level security;
create policy ws_isolation on decoded_source using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());
create trigger aaa_asset_read_mutation before insert or update or delete on decoded_source
for each row execute function tg_asset_read_mutation();

create function tg_decoded_source_record() returns trigger language plpgsql as $fn$
begin
 if tg_op<>'INSERT' then
   raise exception 'decoded source lineage is immutable; rebuild instead' using errcode='23514';
 end if;
 if not (new.receipt_record ?& array['profile','source_sha256','output_sha256','decoder','parameters','pixel_grid'])
   or (select count(*) from jsonb_object_keys(new.receipt_record))<>6 then
   raise exception 'decoded source receipt fields are incomplete' using errcode='23514';
 end if;
 if new.receipt_record->'parameters'->'decoder_inventory' is distinct from new.receipt_record->'decoder'
   or not (new.receipt_record->'decoder' ?& array['pi-heif','libheif','libde265','pillow'])
   or (new.receipt_record->'pixel_grid'->>'orientation') is distinct from '1'
   or (new.receipt_record->'pixel_grid'->>'convention') is distinct from 'display-top-left-x-right-y-down'
   or jsonb_typeof(new.receipt_record->'pixel_grid'->'width') is distinct from 'number'
   or jsonb_typeof(new.receipt_record->'pixel_grid'->'height') is distinct from 'number'
   or (new.receipt_record->'pixel_grid'->>'width')::bigint<=0
   or (new.receipt_record->'pixel_grid'->>'height')::bigint<=0
   or (new.receipt_record->'pixel_grid'->>'width')::bigint *
      (new.receipt_record->'pixel_grid'->>'height')::bigint>64000000 then
   raise exception 'decoded source inventory or pixel grid disagrees' using errcode='23514';
 end if;
 if not exists(select 1 from artifact a join blob b on b.blob_sha256=a.source_blob_sha256
   join stage_registry s on s.stage_key='decoded_source'
   where a.workspace_id=new.workspace_id and a.artifact_id=new.artifact_id
   and a.source_blob_sha256=new.source_sha256 and a.content_sha256=new.output_sha256
   and a.kind='decoded_source' and a.stage_key='decoded_source'
   and a.stage_version=s.current_version and new.receipt_record->'parameters'=s.params_schema
   and a.params_digest=digest(convert_to(privacy_canonical(s.params_schema),'UTF8'),'sha256')
   and b.media_type in ('image/heif','image/heic') and a.purged_at is null
   and a.storage_key is not null and not a.needs_repair) then
   raise exception 'decoded source receipt does not bind its original and artifact' using errcode='23514';
 end if;
 return new;
end $fn$;
create trigger tg_decoded_source_record before insert or update or delete on decoded_source
for each row execute function tg_decoded_source_record();

create function decoded_source_current(p_workspace uuid,p_blob bytea)
returns uuid language sql stable as $fn$
 select d.artifact_id from decoded_source d join artifact a on a.artifact_id=d.artifact_id
 join stage_registry s on s.stage_key='decoded_source'
 join blob b on b.blob_sha256=d.source_sha256 and b.purged_at is null and b.storage_key is not null
 where d.workspace_id=p_workspace and p_workspace=current_workspace()
 and a.workspace_id=d.workspace_id and d.source_sha256=p_blob
 and a.source_blob_sha256=d.source_sha256 and a.content_sha256=d.output_sha256
 and a.kind='decoded_source' and a.stage_key='decoded_source' and a.stage_version=s.current_version
 and a.params_digest=digest(convert_to(privacy_canonical(s.params_schema),'UTF8'),'sha256')
 and d.receipt_record->'parameters'=s.params_schema
 and a.purged_at is null and not a.needs_repair and a.storage_key is not null
 and a.byte_size is not null
 and exists(select 1 from capture c where c.workspace_id=d.workspace_id
   and c.blob_sha256=d.source_sha256 and c.deleted_at is null
   and asset_capture_live(c.workspace_id,c.capture_id,statement_timestamp()))
 order by a.created_at desc,a.artifact_id limit 1;
$fn$;

-- The producer input independently resolves conversion and privacy. A normalized image can
-- never satisfy the masked branch. The read policy and geometry guard share this selection.
create function source_image_input(p_workspace uuid,p_capture uuid,p_at timestamptz)
returns bytea language plpgsql stable as $fn$
declare c record; inputs jsonb; selected bytea;
begin
 if p_workspace is distinct from current_workspace() then return null; end if;
 select c0.blob_sha256,b.media_type into c from capture c0
 join blob b on b.blob_sha256=c0.blob_sha256 where c0.workspace_id=p_workspace
 and c0.capture_id=p_capture and c0.deleted_at is null and b.purged_at is null;
 if not found or not asset_capture_live(p_workspace,p_capture,p_at) then return null; end if;
 inputs:=privacy_inputs_at(p_workspace,p_capture,p_at);
 if asset_mask_needed(inputs) then
   select m.content_sha256 into selected from artifact m where m.workspace_id=p_workspace
   and m.source_blob_sha256=c.blob_sha256
   and privacy_mask_matches(p_workspace,p_capture,m.artifact_id,inputs)
   order by m.artifact_id limit 1;
 elsif c.media_type in ('image/heif','image/heic') then
   select output_sha256 into selected from decoded_source where workspace_id=p_workspace
   and artifact_id=decoded_source_current(p_workspace,c.blob_sha256);
 else selected:=c.blob_sha256;
 end if;
 return selected;
end $fn$;

create or replace function privacy_mask_matches(p_workspace uuid,p_capture uuid,p_artifact uuid,p_inputs jsonb)
returns boolean language sql volatile as $fn$
  with region_hash as (
    select digest(convert_to(privacy_canonical(jsonb_build_object(
      'profile','exulanica.person-region-set/v1','capture_id',p_capture,
      'source_sha256',p_inputs->>'source_sha256','regions',coalesce(jsonb_agg(
        jsonb_build_object('region_key',r->>'region_key','silhouette',r->'silhouette')
        order by r->>'region_key'),'[]'::jsonb))),'UTF8'),'sha256') as h
    from jsonb_array_elements(p_inputs->'regions') r),
  state_hash as (
    select digest(convert_to(privacy_canonical(jsonb_build_object(
      'profile','exulanica.person-consent-state/v1','capture_id',p_capture,
      'source_sha256',p_inputs->>'source_sha256','states',coalesce(jsonb_agg(
        jsonb_build_object('region_key',r->>'region_key','state',r->>'state',
          'masked',r->>'state' in ('unknown','present','withdrawn'),
          'name_permitted',r->'name_permitted') order by r->>'region_key'),'[]'::jsonb))),'UTF8'),'sha256') as h
    from jsonb_array_elements(p_inputs->'regions') r)
  select p_inputs is not null and exists (
    select 1 from artifact m join stage_registry ms on ms.stage_key='masked_source'
      join artifact i on i.workspace_id=m.workspace_id and i.source_blob_sha256=m.source_blob_sha256
      join stage_registry ins on ins.stage_key='intake'
      left join decoded_source d on d.workspace_id=m.workspace_id
        and d.artifact_id=decoded_source_current(m.workspace_id,m.source_blob_sha256)
      join blob b on b.blob_sha256=m.source_blob_sha256
      cross join region_hash rh cross join state_hash sh
    where m.workspace_id=p_workspace and m.artifact_id=p_artifact and m.kind='masked_source'
      and m.stage_key='masked_source' and m.stage_version=ms.current_version
      and m.params_digest=digest(convert_to(privacy_canonical(ms.params_schema),'UTF8'),'sha256')
      and m.source_blob_sha256=decode(p_inputs->>'source_sha256','hex')
      and m.purged_at is null and not m.needs_repair and m.content_sha256 is not null
      and m.storage_key is not null and m.byte_size is not null
      and i.stage_key='intake' and i.stage_version=ins.current_version
      and i.params_digest=digest(convert_to(privacy_canonical(ins.params_schema),'UTF8'),'sha256')
      and i.purged_at is null and not i.needs_repair and i.content_sha256 is not null
      and (case when b.media_type in ('image/heif','image/heic')
        then d.artifact_id is not null and m.read_source_sha256=d.output_sha256
          and exists(select 1 from pipeline_event e join pipeline_run er on er.run_id=e.run_id
            where er.workspace_id=m.workspace_id
            and e.event_id=m.produced_by_event and d.artifact_id=any(e.input_artifact_ids))
        else m.read_source_sha256 is null end)
      and m.input_digest=(select digest(convert_to(privacy_canonical(jsonb_agg(h order by h)),'UTF8'),'sha256')
        from (values(encode(i.content_sha256,'hex')),(encode(rh.h,'hex')),(encode(sh.h,'hex')),
          (encode(d.output_sha256,'hex')),(encode(d.receipt_sha256,'hex'))) x(h) where h is not null));
$fn$;


create or replace function tg_geometry_reads_the_masked_derivative() returns trigger
language plpgsql volatile as $fn$
declare capture_ref uuid; inputs jsonb; needs_mask boolean;
begin
  if new.kind<>'point_map' then return new; end if;
  -- Erasing bytes is not a new geometry operation. Purge must remain possible after expiry.
  if tg_op='UPDATE' and new.content_sha256 is null
    and (new.kind,new.workspace_id,new.source_blob_sha256,new.read_source_sha256,new.privacy_screening_id)
      is not distinct from
        (old.kind,old.workspace_id,old.source_blob_sha256,old.read_source_sha256,old.privacy_screening_id)
    then return new; end if;
  perform privacy_currency_lock(new.workspace_id);
  select c.capture_id into capture_ref from capture c where c.workspace_id=new.workspace_id
    and c.blob_sha256=new.source_blob_sha256 and c.deleted_at is null;
  if capture_ref is null or not privacy_screening_allows_capture(new.workspace_id,capture_ref,new.privacy_screening_id) then
    raise exception 'point-map production requires a current eligible privacy screening' using errcode='integrity_constraint_violation';
  end if;
  if exists(select 1 from blob where blob_sha256=new.source_blob_sha256
    and media_type in ('image/heif','image/heic')) and not exists(
      select 1 from pipeline_event e join pipeline_run er on er.run_id=e.run_id
      where er.workspace_id=new.workspace_id
      and e.event_id=new.produced_by_event
      and decoded_source_current(new.workspace_id,new.source_blob_sha256)=any(e.input_artifact_ids)) then
    raise exception 'point map must bind the current decoded source receipt' using errcode='23514';
  end if;
  inputs:=privacy_inputs_at(new.workspace_id,capture_ref,clock_timestamp());
  select exists(select 1 from jsonb_array_elements(inputs->'regions') r
    where r->>'state' in ('unknown','present','withdrawn')) into needs_mask;
  if coalesce(new.read_source_sha256,new.source_blob_sha256) is distinct from
      source_image_input(new.workspace_id,capture_ref,clock_timestamp()) then
    raise exception 'point map must read the masked derivative or current decoded source: read_source_sha256 disagrees' using errcode='23514';
  end if;
  return new;
end $fn$;

drop trigger tg_geometry_reads_the_masked_derivative on artifact;
create trigger tg_geometry_reads_the_masked_derivative before insert or update of
  kind,workspace_id,source_blob_sha256,read_source_sha256,privacy_screening_id,content_sha256,
  produced_by_event on artifact
for each row execute function tg_geometry_reads_the_masked_derivative();

create or replace function tg_mask_lineage_immutable() returns trigger
language plpgsql as $fn$
begin
  if old.kind in ('masked_source','decoded_source') and (
    (new.kind,new.workspace_id,new.source_blob_sha256,new.stage_key,new.stage_version,
     new.params_digest,new.input_digest,new.idempotency_key,new.read_source_sha256,new.produced_by_event)
    is distinct from
    (old.kind,old.workspace_id,old.source_blob_sha256,old.stage_key,old.stage_version,
     old.params_digest,old.input_digest,old.idempotency_key,old.read_source_sha256,old.produced_by_event)
    or (new.content_sha256 is not null and new.content_sha256 is distinct from old.content_sha256)) then
    raise exception 'masked source lineage is immutable; rebuild instead' using errcode='23514';
  end if;
  return new;
end $fn$;

create or replace function asset_image_source(p_workspace uuid,p_blob bytea,p_at timestamptz,p_original boolean)
returns bytea language plpgsql stable as $fn$
declare c record; inputs jsonb; candidate bytea; chosen bytea; seen boolean:=false;
begin
 if p_workspace is distinct from current_workspace() then return null; end if;
 if not exists(select 1 from blob where blob_sha256=p_blob and purged_at is null
   and storage_key is not null) then return null; end if;
 for c in select capture_id from capture where workspace_id=p_workspace
   and blob_sha256=p_blob and deleted_at is null order by capture_id loop
   seen:=true;
   if not asset_capture_live(p_workspace,c.capture_id,p_at) then return null; end if;
   inputs:=privacy_inputs_at(p_workspace,c.capture_id,p_at);
   if p_original then
     if asset_mask_needed(inputs) then return null; end if;
     candidate:=p_blob;
   else
     candidate:=source_image_input(p_workspace,c.capture_id,p_at);
     if candidate is null then return null; end if;
   end if;
   if chosen is not null and chosen<>candidate then return null; end if;
   chosen:=candidate;
 end loop;
 if not seen then return null; end if;
 return chosen;
end $fn$;

create or replace function asset_point_allows(p_workspace uuid,p_artifact uuid,p_at timestamptz)
returns boolean language plpgsql stable as $fn$
declare a artifact%rowtype; s reconstruction_privacy_screening%rowtype; inputs jsonb; c record;
begin
 if p_workspace is distinct from current_workspace() then return false; end if;
 select * into a from artifact where workspace_id=p_workspace and artifact_id=p_artifact;
 if not found or a.kind<>'point_map' or a.content_sha256 is null or a.purged_at is not null
   or a.needs_repair or a.storage_key is null or a.byte_size is null then return false; end if;
 -- Version 1 masked depth used pre-encode pixels, not the persisted JPEG it named.
 if a.read_source_sha256 is not null and a.stage_version<2 then return false; end if;
 select * into s from reconstruction_privacy_screening where workspace_id=p_workspace
   and screening_id=a.privacy_screening_id and source_sha256=a.source_blob_sha256;
 if not found or not asset_screening_allows(p_workspace,s.capture_id,s.screening_id,p_at)
 then return false; end if;
 if exists(select 1 from blob where blob_sha256=a.source_blob_sha256
   and media_type in ('image/heif','image/heic')) and not exists(
     select 1 from pipeline_event e join pipeline_run er on er.run_id=e.run_id
     where er.workspace_id=a.workspace_id
     and e.event_id=a.produced_by_event
     and decoded_source_current(a.workspace_id,a.source_blob_sha256)=any(e.input_artifact_ids))
 then return false; end if;
 -- Other live identities cannot override a restrictive mapping of the same source.
 for c in select capture_id from capture where workspace_id=p_workspace
   and blob_sha256=a.source_blob_sha256 and deleted_at is null loop
   if not asset_capture_live(p_workspace,c.capture_id,p_at) then return false; end if;
   inputs:=privacy_inputs_at(p_workspace,c.capture_id,p_at);
   if coalesce(a.read_source_sha256,a.source_blob_sha256) is distinct from
     source_image_input(p_workspace,c.capture_id,p_at) then return false; end if;
 end loop;
 return not exists(select 1 from person_derivative_dependency d where d.workspace_id=p_workspace
   and d.target_kind='artifact' and d.target_id=p_artifact
   and asset_tombstone_entity(p_workspace,d.entity_id,p_at));
end $fn$;

commit;
