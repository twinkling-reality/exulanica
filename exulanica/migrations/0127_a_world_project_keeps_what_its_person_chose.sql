-- 0127_a_world_project_keeps_what_its_person_chose.sql
-- A world project keeps what its person chose to keep about their work in one world, and nothing
-- the person did not choose.
--
-- `docs/product-direction.md` asks the Companion to retain "authorized project context,
-- preferences, accepted decisions and unresolved questions" that people "can inspect, correct and
-- delete". Until now the only durable Companion plane was 0043's conversation memory, which is per
-- person and per workspace, names no world, and keeps what was asked rather than what the person
-- decided to keep. This migration adds the second plane: a project bound to one world and one of
-- its authored versions, holding items the person wrote or accepted, each with its correction
-- history, and the ids of records the world's own authorities hold (edits, appearance versions,
-- control receipts, simulated events, open previews). It copies none of those records and is the
-- authority for none of them (`docs/world-memory-model.md`, project projections).
--
-- Nothing here is read from 0043. A remembered question is not a stated goal, and a conversation is
-- not permission to keep a profile of the person: an item exists only because the person wrote it,
-- or because they accepted a suggestion that names what it was drawn from. So this migration
-- backfills nothing.
--
-- --------------------------------------------------------------------------------------------
-- What the planes may not do
-- --------------------------------------------------------------------------------------------
--
-- No foreign key joins these tables to `world_interaction_*`, in either direction. A preference
-- kept here is evidence about what a person wants; a capability the system may exercise is a rule
-- (0043's header). The first may inform a proposal and may never author the second.
--
-- --------------------------------------------------------------------------------------------
-- Deletion erases what was said and keeps that it happened
-- --------------------------------------------------------------------------------------------
--
-- 0043 withdraws an answer by status and keeps its text. Here a withdrawn item's text, note and
-- references are cleared on every revision, and so are the request digests, because a SHA-256 of a
-- short sentence is the sentence to anyone who can guess it. What stays is the residue a later
-- reader needs to know that something existed and when it ended: ids, kinds, bases, origins,
-- instants, reasons and counts. Clearing a value does not remove earlier row versions, WAL or
-- backups; a restore re-applies every deletion its checkpoint carries (below), and nothing here
-- claims more than that.
--
-- A deletion is never blocked by a stale base, and it reaches everything derived from what it
-- deletes: an item copied from another item, and an item drawn from a Companion answer, go with
-- their source. Each cascade writes the source's own instant and tombstone, so replaying the carried
-- deletions earliest first ends each row with the status, instant, reason, tombstone and erasure its
-- deletion gave it. A row's changed_at and a project's revision are not replayed.
--
-- --------------------------------------------------------------------------------------------
-- A restore carries these deletions
-- --------------------------------------------------------------------------------------------
--
-- `exulanica/deletion/withdrawals.v2.json` names `world_project_share`, `world_project_item` and
-- `world_project`, in that order and ahead of Companion memory, as column kinds replayed earliest
-- first: a later deletion's cascade then finds every row an earlier one ended already ended, with
-- the values that deletion wrote. A project or item a tombstone deleted is not carried and is
-- re-derived by the replayed tombstone, as 0043's answers are; a share is carried whatever closed it.
-- Each gets 0107's seal trigger, so a sealed checkpoint refuses these withdrawals like every other.
--
-- Cascade functions run with their owner's rights, their path pinned and PUBLIC's EXECUTE revoked,
-- as 0090 and 0107 do: the roles that delete a Companion answer or write a tombstone (the runtime,
-- the judge, a restore) do not all hold UPDATE here, and a trigger fires without EXECUTE.

begin;

select pg_advisory_xact_lock(119622309);

create type world_project_item_kind as enum
  ('goal', 'preference', 'question', 'task', 'decision', 'event');

-- Where an item's words come from. `docs/world-memory-model.md` keeps observed, authored,
-- generated and simulated content from borrowing one another's truth status; these four keep a
-- person's own statement, a suggestion somebody else drew, an accepted outcome and a simulated
-- event apart in the same way.
create type world_project_item_basis as enum
  ('user_statement', 'inferred_suggestion', 'recorded_outcome', 'simulated_event');

create type world_project_item_status as enum ('proposed', 'active', 'resolved', 'withdrawn');

create type world_project_withdrawal_reason as enum
  ('deleted', 'rejected', 'project_deleted', 'source_withdrawn', 'workspace_deleted');

create type world_project_item_origin as enum ('person', 'companion');

-- --------------------------------------------------------------------------------------------
-- 1. The project, and the versions it has been bound to
-- --------------------------------------------------------------------------------------------

create table world_project (
  workspace_id    uuid not null,
  project_id      uuid not null default uuidv7(),
  world_id        text not null check (length(world_id) between 1 and 200),
  owner_actor_id  uuid not null,
  -- Content: present exactly while the project is.
  title           text check (title is null or (length(title) between 1 and 200
                                                and btrim(title) <> '')),
  -- The authored version the project works on now: a branch head, whose exact state the binding
  -- history records.
  version_id      uuid not null,
  -- The compare-and-swap token every write carries and moves by one.
  revision        bigint not null default 1 check (revision >= 1),
  request_id      uuid,
  request_sha256  text check (request_sha256 is null or request_sha256 ~ '^[0-9a-f]{64}$'),
  created_at      timestamptz not null default statement_timestamp(),
  changed_at      timestamptz not null default statement_timestamp(),
  withdrawn_at    timestamptz,
  -- NULL when the person deleted it; the tombstone that reached it otherwise.
  withdrawn_by    uuid references tombstone(tombstone_id),

  primary key (workspace_id, project_id),
  unique (workspace_id, world_id, project_id),
  constraint world_project_world_is_registered foreign key (workspace_id, world_id)
    references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  constraint world_project_title_while_it_exists check ((withdrawn_at is null) = (title is not null)),
  -- A digest belongs to a key; a rename clears it, because it digests the title it replaced.
  constraint world_project_request_digest_has_its_key check (
    request_sha256 is null or request_id is not null),
  constraint world_project_erased_digest check (withdrawn_at is null or request_sha256 is null),
  constraint world_project_tombstone_has_an_instant check (
    withdrawn_by is null or withdrawn_at is not null)
);

-- An idempotency key names one request of one person.
create unique index world_project_request_key
  on world_project (workspace_id, owner_actor_id, request_id) where request_id is not null;

-- The project list: a person's projects in one world, newest first.
create index world_project_owner_idx
  on world_project (workspace_id, world_id, owner_actor_id, changed_at desc)
  where withdrawn_at is null;

create table world_project_binding (
  workspace_id  uuid not null,
  project_id    uuid not null,
  binding_seq   integer not null check (binding_seq >= 1),
  world_id      text not null check (length(world_id) between 1 and 200),
  version_id    uuid not null,
  -- The version's exact state when it was bound, because a version id alone is a moving head.
  state_sha256  text not null check (state_sha256 ~ '^[0-9a-f]{64}$'),
  edit_seq      bigint not null check (edit_seq >= 0),
  bound_by      uuid not null,
  bound_at      timestamptz not null default statement_timestamp(),

  primary key (workspace_id, project_id, binding_seq),
  constraint world_project_binding_world_is_registered foreign key (workspace_id, world_id)
    references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, project_id)
    references world_project (workspace_id, world_id, project_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id)
);

