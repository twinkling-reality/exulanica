-- 0038_a_place_is_more_than_one_capture.sql
-- The durable plane a place lives on: one identity, an ordered series of scenes, one shared frame.
--
-- Every reconstruction in this system is a scene, and a scene is one set of photographs taken on
-- one occasion. Photograph a place today and again in a month and the system holds two scenes that
-- share a subject and share nothing else: two unrelated coordinate frames, two sets of regions, and
-- no query that can ask what changed. `docs/place-identity.md` is the design; this migration is the
-- schema half of it, and its "What a place is in the schema" section carries the reasoning for
-- every choice below, including the two alternatives this rejected.
--
-- The word `place` is already spent twice in this schema and neither meaning is disturbed here.
-- `occurrence_class` has carried `'place'` since 0001 and means a place OBSERVED IN ONE PHOTOGRAPH,
-- which the vision stage still emits and a user may still name into an `entity`. That is a place a
-- person named. A `place` row is a place the GEOMETRY established, admitted by a joint
-- reconstruction over two capture sets and never by a label. Neither creates the other, and the
-- test named for that failure is what keeps the sentence true.
--
-- `region` is also untouched: a region stays the world's spatial authority and decides what is
-- drawn, while a place only says which scenes belong together and how their frames relate. No
-- column here is called `region_id` or `region_key`, because three unrelated existing things
-- already answer to those names.
--
-- What this migration deliberately does NOT do. It records no transform. The similarity between a
-- scene's own recovered frame and its place's frame is a measured number with held-out residuals
-- behind it, and this repository keeps measured numbers in digest-bound artifacts rather than in
-- columns nothing recomputes, exactly as `point_map_placement` already does. A `place_version`
-- names the artifact that measured it. It also adds no way to name a place: naming is the identity
-- plane's job, it already has a guard requiring an active user assertion, and a second naming path
-- here would be a second answer to one question. It also adds no place tombstone scope, because
-- `tombstone_scope` is an enum and a place's liveness is derivable from its anchor's, which
-- `tombstone_blocks_place` below does.

begin;

select pg_advisory_xact_lock(119622309);

-- A place's identity must survive its member set growing, which is the whole difference between a
-- place and a scene. `scene_id_for` is a uuid5 over the digest of a scene's sorted member capture
-- ids, so adding a photograph to a scene does not extend it, it names a different one. A place
-- cannot be keyed that way and is not: this id is allocated once and never derived, the same choice
-- `entity` makes for the same reason.
create table place (
  place_id     uuid primary key default uuidv7(),
  workspace_id uuid not null,
  created_at   timestamptz not null default now(),
  unique (workspace_id, place_id)
);
create index place_ws_idx on place (workspace_id);

-- One scene's membership of one place, and the frame it was admitted in.
--
-- `frame_hops` is the honesty column. A place's shared frame is its ANCHOR scene's own recovered
-- frame, not a fourth frame from the joint run that nothing else addresses, so the anchor's own
-- transform is exactly identity and it is the row with zero hops. A scene measured against the
-- anchor by one joint reconstruction is one hop. A place with three scenes has two accepted
-- alignments, and the third scene's frame may have been measured against the second rather than
-- against the anchor, which makes its transform a composition of two measurements and not a
-- measurement. Without this column that composition is invisible and a reader takes a composed
-- transform for a measured one.
--
-- The capture time needs its own record because A SCENE HAS NO CAPTURE-TIME COLUMN. The only time
-- available is `capture.started_at` over the members, which 0001 itself calls a best estimate only
-- and which is nullable. Ordering a place's history by a live join on it would rearrange that
-- history whenever a photograph's metadata was corrected, and would have no answer at all when it
-- is null. So the time is recorded here at bind time with the basis that produced it, the ordinal
-- is fixed then, and a version whose time could not be established is admitted as `unavailable`
-- rather than guessed at.
create table place_version (
  workspace_id             uuid not null,
  place_id                 uuid not null,
  scene_id                 uuid not null,
  ordinal                  integer not null check (ordinal >= 0),
  ordered_by_utc           timestamptz,
  ordered_by_basis         text not null
                             check (ordered_by_basis in ('capture_exif','reviewer','unavailable')),
  frame_hops               integer not null check (frame_hops >= 0),
  admitted_by_alignment_id uuid,
  created_at               timestamptz not null default now(),
  primary key (workspace_id, place_id, scene_id),
  -- A scene belongs to at most one place, because two places claiming one scene would be two
  -- coordinate frames claiming one set of photographs.
  unique (workspace_id, scene_id),
  unique (workspace_id, place_id, ordinal),
  -- An unavailable time is the only case with no timestamp, and the only case with a timestamp is
  -- a stated basis. Neither half is inferable from the other without this.
  constraint a_missing_time_says_so
    check ((ordered_by_utc is null) = (ordered_by_basis = 'unavailable')),
  -- The anchor is the one version admitted by no alignment, and every other version was admitted
  -- by one. A version with hops and no receipt would be a frame nobody measured.
  constraint only_the_anchor_arrives_unmeasured
    check ((frame_hops = 0) = (admitted_by_alignment_id is null)),
  foreign key (workspace_id, place_id) references place (workspace_id, place_id),
  foreign key (workspace_id, scene_id)
    references reconstruction_scene (workspace_id, scene_id)
);
-- A place's history is read in capture order every time it is read, and nothing else orders it.
create index place_version_order_idx on place_version (workspace_id, place_id, ordinal);
-- Exactly one anchor per place: the frame every other version is expressed in.
create unique index place_version_one_anchor_idx
  on place_version (workspace_id, place_id) where frame_hops = 0;

