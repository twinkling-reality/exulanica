-- Current permission is distinct from an immutable historical review.
begin;
select pg_advisory_xact_lock(119622309);

-- All participants take this lock before fetching their evaluation snapshot. Serializing at
-- workspace level also covers consent shared by subjects in several captures. READ COMMITTED
-- is required: a transaction snapshot predating a waited-for edit must never authorize work.
create function privacy_currency_lock(p_workspace uuid) returns void
language plpgsql volatile as $fn$
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'privacy currency requires read committed isolation' using errcode='40001';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('privacy-currency:' || p_workspace::text, 0));
end $fn$;

create function tg_privacy_currency_lock() returns trigger
language plpgsql volatile as $fn$
begin
  perform privacy_currency_lock(new.workspace_id);
  if tg_table_name='person_presentation_consent' then
    -- Allocation occurs before INSERT in existing writers. NULL scope keys do not conflict
    -- under the old unique constraint, so explicitly refuse the losing allocation after lock.
    if exists(select 1 from person_presentation_consent c where c.workspace_id=new.workspace_id
      and c.subject_id=new.subject_id and c.consent_scope=new.consent_scope
      and c.region_key is not distinct from new.region_key and c.sequence=new.sequence
      and c.consent_id<>new.consent_id) then
      raise exception 'consent sequence was concurrently allocated; retry the decision'
        using errcode='40001';
    end if;
  end if;
  return new;
end $fn$;
create trigger aa_privacy_currency_lock before insert on person_region
for each row execute function tg_privacy_currency_lock();
create trigger aa_privacy_currency_lock before insert on person_presentation_consent
for each row execute function tg_privacy_currency_lock();
create trigger aa_privacy_currency_lock before insert on reconstruction_privacy_screening
for each row execute function tg_privacy_currency_lock();

-- An explicit instant is shared by every scope and region in the snapshot. Keep the established
-- region-specific then sequence precedence. An expired grant cannot stand in for active consent.
create function privacy_consent_at(
  p_workspace uuid, p_subject uuid, p_region bytea, p_scope text, p_at timestamptz)
returns boolean language plpgsql volatile as $fn$
declare decisions boolean[];
begin
  select array_agg(granted) into decisions from (
    select c.decision='granted' as granted,
      dense_rank() over(order by (c.region_key is not null) desc,c.sequence desc) as priority
    from person_presentation_consent c
    where c.workspace_id=p_workspace and c.subject_id=p_subject and c.consent_scope=p_scope
      and (c.region_key is null or c.region_key=p_region)
      and c.effective_at<=p_at and (c.valid_until is null or c.valid_until>p_at)
  ) ranked where priority=1;
  if cardinality(decisions)>1 then
    raise exception 'ambiguous legacy consent sequence; append a resolving decision'
      using errcode='40001';
  end if;
  return coalesce(decisions[1],false);
end $fn$;

create function privacy_inputs_at(p_workspace uuid, p_capture uuid, p_at timestamptz)
returns jsonb language sql volatile as $fn$
  select jsonb_build_object('profile','exulanica.privacy-inputs/v1',
    'workspace_id',p_workspace,'capture_id',p_capture,'source_sha256',encode(c.blob_sha256,'hex'),
    'inventory',coalesce((select jsonb_agg(encode(r.region_digest,'hex') order by r.region_key)
      from person_region_current r where r.workspace_id=p_workspace and r.capture_id=p_capture),'[]'::jsonb),
    'regions',coalesce((select jsonb_agg(jsonb_build_object(
      'region_key',encode(r.region_key,'hex'),'silhouette',r.silhouette,'subject_id',r.subject_id,
      'state',case when person_subject_is_withdrawn(p_workspace,r.subject_id) then 'withdrawn'
        when privacy_consent_at(p_workspace,r.subject_id,r.region_key,'likeness',p_at) then
          case when privacy_consent_at(p_workspace,r.subject_id,r.region_key,'temporary_hide',p_at)
            then 'hidden' else 'shown' end
        when privacy_consent_at(p_workspace,r.subject_id,r.region_key,'presence',p_at) then 'present'
        else 'unknown' end,
      'name_permitted',not person_subject_is_withdrawn(p_workspace,r.subject_id)
        and privacy_consent_at(p_workspace,r.subject_id,r.region_key,'naming',p_at),
      'consents',coalesce((select jsonb_agg(encode(pc.consent_digest,'hex') order by pc.consent_digest)
        from person_presentation_consent pc where pc.workspace_id=p_workspace
        and pc.subject_id=r.subject_id and (pc.region_key is null or pc.region_key=r.region_key)
        and (pc.decision='withdrawn' or (pc.effective_at<=p_at
          and (pc.valid_until is null or pc.valid_until>p_at)))),'[]'::jsonb)
      ) order by r.region_key) from person_region_current r
      where r.workspace_id=p_workspace and r.capture_id=p_capture and r.action<>'deleted'),'[]'::jsonb))
    from capture c where c.workspace_id=p_workspace and c.capture_id=p_capture
      and p_workspace=current_workspace() and c.deleted_at is null;