-- --------------------------------------------------------------------------------------------
-- 2. Items, their revisions, and what each was drawn from
-- --------------------------------------------------------------------------------------------

create table world_project_item (
  workspace_id      uuid not null,
  item_id           uuid not null default uuidv7(),
  world_id          text not null check (length(world_id) between 1 and 200),
  project_id        uuid not null,
  author_actor_id   uuid not null,
  kind              world_project_item_kind not null,
  status            world_project_item_status not null,
  current_revision  integer not null default 1 check (current_revision between 1 and 50),
  request_id        uuid,
  request_sha256    text check (request_sha256 is null or request_sha256 ~ '^[0-9a-f]{64}$'),
  created_at        timestamptz not null default statement_timestamp(),
  changed_at        timestamptz not null default statement_timestamp(),
  reviewed_at       timestamptz,
  resolved_at       timestamptz,
  withdrawn_at      timestamptz,
  withdrawn_by      uuid references tombstone(tombstone_id),
  withdrawn_reason  world_project_withdrawal_reason,

  primary key (workspace_id, item_id),
  unique (workspace_id, project_id, item_id),
  constraint world_project_item_world_is_registered foreign key (workspace_id, world_id)
    references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, project_id)
    references world_project (workspace_id, world_id, project_id),
  constraint world_project_item_withdrawal_is_whole check (
    (status = 'withdrawn') = (withdrawn_at is not null)
    and (status = 'withdrawn') = (withdrawn_reason is not null)),
  constraint world_project_item_tombstone_has_an_instant check (
    withdrawn_by is null or withdrawn_at is not null),
  constraint world_project_item_resolution_has_an_instant check (
    (status <> 'resolved' or resolved_at is not null)
    and (resolved_at is null or status in ('resolved', 'withdrawn'))),
  constraint world_project_item_proposal_is_undecided check (
    status <> 'proposed' or reviewed_at is null),
  constraint world_project_item_request_digest_while_it_exists check (
    status = 'withdrawn' or (request_id is null) = (request_sha256 is null)),
  constraint world_project_item_erased_digest check (
    status <> 'withdrawn' or request_sha256 is null)
);

