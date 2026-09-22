-- 0091_a_place_can_declare_an_admitted_frame.sql
-- The second way a place can have a frame: declared from a provider, never measured here.
--
-- 0038 gave a place one frame authority, its anchor scene's own recovered frame, and
-- `docs/place-identity.md` says why: a place's identity comes from a joint reconstruction and
-- never from a label. That leaves a geography a person is entitled to bring into their world
-- with no way to exist. `environment_source_admission.place_id` is a foreign key to `place`,
-- and the only two creators of a `place` row both require a reconstruction: `insert_place`
-- leaves the place blocked by `tombstone_blocks_place` until an anchor version exists, and
-- `establish_place` binds an anchor SCENE. An admitted map, footprint set or tile set has no
-- photographs behind it, so neither path can produce the place its admission must reference.
--
-- This migration adds the other authority and says, in a column, that it is a different kind of
-- thing. A source-anchored place DECLARES its frame: the coordinate reference system, axis
-- order, units, orientation, altitude reference and bounds are copied from the provider's own
-- documentation and frozen in a digest-bound receipt. Nothing here measures a coordinate, and
-- `frame_authority` is the honesty column that stops a reader taking a declaration for a
-- measurement, exactly as `place_version.frame_hops` stops a reader taking a composed transform
-- for a measured one.
--
-- What this deliberately does NOT do. It records no transform between a declared geographic
-- frame and any recovered scene frame, because relating them is georeferencing and
-- `docs/place-identity.md` names the physical reference that would need as an unmet dependency.
-- It grants no right to anything: a place carries no operation rights and every right is still
-- resolved per admission by `environment_resource_allows`. And it does not constrain a derived
-- asset's frame, because a derivation may legitimately reproject into a local frame, and a
-- constraint there would forbid the ordinary case to restate a fact about the source.

begin;

select pg_advisory_xact_lock(119622309);

-- The integer coordinates of one bounds object, or null when they are not all integers.
--
-- Separate from the containment predicate below so that "these are integers" is answered once.
-- `canonical_json` refuses floats at any depth and every bounds object in this schema is
-- integers plus an explicit decimal scale, so a non-integer coordinate is a malformed input
-- rather than a case to round.
create function place_bounds_integers(p_bounds jsonb) returns bigint[]
language sql immutable as $fn$
  select case
    when jsonb_typeof(p_bounds->'coordinates') <> 'array' then null
    when exists(
      select 1 from jsonb_array_elements(p_bounds->'coordinates') element
       where jsonb_typeof(element.value) <> 'number'
          or element.value #>> '{}' !~ '^-?[0-9]+$'
    ) then null
    else (
      select array_agg((element.value #>> '{}')::bigint order by element.ordinality)
        from jsonb_array_elements(p_bounds->'coordinates') with ordinality element
    )
  end;
$fn$;

-- Does a declared bounding box contain a candidate's bounds. Integer arithmetic only.
--
-- Kind `feature` is refused rather than accepted. Feature bounds are "at least one integer
-- identifier component": a provider's own feature id, which is not geometry, so nothing can
-- establish that it lies inside a box. Accepting one would record a containment claim nobody
-- checked, which is the shape of exactly the failure this predicate exists to prevent.
create function place_declared_bounds_contain(p_declared jsonb, p_candidate jsonb)
returns boolean language plpgsql immutable as $fn$
declare
  declared bigint[];
  candidate bigint[];
  dimensions int;
  axis int;
  point int;
begin
  if coalesce(p_declared->>'kind','') <> 'bbox' then return false; end if;
  if coalesce(p_candidate->>'kind','') not in ('bbox','polygon') then return false; end if;
  if p_candidate->>'frame_name' is distinct from p_declared->>'frame_name' then return false; end if;
  if p_candidate->>'coordinate_scale' is distinct from p_declared->>'coordinate_scale' then
    return false;
  end if;
  declared := place_bounds_integers(p_declared);
  candidate := place_bounds_integers(p_candidate);
  if declared is null or candidate is null then return false; end if;
  if array_length(declared,1) not in (4,6) then return false; end if;
  dimensions := array_length(declared,1) / 2;
  for axis in 1..dimensions loop
    if declared[axis] > declared[dimensions+axis] then return false; end if;
  end loop;
  if p_candidate->>'kind' = 'bbox' then
    if array_length(candidate,1) <> array_length(declared,1) then return false; end if;
    for axis in 1..dimensions loop
      if candidate[axis] > candidate[dimensions+axis]
        or candidate[axis] < declared[axis]
        or candidate[dimensions+axis] > declared[dimensions+axis]
      then
        return false;
      end if;
    end loop;
    return true;
  end if;
  -- A polygon is a flat run of two-dimensional points, at least three of them. Height is not
  -- compared, because a polygon states none.
  if array_length(candidate,1) < 6 or array_length(candidate,1) % 2 <> 0 then return false; end if;
  point := 1;
  while point < array_length(candidate,1) loop
    if candidate[point] < declared[1] or candidate[point] > declared[dimensions+1]
      or candidate[point+1] < declared[2] or candidate[point+1] > declared[dimensions+2]
    then
      return false;
    end if;
    point := point + 2;
  end loop;
  return true;
end $fn$;

-- One declared frame per place, and the place that has one has no other authority.
--
-- The primary key on `(workspace_id, place_id)` is this plane's `place_version_one_anchor_idx`:
-- a second declaration would be a second frame claiming one place. The receipt columns follow
-- `environment_source_admission` exactly, so a declaration is checkable byte for byte and a
-- changed reduction changes the profile rather than reinterpreting an old row.
create table place_source_frame (
  workspace_id uuid not null,
  place_id uuid not null,
  profile text not null check(profile='exulanica.place-source-frame/v1'),
  -- The honesty column. Its only value today is the only basis that exists: a statement copied
  -- from the provider's documentation. A check constraint rather than free text, so a basis
  -- nobody anticipated fails loudly instead of arriving as a new spelling.
  frame_authority text not null check(frame_authority in ('declared_provider_frame')),
  provider_key text not null check(provider_key=btrim(provider_key) and provider_key<>''),
  -- What the provider itself says about this frame, in their words, so a reader can check the
  -- declaration against its source rather than against this row.
  provider_frame_statement text not null
    check(provider_frame_statement=btrim(provider_frame_statement)
      and length(provider_frame_statement) between 1 and 2000),
  geographic_frame jsonb not null check(jsonb_typeof(geographic_frame)='object'),
  geographic_bounds jsonb not null check(jsonb_typeof(geographic_bounds)='object'),
  receipt_record jsonb not null,
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  declared_by uuid not null,
  declared_at timestamptz not null default now(),
  primary key(workspace_id,place_id),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id),
  -- A declared extent is a box. A polygon or a feature identifier would make "is this source
  -- inside this place" a different question for every place.
  check(geographic_bounds->>'kind'='bbox'),
  check(geographic_bounds->>'frame_name'=geographic_frame->>'name'),
  check(place_bounds_integers(geographic_bounds) is not null),
  check(array_length(place_bounds_integers(geographic_bounds),1) in (4,6)),
  check(receipt_record->>'profile'=profile),
  check(receipt_record->>'place_id'=place_id::text),
  check(receipt_record->>'frame_authority'=frame_authority),
  check(receipt_record->>'provider_key'=provider_key),
  check(receipt_record->>'provider_frame_statement'=provider_frame_statement),
  check(receipt_record->'geographic_frame'=geographic_frame),
  check(receipt_record->'geographic_bounds'=geographic_bounds),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);

alter table place_source_frame enable row level security;
alter table place_source_frame force row level security;
create policy ws_isolation on place_source_frame
  using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());
