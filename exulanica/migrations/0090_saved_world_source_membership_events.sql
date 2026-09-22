-- Detach and rebind as later membership events on a saved world's reference photographs.
--
-- Migration 0086 made every attachment row unique per (workspace, entry, capture) for all
-- history, so a photograph removed from a world could never be added back. This replaces that
-- with a current-membership pointer per (workspace, entry, capture):
--
--   attach   inserts the pointer. The photograph must have no membership history on the entry.
--   detach   appends a detach event naming the current attachment; the pointer becomes null.
--   rebind   appends a new attachment row after a new human review; a null pointer names it.
--
-- History stays append-only. No attachment, operation or detach row is updated or deleted, and
-- no media is touched. The pointer is derived state: it moves only from the AFTER INSERT
-- triggers on attachment and detach rows below, which run with the table owner's rights. The
-- runtime role may read it and may not write it, so no runtime statement can change which
-- photographs a world uses without recording an event that says so.
--
-- Forward-only. After the first rebind two attachment rows name one capture on one entry, and
-- 0086's constraint cannot be restored over them. Recovery is a restore from backup.

begin;

select pg_advisory_xact_lock(119622309);

-- 1. 0086's all-history uniqueness, found by its definition rather than by a generated name.
do $$
declare constraint_name text;
begin
  select c.conname into constraint_name
  from pg_constraint c
  where c.conrelid = 'saved_world_source_attachment'::regclass
    and c.contype = 'u'
    and pg_get_constraintdef(c.oid) = 'UNIQUE (workspace_id, entry_id, capture_id)';
  if constraint_name is null then
    raise exception 'saved_world_source_attachment capture uniqueness constraint missing';
  end if;
  execute format(
    'alter table saved_world_source_attachment drop constraint %I',
    constraint_name
  );
end $$;

-- Lets the pointer and the detach events name an attachment together with its entry and
-- capture, so a foreign key rather than a trigger proves they agree.
alter table saved_world_source_attachment
  add constraint saved_world_source_attachment_membership_key
    unique (workspace_id, entry_id, capture_id, attachment_id);

alter table saved_world_source_attachment_operation
  add column kind text not null default 'attach'
    check (kind in ('attach', 'rebind'));

-- 2. The current collection. attachment_id null means the photograph was removed from this
-- world; its attachment rows remain as history.
create table saved_world_source_current_membership (
  workspace_id  uuid not null,
  entry_id      uuid not null,
  capture_id    uuid not null,
  attachment_id uuid,
  primary key (workspace_id, entry_id, capture_id),
  unique (workspace_id, attachment_id),
  foreign key (workspace_id, entry_id)
    references saved_world_entry(workspace_id, entry_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id),
  foreign key (workspace_id, entry_id, capture_id, attachment_id)
    references saved_world_source_attachment(workspace_id, entry_id, capture_id, attachment_id)
);

comment on table saved_world_source_current_membership is
  'Which attachment of each photograph a saved world currently uses. Null after a detach. '
  'Written only by the attachment and detach insert triggers; the runtime role reads it.';

-- 3. Backfill: before this migration every attachment row is current. The read must see every
-- workspace. A migration role subject to row-level security would otherwise read nothing under
-- FORCE with no workspace set and commit an empty collection, which hides every reference. The
-- owner is exempt once FORCE is lifted for this statement, and row_security=off turns any
-- remaining policy filtering into an error instead of an empty result.
set local row_security = off;
alter table saved_world_source_attachment no force row level security;

insert into saved_world_source_current_membership (
  workspace_id, entry_id, capture_id, attachment_id
)
select workspace_id, entry_id, capture_id, attachment_id
from saved_world_source_attachment;

do $$
declare attachments bigint; pointers bigint;
begin
  select count(*) into attachments from saved_world_source_attachment;
  select count(*) into pointers from saved_world_source_current_membership
    where attachment_id is not null;
  if attachments <> pointers or exists (
    select 1 from saved_world_source_attachment a
    where not exists (
      select 1 from saved_world_source_current_membership c
      where c.workspace_id = a.workspace_id and c.attachment_id = a.attachment_id)
  ) then
    raise exception 'current membership backfill wrote % pointers for % attachments',
      pointers, attachments;
  end if;
