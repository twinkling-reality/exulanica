-- A reviewed photograph's point map, placed in an authored world by the person whose photograph
-- it is.
--
-- WHAT IS PLACED IS NOT THE ATTACHMENT. Migration 0086 makes a photograph a REFERENCE of a saved
-- world: membership, deliberately not geometry, and the composition resolver refuses to compose it
-- (blocked_reason attachment_is_not_composition). What this table places is the DEPTH ARTIFACT
-- reached through a current membership, which is a different object with a different truth status
-- and a different permission behind it. The attachment is still recorded here, because it is the
-- membership that made the photograph part of this world and a detach must reach what it produced.
--
-- WHAT IT IS, stated once so no reader has to infer it from the columns: an authored placement of
-- a MODEL INFERENCE. Content truth class authored_version, from an authorized_memory source. It is
-- never evidence that anybody was there, never spatial authority (nothing here joins navigation or
-- collision), and never an observation of a surface the camera did not see.
--
-- EVERY PINNED DIGEST IS HERE ON PURPOSE. A placement that stored only ids would be a pointer into
-- rows that move: a new review, a re-screening or a rebind would silently change what a stored
-- world draws. The receipts are what let a reader ask "is what is drawn still what was placed?"
-- and get an answer from the row rather than from a join that has already followed the change.
--
-- Shaped on world_alternate_environment_instance (0050) and its undo column (0088).
begin;
select pg_advisory_xact_lock(119622309);

create table world_alternate_point_map_instance (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  instance_id text not null
    check(instance_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),

  -- The membership this placement was made through, and the photograph it names.
  entry_id uuid not null,
  attachment_id uuid not null,
  capture_id uuid not null,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),

  -- The three receipts that stood when it was placed: the personal authority, the human review
  -- that made the photograph eligible, and the depth right that let the model read it.
  authorization_id uuid not null,
  authorization_evidence_sha256 bytea not null
    check(octet_length(authorization_evidence_sha256)=32),
  screening_id uuid not null,
  screening_receipt_sha256 bytea not null check(octet_length(screening_receipt_sha256)=32),
  right_id uuid not null,
  right_receipt_sha256 bytea not null check(octet_length(right_receipt_sha256)=32),

  -- The model, as the right names it. Repeated from personal_model_right rather than joined,
  -- because an inspector states what produced THIS estimate and a right can be granted again for
  -- a different revision of the same repository.
  model_provider text not null,
  model_role text not null,
  model_identifier text not null,
  model_revision text,
  model_destination text not null,

  -- The artifact, its bytes and what the pipeline said about them. `container` is the OPM version
  -- the renderer must be able to decode; `rung` is what decide_rung recorded, and only a rung 3
  -- map has enough recovered surface to be worth standing in front of.
  artifact_id uuid not null,
  point_map_sha256 bytea not null check(octet_length(point_map_sha256)=32),
  byte_size bigint not null check(byte_size>0),
  container text not null check(container='opm/2'),
  stage_version integer not null check(stage_version>=2),
  rung integer not null check(rung=3),
  -- DECLARED, never validated. Nothing in this system checks the model's metric flag against a
  -- measurement and no island is metric, so this column records what the model SAID and the
  -- interface says "approximate" whatever it says. A column called `metric` with no qualifier
  -- would be read as a claim about the world; this one cannot be.
  declared_metric boolean not null,
  -- Micro-degrees, because the state digest is defined over integers: a float here would make two
  -- identical worlds disagree the first time one was written by a different float formatter.
  declared_fov_y_microdegrees bigint not null
    check(declared_fov_y_microdegrees between 1 and 180000000),

  region_id text not null check(length(region_id) between 1 and 500),
  x_mm bigint not null check(abs(x_mm)<=1000000000),
  y_mm bigint not null check(abs(y_mm)<=1000000000),
  z_mm bigint not null check(abs(z_mm)<=1000000000),
  yaw_microradians bigint not null check(yaw_microradians between 0 and 6283185),
  scale_milli bigint not null check(scale_milli between 1 and 1000000),
  origin_kind text not null check(origin_kind='authored'),
  -- PERSONAL ONLY, which is the one place this table is stricter than 0050. An estimate built
  -- from the account holder's own photograph is not fictional, and letting it be labelled so would
  -- put a reading of somebody's home into the same bucket as an invented prop.
  origin_role text not null check(origin_role='personal'),
  removed boolean not null default false,
  addition_undone boolean not null default false,
  created_edit_id uuid not null,
  last_edit_id uuid not null,
  -- 0088's rule for an undone addition: the row is retained rather than deleted, and a retained
  -- row is always removed and always names the edit that reversed it.
  constraint world_alternate_point_map_undone_addition_is_removed check (
    not addition_undone or (removed and created_edit_id <> last_edit_id)
  ),
  primary key(workspace_id,world_id,version_id,instance_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,entry_id,capture_id,attachment_id)
    references saved_world_source_attachment(workspace_id,entry_id,capture_id,attachment_id),
  foreign key(artifact_id) references artifact(artifact_id),
  foreign key(workspace_id,right_id) references personal_model_right(workspace_id,right_id),
  foreign key(workspace_id,authorization_id)
    references capture_reconstruction_authorization(workspace_id,authorization_id),
  foreign key(workspace_id,screening_id)
    references reconstruction_privacy_screening(workspace_id,screening_id)
);