create trigger aaa_asset_read_mutation
before insert or update or delete on place_source_frame
for each row execute function tg_asset_read_mutation();

-- A place has one frame authority, and these two triggers are the two halves of that sentence.
--
-- A recovered COLMAP frame and a geographic CRS are not related by anything this system
-- measures, so a place carrying both would be asserting a correspondence nobody established,
-- and every read of it would have to choose one silently.
create function tg_place_source_frame_is_the_only_anchor() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform 1 from place
    where workspace_id=new.workspace_id and place_id=new.place_id
    for update;
  if exists(
    select 1 from place_version v
     where v.workspace_id=new.workspace_id and v.place_id=new.place_id
  ) then
    raise exception 'a place whose frame a reconstruction measured cannot also declare one'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_place_source_frame_is_the_only_anchor
before insert on place_source_frame
for each row execute function tg_place_source_frame_is_the_only_anchor();

create function tg_place_version_has_no_declared_frame() returns trigger
language plpgsql as $fn$
begin
  if exists(
    select 1 from place_source_frame f
     where f.workspace_id=new.workspace_id and f.place_id=new.place_id
  ) then
    raise exception 'a place that declared an admitted frame cannot also anchor a scene'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_place_version_has_no_declared_frame
before insert on place_version
for each row execute function tg_place_version_has_no_declared_frame();

-- A declaration is what a place IS, so correcting one names a different place.
create function tg_place_source_frame_immutable() returns trigger language plpgsql as $fn$
begin
  raise exception 'a declared place frame is immutable; a different frame is a different place'
    using errcode='23514';
end $fn$;
create trigger tg_place_source_frame_immutable
before update or delete on place_source_frame
for each row execute function tg_place_source_frame_immutable();

-- An admitted source must carry the frame its place declared, and lie inside its bounds.
--
-- Without the first check a place could hold two sources in unrelated coordinate systems and
-- nothing would say which one its declared frame described. Without the second, a place a
-- person created for one neighbourhood could silently receive geography from another, which is
-- the world holding something nobody asked for.
--
-- A place with no declaration is untouched: it claims no frame, so there is nothing for an
-- admission to disagree with, and every fixture that admits into a bare place still works.
create function tg_environment_source_matches_declared_frame() returns trigger
language plpgsql as $fn$
declare declared place_source_frame%rowtype;
begin
  select * into declared from place_source_frame
    where workspace_id=new.workspace_id and place_id=new.place_id;
  if not found then return new; end if;
  if new.geographic_frame is distinct from declared.geographic_frame then
    raise exception 'admitted source frame disagrees with the frame its place declared'
      using errcode='23514';
  end if;
  if not place_declared_bounds_contain(declared.geographic_bounds, new.geographic_bounds) then
    raise exception 'admitted source bounds are not inside the bounds its place declared'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_environment_source_matches_declared_frame
before insert on environment_source_admission
for each row execute function tg_environment_source_matches_declared_frame();

commit;
