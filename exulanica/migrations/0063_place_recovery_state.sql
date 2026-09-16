-- 0063_place_recovery_state.sql
-- A set of photographs has a recovery state, and the dominant real outcome has a name.
--
-- Most ordinary captures never register. A set that never registered has no
-- `reconstruction_scene` row, because a scene is recorded once a receipt exists, and it has no
-- `place_version`, because a version requires an admitted scene and a frame. Before this
-- migration such a set was an absence: nothing in the schema could say that these photographs
-- were looked at and will not rebuild, or why. `place_record` is where that is said, and
-- `recovery_state` is a closed vocabulary of five so the outcome is a name and not a gap.
--
-- `docs/capture-overlap-and-recovery-state.md` is the design. What follows records the shape.
--
-- THE SHAPE CHOSEN. A record of its own, with an allocated identity, an explicit member table of
-- capture ids, and an append-only table of state changes that carries the provenance of every
-- consequential state:
--
--   place_record               one exact set of photographs, its current state, and the verdict
--                              the capture overlap policy produced for it, as integers plus the
--                              canonical bytes and their digest
--   place_record_member        the capture ids, one row each, so a deletion cascade can reach
--                              through them, exactly as `reconstruction_scene_member` and
--                              `reconstruction_scene_job_member` are rows and not an array
--   place_record_state_event   from, to, a closed basis and the evidence that basis points at
--
-- THE ALTERNATIVES REJECTED.
--
-- A `recovery_state` column on `reconstruction_scene`. A scene row is written once a receipt
-- exists, so the refused set this migration exists for would have no row to carry the column,
-- and writing a scene row with no receipt would be a scene nobody reconstructed.
--
-- A column on `place` or `place_version`. A version requires an admitted scene and a frame, and
-- a place is a join of versions. A set that never registered has neither, and a place invented to
-- hold it would be a frame nobody recovered.
--
-- A column on `reconstruction_scene_job`. A job is mutable operational state that exists only
-- once a run is queued. A set refused before any run never has one, and a refusal recorded as a
-- job status would be indistinguishable from a job that failed.
--
-- A member array on the record. `derived_artifact.source_ids` is the precedent and nothing joins
-- it, so no cascade reaches through it: the reason 0024 gave for making scene members rows.
--
-- The identity is allocated rather than derived from the member set, as `place` allocates its
-- own, because the record is the personal plane's handle on a set and later planes will refer to
-- it. The exact set is still unique per workspace, through `member_digest`, so a second record
-- for the same photographs is refused rather than written beside the first. KNOWN AND ACCEPTED,
-- as 0024 accepted it for scenes: nothing in SQL recomputes `member_digest` from the member rows,
-- because reproducing the canonical encoding in plpgsql would be a second writer of it. The
-- member count and the verdict's own list of photographs ARE checked against the member rows,
-- at commit.
--
-- WHAT THIS DELIBERATELY DOES NOT DO. It stores no float. It keeps no clock in anything that
-- reaches a digest: `recorded_at` and `created_at` are columns about the write, not inputs to
-- the verdict. It adds no route, no reader change to the World Read, and no pipeline stage. It
-- does not build anchoring, frames, scale or precincts, which belong to later work.

begin;

select pg_advisory_xact_lock(119622309);

