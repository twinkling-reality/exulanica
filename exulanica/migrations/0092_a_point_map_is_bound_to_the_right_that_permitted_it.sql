-- A point map is bound to the depth right that permitted it, and stops being readable when that
-- right ends.
--
-- Migration 0073 answers WHICH MODEL MAY RECEIVE A PERSON'S OWN PHOTOGRAPH, rechecked at the
-- instant of every read, and that is enough while the act is transient. Depth is not transient.
-- A point map IS a three-dimensional reading of the room the photograph was taken in, and it
-- persists after the right that produced it is withdrawn. Before this migration, withdrawing the
-- depth right stopped the NEXT inference and left every existing map servable: the person read
-- "stopped" and their living room stayed in the world. docs/privacy-consent-threat-model.md
-- section 4.4 requires a revocation to act on every read path immediately, and this is that.
--
-- Shaped on scene_training_artifact (0080), which answers the same question for trained weights.
-- Each DIFFERENCE is justified where it appears; everything unremarked is 0080's decision kept.
--
-- WHAT THIS DOES NOT DO, said plainly rather than left to be found: it does not purge. Making the
-- bytes unreadable everywhere and destroying them are two pieces of work, and 0082 does the second
-- for training weights through the tombstone and purge-queue invariants of 0013 and 0015. The
-- binding table here is what that work will read. A correct half, named, beats a plausible whole.
begin;
select pg_advisory_xact_lock(119622309);

-- ONE ROW PER (ARTIFACT, PHOTOGRAPH). A point map is built from exactly one photograph, so this
-- table will hold one row per artifact in practice; the composite key is 0080's and is kept
-- because it costs nothing and does not assume the one-photograph case will stay true.
create table point_map_model_right (
  workspace_id uuid not null,
  artifact_id uuid not null,
  capture_id uuid not null,
  -- NAMES A personal_model_right, not a right of its own, which is the difference from 0080.
  -- Training needed a separate right because a trainer produces an artefact rather than an answer
  -- and 0073's model identity protected nothing after the run. Depth is both: the model gives an
  -- answer back AND that answer is stored. The identity 0073 records is exactly the identity this
  -- binding needs, so a second right would be a second thing to withdraw for one decision.
  right_id uuid not null,
  bound_at timestamptz not null,
  primary key(workspace_id,artifact_id,capture_id),
  foreign key(artifact_id) references artifact(artifact_id),
  foreign key(workspace_id,capture_id) references capture(workspace_id,capture_id),
  foreign key(workspace_id,right_id) references personal_model_right(workspace_id,right_id)
);
create index point_map_model_right_right_idx on point_map_model_right(workspace_id,right_id);
alter table point_map_model_right enable row level security;
alter table point_map_model_right force row level security;
create policy ws_isolation on point_map_model_right
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- A binding is a fact about a publication that already happened. Never rewritten, never deleted:
-- a binding that can be removed is a point map that can be quietly orphaned from its right.
create trigger tg_point_map_model_right_append_only
before update or delete on point_map_model_right
for each row execute function tg_reconstruction_privacy_append_only();

-- A WITHDRAWAL DURING INFERENCE CANCELS THE PUBLICATION. The depth stage resolves the right, hands
-- the pixels over, and publishes what comes back; on this machine that is seconds, and on a larger
-- photograph it is longer. A person who stops the estimate inside that window has stopped it, and
-- the map the model was already computing must not land. The binding is written inside the
-- publication transaction, so refusing it here rolls the artifact back with it.
create function tg_point_map_model_right_binds() returns trigger language plpgsql as $fn$
declare r personal_model_right%rowtype; a artifact%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into r from personal_model_right
    where workspace_id=new.workspace_id and right_id=new.right_id;
  if not found or r.capture_id<>new.capture_id then
    raise exception 'a point map is bound to a right over the same photograph'
      using errcode='23514';
  end if;
  select * into a from artifact
    where workspace_id=new.workspace_id and artifact_id=new.artifact_id;
  if not found or a.kind<>'point_map' then
    raise exception 'only a point map is bound to a depth right' using errcode='23514';
  end if;
  if a.source_blob_sha256<>r.source_sha256 then
    raise exception 'a point map is bound to a right over the exact bytes it was built from'
      using errcode='23514';
  end if;
  if new.bound_at>clock_timestamp() then
    raise exception 'a binding is recorded now or earlier' using errcode='23514';
  end if;
  if not personal_model_right_allows(
    new.workspace_id,new.right_id,new.capture_id,r.model_provider,r.model_role,r.model_id,
    r.model_revision,r.destination,clock_timestamp())
  then
    raise exception 'this point map may not be published: the depth right that permitted it is no longer current'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_point_map_model_right_binds
before insert on point_map_model_right
for each row execute function tg_point_map_model_right_binds();

-- WITHDRAWN, and not "unbound", which is the distinction that decides what happens to every point
-- map published before this migration. This predicate is true only of an artifact that HAS a
-- binding whose right has ended, expired or lapsed. A map with no binding answers false and is
-- unaffected: nothing here invents a right for a photograph processed before rights existed, and
-- nothing here withdraws one either. The same shape as scene_training_artifact_withdrawn.
create function point_map_model_right_withdrawn(
  p_workspace uuid,p_artifact uuid,p_at timestamptz)
returns boolean language sql stable as $fn$
  select coalesce(p_workspace=current_workspace(),false) and exists(
    select 1 from point_map_model_right b
    join personal_model_right r on r.workspace_id=b.workspace_id and r.right_id=b.right_id
    where b.workspace_id=p_workspace and b.artifact_id=p_artifact
      and not personal_model_right_allows(
        p_workspace,b.right_id,b.capture_id,r.model_provider,r.model_role,r.model_id,
        r.model_revision,r.destination,p_at));
$fn$;

-- Every right a point map was built under, with whether it still stands: the question an interface
-- explaining why an estimate stopped being drawn has to be able to ask from a record.
create function point_map_model_right_sources(p_workspace uuid,p_artifact uuid)
returns table(capture_id uuid,right_id uuid,model_id text,model_revision text,destination text,
  withdrawn_at timestamptz,valid_until timestamptz,current boolean)
language sql stable as $fn$
  select b.capture_id,b.right_id,r.model_id,r.model_revision,r.destination,r.withdrawn_at,
    r.valid_until,
    personal_model_right_allows(p_workspace,b.right_id,b.capture_id,r.model_provider,r.model_role,
      r.model_id,r.model_revision,r.destination,clock_timestamp())
  from point_map_model_right b
  join personal_model_right r on r.workspace_id=b.workspace_id and r.right_id=b.right_id
  where b.workspace_id=p_workspace and b.artifact_id=p_artifact
  order by b.capture_id;
$fn$;

-- The clause. asset_point_allows is the one gate every point-map read passes: the geometry route,
-- the graph, scene selection and the composition resolver all ask it, so adding the term here is
-- what makes "stops being shown" true everywhere at once rather than in the places somebody
-- remembered. It is restated in full from migration 0045 because that is how this function has
-- always been changed; the only new lines are the two named below.
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
 -- NEW: the depth right that permitted this estimate must still stand.
 if point_map_model_right_withdrawn(p_workspace,p_artifact,p_at) then return false; end if;
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

comment on table point_map_model_right is
  'Which depth right permitted each stored point map. Append-only, written inside the depth '
  'stage''s publication transaction. asset_point_allows refuses a bound artifact whose right has '
  'ended; a map with no binding is unaffected.';

commit;
