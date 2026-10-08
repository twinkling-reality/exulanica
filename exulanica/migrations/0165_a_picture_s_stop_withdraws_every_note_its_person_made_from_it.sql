-- 0165_a_picture_s_stop_withdraws_every_note_its_person_made_from_it.sql
-- Stopping a picture's reading right withdraws every reference note its person made from that
-- picture, not only those read under the right being stopped.
--
-- The migration "a stopped picture withdraws the notes made from it" withdraws a finished request
-- when the right its bundle names is stopped. Every right ends (0073), and an expired right is not
-- a stop, so a person whose right expired, who granted it again and then stopped the picture, kept
-- the notes read under the expired right, while the words they
-- stopped against (exulanica/ingest/model-right-uses.v1.json) say the notes made with the picture
-- are withdrawn. A stop of a reference_vision right now also withdraws every finished request whose
-- requester granted that right and whose bundle names its picture. Another person's request naming
-- the same picture under that person's own right is not theirs to stop, and stays.
--
-- A job's finish asks the same question (reference_bundle_withdrawn, restated with the request it
-- finishes) and ends withdrawn when a right its bundle names was stopped, when its requester stopped
-- any reading right on one of its pictures after the request was made, or when a tombstone blocks
-- one of its pictures. A stop made before the request was asked for is a past decision the person
-- has since granted over; it withdraws nothing new.
--
-- ONE LOCK ORDERS THEM. A stop of a reading right now takes the per-workspace lifecycle lock before
-- it withdraws, as an embedding stop already does through its tombstone, and as every tombstone
-- insert does. A finish takes that lock before it asks, and holds it until it commits. So a stop or a
-- deletion either waits for the finish and then withdraws the request it finished, or the finish
-- waits for it and then sees it, whichever right it names, including one granted while the finish
-- was under way. The finish no longer locks right rows: the lifecycle lock already orders it against
-- every stop and tombstone. Each path: a stop takes its right row, then the lifecycle lock, then
-- finished request rows; a tombstone the lifecycle lock, then finished request rows; a finish its
-- job row, the lifecycle lock, then its own request row.
--
-- Objects: tg_reference_picture_right_withdrawn() (replaced; its trigger is unchanged),
-- reference_bundle_withdrawn(uuid, jsonb) (dropped), reference_bundle_withdrawn(uuid, uuid, jsonb)
-- (created). No table, constraint, grant or definer function.
begin;
select pg_advisory_xact_lock(119622309);

create or replace function tg_reference_picture_right_withdrawn() returns trigger
language plpgsql as $fn$
begin
  if new.model_role <> 'reference_vision' or old.withdrawn_at is not null
     or new.withdrawn_at is null then
    return new;
  end if;
  perform pg_advisory_xact_lock(hashtextextended(
    'caption-vector-lifecycle:' || new.workspace_id::text, 0));
  update reference_request r
     set status = 'withdrawn', bundle = null, bundle_sha256 = null
   where r.workspace_id = new.workspace_id
     and r.status in ('complete', 'partial')
     and exists (select 1 from jsonb_array_elements(r.bundle->'pictures') p
                  where p->'model_right_ids' ? new.right_id::text
                     or (r.owner_actor_id = new.granted_by
                         and (p->>'picture_id')::uuid = new.capture_id));
  return new;
end $fn$;

drop function if exists reference_bundle_withdrawn(uuid, jsonb);

-- Whether the bundle a request is finishing with names a stopped right, a picture whose requester
-- stopped a reading right on it since the request was made, or a picture a tombstone blocks, asked
-- under the lifecycle lock every stop and tombstone takes.
create or replace function reference_bundle_withdrawn(
  p_workspace uuid, p_reference uuid, p_bundle jsonb) returns boolean
language plpgsql volatile as $fn$
declare
  v_rights uuid[];
  v_pictures uuid[];
  v_owner uuid;
  v_asked timestamptz;
begin
  select coalesce(array_agg(distinct (p->>'picture_id')::uuid), '{}')
    into v_pictures
    from jsonb_array_elements(coalesce(p_bundle->'pictures', '[]'::jsonb)) p;
  if cardinality(v_pictures) = 0 then
    return false;
  end if;
  select coalesce(array_agg(distinct r::uuid), '{}')
    into v_rights
    from jsonb_array_elements(p_bundle->'pictures') p,
         jsonb_array_elements_text(p->'model_right_ids') r;
  select owner_actor_id, created_at into v_owner, v_asked
    from reference_request where workspace_id = p_workspace and reference_id = p_reference;
  perform pg_advisory_xact_lock(hashtextextended(
    'caption-vector-lifecycle:' || p_workspace::text, 0));
  return exists (
           select 1 from personal_model_right
            where workspace_id = p_workspace and right_id = any(v_rights)
              and withdrawn_at is not null)
      or exists (
           select 1 from personal_model_right
            where workspace_id = p_workspace and model_role = 'reference_vision'
              and granted_by = v_owner and capture_id = any(v_pictures)
              and withdrawn_at >= v_asked)
      or exists (
           select 1 from tombstone t
            where t.workspace_id = p_workspace
              and (t.scope::text = 'workspace'
                   or (t.scope::text in ('capture', 'interval')
                       and t.capture_id = any(v_pictures))));
end $fn$;

commit;