$fn$;

create function current_privacy_inputs(p_workspace uuid,p_capture uuid)
returns jsonb language plpgsql volatile as $fn$
begin
  perform privacy_currency_lock(p_workspace);
  return privacy_inputs_at(p_workspace,p_capture,clock_timestamp());
end $fn$;

-- Canonical encoding for the existing mask digests: keys in C order, integral JSON values,
-- no insignificant whitespace. This does not canonicalize arbitrary receipt text or floats.
create function privacy_canonical(p_value jsonb) returns text
language plpgsql immutable strict as $fn$
declare result text;
begin
  case jsonb_typeof(p_value)
    when 'object' then
      select '{'||coalesce(string_agg(to_jsonb(key)::text||':'||privacy_canonical(value),','
        order by key collate "C"),'')||'}' into result from jsonb_each(p_value);
    when 'array' then
      select '['||coalesce(string_agg(privacy_canonical(value),',' order by n),'')||']'
        into result from jsonb_array_elements(p_value) with ordinality e(value,n);
    when 'number' then
      if p_value::text !~ '^-?[0-9]+$' then
        raise exception 'privacy digest inputs must be integral';
      end if;
      result:=p_value::text;
    else result:=p_value::text;
  end case;
  return result;
end $fn$;

create function privacy_mask_matches(p_workspace uuid,p_capture uuid,p_artifact uuid,p_inputs jsonb)
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
      and m.input_digest=(select digest(convert_to(privacy_canonical(jsonb_agg(h order by h)),'UTF8'),'sha256')
        from (values(encode(i.content_sha256,'hex')),(encode(rh.h,'hex')),(encode(sh.h,'hex'))) x(h)));
$fn$;

create function current_privacy_mask(p_workspace uuid,p_capture uuid,p_artifact uuid default null)
returns boolean language plpgsql volatile as $fn$
declare inputs jsonb;
begin
  inputs:=current_privacy_inputs(p_workspace,p_capture);
  if inputs is null then return false; end if;
  if p_artifact is not null then
    return privacy_mask_matches(p_workspace,p_capture,p_artifact,inputs);
  end if;
  if not exists(select 1 from jsonb_array_elements(inputs->'regions') r
    where r->>'state' in ('unknown','present','withdrawn')) then return true; end if;
  return exists(select 1 from artifact m where m.workspace_id=p_workspace and m.kind='masked_source'
    and m.source_blob_sha256=decode(inputs->>'source_sha256','hex')
    and privacy_mask_matches(p_workspace,p_capture,m.artifact_id,inputs));
end $fn$;

create or replace function privacy_screening_allows_capture(p_workspace uuid,p_capture uuid,p_screening uuid)
returns boolean language plpgsql volatile as $fn$
declare inputs jsonb; at_time timestamptz;
begin
  perform privacy_currency_lock(p_workspace);
  at_time:=clock_timestamp();
  inputs:=privacy_inputs_at(p_workspace,p_capture,at_time);
  if inputs is null then return false; end if;
  return exists(select 1 from reconstruction_privacy_screening s
    join capture_reconstruction_authorization a on a.workspace_id=s.workspace_id and a.authorization_id=s.authorization_id
    join capture c on c.workspace_id=s.workspace_id and c.capture_id=s.capture_id
    where s.workspace_id=p_workspace and s.capture_id=p_capture and s.screening_id=p_screening
      and s.source_sha256=c.blob_sha256 and a.capture_id=s.capture_id and a.source_sha256=s.source_sha256
      and a.authorization_scope=s.authorization_scope and s.eligibility_state='eligible'
      and s.screening_method in ('human_review','synthetic_exemption')
      and s.policy_version=current_privacy_policy()
      and (s.valid_until is null or s.valid_until>at_time) and (a.valid_until is null or a.valid_until>at_time)
      and not tombstone_blocks_capture(p_workspace,p_capture)
      and s.receipt_record->'privacy_inputs'=inputs
      and not exists(select 1 from jsonb_array_elements(inputs->'regions') r where r->>'state'='withdrawn')
      and (s.screening_method<>'synthetic_exemption' or jsonb_array_length(inputs->'regions')=0)
      and (s.screening_method<>'human_review' or (
        jsonb_array_length(s.sensitive_regions)=jsonb_array_length(inputs->'regions')
        and not exists(select 1 from jsonb_array_elements(inputs->'regions') r
          where not exists(select 1 from jsonb_array_elements(s.sensitive_regions) sr
            where sr->>'region_key'=r->>'region_key' and sr->>'state'=r->>'state'
              and sr ?& array['silhouette','subject_id','name_permitted']
              and sr->'silhouette'=r->'silhouette' and sr->'subject_id'=r->'subject_id'
              and sr->'name_permitted'=r->'name_permitted'))))
      and (not exists(select 1 from jsonb_array_elements(inputs->'regions') r
          where r->>'state' in ('unknown','present','withdrawn'))
        or exists(select 1 from artifact m where m.workspace_id=p_workspace and m.kind='masked_source'
          and m.source_blob_sha256=c.blob_sha256
          and privacy_mask_matches(p_workspace,p_capture,m.artifact_id,inputs)
          and s.mask_artifacts=s.receipt_record->'mask_artifacts'
          and s.mask_artifacts @> jsonb_build_array(jsonb_build_object(
            'artifact_id',m.artifact_id,'content_sha256',encode(m.content_sha256,'hex'))))));
