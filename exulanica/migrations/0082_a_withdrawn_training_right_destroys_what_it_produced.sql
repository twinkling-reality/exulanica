-- A withdrawn training right destroys what the run produced, through the one purge machinery.
--
-- Migration 0080 built three quarters of a withdrawal and named the quarter it did not build. It
-- CANCELS THE RUN, queued or running. It REFUSES EVERY FURTHER READ of the artefact at the instant
-- of the read. It BINDS which artefacts a destruction would have to reach. It does not enqueue
-- destruction, and its own comment says why: that reaches the tombstone and purge-queue invariants
-- of 0013 and 0015 and is its own piece of work. This is that work.
--
-- WHY IT COULD NOT JUST BE ADDED THERE, measured rather than repeated from the brief that asked
-- for it. `purge_job.tombstone_id` is `not null references tombstone(tombstone_id)`, and the
-- anchor is load-bearing in four more places than the column: `claim_purge` reads `requested_by`
-- and `reason` off the tombstone row and asserts it exists, `PurgeAuthorization` cannot be
-- constructed without a tombstone id, the worker picks its destroy question by asking the
-- tombstone's scope, and completion is recorded on `tombstone.purge_completed_at`. Measured on a
-- private PostgreSQL through the real migrations: granting a right, queuing a run, publishing an
-- artefact and withdrawing left the tombstone count at 0 and the purge_job count at 0; writing a
-- purge job with a null anchor raised the not-null on `purge_job.tombstone_id`, and with an
-- invented one raised `purge_job_tombstone_id_fkey`.
--
-- SO THE WITHDRAWAL WRITES A TOMBSTONE, rather than the queue learning a second anchor. The
-- alternative was making `tombstone_id` nullable beside a second origin column, and it was
-- rejected for one reason rather than on price: it breaks "every destroyed byte traces to a
-- tombstone", which is an audit property of the whole system, and it would either widen
-- `PurgeAuthorization` or hand it a right id under a field named `tombstone_id`, which is a lie in
-- an erasure record.
--
-- ------------------------------------------------------------------------------------------------
-- THE SENTENCE THE NEW SCOPE HAS TO MAKE TRUE, because its meaning is not self-evident from its
-- spelling and a reader will otherwise assume the opposite:
--
--   A SCENE_TRAINING TOMBSTONE OVER A CAPTURE ERASES WHAT WAS TRAINED FROM THAT CAPTURE, AND THE
--   CAPTURE ITSELF SURVIVES BY DESIGN.
--
-- The account holder withdrew permission to train on their photograph. They did not delete the
-- photograph, and 0080 says what withdrawal means to the person who asks for it: take THAT
-- photograph out, not revoke the scene. So this erases outputs and spares its own subject.
--
-- AN ERASURE SCOPE THAT SPARES ITS SUBJECT IS NOT NEW HERE, which is the thing to know before
-- reading it as a bug. 0030's entity tombstone already destroys a person's derivatives while
-- retaining the source photographs, and records `source_capture_policy: retained` in its receipt.
-- This is the same shape with a different subject.
--
-- WIDENING THE ENUM IS ON THE RULE THE EARLIER THREE WERE DECLINED UNDER, not against it. 0024,
-- 0038 and 0066 each declined to add a `tombstone_scope` value, and 0066 states the rule they
-- declined under: a tombstone erases personal data, and an authored change that is not erasure
-- goes in its own table. A reconstruction trained from somebody's photographs of their own home,
-- erased because they withdrew the right that permitted it, is erasure of personal data. This is
-- the first case that is on the rule rather than against it, and it is said here so that the
-- fourth person to meet three refusals does not read them as a fourth.
--
-- WHAT A NEW VALUE REACHES, measured before it was chosen. In a scratch database the value was
-- added and a tombstone carrying it was inserted naming a live capture. Nothing moved:
-- `tombstone_blocks_capture`, `tombstone_blocks_scene`, `tombstone_blocks_derivative` and
-- `asset_tombstone_capture` all still answered false, `capture.deleted_at` was still null, and the
-- purge queue was still empty. Every scope branch in this schema is an inclusion test on a named
-- value, never an exclusion, so a new value is inert until something is written for it. That is
-- MEASURED for those six and READ for the rest: the six early returns of the form `if new.scope
-- not in (...) then return new` are the correct silence here, and the remaining tests name scopes
-- this one is not.
--
-- NOTHING IN THIS FILE MAY USE THE NEW VALUE. PostgreSQL permits `alter type ... add value` inside
-- a transaction and refuses to USE the value in that same transaction, and a migration file is one
-- transaction. So every reference below is either inside a plpgsql body, which is not planned
-- until it runs, or written as `scope::text`, which constructs no enum value at all. Measured, by
-- adding one `language sql` function comparing `scope` to the literal and applying the file:
-- `UnsafeNewEnumValueUsage: unsafe use of new value "scene_training" of enum type tombstone_scope`,
-- raised while the migration ran, because a SQL body is planned at creation and a plpgsql body is
-- not. That probe was removed; this sentence is what it left behind.
-- ------------------------------------------------------------------------------------------------
--
-- THE DESTROY QUESTION IS NOT OPTIONAL AND IT IS WHY THIS FILE IS NOT ONLY AN ANCHOR. Measured:
-- `purge_releases_bytes` answers FALSE for a trained artefact while its capture is live, because
-- 0024's third clause says a scene artefact none of whose members is deleted still holds its
-- bytes. A training right withdrawal deliberately leaves the photograph alive. So a design that
-- fixed only the anchor would enqueue jobs that skip, spend their eight attempts and report as
-- exhausted, and it would look like it worked. `scene_training_withdrawal_releases_artifact` below
-- is the question this tombstone actually asks, in the shape 0030 needed for the same reason.
--
-- WHAT THIS DOES NOT SOLVE, said plainly rather than left to be discovered. WHEN TRAINED BYTES ARE
-- SHARED ACROSS WORKSPACES, A WITHDRAWAL MAY NEVER DESTROY ANYTHING. The purge role reads the
-- binding and the withdrawal flag within one workspace only, so a second workspace's artefact
-- holding the same content hash cannot be shown to be withdrawn and therefore blocks the
-- destruction. That is the safe direction and it is a deliberate default, but it does not defer,
-- it blocks permanently: nothing here can observe the second workspace's later withdrawal. Whether
-- a second holder's own withdrawal should release the bytes, and by what mechanism, is an
-- unanswered policy question and not this file's to invent.
--
-- AND ONE OPERATIONAL CONSEQUENCE, measured rather than reasoned from the grant shape. A purge role
-- provisioned before this migration goes on draining every other tombstone normally, and only a
-- training-withdrawal job fails, with `permission denied for function
-- scene_training_withdrawal_releases_artifact`, until the role is re-provisioned in the ordinary
-- migrations-then-roles order `exulanica-db provision` already runs in. Loud and local rather than
-- closed and global, because the two new reads go in `_PURGE_WORKSPACE_READS`, which carries no
-- cross-workspace policy and so does not move the list `read_visibility` requires.
--
-- THAT LOCALITY WAS NOT FREE AND IT WAS NOT TRUE OF THE FIRST DESIGN. With the three destroy
-- questions in one SQL `case`, an old role failed EVERY artifact job, including jobs of an
-- ordinary capture deletion whose arm would never have been taken, because PostgreSQL checks
-- EXECUTE on every function in an expression when the expression is initialised rather than on the
-- arm that runs. `exulanica/deletion/worker.py` now chooses the question in Python, and the test
-- that measured it asserts the failed job is exactly one.