create unique index world_project_item_request_key
  on world_project_item (workspace_id, author_actor_id, request_id) where request_id is not null;

create index world_project_item_project_idx
  on world_project_item (workspace_id, project_id, changed_at desc)
  where status <> 'withdrawn';

create table world_project_item_revision (
  workspace_id  uuid not null,
  item_id       uuid not null,
  revision      integer not null check (revision between 1 and 50),
  basis         world_project_item_basis not null,
  origin        world_project_item_origin not null,
  -- Content, cleared when the item is withdrawn.
  text          text check (text is null or (length(text) between 1 and 2000
                                             and btrim(text) <> '')),
  note          text check (note is null or length(note) between 1 and 2000),
  refs          jsonb check (refs is null or (jsonb_typeof(refs) = 'array'
                                              and jsonb_array_length(refs) <= 8)),
  recorded_by   uuid not null,
  recorded_at   timestamptz not null default statement_timestamp(),
  erased_at     timestamptz,

  primary key (workspace_id, item_id, revision),
  foreign key (workspace_id, item_id) references world_project_item (workspace_id, item_id),
  constraint world_project_revision_erasure_is_whole check (
    (erased_at is null) = (refs is not null)
    and (erased_at is null or (text is null and note is null))),
  -- A suggestion is somebody else's words about the person; the person's own words are never
  -- filed as one, and nothing but the Companion writes one.
  constraint world_project_revision_origin_matches_basis check (
    (basis = 'inferred_suggestion') = (origin = 'companion'))
);

create table world_project_item_source (
  workspace_id      uuid not null,
  item_id           uuid not null,
  ordinal           smallint not null check (ordinal between 0 and 15),
  source_answer_id  uuid,
  source_item_id    uuid,

  primary key (workspace_id, item_id, ordinal),
  foreign key (workspace_id, item_id) references world_project_item (workspace_id, item_id),
  foreign key (workspace_id, source_answer_id)
    references companion_answer (workspace_id, answer_id),
  foreign key (workspace_id, source_item_id)
    references world_project_item (workspace_id, item_id),
  constraint world_project_source_names_one_source check (
    (source_answer_id is null) <> (source_item_id is null)),
  constraint world_project_source_is_not_itself check (source_item_id is distinct from item_id)
);

create unique index world_project_source_answer_once
  on world_project_item_source (workspace_id, item_id, source_answer_id)
  where source_answer_id is not null;
create unique index world_project_source_item_once
  on world_project_item_source (workspace_id, item_id, source_item_id)
  where source_item_id is not null;
-- The two questions a withdrawal asks: which items came from this answer, and from this item.
create index world_project_source_by_answer
  on world_project_item_source (workspace_id, source_answer_id)
  where source_answer_id is not null;
create index world_project_source_by_item
  on world_project_item_source (workspace_id, source_item_id)
  where source_item_id is not null;

-- --------------------------------------------------------------------------------------------
-- 3. Shares: what another person of the workspace may read
-- --------------------------------------------------------------------------------------------

-- One row per decision to share, never re-opened: sharing again is a new row, so stopping one is
-- a withdrawal a restore can carry rather than a flag a restore could turn back on.
create table world_project_share (
  workspace_id  uuid not null,
  share_id      uuid not null default uuidv7(),
  project_id    uuid not null,
  -- NULL shares the project itself: its title, binding and counts. An item needs its own share.
  item_id       uuid,
  shared_by     uuid not null,
  shared_at     timestamptz not null default statement_timestamp(),
  withdrawn_at  timestamptz,

  primary key (workspace_id, share_id),
  foreign key (workspace_id, project_id) references world_project (workspace_id, project_id),
  foreign key (workspace_id, project_id, item_id)
    references world_project_item (workspace_id, project_id, item_id)
);

