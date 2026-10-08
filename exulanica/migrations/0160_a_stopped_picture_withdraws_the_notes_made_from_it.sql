-- 0160_a_stopped_picture_withdraws_the_notes_made_from_it.sql
-- Stopping a picture's reading right, or deleting the picture, withdraws the notes made from it.
--
-- A reference request may read a person's own pictures (exulanica/references/worker.py), and its
-- bundle (exulanica.reference-bundle/v1) names each picture the request policy let through, with
-- the rights it was read under. 0148 keeps a finished request unchanged for good, so the notes made
-- from a picture would outlive the person's stop. They do not: the request becomes WITHDRAWN, its
-- bundle and the bundle's digest are cleared, and nothing else about it changes. A
-- drafter asking for its notes is told reference_withdrawn. A drafted document that already used
-- them keeps only the digest it recorded, which holds no text.
--
-- BY TRIGGER, NEVER BY A CALLER, for 0104's reason: a withdrawal a caller must remember is missing
-- on the withdrawal that matters, and neither withdraw_model_right nor the deletion routes are the
-- only writers of a right's stop or a tombstone. Two triggers do it:
--
--   * a reference_vision right whose withdrawn_at goes from null to set (0073 lets it change once)
--     withdraws every finished request whose bundle names that right among a picture's rights;
--   * a tombstone that blocks a capture (scope capture or interval naming it, or workspace)
--     withdraws every finished request whose bundle names that capture, when the deletion is asked
--     and whatever its effective time, so the notes go before the purge does.
--
-- Both are plain (invoker) functions: they run as the role writing the right or the tombstone, under
-- its row security. Every such write is made in its own workspace's session, because a BEFORE
-- trigger asserts the workspace context before any AFTER trigger runs (0073's on a right, 0044's
-- lifecycle lock as 0104 restates it on a tombstone); a role that bypasses row security, as a
-- restore's does, is held to that workspace by the explicit workspace condition in each update. The runtime role holds update on
-- reference_request (0148); the owner, which writes on a restore, holds everything. The purge role
-- updates a tombstone's purge time only and writes no right, so it fires neither.
--
-- A READING IN FLIGHT. A job reads a picture under a current right, and the person stops the right
-- while the model call runs. The right's trigger finds the request still running and leaves it, so
-- the job's own finish asks reference_bundle_withdrawn first: it takes the bundle's right rows FOR
-- SHARE and then the per-workspace lifecycle lock every tombstone insert takes (0044), and answers
-- whether a right it names has stopped or a tombstone blocks a picture it names. A finish that would
-- keep such a bundle ends withdrawn instead. One of the two always sees the other: a stop waiting on
-- the finish's share lock updates the right after the finish commits, and its trigger then sees a
-- finished request; a finish waiting on a stop reads the stop. No path takes these in another
-- order: a stop takes its right row and then request rows (no lifecycle lock), a tombstone takes the
-- lifecycle lock and then request rows, and a finish takes its job row, the right rows, the
-- lifecycle lock and then its own request row.
--
-- A RESTORE WITHDRAWS AGAIN. withdrawals.v2.json carries a right's stop and replays every tombstone,
-- each written as the product writes it, so these triggers run again on a restored database. The
-- withdrawn status is therefore excluded from the withdrawal catalog by name, as material_bake's is.
--
-- NOTHING IN THIS FILE USES A TOMBSTONE SCOPE AS AN ENUM, for 0082's reason: scope is compared as text.
begin;
select pg_advisory_xact_lock(119622309);

alter table reference_request drop constraint if exists reference_request_status_check;
alter table reference_request add constraint reference_request_status_check
  check (status in ('queued', 'running', 'complete', 'partial', 'failed', 'cancelled', 'withdrawn'));
alter table reference_request drop constraint if exists reference_request_finished;
alter table reference_request add constraint reference_request_finished
  check ((status in ('complete', 'partial', 'failed', 'cancelled', 'withdrawn'))
         = (finished_at is not null));

