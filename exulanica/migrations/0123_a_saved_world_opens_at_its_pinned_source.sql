-- A successful scene build keeps its own claim while a later build becomes the scene's current
-- claim. The functional reconstruction_scene_rung_is predicate still says which build answers the
-- ordinary graph. This nonfunctional predicate is for a saved world's pinned arrival source only:
-- its reader checks the exact job, gate, receipts and current authorization on every read.
begin;
select pg_advisory_xact_lock(119622309);

insert into predicate (key,value_schema,functional,allows_kind,writes_a_name) values
 ('reconstruction_scene_build_rung_is',
  '{"type":"object","required":["rung","reasons","member_count","registered_member_count","gate_digest","job_id"],"properties":{"rung":{"type":"integer","minimum":1,"maximum":4},"reasons":{"type":"array"},"member_count":{"type":"integer","minimum":1},"registered_member_count":{"type":"integer","minimum":0},"gate_digest":{"type":"string"},"job_id":{"type":"string"}}}',
  false,'{inference}',false);

-- Existing v4 societies do not exist. The only old job that a newly created v4 society may pin
-- is the currently active succeeded one. Superseded and retracted claims are never revived.
insert into assertion (workspace_id,kind,predicate_id,subject_ref,object_value,
  support_span_ids,produced_by_run,status,emit_key)
select a.workspace_id,'inference',p.predicate_id,
  jsonb_build_object('type','scene','id',s.scene_id::text,'job_id',j.job_id::text),
  a.object_value || jsonb_build_object('job_id',j.job_id::text),
  a.support_span_ids,a.produced_by_run,'active',
  'scene-build-rung:' || j.job_id::text || ':' || (a.object_value->>'gate_digest')
from reconstruction_scene s
join reconstruction_scene_job j on j.workspace_id=s.workspace_id
  and j.scene_id=s.scene_id and j.job_id=s.current_job_id and j.status='succeeded'
join assertion a on a.workspace_id=j.workspace_id
  and a.assertion_id=j.rung_assertion_id and a.status='active'
join predicate old on old.predicate_id=a.predicate_id
  and old.key='reconstruction_scene_rung_is'
join predicate p on p.key='reconstruction_scene_build_rung_is'
where not tombstone_blocks_scene(s.workspace_id,s.scene_id)
  and a.object_value->>'gate_digest' is not null
on conflict (workspace_id,emit_key) do nothing;

-- A build's claim depends on every member of that immutable job. The original scene-rung
-- withdrawal trigger remains unchanged for the scene's current claim. This trigger reaches an
-- unregistered input too, even though the rung's evidence support cites registered members only.
create function retract_scene_build_rungs_for_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope not in ('capture','interval','workspace') then return new; end if;
  insert into retraction (workspace_id,assertion_id,retracted_by,reason,retracted_at)
  select a.workspace_id,a.assertion_id,new.requested_by,
    'scene build membership withdrawn by tombstone ' || new.tombstone_id::text,new.effective_at
  from assertion a
  join predicate p on p.predicate_id=a.predicate_id
    and p.key='reconstruction_scene_build_rung_is'
  join reconstruction_scene_job j on j.workspace_id=a.workspace_id
    and j.job_id=(a.subject_ref->>'job_id')::uuid
    and j.scene_id=(a.subject_ref->>'id')::uuid
  where a.workspace_id=new.workspace_id and a.status='active'
    and (new.scope='workspace' or exists (
      select 1 from reconstruction_scene_job_member m
      where m.workspace_id=j.workspace_id and m.job_id=j.job_id
        and m.capture_id=new.capture_id));
  update assertion a set status='retracted'
  from predicate p,reconstruction_scene_job j
  where p.predicate_id=a.predicate_id and p.key='reconstruction_scene_build_rung_is'
    and j.workspace_id=a.workspace_id
    and j.job_id=(a.subject_ref->>'job_id')::uuid
    and j.scene_id=(a.subject_ref->>'id')::uuid
    and a.workspace_id=new.workspace_id and a.status='active'
    and (new.scope='workspace' or exists (
      select 1 from reconstruction_scene_job_member m
      where m.workspace_id=j.workspace_id and m.job_id=j.job_id
        and m.capture_id=new.capture_id));
  return new;
end $fn$;
create trigger tg_tombstone_retracts_scene_build_rungs after insert on tombstone
for each row execute function retract_scene_build_rungs_for_tombstone();

-- New made-world societies carry a region-local pose and an immutable source pin. Stored v3
-- inputs remain valid with no arrival field, and their successor policy stays v3 in the runtime.
alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3',
     'exulanica.society-input/authored-ground-v4',
     'exulanica.society-input/walking-surfaces-v1',
     'exulanica.society-input/walking-surfaces-v2')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)) is true
    else not (document ? 'unread_placements') end
  );

alter table world_society_input drop constraint world_society_input_routine_check;
alter table world_society_input add constraint world_society_input_routine_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

alter table world_society_input add constraint world_society_input_arrival_check
  check (
    case when document->>'profile'='exulanica.society-input/authored-ground-v4'
      then (jsonb_typeof(document->'arrival')='object'
        and document->'arrival'->>'profile'='exulanica.arrival-descriptor/v1'
        and document->'arrival'->>'presentation_policy'='exulanica.arrival-presentation/v1'
        and document->'arrival'->>'region_id' is not null
        and jsonb_typeof(document->'arrival'->'position_local_mm')='array'
        and jsonb_array_length(document->'arrival'->'position_local_mm')=3
        and jsonb_typeof(document->'arrival'->'forward_local_millionths')='array'
        and jsonb_array_length(document->'arrival'->'forward_local_millionths')=3
        and jsonb_typeof(document->'arrival'->'source')='object'
        and document->'arrival'->'source'->>'world_id'=document->>'world_id'
        and document->'arrival'->'source'->>'version_id'=document->>'version_id') is true
    else not (document ? 'arrival') end
  );

commit;