begin;
select pg_advisory_xact_lock(119622309);

alter type tombstone_scope add value if not exists 'scene_training';

-- ------------------------------------------------------------------------------------------------
-- What a scene_training tombstone enqueues
-- ------------------------------------------------------------------------------------------------
-- ON THE TOMBSTONE'S INSERT RATHER THAN ON THE WITHDRAWAL, which is 0030's shape and is what makes
-- an offline restore work: `exulanica/deletion/restore.py` replays a tombstone with
-- `jsonb_populate_record`, so a subject that is a tombstone column travels with it and this
-- cascade runs again. A side table naming the withdrawn right would not be replayed, and the
-- replayed tombstone would enqueue nothing.
--
-- EVERY ARTEFACT OF THIS CAPTURE WHOSE RIGHT IS WITHDRAWN, not only the one right that produced
-- this tombstone, because the tombstone's subject is the capture and it has no column for a right.
-- Two rights over one photograph withdrawn separately therefore write two tombstones, and the
-- second enqueues the first's artefacts again if the first purge has not finished. THAT DUPLICATE
-- IS A CHOICE, not an oversight: the unique key is (tombstone_id, target_kind, target_ref), a
-- second job for one object is idempotent by construction, and a uniqueness constraint that
-- collapsed them would make one tombstone's completion depend on another tombstone's job.
--
-- WITHDRAWN, NOT `scene_training_artifact_withdrawn`. That predicate is true of an expired or
-- lapsed right too, and an expiry is not a request to destroy anything. A tombstone exists here
-- because somebody withdrew, so the term that put it here is the term this reads.
create function tg_scene_training_tombstone_cascade() returns trigger
language plpgsql as $fn$
begin
  if new.scope::text <> 'scene_training' then
    return new;
  end if;
  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select distinct new.tombstone_id, new.workspace_id, 'artifact',
         encode(a.content_sha256, 'hex')
    from scene_training_artifact b
    join scene_training_right r
      on r.workspace_id = b.workspace_id and r.right_id = b.right_id
    join artifact a
      on a.workspace_id = b.workspace_id and a.artifact_id = b.artifact_id
   where b.workspace_id = new.workspace_id
     and b.capture_id = new.capture_id
     and r.withdrawn_at is not null
     and a.content_sha256 is not null
     and a.purged_at is null
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;

