-- Delivery authorization is distinct from geometry admission and historical review.
begin;
select pg_advisory_xact_lock(119622309);

-- Readers never acquire training/privacy/purge locks. Mutations take a shared global
-- barrier without waiting: even a caller already holding any other lock cannot form a
-- cycle with a reader. A conflicting mutation aborts with retryable 40001. This coarse
-- barrier includes global registry edits and old/new workspace moves without RLS scans.
create function asset_read_lock() returns void language plpgsql volatile as $fn$
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'final asset reads require read committed' using errcode='40001';
  end if;
  perform pg_advisory_xact_lock(119622341);
end $fn$;
create function tg_asset_read_mutation() returns trigger language plpgsql as $fn$
begin
  if not pg_try_advisory_xact_lock_shared(119622341) then
    raise exception 'asset delivery in progress; retry mutation' using errcode='40001';
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end $fn$;
do $$ declare t text; begin
  foreach t in array array[
    'tombstone','capture','blob','evidence_span','media_track','person_region',
    'person_presentation_consent','person_subject','occurrence','entity_link','entity',
    'person_derivative_dependency','assertion','artifact','stage_registry','stage_definition',
    'capture_reconstruction_authorization','reconstruction_privacy_screening',
    'reconstruction_scene','reconstruction_scene_member','reconstruction_scene_job',
    'reconstruction_scene_job_member','place','place_version','place_alignment'] loop
    execute format('create trigger aaa_asset_read_mutation before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()',t);
  end loop;
end $$;

-- Training export acquires training-source before asking admission. The old reverse
-- order deadlocked an actual consent INSERT against export (retained 40P01 baseline).
-- All callers of the shared privacy helper now acquire in the same order, including
-- reads that precede a later INSERT in the caller's transaction.
create or replace function privacy_currency_lock(p_workspace uuid) returns void
language plpgsql volatile as $fn$
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'privacy currency requires read committed isolation' using errcode='40001';
  end if;
  perform pg_advisory_xact_lock_shared(
    hashtextextended('training-source:' || p_workspace::text, 0));
  perform pg_advisory_xact_lock(hashtextextended('privacy-currency:' || p_workspace::text, 0));
end $fn$;

create function asset_tombstone_span(
  p_workspace uuid,
  p_blob      bytea,
  p_track     text,
  p_start_ns  bigint,
  p_end_ns    bigint, p_at timestamptz
) returns boolean
language sql stable as $fn$
  select exists (
    select 1
      from tombstone t
      left join capture c on c.capture_id = t.capture_id
     where t.workspace_id = p_workspace
       and t.effective_at <= p_at
       and (
             t.scope = 'workspace'
          or (t.blocklist_hash and c.blob_sha256 = p_blob)
          or (t.scope = 'capture'
              and c.blob_sha256 = p_blob
              and not exists (
                    select 1 from capture live
                     where live.workspace_id = p_workspace
                       and live.blob_sha256  = p_blob
                       and live.deleted_at is null))
          or (t.scope = 'interval'
              and c.blob_sha256 = p_blob
              and t.track_key   = p_track
              and t.interval_ns && int8multirange(int8range(p_start_ns, p_end_ns, '[)')))
       )
  );
$fn$;

create function asset_tombstone_capture(p_workspace uuid, p_capture uuid, p_at timestamptz)
returns boolean
language sql stable as $fn$
  select exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.effective_at <= p_at
       and (t.scope = 'workspace' or (t.scope in ('capture','interval')
                                      and t.capture_id = p_capture))
  );
$fn$;

create function asset_tombstone_entity(p_workspace uuid, p_entity uuid, p_at timestamptz)
returns boolean
language sql stable as $fn$
  select exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.effective_at <= p_at
       and (t.scope = 'workspace' or (t.scope = 'entity' and t.entity_id = p_entity))
  );
$fn$;

create function asset_capture_live(p_workspace uuid,p_capture uuid,p_at timestamptz)
returns boolean language sql stable as $fn$
 select p_workspace=current_workspace() and exists(select 1 from capture c
 where c.workspace_id=p_workspace and c.capture_id=p_capture and c.deleted_at is null
 and not asset_tombstone_capture(p_workspace,p_capture,p_at)
 and not exists(select 1 from occurrence o join entity_link l
 on l.workspace_id=o.workspace_id and l.occurrence_id=o.occurrence_id and l.state='confirmed'
 where o.workspace_id=p_workspace and o.capture_id=p_capture
 and asset_tombstone_entity(p_workspace,l.entity_id,p_at))
 and not exists(select 1 from person_region_current r where r.workspace_id=p_workspace
 and r.capture_id=p_capture and r.action<>'deleted'
 and person_subject_is_withdrawn(p_workspace,r.subject_id)));
