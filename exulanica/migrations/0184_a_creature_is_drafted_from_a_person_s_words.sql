-- 0184_a_creature_is_drafted_from_a_person_s_words.sql
-- A person's words drafted into a creature: a request kept as a row, played by a job.
--
-- A DRAFT is a row of creature_draft and a job of kind 'creature_draft' on the generic job table,
-- claimed as a reference job is (0148): for update skip locked, a lease and a claim token, at most
-- a few claims, a stranded or unclaimed job ended as failed. The job asks the creature drafter for
-- a creature, and a creature the checks pass is kept in the workspace's own store (0159); the
-- draft then names the kind it made by the digest of its document alone. A draft the checks
-- refuse names the check's code and the field of the drafter's form it refused, never a sentence:
-- a check's sentence may quote the drafted label, so a person reads the code's fixed sentence. A
-- draft that could not be made names why by code.
--
-- THE WORDS. The job's payload holds the person's words as they are sent (every saved name
-- replaced) and nothing more, and every end of a draft blanks them, so after a draft ends nothing
-- of the words is kept here, not even their digest: a digest of a short sentence is the sentence.
-- The kept kind is named by its document's digest with no foreign key, so erasing the creature
-- (thing_erasure) deletes its kind as it deletes any other, and the draft then names a kind nobody
-- holds.
-- The row is read by its requester alone through the routes.
--
-- A WORKSPACE TOMBSTONE ends the workspace's unfinished drafts in its own transaction: each queued or
-- running creature job is cancelled with its words blanked, and its draft ends cancelled, failure
-- workspace_deleted, so a person who erases their workspace leaves no word of a draft behind. The
-- trigger runs as whoever writes the tombstone (the runtime role, or the owner a restore replays as,
-- each of which may update both tables), reaches only the tombstone's own workspace, keyed on the
-- tombstone's columns so a replayed tombstone ends the same drafts, sorts after 0137's trigger so the
-- workspace's lock is already held, and updates each job before its draft, as every other path
-- does. A worker that drafted for a cancelled draft finds its claim gone and keeps nothing; a call
-- already sent finishes at the provider, and its answer is discarded.
--
-- Row-level security keeps every row inside its workspace. A draft names no world or version.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

create table creature_draft (
  workspace_id    uuid not null,
  draft_id        uuid not null,
  owner_actor_id  uuid not null,
  job_id          uuid not null unique,
  status          text not null default 'queued'
    check (status in ('queued', 'running', 'kept', 'refused', 'failed', 'cancelled')),
  kind_sha256     text check (kind_sha256 ~ '^[0-9a-f]{64}$'),
  refusal_code    text check (refusal_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  refusal_field   text check (refusal_field ~ '^[a-z][a-z0-9_]{0,63}$'),
  failure         text check (failure ~ '^[a-z][a-z0-9_]{0,63}$'),
  model_id        text check (length(model_id) between 1 and 200),
  created_at      timestamptz not null default statement_timestamp(),
  -- When a worker first took the draft; a draft that ends untaken never started.
  started_at      timestamptz,
  finished_at     timestamptz,
  primary key (workspace_id, draft_id),
  constraint creature_draft_job foreign key (job_id, workspace_id)
    references job (job_id, workspace_id),
  constraint creature_draft_finished check (
    ((status in ('kept', 'refused', 'failed', 'cancelled')) = (finished_at is not null)) is true),
  constraint creature_draft_kept_names_its_kind check (
    ((status = 'kept') = (kind_sha256 is not null)) is true),
  constraint creature_draft_refusal_named check (
    ((status = 'refused') = (refusal_code is not null)) is true),
  constraint creature_draft_field_of_a_refusal check (
    (refusal_field is null or refusal_code is not null) is true),
  constraint creature_draft_failure_named check (
    ((status in ('failed', 'cancelled')) = (failure is not null)) is true),
  constraint creature_draft_started check ((status <> 'running' or started_at is not null) is true)
);

-- A requester's open drafts and their last hour, counted before a new one is queued.
create index creature_draft_by_requester on creature_draft (workspace_id, owner_actor_id, created_at);

comment on table creature_draft is
  'A person''s words drafted into a creature: the request, moved by its job under the job''s claim '
  '(exulanica/selection/creature_drafts.py). Its words live only in the job''s payload until the draft '
  'ends; the row keeps nothing of them, and names a kept kind by its document''s digest alone.';

create trigger tg_creature_draft_binding before insert on creature_draft
  for each row execute function tg_thing_store_binding();

alter table creature_draft enable row level security;
alter table creature_draft force row level security;
create policy ws_isolation on creature_draft
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

create function tg_creature_draft_ends_on_workspace_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope <> 'workspace' then
    return null;
  end if;
  update job
     set state = 'cancelled', lease_expires_at = null, claim_token = null, completed_at = now(),
         failure_class = 'creature_workspace_deleted', last_error = 'its workspace was deleted',
         duration_ms = greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint),
         payload = jsonb_build_object('draft_id', payload->'draft_id')
   where workspace_id = new.workspace_id
     and kind = 'creature_draft'
     and state in ('queued', 'running');
  update creature_draft
     set status = 'cancelled', failure = 'workspace_deleted', finished_at = now()
   where workspace_id = new.workspace_id
     and status in ('queued', 'running');
  return null;
end $fn$;

comment on function tg_creature_draft_ends_on_workspace_tombstone() is
  'A workspace tombstone cancels the workspace''s unfinished creature drafts and blanks the words '
  'in their jobs, in the tombstone''s own transaction (exulanica/selection/creature_drafts.py).';

create trigger tg_creature_draft_ends_on_workspace_tombstone
  after insert on tombstone
  for each row execute function tg_creature_draft_ends_on_workspace_tombstone();

commit;