-- One joint reconstruction, accepted or refused, and a refusal is a row like any other.
--
-- A refused pair stays two places and the world says their frames could not be reconciled. That is
-- a result and it is recorded as one: the 2026-09-05 volcanic coverage refusal is the precedent.
-- The reasons are the three `exulanica/reconstruction/place_alignment.py` already returns, listed
-- here rather than left to free text so a refusal nobody anticipated fails loudly.
--
-- No threshold from `PLACE_ALIGNMENT_POLICY` appears in any constraint here. Those numbers are
-- versioned engineering choices measured against a synthetic fixture, no real capture pair has been
-- measured, and a threshold frozen into the schema would have to be right before anybody could
-- measure it.
create table place_alignment (
  alignment_id          uuid primary key,
  workspace_id          uuid not null,
  place_id              uuid not null,
  -- The scene proposed for admission, and the member it was jointly reconstructed against.
  candidate_scene_id    uuid not null,
  against_scene_id      uuid not null,
  -- The exact member set of the union that was reconstructed, so the build is reproducible from
  -- the row without reading the receipt.
  union_member_digest   bytea not null check (octet_length(union_member_digest) = 32),
  policy_digest         bytea not null check (octet_length(policy_digest) = 32),
  -- The joint sparse model is a build intermediate in a third frame that nothing addresses, so it
  -- is not promoted to citable geometry. Its digest is kept so the fit stays checkable. Null when
  -- the run produced no connected model at all.
  joint_model_sha256    bytea check (octet_length(joint_model_sha256) = 32),
  accepted              boolean not null,
  reason                text
                          check (reason in ('place-alignment-not-connected',
                                            'place-alignment-insufficient-correspondences',
                                            'place-alignment-inconsistent')),
  receipt_artifact_id   uuid not null references artifact (artifact_id),
  created_at            timestamptz not null default now(),
  unique (workspace_id, alignment_id),
  -- An acceptance carries no reason and a refusal carries one. A refusal with no reason would be
  -- the outcome this design most wants to be able to read back.
  constraint a_refusal_says_why check (accepted = (reason is null)),
  -- One scene jointly reconstructed with itself measures nothing and fits perfectly, which is the
  -- shape of a bug that would read as the best alignment in the table.
  constraint an_alignment_is_between_two_scenes
    check (against_scene_id <> candidate_scene_id),
  foreign key (workspace_id, place_id) references place (workspace_id, place_id),
  foreign key (workspace_id, candidate_scene_id)
    references reconstruction_scene (workspace_id, scene_id),
  foreign key (workspace_id, against_scene_id)
    references reconstruction_scene (workspace_id, scene_id),
  -- One build over one union under one policy has one answer. A second run of the same inputs
  -- finds this row rather than writing a second verdict beside the first.
  unique (workspace_id, place_id, candidate_scene_id, against_scene_id,
          union_member_digest, policy_digest)
);
create index place_alignment_place_idx on place_alignment (workspace_id, place_id);

alter table place_version
  add constraint place_version_admitted_by_alignment_fkey
  foreign key (workspace_id, admitted_by_alignment_id)
  references place_alignment (workspace_id, alignment_id);

-- An artifact may now name a place.
--
-- 0024 gave `artifact` exactly one subject per row, a blob or a scene, and said so in a constraint
-- rather than in prose. A place alignment's subject is a PAIR of scenes, which is neither, and
-- attaching its receipt to one of the two would be a claim about one scene that was measured over
-- two. The invariant is unchanged: exactly one subject, now chosen from three.
alter table artifact add column place_id uuid;
alter table artifact
  add constraint artifact_place_is_in_its_own_workspace
  foreign key (workspace_id, place_id) references place (workspace_id, place_id);
alter table artifact drop constraint an_artifact_names_one_subject;
alter table artifact
  add constraint an_artifact_names_one_subject
  check (num_nonnulls(source_blob_sha256, scene_id, place_id) = 1);
create index artifact_place_idx on artifact (workspace_id, place_id) where place_id is not null;

-- A place is as live as the frame every one of its versions is expressed in.
--
-- The anchor's scene supplies that frame, so a withdrawn anchor takes the place with it: the other
-- versions' transforms are still numbers, but they are numbers about a frame recovered from
-- photographs somebody withdrew, and serving them would route around the withdrawal. A place with
-- no anchor is blocked too, which is the empty case failing closed, the same shape
-- `tombstone_blocks_scene` uses for a scene with no members.
--
-- A non-anchor version whose own scene is blocked is not blocked here. It is simply not returned,
-- because a place is a join and never a merge: one withdrawn capture removes its own version and
-- leaves the others standing.
create or replace function tombstone_blocks_place(p_workspace uuid, p_place uuid)
returns boolean language sql as $$
  select
    not exists (select 1 from place_version v
                 where v.workspace_id = p_workspace
                   and v.place_id = p_place
                   and v.frame_hops = 0)
    or exists (select 1 from place_version v
                where v.workspace_id = p_workspace
                  and v.place_id = p_place
                  and v.frame_hops = 0
                  and tombstone_blocks_scene(p_workspace, v.scene_id));
$$;

do $$
declare
  t text;
begin
  foreach t in array array[
    'place',
    'place_version',
    'place_alignment'] loop
    execute format(
      'create trigger %I before update or delete on %I '
      'for each row execute function tg_reconstruction_privacy_append_only()',
      'tg_' || t || '_append_only', t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

commit;