comment on column world_alternate_point_map_instance.declared_metric is
  'What the depth model said about its own scale. Nothing validates it and no island is metric, '
  'so every interface says approximate.';

-- The binding is a statement about a placement that happened. The transform, the region and the
-- removal flags change; nothing that identifies WHAT is drawn does, because an instance whose
-- source could be swapped is a stored world that can be changed without an edit.
--
-- The one update that is not a move or a removal is a same-id RE-ADD over a retained undone row,
-- which 0088 introduced for the environment kind. It clears `addition_undone`, and it falls
-- through to the insert checks below rather than the immutability check, because re-adding is a
-- new placement and must pass the same current permission this kind demands of a first one. A
-- person who stopped their estimates between the undo and the re-add gets the refusal.
create function tg_world_point_map_binding() returns trigger language plpgsql as $fn$
declare a artifact%rowtype; r personal_model_right%rowtype;
begin
  if tg_op='UPDATE' and not (old.addition_undone and not new.addition_undone) then
    if (to_jsonb(new)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'addition_undone' - 'last_edit_id')
       is distinct from
       (to_jsonb(old)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'scale_milli' - 'removed' - 'addition_undone' - 'last_edit_id')
    then
      raise exception 'point map instance source binding is immutable' using errcode='23514';
    end if;
    return new;
  end if;

  select * into a from artifact
    where workspace_id=new.workspace_id and artifact_id=new.artifact_id;
  if not found or a.kind<>'point_map'
    or a.source_blob_sha256<>new.source_sha256
    or a.content_sha256<>new.point_map_sha256
    or a.byte_size<>new.byte_size
    or a.stage_version<>new.stage_version
    or a.privacy_screening_id<>new.screening_id
  then
    raise exception 'a placed point map names the exact artifact it was resolved from'
      using errcode='23514';
  end if;
  select * into r from personal_model_right
    where workspace_id=new.workspace_id and right_id=new.right_id;
  if not found or r.capture_id<>new.capture_id or r.source_sha256<>new.source_sha256
    or r.model_provider<>new.model_provider or r.model_role<>new.model_role
    or r.model_id<>new.model_identifier
    or r.model_revision is distinct from new.model_revision
    or r.destination<>new.model_destination
    or r.receipt_sha256<>new.right_receipt_sha256
  then
    raise exception 'a placed point map names the exact right that permitted it'
      using errcode='23514';
  end if;
  -- The one condition that is about NOW rather than about agreement between rows: the right must
  -- still stand, and the artifact must still be readable, at the moment the placement is written.
  if not personal_model_right_allows(
    new.workspace_id,new.right_id,new.capture_id,r.model_provider,r.model_role,r.model_id,
    r.model_revision,r.destination,statement_timestamp())
  then
    raise exception 'the depth right for this photograph is no longer current'
      using errcode='23514';
  end if;
  if not asset_point_allows(new.workspace_id,new.artifact_id,statement_timestamp()) then
    raise exception 'this point map is not readable, so it cannot be placed'
      using errcode='23514';
  end if;
  if not exists(select 1 from point_map_model_right b
    where b.workspace_id=new.workspace_id and b.artifact_id=new.artifact_id
      and b.right_id=new.right_id and b.capture_id=new.capture_id) then
    raise exception 'a placed point map is bound to the right it names' using errcode='23514';
  end if;
  return new;
end $fn$;

create trigger tg_world_point_map_binding
before insert or update on world_alternate_point_map_instance
for each row execute function tg_world_point_map_binding();

alter table world_alternate_point_map_instance enable row level security;
alter table world_alternate_point_map_instance force row level security;
create policy ws_isolation on world_alternate_point_map_instance
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

create index world_alternate_point_map_live_idx
  on world_alternate_point_map_instance(workspace_id,world_id,version_id)
  where not removed;

alter table world_alternate_version_edit
  add column point_map_instance_id text;
alter table world_alternate_version_edit
  drop constraint world_alternate_version_edit_kind_check;
alter table world_alternate_version_edit
  add constraint world_alternate_version_edit_kind_check check(
    kind in ('add_object','move_object','remove_object',
             'suppress_element','transform_element',
             'add_environment','move_environment','remove_environment',
             'add_point_map','move_point_map','remove_point_map','undo')
  );
alter table world_alternate_version_edit
  drop constraint world_alternate_edit_names_its_subject;
alter table world_alternate_version_edit
  add constraint world_alternate_edit_names_its_subject check(
    (kind in ('add_object','move_object','remove_object')
      and object_id is not null and element_id is null and environment_instance_id is null
      and point_map_instance_id is null)
    or
    (kind in ('suppress_element','transform_element')
      and element_id is not null and object_id is null and environment_instance_id is null
      and point_map_instance_id is null)
    or
    (kind in ('add_environment','move_environment','remove_environment')
      and environment_instance_id is not null and object_id is null and element_id is null
      and point_map_instance_id is null)
    or
    (kind in ('add_point_map','move_point_map','remove_point_map')
      and point_map_instance_id is not null and object_id is null and element_id is null
      and environment_instance_id is null)
    or kind='undo'
  );

comment on table world_alternate_point_map_instance is
  'A depth estimate from one reviewed photograph, placed in an authored version by its owner. '
  'An authored placement of a model inference: not evidence of a visit, not spatial authority, '
  'and not an observation of anything the camera did not see.';

commit;