end $fn$;

-- A historical receipt may still be stored. Never invent a current binding for it on INSERT.
-- Observation retains its purpose-specific detection route; eligible geometry receipts use
-- the corrected shared predicate, so a stale review cannot silently become observation authority.
create or replace function privacy_screening_allows_observation(p_workspace uuid,p_capture uuid,p_screening uuid)
returns boolean language sql volatile as $fn$
  select privacy_screening_allows_capture(p_workspace,p_capture,p_screening) or exists(
    select 1 from reconstruction_privacy_screening s
    join capture_reconstruction_authorization a on a.workspace_id=s.workspace_id and a.authorization_id=s.authorization_id
    join capture c on c.workspace_id=s.workspace_id and c.capture_id=s.capture_id
    where s.workspace_id=p_workspace and p_workspace=current_workspace() and s.capture_id=p_capture
      and s.screening_id=p_screening and s.screening_method='person_detection_only'
      and s.source_sha256=c.blob_sha256 and a.capture_id=s.capture_id and a.source_sha256=s.source_sha256
      and s.authorization_scope=a.authorization_scope and s.policy_version=current_privacy_policy()
      and (s.valid_until is null or s.valid_until>clock_timestamp())
      and (a.valid_until is null or a.valid_until>clock_timestamp())
      and c.deleted_at is null and not tombstone_blocks_capture(p_workspace,p_capture));
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
  inputs:=privacy_inputs_at(new.workspace_id,capture_ref,clock_timestamp());
  select exists(select 1 from jsonb_array_elements(inputs->'regions') r
    where r->>'state' in ('unknown','present','withdrawn')) into needs_mask;
  if (needs_mask or new.read_source_sha256 is not null) and not exists(
    select 1 from artifact m where m.workspace_id=new.workspace_id
      and m.content_sha256=new.read_source_sha256
      and privacy_mask_matches(new.workspace_id,capture_ref,m.artifact_id,inputs)) then
    raise exception 'point map must read the masked derivative: name a current masked source in read_source_sha256' using errcode='23514';
  end if;
  return new;
end $fn$;
drop trigger tg_geometry_reads_the_masked_derivative on artifact;
create trigger tg_geometry_reads_the_masked_derivative before insert or update of
  kind,workspace_id,source_blob_sha256,read_source_sha256,privacy_screening_id,content_sha256 on artifact
for each row execute function tg_geometry_reads_the_masked_derivative();
-- Never relabel an already-produced mask with inputs it did not use. Purge may clear bytes.
create function tg_mask_lineage_immutable() returns trigger
language plpgsql as $fn$
begin
  if old.kind='masked_source' and (
    (new.kind,new.workspace_id,new.source_blob_sha256,new.stage_key,new.stage_version,
     new.params_digest,new.input_digest,new.idempotency_key)
    is distinct from
    (old.kind,old.workspace_id,old.source_blob_sha256,old.stage_key,old.stage_version,
     old.params_digest,old.input_digest,old.idempotency_key)
    or (new.content_sha256 is not null and new.content_sha256 is distinct from old.content_sha256)) then
    raise exception 'masked source lineage is immutable; rebuild instead' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_mask_lineage_immutable before update on artifact
for each row execute function tg_mask_lineage_immutable();
commit;