$fn$;
create function asset_mask_needed(p_inputs jsonb) returns boolean language sql immutable as $fn$
 select p_inputs is null or exists(select 1 from jsonb_array_elements(p_inputs->'regions') r
 where r->>'state' in ('unknown','present','withdrawn'));
$fn$;
-- One source digest can have several capture identities. Every live mapping must agree;
-- an absent mapping for an image does not establish permission.
create function asset_image_source(p_workspace uuid,p_blob bytea,p_at timestamptz,p_original boolean)
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
   candidate:=p_blob;
   if asset_mask_needed(inputs) then
     if p_original then return null; end if;
     select m.content_sha256 into candidate from artifact m
       where m.workspace_id=p_workspace and m.source_blob_sha256=p_blob
       and privacy_mask_matches(p_workspace,c.capture_id,m.artifact_id,inputs)
       order by m.artifact_id limit 1;
     if candidate is null then return null; end if;
   end if;
   if chosen is not null and chosen<>candidate then return null; end if;
   chosen:=candidate;
 end loop;
 if not seen then return null; end if;
 return chosen;
end $fn$;
create function asset_screening_allows(p_workspace uuid,p_capture uuid,p_screening uuid,p_at timestamptz)
returns boolean language plpgsql stable as $fn$
declare inputs jsonb; at_time timestamptz;
begin
  at_time:=p_at;
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
      and asset_capture_live(p_workspace,p_capture,p_at)
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
create function asset_artifact_live(p_workspace uuid,p_artifact uuid,p_at timestamptz)
returns boolean language sql stable as $fn$
 select p_workspace=current_workspace() and exists(select 1 from artifact a
 where a.workspace_id=p_workspace and a.artifact_id=p_artifact and a.purged_at is null
 and not a.needs_repair and a.content_sha256 is not null and a.storage_key is not null
 and a.byte_size is not null
 and not exists(select 1 from person_derivative_dependency d where d.workspace_id=p_workspace
   and d.target_kind='artifact' and d.target_id=p_artifact
   and asset_tombstone_entity(p_workspace,d.entity_id,p_at)));
$fn$;
create function asset_point_allows(p_workspace uuid,p_artifact uuid,p_at timestamptz)
returns boolean language plpgsql stable as $fn$
declare a artifact%rowtype; s reconstruction_privacy_screening%rowtype; inputs jsonb; c record;
begin
 if p_workspace is distinct from current_workspace() then return false; end if;
 select * into a from artifact where workspace_id=p_workspace and artifact_id=p_artifact;
 if not found or a.kind<>'point_map' or a.content_sha256 is null or a.purged_at is not null
   or a.needs_repair or a.storage_key is null or a.byte_size is null then return false; end if;
 select * into s from reconstruction_privacy_screening where workspace_id=p_workspace
   and screening_id=a.privacy_screening_id and source_sha256=a.source_blob_sha256;
 if not found or not asset_screening_allows(p_workspace,s.capture_id,s.screening_id,p_at)
 then return false; end if;
 -- Other live identities cannot override a restrictive mapping of the same source.
 for c in select capture_id from capture where workspace_id=p_workspace
   and blob_sha256=a.source_blob_sha256 and deleted_at is null loop
   if not asset_capture_live(p_workspace,c.capture_id,p_at) then return false; end if;
   inputs:=privacy_inputs_at(p_workspace,c.capture_id,p_at);
   if a.read_source_sha256 is not null then
     if not exists(select 1 from artifact m where m.workspace_id=p_workspace
       and m.content_sha256=a.read_source_sha256
       and privacy_mask_matches(p_workspace,c.capture_id,m.artifact_id,inputs)) then return false; end if;
   elsif asset_mask_needed(inputs) then return false;
   end if;
 end loop;
 return not exists(select 1 from person_derivative_dependency d where d.workspace_id=p_workspace
   and d.target_kind='artifact' and d.target_id=p_artifact
   and asset_tombstone_entity(p_workspace,d.entity_id,p_at));
end $fn$;
commit;
