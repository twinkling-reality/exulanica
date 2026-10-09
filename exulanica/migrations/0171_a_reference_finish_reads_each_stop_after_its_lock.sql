-- 0171_a_reference_finish_reads_each_stop_after_its_lock.sql
-- A reference request's finish refuses to ask its question where it could read a stale answer.
--
-- reference_bundle_withdrawn (restated by "a picture's stop withdraws every note its person made
-- from it") takes the per-workspace lifecycle lock that every stop of a picture's reading right
-- and every tombstone takes, then reads whether a right was stopped or a picture deleted. That read
-- is fresh only at READ COMMITTED, where each statement takes a new snapshot after the lock wait;
-- under REPEATABLE READ or SERIALIZABLE it would read the snapshot taken before the wait and could
-- keep notes a stop had just withdrawn. Every caller runs at READ COMMITTED today
-- (exulanica/db/session.py); the function now refuses any other level with 40001, as 0041 refuses
-- a stale privacy read. It also refuses a request it cannot find, rather than read its owner and
-- asking time as unknown and let the person's own stops pass unseen.
--
-- What the stop and finish paths hold, stated whole: a stop of a reading right holds its right row,
-- the training-source lock's shared side, the privacy-currency lock and the shared side of 0041's
-- asset read barrier (its BEFORE triggers), then waits for the lifecycle lock in its AFTER trigger;
-- a tombstone takes the lifecycle lock in its BEFORE trigger; a finish holds its job row, then
-- waits for the lifecycle lock. A finish counts a requester's stop made at or after the instant the
-- request was made. A stop of one reading right ends every reading right not yet withdrawn that its
-- grantor holds on that picture (the withdraw route, one transaction, rows locked in id order
-- before any changes), so no other right of the same person goes on sending it.
--
-- Objects: reference_bundle_withdrawn(uuid, uuid, jsonb) (replaced, same signature, owner and
-- privileges). No table, constraint, trigger, grant or definer function.
begin;
select pg_advisory_xact_lock(119622309);

create or replace function reference_bundle_withdrawn(
  p_workspace uuid, p_reference uuid, p_bundle jsonb) returns boolean
language plpgsql volatile as $fn$
declare
  v_rights uuid[];
  v_pictures uuid[];
  v_owner uuid;
  v_asked timestamptz;
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'a reference request finishes at READ COMMITTED, so it reads each stop after '
                    'waiting for its lock' using errcode = '40001';
  end if;
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
  if not found then
    raise exception 'no reference request % in this workspace to finish', p_reference
      using errcode = '23514';
  end if;
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