create table place_record (
  workspace_id               uuid not null,
  record_id                  uuid not null default uuidv7(),
  member_digest              bytea not null check (octet_length(member_digest) = 32),
  member_count               integer not null check (member_count >= 1),
  -- The five, and no sixth, no free text and no null. `exulanica.capture.recovery` carries the
  -- same five in the same order, and a test holds the two lists equal.
  recovery_state             text not null default 'not_attempted'
    check (recovery_state in ('not_attempted', 'insufficient_overlap', 'registered_partial',
                              'registered_scene', 'trained_radiance')),
  -- The number of state events applied. The state changes only through an event, and the event
  -- with this sequence number is the provenance of the state the record is in.
  state_seq                  integer not null default 0 check (state_seq >= 0),
  -- The verdict, whole or absent. The canonical bytes are what the pure function emitted; the
  -- jsonb is the same document for querying; the digest is over the bytes. The integer columns
  -- repeat what a reader needs without parsing, and a constraint holds them equal to the record.
  verdict_policy             text,
  verdict_canonical          bytea,
  verdict_record             jsonb,
  verdict_sha256             bytea check (octet_length(verdict_sha256) = 32),
  verdict_refusal_authorised boolean,
  predicted_ceiling          text
    check (predicted_ceiling in ('insufficient_overlap', 'registered_partial',
                                 'registered_scene')),
  verdict_worth_attempting   boolean,
  verdict_fault              text
    check (verdict_fault in ('too_few_photographs', 'no_overlapping_neighbours',
                             'separate_groups', 'mostly_unconnected')),
  photograph_count           integer check (photograph_count >= 0),
  measured_count             integer check (measured_count >= 0),
  edge_min_score             integer check (edge_min_score >= 1),
  edge_count                 integer check (edge_count >= 0),
  largest_component          integer check (largest_component >= 0),
  group_count                integer check (group_count >= 0),
  isolated_count             integer check (isolated_count >= 0),
  created_at                 timestamptz not null default statement_timestamp(),
  primary key (workspace_id, record_id),
  unique (workspace_id, member_digest),
  constraint a_record_without_history_was_never_changed
    check (state_seq > 0 or recovery_state = 'not_attempted'),
  constraint a_verdict_is_whole_or_absent
    check (num_nulls(verdict_policy, verdict_canonical, verdict_record, verdict_sha256,
                     verdict_refusal_authorised, predicted_ceiling, verdict_worth_attempting,
                     photograph_count, measured_count, edge_min_score, edge_count,
                     largest_component, group_count, isolated_count) in (0, 14)
           and (verdict_fault is null or verdict_record is not null)),
  -- The same two checks 0030 puts on a withdrawal receipt: the digest is over the stored bytes,
  -- and the queryable document is those bytes, so neither can drift from the other.
  constraint the_verdict_digest_is_over_its_bytes
    check (verdict_canonical is null
           or public.digest(verdict_canonical, 'sha256') = verdict_sha256),
  constraint the_verdict_document_is_its_bytes
    check (verdict_canonical is null
           or convert_from(verdict_canonical, 'UTF8')::jsonb = verdict_record),
  constraint the_verdict_columns_are_its_document
    check (verdict_record is null or (
      verdict_record ->> 'profile' = 'exulanica.capture-overlap-verdict/v1'
      and verdict_record -> 'policy' ->> 'version' = verdict_policy
      and verdict_record -> 'policy' -> 'refusal_authorised'
          = to_jsonb(verdict_refusal_authorised)
      and verdict_record -> 'prediction' ->> 'ceiling' = predicted_ceiling
      and verdict_record -> 'prediction' -> 'worth_attempting'
          = to_jsonb(verdict_worth_attempting)
      and verdict_record -> 'prediction' -> 'fault'
          = coalesce(to_jsonb(verdict_fault), 'null'::jsonb)
      and verdict_record -> 'graph' -> 'photograph_count' = to_jsonb(photograph_count)
      and verdict_record -> 'graph' -> 'measured_count' = to_jsonb(measured_count)
      and verdict_record -> 'graph' -> 'edge_min_score' = to_jsonb(edge_min_score)
      and verdict_record -> 'graph' -> 'edge_count' = to_jsonb(edge_count)
      and verdict_record -> 'graph' -> 'largest_component' = to_jsonb(largest_component)
      and verdict_record -> 'graph' -> 'groups' = to_jsonb(group_count)
      and verdict_record -> 'graph' -> 'isolated' = to_jsonb(isolated_count)
      and photograph_count = member_count
      -- A prediction that would run the set is not a refusal, and nothing but a refusal may
      -- carry a fault.
      and verdict_worth_attempting = (predicted_ceiling = 'registered_scene')
      and (verdict_fault is null) = verdict_worth_attempting))
);
create index place_record_state_idx on place_record (workspace_id, recovery_state);

create table place_record_member (
  workspace_id uuid not null,
  record_id    uuid not null,
  capture_id   uuid not null,
  ordinal      integer not null check (ordinal >= 0),
  primary key (workspace_id, record_id, capture_id),
  unique (workspace_id, record_id, ordinal),
  foreign key (workspace_id, record_id) references place_record (workspace_id, record_id),
  foreign key (workspace_id, capture_id) references capture (workspace_id, capture_id)
);
-- "Which records was this capture in", asked by the predicate below and by any cascade, which
-- the primary key cannot answer because the capture is its last column.
create index place_record_member_capture_idx
  on place_record_member (workspace_id, capture_id, record_id);