end $$;

alter table saved_world_source_attachment force row level security;
set local row_security = on;

-- 4. Detach events.
create table saved_world_source_detach_operation (
  workspace_id          uuid not null,
  operation_id          uuid not null,
  entry_id              uuid not null,
  request_sha256        bytea not null check (octet_length(request_sha256) = 32),
  base_entry_revision   bigint not null check (base_entry_revision >= 1),
  result_entry_revision bigint not null check (result_entry_revision = base_entry_revision + 1),
  authored_version_id   uuid not null,
  authored_state_sha256 text not null check (authored_state_sha256 ~ '^[0-9a-f]{64}$'),
  authored_edit_seq     bigint not null check (authored_edit_seq >= 0),
  style_version_id      uuid not null,
  created_by            uuid not null,
  created_at            timestamptz not null default statement_timestamp(),
  primary key (workspace_id, operation_id),
  unique (workspace_id, entry_id, operation_id),
  foreign key (workspace_id, entry_id)
    references saved_world_entry(workspace_id, entry_id)
);

create table saved_world_source_detach (
  detach_id               uuid primary key default uuidv7(),
  workspace_id            uuid not null,
  entry_id                uuid not null,
  operation_id            uuid not null,
  attachment_id           uuid not null,
  capture_id              uuid not null,
  detached_entry_revision bigint not null check (detached_entry_revision >= 2),
  detached_by             uuid not null,
  detached_at             timestamptz not null default statement_timestamp(),
  unique (workspace_id, detach_id),
  unique (workspace_id, attachment_id),
  foreign key (workspace_id, entry_id, operation_id)
    references saved_world_source_detach_operation(workspace_id, entry_id, operation_id),
  foreign key (workspace_id, entry_id, capture_id, attachment_id)
    references saved_world_source_attachment(workspace_id, entry_id, capture_id, attachment_id)
);

create index saved_world_source_detach_entry_idx
  on saved_world_source_detach(workspace_id, entry_id, detached_at, detach_id);

-- 5. One operation identity per workspace across attach, rebind and detach. The two tables
-- each have their own primary key, so the other table is checked here, under a lock on the
-- identity so two transactions cannot both pass the check.
create function tg_saved_world_membership_operation_identity() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(
    'saved-world-membership-operation:' || new.workspace_id::text || ':'
      || new.operation_id::text, 0));
  if exists (
    select 1 from saved_world_source_attachment_operation o
    where o.workspace_id = new.workspace_id and o.operation_id = new.operation_id
  ) or exists (
    select 1 from saved_world_source_detach_operation o
    where o.workspace_id = new.workspace_id and o.operation_id = new.operation_id
  ) then
    raise exception 'operation % already names a saved-world membership event',
      new.operation_id using errcode = 'unique_violation';
  end if;
  return new;
end $fn$;

create trigger tg_saved_world_membership_operation_identity
  before insert on saved_world_source_attachment_operation
  for each row execute function tg_saved_world_membership_operation_identity();
create trigger tg_saved_world_membership_operation_identity
  before insert on saved_world_source_detach_operation
  for each row execute function tg_saved_world_membership_operation_identity();

