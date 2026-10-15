-- 0220_a_creature_s_look_is_made_by_a_job.sql
-- A creature's made look: asked as a row, made by the operator's run, worn by its kind.
--
-- A LOOK JOB is a row of creature_look: a person asks for a made look of a creature their
-- workspace keeps (a drafted kind, 0159 and 0172), and the row waits, queued. The paid step is not
-- the API's: an operator's run takes the queued rows of the workspaces it serves, writes each one's
-- request from the creature's kept documents (exulanica/things/creature_looks.py), and marks them
-- staged under the run's id with the request's digest. A GPU job makes a picture and a 3D model per
-- request, the operator's machine fits the creature's skeleton into each model, and the run ends
-- each row: made, naming the look the workspace now keeps (0159's look_version) by its document's
-- digest; refused, by the fit's code; failed, by why; with the row's share of what the run cost. A
-- queued or staged row may be cancelled. A row moves forward once and an ended row never changes.
--
-- A KIND LOOK is a row of kind_look: the look a workspace's creature wears wherever it is placed,
-- appended (a made look appends one), the newest per kind the one worn, until the creature is
-- erased or a newer one appended. A thing's own choice (0156) still wins over it.
--
-- WHAT THE ROWS HOLD. Ids, digests, codes, times, a cost and who asked or chose: no word. The
-- request a run writes carries the creature's drafted appearance words, and lives only in the run's
-- folder and the GPU job, never here; its digest is no sentence (it covers every bone of the plan).
-- The creature is named by its kind document's digest with no foreign key, as a draft names it
-- (0184), and the made look by its document's digest.
--
-- ERASURE REACHES BOTH TABLES, for 0172's sentence: every row that names a creature is erased with
-- it, and every row of a workspace with the workspace.
--   * A creature's erasure (0172's thing_erasure, written beside its creature tombstone) deletes
--     the look jobs and kind looks naming its kind, in tg_creature_look_erases_with_its_creature,
--     after insert on thing_erasure, as tg_thing_erasure_erases deletes the kind; a restore that
--     carries the erasure fires it again.
--   * A workspace tombstone deletes every look job and kind look of its workspace, in
--     tg_creature_look_erases_on_tombstone, keyed on the tombstone's columns, so a replayed
--     tombstone deletes the same rows. It acts on workspace scope only; its order among the
--     tombstone's after-insert triggers does not matter, as 0172's does not.
-- Both run as exulanica_definer, in the row's own workspace, which each asserts first; their
-- DELETE on the two tables is this migration's grant (0161's rule for every definer), used by these
-- two bodies alone. A run that later finds its row gone keeps nothing for it.
--
-- THE GUARDS. creature_look refuses a row inserted in any status but queued, and dates every row by
-- the statement that inserts it (a requester's limits count those dates); it refuses every delete
-- but the definer's, any change to who asked, for which creature and when, any move but queued to
-- staged or cancelled and staged to an end, and any change to a staged row's run
-- (tg_creature_look_moves_forward), so every job is asked, staged and ended in that order, once.
-- kind_look refuses every update and every delete but the definer's (0172's
-- tg_thing_store_append_only). The runtime may not update kind_look (provisioning's
-- INSERT_ONLY_TABLES).
--
-- At most one unfinished look job per creature: a second ask while one waits is answered with the
-- one already asked (a unique index on the unfinished rows).
--
-- Row-level security keeps every row inside its workspace. Neither table names a world.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

create table creature_look (
  workspace_id    uuid not null,
  look_id         uuid not null,
  requested_by    uuid not null,
  kind_sha256     text not null check (kind_sha256 ~ '^[0-9a-f]{64}$'),
  status          text not null default 'queued'
    check (status in ('queued', 'staged', 'made', 'refused', 'failed', 'cancelled')),
  -- The operator's run that staged it, and the digest of the request that run wrote.
  run_id          uuid,
  request_sha256  text check (request_sha256 ~ '^[0-9a-f]{64}$'),
  -- The look made, by its document's digest.
  look_sha256     text check (look_sha256 ~ '^[0-9a-f]{64}$'),
  refusal_code    text check (refusal_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  failure         text check (failure ~ '^[a-z][a-z0-9_]{0,63}$'),
  -- The row's share of what its run cost, in US dollars, once the run ended it.
  cost_usd        numeric(14, 8) check (cost_usd >= 0),
  created_at      timestamptz not null default statement_timestamp(),
  staged_at       timestamptz,
  finished_at     timestamptz,
  primary key (workspace_id, look_id),
  constraint creature_look_queued_has_no_run check (
    (status <> 'queued' or (run_id is null and request_sha256 is null and staged_at is null))
    is true),
  constraint creature_look_run_named_whole check (
    ((run_id is null) = (request_sha256 is null)
     and (run_id is null) = (staged_at is null)) is true),
  constraint creature_look_made_by_a_run check (
    (status not in ('staged', 'made', 'refused') or run_id is not null) is true),
  constraint creature_look_finished check (
    ((status in ('made', 'refused', 'failed', 'cancelled')) = (finished_at is not null)) is true),
  constraint creature_look_made_names_its_look check (
    ((status = 'made') = (look_sha256 is not null)) is true),
  constraint creature_look_refusal_named check (
    ((status = 'refused') = (refusal_code is not null)) is true),
  constraint creature_look_failure_named check (
    ((status in ('failed', 'cancelled')) = (failure is not null)) is true),
  constraint creature_look_cost_of_a_run check (
    (cost_usd is null or (run_id is not null and finished_at is not null)) is true)
);

-- One unfinished look job per creature.
create unique index creature_look_one_open_per_kind on creature_look (workspace_id, kind_sha256)
  where status in ('queued', 'staged');
-- A requester's open asks and their last hour, counted before a new one is queued.
create index creature_look_by_requester on creature_look (workspace_id, requested_by, created_at);
-- A run's rows, read when it ends them.
create index creature_look_by_run on creature_look (workspace_id, run_id) where run_id is not null;

comment on table creature_look is
  'A creature''s made look, asked by a person and made by the operator''s run '
  '(exulanica/world/creature_look_jobs.py): queued, staged under a run, then made, refused, failed '
  'or cancelled, once. It holds ids, digests, codes, times and a cost, and no word.';

create table kind_look (
  workspace_id  uuid not null,
  choice_id     bigint generated always as identity,
  kind_sha256   text not null check (kind_sha256 ~ '^[0-9a-f]{64}$'),
  look_sha256   text not null check (look_sha256 ~ '^[0-9a-f]{64}$'),
  -- The look job that made the look, where one did.
  look_id       uuid,
  chosen_by     uuid not null,
  chosen_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, choice_id)
);