create table place_record_state_event (
  workspace_id            uuid not null,
  record_id               uuid not null,
  seq                     integer not null check (seq >= 1),
  from_state              text not null
    check (from_state in ('not_attempted', 'insufficient_overlap', 'registered_partial',
                          'registered_scene', 'trained_radiance')),
  to_state                text not null
    check (to_state in ('not_attempted', 'insufficient_overlap', 'registered_partial',
                        'registered_scene', 'trained_radiance')),
  basis                   text not null
    check (basis in ('verdict', 'pose_receipt', 'training_receipt', 'withdrawal')),
  -- The evidence. Exactly the columns the basis names are set, and no others.
  verdict_sha256          bytea check (octet_length(verdict_sha256) = 32),
  receipt_artifact_id     uuid references artifact (artifact_id),
  registered_count        integer check (registered_count >= 0),
  receipt_accepted        boolean,
  withdrawal_tombstone_id uuid references tombstone (tombstone_id),
  recorded_at             timestamptz not null default statement_timestamp(),
  primary key (workspace_id, record_id, seq),
  foreign key (workspace_id, record_id) references place_record (workspace_id, record_id),
  constraint a_state_event_changes_the_state check (from_state <> to_state),
  constraint the_basis_names_its_evidence check (
    case basis
      when 'verdict' then
        verdict_sha256 is not null
        and num_nonnulls(receipt_artifact_id, registered_count, receipt_accepted,
                         withdrawal_tombstone_id) = 0
      when 'pose_receipt' then
        receipt_artifact_id is not null and registered_count is not null
        and receipt_accepted is not null
        and num_nonnulls(verdict_sha256, withdrawal_tombstone_id) = 0
      when 'training_receipt' then
        receipt_artifact_id is not null
        and num_nonnulls(verdict_sha256, registered_count, receipt_accepted,
                         withdrawal_tombstone_id) = 0
      else
        withdrawal_tombstone_id is not null
        and num_nonnulls(verdict_sha256, receipt_artifact_id, registered_count,
                         receipt_accepted) = 0
    end),
  -- Which basis may say which state. A verdict may only refuse a set that was never attempted,
  -- and only a run's own receipt may say anything was registered or trained. A withdrawal only
  -- ever lowers a state.
  constraint the_basis_can_reach_the_state check (
    (basis = 'verdict' and from_state = 'not_attempted' and to_state = 'insufficient_overlap')
    or (basis = 'pose_receipt' and from_state <> 'trained_radiance'
        and to_state in ('insufficient_overlap', 'registered_partial', 'registered_scene'))
    or (basis = 'training_receipt' and from_state = 'registered_scene'
        and to_state = 'trained_radiance')
    or (basis = 'withdrawal'
        and array_position(array['not_attempted', 'insufficient_overlap', 'registered_partial',
                                  'registered_scene', 'trained_radiance'], to_state)
          < array_position(array['not_attempted', 'insufficient_overlap', 'registered_partial',
                                 'registered_scene', 'trained_radiance'], from_state))),
  -- A pose receipt's state is its counts, read the way `outcome_from_pose_receipt` reads them:
  -- nothing placed, some placed without the gate, the gate accepted.
  constraint a_pose_receipt_state_is_its_counts check (
    basis <> 'pose_receipt'
    or to_state = case
                    when registered_count = 0 then 'insufficient_overlap'
                    when receipt_accepted then 'registered_scene'
                    else 'registered_partial'
                  end)
);

-- A fact about a set is withdrawn by the withdrawal of any one of its photographs.
--
-- The shape of `tombstone_blocks_reconstruction_job` (0026), with the person-scoped branch
-- `tombstone_blocks_scene` gained in 0030, so a record is withdrawn by exactly what withdraws a
-- scene over the same photographs. VOLATILE for the reason 0024 gives: a fresh snapshot per call,
-- so a tombstone committing while a write runs is seen. An empty membership fails closed, which
-- also covers a session that cannot see the member rows because it never declared a workspace.
-- Every read of a record asks this in its `where` clause. It is never reduced in Python: a
-- per-capture answer reduced there is an OR over the captures sharing a blob, and one live
-- capture would keep serving a fact about a set another was withdrawn from.
create or replace function tombstone_blocks_place_record(p_workspace uuid, p_record uuid)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from place_record_member m
                 where m.workspace_id = p_workspace and m.record_id = p_record)
    or exists (
      select 1
        from place_record_member m
        join capture c on c.workspace_id = m.workspace_id and c.capture_id = m.capture_id
       where m.workspace_id = p_workspace
         and m.record_id = p_record
         and (c.deleted_at is not null
              or tombstone_blocks_capture(p_workspace, m.capture_id)
              or person_withdrawal_blocks_capture(p_workspace, m.capture_id)));