-- 6. What a rebind must pin: a human review recorded after the photograph was removed from
-- this world, and receipts no earlier membership of this photograph on this world pinned.
--
-- Both halves are needed. Checking only the newest membership let a rebind pin the first
-- membership's receipts again once a later review expired. Checking only "not already used"
-- let a review recorded while the photograph was still in the world bring it back, so the
-- person never made a decision after choosing to remove it.
create function tg_saved_world_source_attachment_kind() returns trigger
language plpgsql as $fn$
declare op_kind text; removed_at timestamptz;
begin
  perform assert_workspace_context(new.workspace_id);
  select kind into op_kind from saved_world_source_attachment_operation
    where workspace_id = new.workspace_id and operation_id = new.operation_id;
  if op_kind is null then
    raise exception 'source attachment does not match its exact saved-world operation'
      using errcode = 'integrity_constraint_violation';
  end if;
  if op_kind = 'rebind' then
    if exists (
      select 1 from saved_world_source_attachment a
      where a.workspace_id = new.workspace_id and a.entry_id = new.entry_id
        and a.capture_id = new.capture_id
        and (a.authorization_id = new.authorization_id or a.screening_id = new.screening_id)
    ) then
      raise exception 'rebind must pin a new human review, not receipts this world already used'
        using errcode = 'integrity_constraint_violation';
    end if;
    select max(d.detached_at) into removed_at from saved_world_source_detach d
      where d.workspace_id = new.workspace_id and d.entry_id = new.entry_id
        and d.capture_id = new.capture_id;
    if removed_at is null then
      raise exception 'rebind requires a photograph removed from this saved world'
        using errcode = 'integrity_constraint_violation';
    end if;
    if exists (
      select 1 from capture_reconstruction_authorization a
      where a.workspace_id = new.workspace_id and a.authorization_id = new.authorization_id
        and a.authorized_at <= removed_at
    ) or exists (
      select 1 from reconstruction_privacy_screening p
      where p.workspace_id = new.workspace_id and p.screening_id = new.screening_id
        and p.screened_at <= removed_at
    ) then
      raise exception
        'rebind must pin a human review recorded after the photograph was removed'
        using errcode = 'integrity_constraint_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_saved_world_source_attachment_kind before insert
  on saved_world_source_attachment for each row
  execute function tg_saved_world_source_attachment_kind();

-- 7. The pointer moves with its events and in no other way.
create function tg_saved_world_source_attachment_moves_membership() returns trigger
language plpgsql security definer as $fn$
declare op_kind text; moved integer;
begin
  perform assert_workspace_context(new.workspace_id);
  select kind into op_kind from saved_world_source_attachment_operation
    where workspace_id = new.workspace_id and operation_id = new.operation_id;
  if op_kind = 'attach' then
    if exists (
      select 1 from saved_world_source_current_membership c
      where c.workspace_id = new.workspace_id and c.entry_id = new.entry_id
        and c.capture_id = new.capture_id
    ) then
      raise exception 'attach requires a photograph with no membership on this saved world'
        using errcode = 'integrity_constraint_violation';
    end if;
    insert into saved_world_source_current_membership (
      workspace_id, entry_id, capture_id, attachment_id
    ) values (new.workspace_id, new.entry_id, new.capture_id, new.attachment_id);
  elsif op_kind = 'rebind' then
    update saved_world_source_current_membership set attachment_id = new.attachment_id
      where workspace_id = new.workspace_id and entry_id = new.entry_id
        and capture_id = new.capture_id and attachment_id is null;
    get diagnostics moved = row_count;
    if moved <> 1 then
      raise exception 'rebind requires a photograph removed from this saved world'
        using errcode = 'integrity_constraint_violation';
    end if;
  else
    raise exception 'source attachment names no attach or rebind operation'
      using errcode = 'integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create trigger tg_saved_world_source_attachment_moves_membership after insert
  on saved_world_source_attachment for each row
  execute function tg_saved_world_source_attachment_moves_membership();

create function tg_saved_world_source_detach_valid() returns trigger
language plpgsql volatile as $fn$
declare op saved_world_source_detach_operation%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into op from saved_world_source_detach_operation
    where workspace_id = new.workspace_id and operation_id = new.operation_id;
  if op.operation_id is null or op.entry_id <> new.entry_id
    or op.result_entry_revision <> new.detached_entry_revision
    or op.created_by <> new.detached_by then
    raise exception 'source detach does not match its exact saved-world operation'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_saved_world_source_detach_valid before insert
  on saved_world_source_detach for each row
  execute function tg_saved_world_source_detach_valid();

create function tg_saved_world_source_detach_moves_membership() returns trigger
language plpgsql security definer as $fn$
declare moved integer;
begin
  perform assert_workspace_context(new.workspace_id);
  update saved_world_source_current_membership set attachment_id = null
    where workspace_id = new.workspace_id and entry_id = new.entry_id
      and capture_id = new.capture_id and attachment_id = new.attachment_id;
  get diagnostics moved = row_count;
  if moved <> 1 then
    raise exception 'source detach must name the current membership of this photograph'
      using errcode = 'integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create trigger tg_saved_world_source_detach_moves_membership after insert
  on saved_world_source_detach for each row
  execute function tg_saved_world_source_detach_moves_membership();