create unique index world_project_share_open_once
  on world_project_share (workspace_id, project_id,
                          coalesce(item_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where withdrawn_at is null;

-- --------------------------------------------------------------------------------------------
-- 4. Remembered simulation citations (gap N-G3)
-- --------------------------------------------------------------------------------------------

-- A remembered answer about a world's simulated people keeps what it cited and whom its labels
-- stood for, as ids. 0043 kept photograph citations only, so such an answer was never kept. No
-- event line is stored: it is read again, under current authorization, when the answer is drawn.
create table companion_answer_simulation_citation (
  workspace_id   uuid not null,
  answer_id      uuid not null,
  ordinal        integer not null check (ordinal between 0 and 4096),
  result_kind    text not null check (result_kind in ('synthetic_inhabitant', 'simulation_event')),
  world_id       text not null check (length(world_id) between 1 and 200),
  version_id     uuid not null,
  inhabitant_id  uuid not null,
  event_id       uuid,
  tick           bigint not null check (tick >= 0),
  input_seq      bigint check (input_seq is null or input_seq >= 1),
  object_id      text check (object_id is null or length(object_id) between 1 and 200),
  edit_seq       bigint check (edit_seq is null or edit_seq >= 1),
  edit_id        uuid,

  primary key (workspace_id, answer_id, ordinal),
  constraint companion_answer_simulation_citation_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, answer_id) references companion_answer (workspace_id, answer_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  constraint companion_simulation_event_names_its_event check (
    (result_kind = 'simulation_event') = (event_id is not null)),
  constraint companion_simulation_edit_is_named_whole check ((edit_seq is null) = (edit_id is null))
);

create table companion_answer_simulation_label (
  workspace_id   uuid not null,
  answer_id      uuid not null,
  label          text not null check (label ~ '^\[(inhabitant|spot) [A-Z]+\]$'),
  version_id     uuid,
  inhabitant_id  uuid,
  spot_target    text check (spot_target is null or length(spot_target) between 1 and 500),

  primary key (workspace_id, answer_id, label),
  foreign key (workspace_id, answer_id) references companion_answer (workspace_id, answer_id),
  constraint companion_simulation_label_names_one_thing check (
    (label like '[inhabitant %' and version_id is not null and inhabitant_id is not null
     and spot_target is null)
    or (label like '[spot %' and spot_target is not null and version_id is null
        and inhabitant_id is null))
);

create trigger tg_companion_answer_simulation_citation_append_only
  before update or delete on companion_answer_simulation_citation
  for each row execute function tg_companion_memory_append_only();
create trigger tg_companion_answer_simulation_label_append_only
  before update or delete on companion_answer_simulation_label
  for each row execute function tg_companion_memory_append_only();

create function tg_companion_simulation_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;

create trigger tg_guard_companion_answer_simulation_citation
  before insert on companion_answer_simulation_citation
  for each row execute function tg_companion_simulation_live();
create trigger tg_guard_companion_answer_simulation_label
  before insert on companion_answer_simulation_label
  for each row execute function tg_companion_simulation_live();

-- --------------------------------------------------------------------------------------------
-- 5. Guards: what may be written, and the one lifecycle each row may follow
-- --------------------------------------------------------------------------------------------

-- A workspace a tombstone deleted as a whole takes no new project content (0043 left this open
-- for answers; it is closed here from the first row).
create function world_project_workspace_deleted(p_workspace uuid) returns boolean
language sql stable as $fn$
  select exists (select 1 from tombstone t
                  where t.workspace_id = p_workspace and t.scope = 'workspace');
$fn$;
do $pin$ begin
  execute format('alter function world_project_workspace_deleted(uuid) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $pin$;

create function tg_world_project_lifecycle() returns trigger
language plpgsql as $fn$
declare
  v_changed text;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if world_project_workspace_deleted(new.workspace_id) then
      perform tombstone_refuse('world_project');
    end if;
    if new.withdrawn_at is not null or new.withdrawn_by is not null or new.revision <> 1 then
      raise exception 'a world project starts live at revision 1'
        using errcode = 'integrity_constraint_violation';
    end if;
    return new;
  end if;
  v_changed := case
    when new.workspace_id   is distinct from old.workspace_id   then 'workspace_id'
    when new.project_id     is distinct from old.project_id     then 'project_id'
    when new.world_id       is distinct from old.world_id       then 'world_id'
    when new.owner_actor_id is distinct from old.owner_actor_id then 'owner_actor_id'
    when new.request_id     is distinct from old.request_id     then 'request_id'
    when new.created_at     is distinct from old.created_at     then 'created_at'
    else null
  end;
  if v_changed is not null then
    raise exception 'world project % is not editable: % may not be rewritten', old.project_id,
      v_changed using errcode = 'integrity_constraint_violation';
  end if;
  if old.withdrawn_at is not null then
    raise exception 'world project % is deleted and does not come back', old.project_id
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.revision not in (old.revision, old.revision + 1) then
    raise exception 'a world project revision moves by one' using errcode = 'integrity_constraint_violation';
  end if;
  if new.withdrawn_at is not null then
    -- Deleting a project erases what it said: its title and the digest of the request that made
    -- it. Here rather than in the caller, so a restore's own update erases too.
    new.title := null;
    new.request_sha256 := null;
  elsif new.withdrawn_by is not null then
    raise exception 'a tombstone names a deletion' using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_project_lifecycle
  before insert or update on world_project
  for each row execute function tg_world_project_lifecycle();

create function tg_world_project_binding_live() returns trigger
language plpgsql as $fn$
declare
  v_project record;
begin
  perform assert_workspace_context(new.workspace_id);
  select p.version_id, p.withdrawn_at into v_project
    from world_project p
   where p.workspace_id = new.workspace_id and p.project_id = new.project_id;
  if v_project.withdrawn_at is not null then
    raise exception 'a deleted world project takes no binding'
      using errcode = 'integrity_constraint_violation';
  end if;
  if v_project.version_id is distinct from new.version_id then
    raise exception 'a binding records the version its project is bound to'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.binding_seq <> coalesce((select max(b.binding_seq) from world_project_binding b
                                   where b.workspace_id = new.workspace_id
                                     and b.project_id = new.project_id), 0) + 1 then
    raise exception 'world project bindings are numbered without a gap'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_project_binding_live
  before insert on world_project_binding
  for each row execute function tg_world_project_binding_live();

create function tg_world_project_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation',
          hint = 'A project records a new binding, revision or source; it never rewrites one.';
end $fn$;

create trigger tg_world_project_binding_append_only
  before update or delete on world_project_binding
  for each row execute function tg_world_project_append_only();
create trigger tg_world_project_item_source_append_only
  before update or delete on world_project_item_source
  for each row execute function tg_world_project_append_only();

create trigger tg_world_project_no_delete
  before delete on world_project
  for each row execute function tg_world_project_append_only();
create trigger tg_world_project_item_no_delete
  before delete on world_project_item
  for each row execute function tg_world_project_append_only();
create trigger tg_world_project_item_revision_no_delete
  before delete on world_project_item_revision
  for each row execute function tg_world_project_append_only();
create trigger tg_world_project_share_no_delete
  before delete on world_project_share
  for each row execute function tg_world_project_append_only();

create function tg_world_project_item_lifecycle() returns trigger
language plpgsql as $fn$
declare
  v_changed text;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if world_project_workspace_deleted(new.workspace_id) then
      perform tombstone_refuse('world_project_item');
    end if;
    -- One writer per project: its owner. Another person reads what the owner shares.
    if not exists (select 1 from world_project p
                    where p.workspace_id = new.workspace_id and p.project_id = new.project_id
                      and p.withdrawn_at is null and p.owner_actor_id = new.author_actor_id) then
      raise exception 'only a live project''s owner adds to it'
        using errcode = 'integrity_constraint_violation';
    end if;
    if new.status not in ('proposed', 'active') or new.current_revision <> 1
       or new.reviewed_at is not null or new.resolved_at is not null then
      raise exception 'a world project item starts as a proposal or active at revision 1'
        using errcode = 'integrity_constraint_violation';
    end if;
    return new;
  end if;
  v_changed := case
    when new.workspace_id    is distinct from old.workspace_id    then 'workspace_id'
    when new.item_id         is distinct from old.item_id         then 'item_id'
    when new.world_id        is distinct from old.world_id        then 'world_id'
    when new.project_id      is distinct from old.project_id      then 'project_id'
    when new.author_actor_id is distinct from old.author_actor_id then 'author_actor_id'
    when new.kind            is distinct from old.kind            then 'kind'
    when new.request_id      is distinct from old.request_id      then 'request_id'
    when new.created_at      is distinct from old.created_at      then 'created_at'
    else null
  end;
  if v_changed is not null then
    raise exception 'world project item % is not editable: % may not be rewritten', old.item_id,
      v_changed using errcode = 'integrity_constraint_violation';
  end if;
  if old.status = 'withdrawn' then
    raise exception 'world project item % is deleted and does not come back', old.item_id
      using errcode = 'integrity_constraint_violation';
  end if;
  -- The transitions, and nothing else: a proposal is accepted or rejected, an active item is
  -- resolved, and anything may be deleted.
  if new.status is distinct from old.status and not (
       (old.status = 'proposed' and new.status in ('active', 'withdrawn'))
    or (old.status = 'active' and new.status in ('resolved', 'withdrawn'))
    or (old.status = 'resolved' and new.status = 'withdrawn')) then
    raise exception 'world project item % may not move from % to %', old.item_id, old.status,
      new.status using errcode = 'integrity_constraint_violation';
  end if;
  if new.current_revision not in (old.current_revision, old.current_revision + 1)
     or (new.current_revision <> old.current_revision
         and old.status not in ('proposed', 'active')) then
    raise exception 'a world project item takes a correction by one revision while it is open'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.status = 'withdrawn' then
    new.request_sha256 := null;
  end if;
  return new;
end $fn$;

create trigger tg_world_project_item_lifecycle
  before insert or update on world_project_item
  for each row execute function tg_world_project_item_lifecycle();

create function tg_world_project_item_revision_guard() returns trigger
language plpgsql as $fn$
declare
  v_item record;
begin
  perform assert_workspace_context(new.workspace_id);
  select i.kind, i.status, i.current_revision into v_item
    from world_project_item i
   where i.workspace_id = new.workspace_id and i.item_id = new.item_id;
  if tg_op = 'UPDATE' then
    -- Erasure is the one change, and only for a deleted item.
    if (to_jsonb(new) - 'text' - 'note' - 'refs' - 'erased_at')
         is distinct from (to_jsonb(old) - 'text' - 'note' - 'refs' - 'erased_at')
       or old.erased_at is not null or new.erased_at is null
       or new.text is not null or new.note is not null or new.refs is not null
       or v_item.status is distinct from 'withdrawn' then
      raise exception 'a world project revision is never rewritten; it is erased with its item'
        using errcode = 'integrity_constraint_violation';
    end if;
    return new;
  end if;
  if world_project_workspace_deleted(new.workspace_id) then
    perform tombstone_refuse('world_project_item_revision');
  end if;
  if v_item.status is null or v_item.status = 'withdrawn' or new.erased_at is not null then
    raise exception 'a deleted world project item takes no revision'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.revision <> v_item.current_revision then
    raise exception 'a revision is the item''s current revision, recorded once'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.revision > 1 and not exists (
       select 1 from world_project_item_revision r
        where r.workspace_id = new.workspace_id and r.item_id = new.item_id
          and r.revision = new.revision - 1) then
    raise exception 'world project revisions are numbered without a gap'
      using errcode = 'integrity_constraint_violation';
  end if;
  -- What each kind is, stated where no caller can skip it.
  if v_item.kind in ('goal', 'preference', 'question', 'task') then
    if new.basis not in ('user_statement', 'inferred_suggestion') or new.text is null then
      raise exception 'a % states its words as the person''s or as a suggestion', v_item.kind
        using errcode = 'check_violation';
    end if;
  elsif v_item.kind = 'decision' then
    if new.basis <> 'recorded_outcome' or jsonb_array_length(new.refs) = 0 then
      raise exception 'a decision is a recorded outcome naming at least one accepted record'
        using errcode = 'check_violation';
    end if;
  elsif v_item.kind = 'event' then
    if new.basis <> 'simulated_event' or jsonb_array_length(new.refs) = 0 then
      raise exception 'an event is a simulated event naming at least one simulated record'
        using errcode = 'check_violation';
    end if;
  end if;
  if new.revision = 1 and (new.basis = 'inferred_suggestion') <> (v_item.status = 'proposed') then
    raise exception 'a suggestion waits for review, and nothing else does'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_project_item_revision_guard
  before insert or update on world_project_item_revision
  for each row execute function tg_world_project_item_revision_guard();

-- Deferred, so the item row and its first revision can be written in either order within the
-- transaction and neither can be committed without the other.
create function tg_world_project_item_has_its_revision() returns trigger
language plpgsql as $fn$
begin
  if not exists (select 1 from world_project_item_revision r
                  where r.workspace_id = new.workspace_id and r.item_id = new.item_id
                    and r.revision = new.current_revision)
     and not exists (select 1 from world_project_item i
                      where i.workspace_id = new.workspace_id and i.item_id = new.item_id
                        and i.status = 'withdrawn') then
    raise exception 'world project item % has no revision %', new.item_id, new.current_revision
      using errcode = 'integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_world_project_item_has_its_revision
  after insert or update of current_revision on world_project_item
  deferrable initially deferred
  for each row execute function tg_world_project_item_has_its_revision();

create function tg_world_project_item_source_live() returns trigger
language plpgsql as $fn$
declare
  v_item record;
begin
  perform assert_workspace_context(new.workspace_id);
  select i.author_actor_id, i.project_id, i.status into v_item
    from world_project_item i
   where i.workspace_id = new.workspace_id and i.item_id = new.item_id;
  if v_item.status is null or v_item.status = 'withdrawn' then
    raise exception 'a deleted world project item takes no source'
      using errcode = 'integrity_constraint_violation';
  end if;
  -- A person's item is drawn from that person's own answer or item, never another person's.
  if new.source_answer_id is not null and not exists (
       select 1 from companion_answer a
        where a.workspace_id = new.workspace_id and a.answer_id = new.source_answer_id
          and a.actor_id = v_item.author_actor_id and a.status <> 'withdrawn') then
    raise exception 'a world project item names a Companion answer its author does not hold'
      using errcode = 'foreign_key_violation';
  end if;
  if new.source_item_id is not null and not exists (
       select 1 from world_project_item s
        where s.workspace_id = new.workspace_id and s.item_id = new.source_item_id
          and s.author_actor_id = v_item.author_actor_id and s.status <> 'withdrawn'
          and s.project_id <> v_item.project_id) then
    raise exception 'a world project item is copied from its author''s item in another project'
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_project_item_source_live
  before insert on world_project_item_source
  for each row execute function tg_world_project_item_source_live();

create function tg_world_project_share_lifecycle() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if world_project_workspace_deleted(new.workspace_id) then
      perform tombstone_refuse('world_project_share');
    end if;
    if new.withdrawn_at is not null or not exists (
         select 1 from world_project p
          where p.workspace_id = new.workspace_id and p.project_id = new.project_id
            and p.withdrawn_at is null and p.owner_actor_id = new.shared_by) then
      raise exception 'only a live project''s owner shares it'
        using errcode = 'integrity_constraint_violation';
    end if;
    if new.item_id is not null and not exists (
         select 1 from world_project_item i
          where i.workspace_id = new.workspace_id and i.item_id = new.item_id
            and i.status in ('active', 'resolved')) then
      raise exception 'only an accepted item is shared'
        using errcode = 'integrity_constraint_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'withdrawn_at') is distinct from (to_jsonb(old) - 'withdrawn_at')
     or old.withdrawn_at is not null or new.withdrawn_at is null then
    raise exception 'a share is only ever stopped, once'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_project_share_lifecycle
  before insert or update on world_project_share
  for each row execute function tg_world_project_share_lifecycle();

-- --------------------------------------------------------------------------------------------
-- 6. Cascades, with their owner's rights and the source's own instant
-- --------------------------------------------------------------------------------------------

create function tg_world_project_withdraws_its_items() returns trigger
language plpgsql security definer as $fn$
begin
  if old.withdrawn_at is null and new.withdrawn_at is not null then
    -- Under FORCE RLS its owner sees only the workspace the session names; a session that names
    -- none would erase nothing, so it is refused rather than allowed to.
    perform assert_workspace_context(new.workspace_id);
    update world_project_item i
       set status = 'withdrawn',
           withdrawn_at = new.withdrawn_at,
           withdrawn_by = new.withdrawn_by,
           withdrawn_reason = case when new.withdrawn_by is null
                                   then 'project_deleted'::world_project_withdrawal_reason
                                   else 'workspace_deleted'::world_project_withdrawal_reason end,
           changed_at = new.withdrawn_at
     where i.workspace_id = new.workspace_id and i.project_id = new.project_id
       and i.status <> 'withdrawn';
    update world_project_share s
       set withdrawn_at = new.withdrawn_at
     where s.workspace_id = new.workspace_id and s.project_id = new.project_id
       and s.withdrawn_at is null;
  end if;
  return null;
end $fn$;

create trigger tg_world_project_withdraws_its_items
  after update of withdrawn_at on world_project
  for each row execute function tg_world_project_withdraws_its_items();

create function tg_world_project_item_erases_on_withdrawal() returns trigger
language plpgsql security definer as $fn$
begin
  if old.status <> 'withdrawn' and new.status = 'withdrawn' then
    perform assert_workspace_context(new.workspace_id);
    update world_project_item_revision r
       set text = null, note = null, refs = null, erased_at = new.withdrawn_at
     where r.workspace_id = new.workspace_id and r.item_id = new.item_id
       and r.erased_at is null;
    update world_project_share s
       set withdrawn_at = new.withdrawn_at
     where s.workspace_id = new.workspace_id and s.item_id = new.item_id
       and s.withdrawn_at is null;
    -- What was copied from this item goes with it; each copy's own trigger carries it further.
    update world_project_item d
       set status = 'withdrawn',
           withdrawn_at = new.withdrawn_at,
           withdrawn_by = new.withdrawn_by,
           withdrawn_reason = 'source_withdrawn',
           changed_at = new.withdrawn_at
     where d.workspace_id = new.workspace_id and d.status <> 'withdrawn'
       and exists (select 1 from world_project_item_source s
                    where s.workspace_id = d.workspace_id and s.item_id = d.item_id
                      and s.source_item_id = new.item_id);
  end if;
  return null;
end $fn$;

create trigger tg_world_project_item_erases_on_withdrawal
  after update of status on world_project_item
  for each row execute function tg_world_project_item_erases_on_withdrawal();

-- Once per statement, so every answer one statement withdraws (a deleted lineage, or the answers
-- a tombstone reaches) locks the projects of the items drawn from them together, in id order, and
-- only then the items: the order every writer of a project takes them in after the answers it names.
-- A row trigger would lock each answer's projects in turn, in whatever order the update visits them.
-- Transition tables admit no column list, so this runs after every update of an answer and does
-- nothing unless one became withdrawn.
create function tg_companion_answers_withdraw_project_items() returns trigger
language plpgsql security definer as $fn$
declare
  v_workspace uuid;
begin
  for v_workspace in
    select distinct n.workspace_id from changed_answers n
      join previous_answers o on o.workspace_id = n.workspace_id and o.answer_id = n.answer_id
     where n.status = 'withdrawn' and o.status <> 'withdrawn'
  loop
    perform assert_workspace_context(v_workspace);
  end loop;
  perform 1 from world_project p
   where p.project_id in (
           select d.project_id
             from changed_answers n
             join previous_answers o on o.workspace_id = n.workspace_id and o.answer_id = n.answer_id
             join world_project_item_source s
               on s.workspace_id = n.workspace_id and s.source_answer_id = n.answer_id
             join world_project_item d on d.workspace_id = s.workspace_id and d.item_id = s.item_id
            where n.status = 'withdrawn' and o.status <> 'withdrawn' and d.status <> 'withdrawn')
   order by p.project_id
     for update of p;
  update world_project_item d
     set status = 'withdrawn',
         withdrawn_at = drawn.withdrawn_at,
         withdrawn_by = drawn.withdrawn_by,
         withdrawn_reason = 'source_withdrawn',
         changed_at = drawn.withdrawn_at
    from (select s.workspace_id, s.item_id,
                 min(n.withdrawn_at) as withdrawn_at,
                 (array_agg(n.withdrawn_by order by n.withdrawn_at, n.answer_id))[1] as withdrawn_by
            from changed_answers n
            join previous_answers o on o.workspace_id = n.workspace_id and o.answer_id = n.answer_id
            join world_project_item_source s
              on s.workspace_id = n.workspace_id and s.source_answer_id = n.answer_id
           where n.status = 'withdrawn' and o.status <> 'withdrawn'
           group by s.workspace_id, s.item_id) drawn
   where d.workspace_id = drawn.workspace_id and d.item_id = drawn.item_id
     and d.status <> 'withdrawn';
  return null;
end $fn$;

create trigger tg_companion_answers_withdraw_project_items
  after update on companion_answer
  referencing old table as previous_answers new table as changed_answers
  for each statement execute function tg_companion_answers_withdraw_project_items();

-- Keyed on the tombstone's own columns only, so the replayed tombstone reaches exactly what the
-- original did (0082's rule).
create function tg_tombstone_withdraws_project_context() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope = 'workspace' then
    perform assert_workspace_context(new.workspace_id);
    -- The key a project's creation holds shared: a creation that has not committed yet is waited
    -- for and then deleted here, and one that starts after this sees the tombstone and is refused.
    -- Not the workspace lock; this key names the project plane.
    perform pg_advisory_xact_lock(hashtextextended('world_project:' || new.workspace_id::text, 0));
    perform 1 from world_project p
     where p.workspace_id = new.workspace_id and p.withdrawn_at is null
     order by p.project_id
       for update of p;
    update world_project p
       set withdrawn_at = new.effective_at,
           withdrawn_by = new.tombstone_id,
           changed_at = new.effective_at
     where p.workspace_id = new.workspace_id and p.withdrawn_at is null;
  end if;
  return new;
end $fn$;

create trigger tg_tombstone_withdraws_project_context
  after insert on tombstone
  for each row execute function tg_tombstone_withdraws_project_context();

do $pin$
declare
  f text;
begin
  foreach f in array array[
    'tg_world_project_withdraws_its_items()',
    'tg_world_project_item_erases_on_withdrawal()',
    'tg_companion_answers_withdraw_project_items()',
    'tg_tombstone_withdraws_project_context()'] loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f, current_schema());
    execute format('revoke all on function %s from public', f);
  end loop;
end $pin$;

-- --------------------------------------------------------------------------------------------
-- 7. The seal: a sealed restore checkpoint refuses these withdrawals (0107)
-- --------------------------------------------------------------------------------------------

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at on world_project
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of status, withdrawn_at, withdrawn_reason on world_project_item
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at on world_project_share
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- --------------------------------------------------------------------------------------------
-- 8. Row-level security, on the same terms as every other workspace-scoped table
-- --------------------------------------------------------------------------------------------

do $$
declare
  t text;
begin
  foreach t in array array[
    'world_project',
    'world_project_binding',
    'world_project_item',
    'world_project_item_revision',
    'world_project_item_source',
    'world_project_share',
    'companion_answer_simulation_citation',
    'companion_answer_simulation_label'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

commit;