$fn$;

comment on function tombstone_blocks_place_record(uuid, uuid) is
  'Does a deletion reach this record through any of its members. ANY and not ALL, and an empty '
  'membership fails closed, as tombstone_blocks_reconstruction_job does for a pending set.';

-- A record arrives not_attempted, and afterwards only its state moves, and only to what its newest
-- event says.
create function tg_place_record_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.recovery_state <> 'not_attempted' or new.state_seq <> 0 then
      raise exception 'a place record arrives not_attempted; every other state is an event'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'recovery_state' - 'state_seq')
       is distinct from (to_jsonb(old) - 'recovery_state' - 'state_seq') then
    raise exception 'a place record is immutable except for its recovery state'
      using errcode = 'check_violation';
  end if;
  if new.state_seq <> old.state_seq + 1
     or not exists (
       select 1 from place_record_state_event e
        where e.workspace_id = new.workspace_id
          and e.record_id = new.record_id
          and e.seq = new.state_seq
          and e.from_state = old.recovery_state
          and e.to_state = new.recovery_state) then
    raise exception 'a recovery state changes only through place_record_state_event'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_place_record_guard
  before insert or update on place_record
  for each row execute function tg_place_record_guard();

-- At commit, a new record holds exactly its members, and its verdict describes exactly them.
-- Deferred because the members reference the record and so arrive after it.
create function tg_place_record_complete() returns trigger
language plpgsql as $fn$
declare
  held    integer;
  members text[];
  refs    text[];
begin
  perform assert_workspace_context(new.workspace_id);
  select count(*), array_agg(m.capture_id::text order by m.capture_id::text)
    into held, members
    from place_record_member m
   where m.workspace_id = new.workspace_id and m.record_id = new.record_id;
  if held <> new.member_count then
    raise exception 'place record % holds % members and declares %',
      new.record_id, held, new.member_count
      using errcode = 'check_violation';
  end if;
  if new.verdict_record is not null then
    select array_agg(p ->> 'ref' order by p ->> 'ref')
      into refs
      from jsonb_array_elements(new.verdict_record -> 'graph' -> 'photographs') p;
    if refs is distinct from members then
      raise exception 'the verdict describes other photographs than place record % holds',
        new.record_id
        using errcode = 'check_violation';
    end if;
  end if;
  return null;
end $fn$;

create constraint trigger tg_place_record_complete
  after insert on place_record
  deferrable initially deferred
  for each row execute function tg_place_record_complete();

-- A member is a live photograph nobody has withdrawn, and a record's members are fixed by the
-- count it declared. The same guard shape as `tg_reconstruction_job_member_live` in 0026.
create function tg_place_record_member_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id
                    and c.deleted_at is null) then
    raise exception 'a place record member names an absent or deleted photograph'
      using errcode = 'foreign_key_violation';
  end if;
  if tombstone_blocks_capture(new.workspace_id, new.capture_id)
     or person_withdrawal_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('place_record_member');
  end if;
  if (select count(*) from place_record_member m
       where m.workspace_id = new.workspace_id and m.record_id = new.record_id)
     >= (select r.member_count from place_record r
          where r.workspace_id = new.workspace_id and r.record_id = new.record_id) then
    raise exception 'place record % already holds every member it declared', new.record_id
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_guard_place_record_member
  before insert on place_record_member
  for each row execute function tg_place_record_member_live();

-- A state event is admitted only against the record's current state, only when nothing has
-- withdrawn the set, and only with evidence that is about this set.
create function tg_place_record_state_event_guard() returns trigger
language plpgsql as $fn$
declare
  current_state   text;
  current_seq     integer;
  own_verdict     bytea;
  authorised      boolean;
  worth           boolean;
  receipt_scene   uuid;
