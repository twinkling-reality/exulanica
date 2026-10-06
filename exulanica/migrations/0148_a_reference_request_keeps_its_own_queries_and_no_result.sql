-- 0148_a_reference_request_keeps_its_own_queries_and_no_result.sql
-- A reference request keeps the queries it sent and no result a source returned.
--
-- A person may ask, for one draft, for notes on what the things in their words look like
-- (exulanica/references). The work runs off the request path as a job of kind 'reference_bundle'
-- on the generic job table (0001, leases 0016, timing 0018), which needs no change here. Two
-- tables, neither changing anything a recorded row relied on:
--
-- reference_request, the request's public face: who asked, for which drafter (purpose), whether
-- web notes were asked for (per request, so off unless asked), the idempotency key and the digest
-- of the request it named, the job that does the work, the digest of the prompt file the job asks
-- with, its steps as the page reads them, and at the end the reference bundle
-- (exulanica.reference-bundle/v1) with its digest, or the failure's code. A request is queued,
-- then running, then complete, partial, failed or cancelled (a queued one may also be cancelled or
-- expire as failed), and a finished request never changes. A stop once asked is never withdrawn.
-- The digest of the request an idempotency key named is cleared when the request ends, so nothing
-- derived from the person's words outlives the request. The job is named with its workspace, so a
-- request can only name a job of its own workspace.
-- reference_lookup, our own record of each search sent for a request: the source, the aspect, the
-- query text as it left, the outcome, the credits the source reported, its request id and how
-- many results it returned. No result's text, title, address or picture is kept here or anywhere:
-- the source's terms give no right to keep one. A record is appended and never changed.
--
-- Both are under forced row-level security keyed on the workspace.
begin;
select pg_advisory_xact_lock(119622309);

create table reference_request (
  workspace_id uuid not null,
  reference_id uuid not null default uuidv7(),
  owner_actor_id uuid not null,
  purpose text not null check (purpose in ('world_draft', 'kind', 'look', 'pieces', 'things')),
  web boolean not null,
  request_id uuid,
  request_sha256 text check (request_sha256 is null or request_sha256 ~ '^[0-9a-f]{64}$'),
  job_id uuid not null unique,
  prompts_sha256 text not null check (prompts_sha256 ~ '^[0-9a-f]{64}$'),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'complete', 'partial', 'failed', 'cancelled')),
  steps jsonb not null default '[]'::jsonb check (jsonb_typeof(steps) = 'array'),
  bundle jsonb check (
    bundle is null or (bundle->>'profile' = 'exulanica.reference-bundle/v1') is true),
  bundle_sha256 text check (bundle_sha256 is null or bundle_sha256 ~ '^[0-9a-f]{64}$'),
  failure text check (failure is null or failure ~ '^[a-z][a-z0-9_]{0,63}$'),
  cancel_requested_at timestamptz,
  created_at timestamptz not null default statement_timestamp(),
  finished_at timestamptz,
  primary key (workspace_id, reference_id),
  constraint reference_request_job foreign key (job_id, workspace_id)
    references job (job_id, workspace_id),
  constraint reference_request_digest_has_key check (request_sha256 is null or request_id is not null),
  constraint reference_request_digest_cleared check (finished_at is null or request_sha256 is null),
  constraint reference_request_bundle_and_digest check ((bundle is null) = (bundle_sha256 is null)),
  constraint reference_request_bundle_when_drafted
    check ((status in ('complete', 'partial')) = (bundle is not null)),
  constraint reference_request_finished
    check ((status in ('complete', 'partial', 'failed', 'cancelled')) = (finished_at is not null)),
  constraint reference_request_failure_named check ((status = 'failed') = (failure is not null))
);

create unique index reference_request_key on reference_request (workspace_id, owner_actor_id, request_id)
  where request_id is not null;
create index reference_request_recent on reference_request (workspace_id, owner_actor_id, created_at desc);

-- A finished request never changes, and nothing but its progress moves while it runs.
create function tg_reference_request_progress() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    if old.status in ('complete', 'partial', 'failed', 'cancelled') then
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
create trigger tg_reference_request_progress before insert or update on reference_request
  for each row execute function tg_reference_request_progress();

create table reference_lookup (
  workspace_id uuid not null,
  lookup_id uuid not null default uuidv7(),
  reference_id uuid not null,
  source text not null check (source ~ '^[a-z][a-z0-9_]{0,62}$'),
  aspect text not null check (aspect ~ '^[a-z][a-z0-9_]{0,62}$'),
  query text not null check (char_length(query) between 1 and 80),
  outcome text not null check (outcome ~ '^[a-z][a-z0-9_]{0,63}$'),
  credits integer not null check (credits >= 0),
  result_count integer not null check (result_count >= 0),
  provider_request_id text
    check (provider_request_id is null or provider_request_id ~ '^[A-Za-z0-9-]{1,64}$'),
  sent_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, lookup_id),
  foreign key (workspace_id, reference_id) references reference_request (workspace_id, reference_id)
);
create index reference_lookup_request on reference_lookup (workspace_id, reference_id, sent_at);

create function tg_reference_lookup_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    return new;
  end if;
  raise exception 'a reference lookup record is appended and never changed' using errcode = '23514';
end $fn$;
create trigger tg_reference_lookup_append_only before insert or update on reference_lookup
  for each row execute function tg_reference_lookup_append_only();

alter table reference_request enable row level security;
alter table reference_request force row level security;
create policy ws_isolation on reference_request
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table reference_lookup enable row level security;
alter table reference_lookup force row level security;
create policy ws_isolation on reference_lookup
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on reference_request to %I', r);
      execute format('grant select, insert on reference_lookup to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on reference_request, reference_lookup to %I', r);
    end if;
  end loop;
end $$;

commit;