create index kind_look_newest on kind_look (workspace_id, kind_sha256, choice_id desc);

comment on table kind_look is
  'The look a workspace''s creature wears wherever it is placed: appended, the newest per kind '
  'worn, a thing''s own choice still first (exulanica/world/thing_looks.py).';

create function tg_creature_look_moves_forward() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    if new.status <> 'queued' then
      raise exception 'a creature look is asked queued (not %)', new.status
        using errcode = 'integrity_constraint_violation';
    end if;
    -- Dated by the statement that asks it, whatever the row says: the limits count these dates.
    new.created_at := statement_timestamp();
    return new;
  end if;
  if tg_op = 'DELETE' then
    if current_user = 'exulanica_definer' then
      return old;
    end if;
    raise exception 'a creature look is erased with its creature or its workspace, never alone'
      using errcode = 'integrity_constraint_violation';
  end if;
  if (new.workspace_id, new.look_id, new.requested_by, new.kind_sha256, new.created_at)
     is distinct from
     (old.workspace_id, old.look_id, old.requested_by, old.kind_sha256, old.created_at) then
    raise exception 'a creature look keeps who asked, for which creature and when'
      using errcode = 'integrity_constraint_violation';
  end if;
  if not ((old.status = 'queued' and new.status in ('staged', 'cancelled'))
          or (old.status = 'staged'
              and new.status in ('made', 'refused', 'failed', 'cancelled'))) then
    raise exception 'a creature look moves from queued to staged to an end, once (% to %)',
      old.status, new.status
      using errcode = 'integrity_constraint_violation';
  end if;
  if old.status = 'staged'
     and (new.run_id, new.request_sha256, new.staged_at)
         is distinct from (old.run_id, old.request_sha256, old.staged_at) then
    raise exception 'a staged creature look keeps its run'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_creature_look_moves_forward before insert or update or delete on creature_look
  for each row execute function tg_creature_look_moves_forward();

create trigger tg_kind_look_append_only before update or delete on kind_look
  for each row execute function tg_thing_store_append_only();

create trigger tg_creature_look_binding before insert on creature_look
  for each row execute function tg_thing_store_binding();
create trigger tg_kind_look_binding before insert on kind_look
  for each row execute function tg_thing_store_binding();

alter table creature_look enable row level security;
alter table creature_look force row level security;
create policy ws_isolation on creature_look
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

alter table kind_look enable row level security;
alter table kind_look force row level security;
create policy ws_isolation on kind_look
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- --------------------------------------------------------------------------------------------
-- The erasures.
-- --------------------------------------------------------------------------------------------

create function tg_creature_look_erases_with_its_creature() returns trigger
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  delete from kind_look k where k.workspace_id = new.workspace_id and k.kind_sha256 = new.sha256;
  delete from creature_look l
   where l.workspace_id = new.workspace_id and l.kind_sha256 = new.sha256;
  return null;
end $fn$;

comment on function tg_creature_look_erases_with_its_creature() is
  'A creature''s erasure deletes the look jobs and kind looks naming its kind. Runs as '
  'exulanica_definer, in the erasure''s own workspace.';

create trigger tg_creature_look_erases_with_its_creature after insert on thing_erasure
  for each row execute function tg_creature_look_erases_with_its_creature();

create function tg_creature_look_erases_on_tombstone() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope::text <> 'workspace' then
    return new;
  end if;
  -- Row-level security binds this owner, so the tombstone's workspace must be the session's.
  perform assert_workspace_context(new.workspace_id);
  delete from kind_look k where k.workspace_id = new.workspace_id;
  delete from creature_look l where l.workspace_id = new.workspace_id;
  return new;
end $fn$;

comment on function tg_creature_look_erases_on_tombstone() is
  'A workspace tombstone deletes every look job and kind look of its workspace. Runs as '
  'exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_creature_look_erases_on_tombstone
  after insert on tombstone
  for each row execute function tg_creature_look_erases_on_tombstone();

-- --------------------------------------------------------------------------------------------
-- The two definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ begin
  execute format('alter function tg_creature_look_erases_with_its_creature() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_creature_look_erases_on_tombstone() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function tg_creature_look_erases_with_its_creature() from public;
revoke all on function tg_creature_look_erases_on_tombstone() from public;

-- The erasures' reads and deletes. The tombstone and the erasure they read are 0161's and 0172's.
grant select, delete on creature_look, kind_look to exulanica_definer;
alter function tg_creature_look_erases_with_its_creature() owner to exulanica_definer;
alter function tg_creature_look_erases_on_tombstone() owner to exulanica_definer;

commit;