-- 0148's rules, and one more: a complete or partial request may become withdrawn, clearing exactly
-- its bundle and digest. A running one may end withdrawn (its finish found a stopped picture).
create or replace function tg_reference_request_progress() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    if old.status in ('complete', 'partial') and new.status = 'withdrawn' then
      if new.bundle is not null or new.bundle_sha256 is not null
         or (to_jsonb(new) - array['status', 'bundle', 'bundle_sha256'])
            is distinct from (to_jsonb(old) - array['status', 'bundle', 'bundle_sha256']) then
        raise exception 'a withdrawn reference request clears its bundle and nothing else'
          using errcode = '23514';
      end if;
      return new;
    end if;
    if old.status in ('complete', 'partial', 'failed', 'cancelled', 'withdrawn') then
      raise exception 'a finished reference request never changes' using errcode = '23514';
    end if;
    if new.workspace_id <> old.workspace_id or new.reference_id <> old.reference_id
       or new.owner_actor_id <> old.owner_actor_id or new.purpose <> old.purpose
       or new.web <> old.web or new.request_id is distinct from old.request_id
       or new.job_id <> old.job_id
       or new.prompts_sha256 <> old.prompts_sha256 or new.created_at <> old.created_at then
      raise exception 'a reference request''s progress moves, not what it asked'
        using errcode = '23514';
    end if;
    if (old.status = 'queued' and new.status not in ('queued', 'running', 'cancelled', 'failed'))
       or (old.status = 'running' and new.status = 'queued') then
      raise exception 'a reference request moves from queued to running to its end'
        using errcode = '23514';
    end if;
    if old.cancel_requested_at is not null
       and new.cancel_requested_at is distinct from old.cancel_requested_at then
      raise exception 'a stop once asked is never withdrawn' using errcode = '23514';
    end if;
    if new.request_sha256 is not null and new.request_sha256 is distinct from old.request_sha256 then
      raise exception 'a request''s digest is only ever cleared' using errcode = '23514';
    end if;
  end if;
  return new;
end $fn$;

-- Whether a bundle names a stopped right or a blocked picture, taking the locks a finish needs
-- first: the named right rows, then the lifecycle lock a tombstone insert takes. A right named but
-- absent is not a stop; an expired right is not a stop (as in 0104).
create or replace function reference_bundle_withdrawn(p_workspace uuid, p_bundle jsonb) returns boolean
language plpgsql volatile as $fn$
declare
  v_rights uuid[];
  v_pictures uuid[];
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
  perform 1 from personal_model_right
    where workspace_id = p_workspace and right_id = any(v_rights)
    order by right_id for share;
  perform pg_advisory_xact_lock(hashtextextended(
    'caption-vector-lifecycle:' || p_workspace::text, 0));
  return exists (
           select 1 from personal_model_right
            where workspace_id = p_workspace and right_id = any(v_rights)
              and withdrawn_at is not null)
      or exists (
           select 1 from tombstone t
            where t.workspace_id = p_workspace
              and (t.scope::text = 'workspace'
                   or (t.scope::text in ('capture', 'interval')
                       and t.capture_id = any(v_pictures))));
end $fn$;

create or replace function tg_reference_picture_right_withdrawn() returns trigger
language plpgsql as $fn$
begin
  if new.model_role <> 'reference_vision' or old.withdrawn_at is not null
     or new.withdrawn_at is null then
    return new;
  end if;
  update reference_request r
     set status = 'withdrawn', bundle = null, bundle_sha256 = null
   where r.workspace_id = new.workspace_id
     and r.status in ('complete', 'partial')
     and exists (select 1 from jsonb_array_elements(r.bundle->'pictures') p
                  where p->'model_right_ids' ? new.right_id::text);
  return new;
end $fn$;

create or replace trigger tg_reference_picture_right_withdrawn
  after update on personal_model_right
  for each row execute function tg_reference_picture_right_withdrawn();

create or replace function tg_reference_picture_tombstoned() returns trigger
language plpgsql as $fn$
begin
  if new.scope::text not in ('workspace', 'capture', 'interval') then
    return new;
  end if;
  update reference_request r
     set status = 'withdrawn', bundle = null, bundle_sha256 = null
   where r.workspace_id = new.workspace_id
     and r.status in ('complete', 'partial')
     and exists (select 1 from jsonb_array_elements(r.bundle->'pictures') p
                  where new.scope::text = 'workspace'
                     or (p->>'picture_id')::uuid = new.capture_id);
  return new;
end $fn$;

create or replace trigger tg_reference_picture_tombstoned
  after insert on tombstone
  for each row execute function tg_reference_picture_tombstoned();

commit;