create trigger tg_scene_training_tombstone_cascade
  after insert on tombstone
  for each row execute function tg_scene_training_tombstone_cascade();

-- ------------------------------------------------------------------------------------------------
-- The withdrawal writes the tombstone
-- ------------------------------------------------------------------------------------------------
-- BY TRIGGER, NEVER BY A CALLER, for the reason 0080 gives about its own binding: a GPU runner
-- invoked from a script is exactly the caller that routes around a Python step, and an erasure a
-- caller must remember to ask for is an erasure that will be missing on the withdrawal that
-- matters. `withdraw_training_right` is not the only way `withdrawn_at` can be set.
--
-- NAMED TO SORT AFTER 0080's `tg_scene_training_right_withdrawn`, which cancels the run, because
-- triggers on one event fire in name order and cancelling a run that is about to be erased should
-- happen first. Neither depends on the other; the order is stated so it is not accidental.
--
-- UNCONDITIONAL, even when the right produced nothing. The tombstone is the record that the
-- account holder asked, and a withdrawal with no bindings leaves a tombstone with no jobs, which
-- is what an entity tombstone over a person with no derivatives already leaves. Its
-- `purge_completed_at` stays null because nothing claims a job to record it, and 0013's own
-- paragraph says a tombstone with no jobs is complete in the sense that matters.
create function tg_scene_training_right_withdrawn_erases() returns trigger
language plpgsql as $fn$
begin
  if new.withdrawn_at is null then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  insert into tombstone (workspace_id, scope, capture_id, requested_by, effective_at, reason)
  values (new.workspace_id, 'scene_training', new.capture_id, new.withdrawn_by, new.withdrawn_at,
          'a scene training right over this photograph was withdrawn');
  return new;