begin
  perform assert_workspace_context(new.workspace_id);
  select r.recovery_state, r.state_seq, r.verdict_sha256, r.verdict_refusal_authorised,
         r.verdict_worth_attempting
    into current_state, current_seq, own_verdict, authorised, worth
    from place_record r
   where r.workspace_id = new.workspace_id and r.record_id = new.record_id
     for update;
  if not found then
    raise exception 'a state event names no place record in this workspace'
      using errcode = 'foreign_key_violation';
  end if;
  if new.seq <> current_seq + 1 or new.from_state <> current_state then
    raise exception 'a state event must follow the record''s current state % at %',
      current_state, current_seq
      using errcode = 'check_violation';
  end if;
  if tombstone_blocks_place_record(new.workspace_id, new.record_id) then
    perform tombstone_refuse('place_record_state_event');
  end if;
  if new.basis = 'verdict' then
    if own_verdict is distinct from new.verdict_sha256 then
      raise exception 'the verdict named is not this record''s verdict'
        using errcode = 'check_violation';
    end if;
    -- Read from the verdict's own bytes, so a policy that has not passed a held-out set cannot
    -- seal a set however confident its prediction is.
    if authorised is not true then
      raise exception 'the policy that produced this verdict is not authorised to refuse a set'
        using errcode = 'check_violation';
    end if;
    if worth is not false then
      raise exception 'this record''s verdict does not refuse the set'
        using errcode = 'check_violation';
    end if;
  elsif new.basis in ('pose_receipt', 'training_receipt') then
    select a.scene_id into receipt_scene
      from artifact a
     where a.workspace_id = new.workspace_id
       and a.artifact_id = new.receipt_artifact_id
       and a.kind = case new.basis when 'pose_receipt' then 'pose_receipt'
                                   else 'scene_splat_receipt' end
       and a.scene_id is not null
       and a.purged_at is null
       and not a.needs_repair
       and not person_withdrawal_blocks_artifact(a.workspace_id, a.artifact_id);
    if receipt_scene is null then
      raise exception 'the % named is not a live receipt about a scene in this workspace',
        new.basis
        using errcode = 'check_violation';
    end if;
    if tombstone_blocks_scene(new.workspace_id, receipt_scene) then
      perform tombstone_refuse('place_record_state_event');
    end if;
    -- A receipt about another set of photographs says nothing about this one, however similar.
    if exists (select m.capture_id from place_record_member m
                where m.workspace_id = new.workspace_id and m.record_id = new.record_id
               except
               select s.capture_id from reconstruction_scene_member s
                where s.workspace_id = new.workspace_id and s.scene_id = receipt_scene)
       or exists (select s.capture_id from reconstruction_scene_member s
                   where s.workspace_id = new.workspace_id and s.scene_id = receipt_scene
                  except
                  select m.capture_id from place_record_member m
                   where m.workspace_id = new.workspace_id and m.record_id = new.record_id) then
      raise exception 'the receipt is about a different set of photographs than this record'
        using errcode = 'check_violation';
    end if;
    if new.basis = 'training_receipt' and not exists (
         select 1 from artifact d
          where d.workspace_id = new.workspace_id
            and d.scene_id = receipt_scene
            and d.kind = 'gaussian_splat_scene'
            and d.purged_at is null
            and not d.needs_repair
            and not person_withdrawal_blocks_artifact(d.workspace_id, d.artifact_id)) then
      raise exception 'no trained scene was delivered for this set, so it is not trained_radiance'
        using errcode = 'check_violation';
    end if;
  else
    if not exists (select 1 from tombstone t
                    where t.workspace_id = new.workspace_id
                      and t.tombstone_id = new.withdrawal_tombstone_id) then
      raise exception 'the withdrawal named is not a tombstone in this workspace'
        using errcode = 'foreign_key_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_guard_place_record_state_event
  before insert on place_record_state_event
  for each row execute function tg_place_record_state_event_guard();

-- The event is applied to the record in the same statement that admits it, so a record's state
-- and its newest event cannot disagree.
create function tg_place_record_state_event_applies() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  update place_record
     set recovery_state = new.to_state, state_seq = new.seq
   where workspace_id = new.workspace_id and record_id = new.record_id;
  if not found then
    raise exception 'a state event could not be applied to its record'
      using errcode = 'check_violation';
  end if;
  return null;
end $fn$;

create trigger tg_place_record_state_event_applies
  after insert on place_record_state_event
  for each row execute function tg_place_record_state_event_applies();

-- Append-only, in the shape of `tg_world_society_event_append_only` (0052). A membership a
-- deletion can reach is not editable, and provenance that can be rewritten is not provenance.
create function tg_place_record_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create trigger tg_place_record_no_delete
  before delete on place_record
  for each row execute function tg_place_record_append_only();

do $$
declare
  t text;
begin
  foreach t in array array['place_record_member', 'place_record_state_event'] loop
    execute format(
      'create trigger %I before update or delete on %I '
      'for each row execute function tg_place_record_append_only()',
      'tg_' || t || '_append_only', t);
  end loop;
end $$;

do $$ declare t text; begin
  foreach t in array array['place_record', 'place_record_member', 'place_record_state_event'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

commit;