-- Owner rights with a pinned search path, as 0044 and 0066 pin theirs. Only the triggers run
-- them: firing a trigger checks no EXECUTE privilege, so no role needs one, and the account
-- role's check refuses any role that could call an owner-rights function.
do $$ begin
  execute format('alter function tg_saved_world_source_attachment_moves_membership() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
  execute format('alter function tg_saved_world_source_detach_moves_membership() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $$;
revoke all on function tg_saved_world_source_attachment_moves_membership() from public;
revoke all on function tg_saved_world_source_detach_moves_membership() from public;

-- Any write that is not one of the two maintainers above is refused, whoever holds the grant.
create function tg_saved_world_source_current_membership_guard() returns trigger
language plpgsql as $fn$
begin
  if pg_trigger_depth() < 2 then
    raise exception 'current reference membership moves only with an attach, detach or rebind'
      using errcode = 'insufficient_privilege';
  end if;
  if tg_op = 'DELETE' then
    raise exception 'current reference membership is never deleted'
      using errcode = 'integrity_constraint_violation';
  end if;
  if tg_op = 'UPDATE' and (
    new.workspace_id is distinct from old.workspace_id
    or new.entry_id is distinct from old.entry_id
    or new.capture_id is distinct from old.capture_id
  ) then
    raise exception 'current membership identity is immutable'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_saved_world_source_current_membership_guard
  before insert or update or delete on saved_world_source_current_membership
  for each row execute function tg_saved_world_source_current_membership_guard();

create function tg_saved_world_source_detach_operation_committed() returns trigger
language plpgsql as $fn$
begin
  if not exists (
    select 1 from saved_world_entry e
    where e.workspace_id = new.workspace_id and e.entry_id = new.entry_id
      and e.revision = new.result_entry_revision
      and e.authored_version_id = new.authored_version_id
      and e.authored_state_sha256 = new.authored_state_sha256
      and e.authored_edit_seq = new.authored_edit_seq
      and e.style_version_id = new.style_version_id
      and exists (
        select 1 from saved_world_source_detach d
        where d.workspace_id = new.workspace_id and d.operation_id = new.operation_id)
  ) then
    raise exception 'source detach operation did not preserve and advance its exact cursor'
      using errcode = 'integrity_constraint_violation';
  end if;
  if exists (
    select 1 from saved_world_source_detach d
    join saved_world_source_current_membership c
      on c.workspace_id = d.workspace_id
     and c.entry_id = d.entry_id
     and c.capture_id = d.capture_id
    where d.workspace_id = new.workspace_id and d.operation_id = new.operation_id
      and c.attachment_id is not null
  ) then
    raise exception 'source detach left a capture in the current collection'
      using errcode = 'integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_saved_world_source_detach_operation_committed
  after insert on saved_world_source_detach_operation deferrable initially deferred
  for each row execute function tg_saved_world_source_detach_operation_committed();

create function tg_saved_world_source_membership_event_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

do $$
declare t text;
begin
  foreach t in array array[
    'saved_world_source_detach_operation',
    'saved_world_source_detach'] loop
    execute format(
      'create trigger %I before update or delete on %I for each row '
      'execute function tg_saved_world_source_membership_event_append_only()',
      'tg_' || t || '_append_only', t);
  end loop;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'saved_world_source_current_membership',
    'saved_world_source_detach_operation',
    'saved_world_source_detach'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id=current_workspace()) '
      'with check (workspace_id=current_workspace())', t);
  end loop;
end $$;

-- Grants for roles that already exist. Provisioning applies the same shape through
-- exulanica.db.roles: the pointer is read-only to the runtime, the events are insert-only.
do $$
declare r text; t text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array[
        'saved_world_source_current_membership',
        'saved_world_source_detach_operation',
        'saved_world_source_detach'] loop
        execute format('grant select on %I to %I', t, r);
        if r in ('exulanica_app','orimera_app')
          and t <> 'saved_world_source_current_membership' then
          execute format('grant insert on %I to %I', t, r);
          execute format('revoke update,delete on %I from %I', t, r);
        else
          execute format('revoke insert,update,delete on %I from %I', t, r);
        end if;
      end loop;
    end if;
  end loop;
end $$;

commit;