end $fn$;

create trigger tg_scene_training_right_withdrawn_erases
  after update on scene_training_right
  for each row execute function tg_scene_training_right_withdrawn_erases();

-- ------------------------------------------------------------------------------------------------
-- The destroy question
-- ------------------------------------------------------------------------------------------------
-- MEASURED, AND THE REASON THIS FILE IS NOT ONLY AN ANCHOR: `purge_releases_bytes` answers FALSE
-- for a trained artefact while its capture is live. Its third clause, added by 0024, says a scene
-- artefact none of whose members is deleted still holds its bytes, and that clause is right for
-- every other caller. A training right withdrawal is the one erasure that deliberately leaves the
-- photograph alive, so it needs its own question, exactly as a person withdrawal did.
--
-- THE INVERSION IS 0030's AND 0024's, and it is the whole of it: AN ARTEFACT WHOSE TRAINING RIGHT
-- STILL STANDS IS A REASON TO KEEP THESE BYTES, AND ONE WHOSE RIGHT IS WITHDRAWN IS ITSELF DOOMED
-- AND IS NO REASON FOR ANYTHING. Without that, the predicate refuses the very artefact being
-- purged, which is 0013's own correction 2 arriving one table over.
--
-- NOT RESTRICTED TO THIS TOMBSTONE'S CAPTURE, deliberately. Two artefacts sharing one content hash
-- under two withdrawn rights would otherwise each be a reason to keep bytes the other tombstone is
-- also trying to destroy, and neither would ever go.
--
-- RAISES ON NULL like every other predicate in this family. Bytes nobody can name are bytes this
-- cannot decide about, and destroying them because the question was unanswerable is the wrong
-- direction to fail.
--
-- ONLY AS TRUTHFUL AS THE CALLER CAN SEE, and here that is narrower than for `purge_releases_bytes`
-- on purpose. `artifact` is read across workspaces by the purge role; `scene_training_artifact` and
-- `scene_training_right` are not, so another workspace's artefact holding these bytes cannot be
-- shown to be withdrawn and blocks. Safe, permanent, and written up in this file's header.
create function scene_training_withdrawal_releases_artifact(p_tombstone uuid, p_bytes bytea)
returns boolean
language plpgsql volatile as $fn$
declare
  v_capture uuid;
begin
  if p_bytes is null then
    raise exception 'a training withdrawal was asked to release an absent content hash'
      using errcode = 'null_value_not_allowed',
            hint = 'Bytes nobody can name are bytes this cannot decide about.';
  end if;
  select t.capture_id into v_capture
    from tombstone t
   where t.tombstone_id = p_tombstone and t.scope::text = 'scene_training';
  if v_capture is null then
    return false;
  end if;
  return
    not exists (select 1 from capture c
                 where c.blob_sha256 = p_bytes and c.deleted_at is null)
    and not exists (
      select 1 from artifact a
       where a.content_sha256 = p_bytes and a.purged_at is null
         and not exists (
           select 1 from scene_training_artifact b
             join scene_training_right r
               on r.workspace_id = b.workspace_id and r.right_id = b.right_id
            where b.workspace_id = a.workspace_id
              and b.artifact_id = a.artifact_id
              and r.withdrawn_at is not null));
end $fn$;

comment on function scene_training_withdrawal_releases_artifact(uuid, bytea) is
  'May these trained bytes be destroyed: no live capture holds them, and no unpurged artefact '
  'holding them has a training right that still stands. Raises on NULL rather than failing open.';

-- The destroy question is a capability, not a fact anybody may ask for: 0066 revokes its bake
-- equivalent from PUBLIC for the same reason, and the purge role is granted it in
-- `exulanica/db/roles.py` beside the two reads it needs to answer it.
revoke all on function scene_training_withdrawal_releases_artifact(uuid, bytea) from public;

commit;
