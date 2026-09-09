-- 0043_the_companion_remembers_across_a_reload.sql
-- The Companion's memory lived in a browser tab, so closing the tab was amnesia.
--
-- `web/packages/companion-runtime/src/memory.ts` already holds the whole model: the Not sure and
-- Skip cooldown windows, the wrong-question signal, the dismissed threads, and a transcript of
-- what was asked and answered. Every field of it is built at mount and dropped at unload. The
-- consequence is not a missing nicety. `interaction-model.md` 4.3 and 5.5 both say the Companion
-- may never speak "within 7 days of a Skip or 14 days of a Not sure on the same entity", and a
-- fourteen-day window held in a page that a reload discards is a fourteen-day window that has
-- never once been enforced past a single page view. The user who said "not sure" and came back
-- tomorrow was asked again.
--
-- `product-direction.md` makes the durable half a delivery gate in the Improvement over time
-- table, on the Companion continuity row: "Persist approved memory, retrieve it across sessions,
-- and support correction and deletion; this is not model weight training." All four verbs are
-- here. Nothing in this file trains anything.
--
-- --------------------------------------------------------------------------------------------
-- What this plane is NOT, stated first because the neighbouring plane refuses it by name
-- --------------------------------------------------------------------------------------------
--
-- `world_interaction_policy_proposal` is the durable, reviewed interaction-preference plane, and
-- `exulanica/world/interaction_repository.py` refuses conversation content in its input with a
-- named constant and a raised error:
--
--     _PRIVATE_INPUT_KEYS = frozenset(
--         {"conversation", "messages", "raw_utterance", "transcript", "prompt_text"})
--     ...
--     raise InvalidInteractionData(
--         "conversation content is excluded from durable interaction policy input: " ...)
--
-- and 0021 says the same thing in its own header: that plane "contains no camera pose, open
-- panel, pending choice, conversation transcript, topology, renderer code, or neural weights".
--
-- **The tables below hold conversation text, and that is exactly why they are not that plane.**
-- The refusal there is not a statement that conversation text may never be stored; it is a
-- statement that it may never become an INPUT TO A POLICY DECISION about what this system is
-- permitted to do. A question a person typed is evidence about that person. A capability the
-- system may exercise is a rule. Letting the first author the second is how a typed sentence
-- silently widens a permission, and that boundary is worth more than the convenience of one
-- table.
--
-- So there is no foreign key from here into `world_interaction_policy_*`, no trigger that reads
-- one from the other, and no column here that any policy input is derived from. The two planes
-- are joined by nothing. `interaction-model.md` 4.4's "policy over the entity graph snapshot plus
-- the conversation transcript" is the TURN GENERATOR, which is per-session and produces a
-- question; it is a different sense of the word "policy" from the capability plane, and the
-- collision of the word is the reason this paragraph is here.
--
-- --------------------------------------------------------------------------------------------
-- Deletion reaches this plane through the machinery that already exists
-- --------------------------------------------------------------------------------------------
--
-- A Companion answer quotes photographs. `domain-and-evidence-model.md` 6.4 names the failure
-- this creates in its own words: "a generated title naming a person can be invalidated when that
-- person is deleted. Without the recorded set, the name survives its own deletion inside a
-- caption." An answer is a generated title with a longer sentence. Storing one durably without
-- recording what it quoted would put a description of a withdrawn photograph in a table that no
-- withdrawal reaches, and it would be readable after the bytes were destroyed.
--
-- `companion_answer_citation` is the recorded set. It is the join a tombstone travels along, it
-- is append-only for the reason 0024 gives about `reconstruction_scene_member` (a membership that
-- can be UPDATEd is a deletion that an UPDATE can undo), and it is what makes the sweep below an
-- indexed lookup rather than a scan of stored prose.
--
-- Both halves of 0035's lesson are here and they are different mechanisms:
--
--   BACKWARDS, at tombstone time: `tg_tombstone_withdraws_companion_memory` marks every answer
--     already stored whose citations the new tombstone reaches.
--   FORWARDS, afterwards:         `tg_companion_answer_citation_live` refuses to record a NEW
--     citation of evidence a tombstone already covers.
--
-- The forward half REFUSES where 0035 marks stale, and the asymmetry is deliberate. 0035 argues
-- that refusing an insert "would fail the whole ingest for a workspace where somebody has
-- withdrawn, which turns exercising a right into an outage", and that a derivative may serve
-- captures the withdrawn person is not in. Neither applies here: a Companion answer is composed
-- on demand from a packet the same request just built, one answer is not an ingest, and an answer
-- that cites withdrawn evidence has no legitimate remainder to preserve. Refusing it costs one
-- unstored answer that the person can ask for again, and it is the stronger guarantee.
--
-- **Independent of trigger order**, and that is load-bearing rather than incidental. The sweep
-- calls `tombstone_blocks_capture`, which reads the `tombstone` table directly and does not look
-- at `capture.deleted_at`. `tg_tombstone_enqueues_its_purge` is the only writer of that column
-- and it happens to sort before `tg_tombstone_withdraws_companion_memory` alphabetically, so the
-- ordering is in fact favourable; depending on that would still be a defect waiting for the next
-- trigger somebody names `tg_tombstone_a...`, which is 0035's own argument for reading `dep_index`
-- rather than the rows another trigger writes.
--
-- --------------------------------------------------------------------------------------------
-- Correction supersedes; it never edits
-- --------------------------------------------------------------------------------------------
--
-- The spine already settled this for `assertion`: `supersedes uuid references assertion`, a
-- status enum, and `tg_assertion_no_in_place_rewrite` whose hint reads "Write a new assertion with
-- supersedes set, or record a retraction. Only status, calibration_id and calibrated_p are
-- mutable." The same shape is used here for the same reason. A correction is a person telling the
-- system it was wrong, and that is the single most valuable thing in this table; an UPDATE that
-- overwrote the wrong answer would destroy the evidence that the system had been wrong, which is
-- the one record a correction exists to create.
--
-- 5.4: "Nothing is ever silently rewritten, including by the system's own later inferences."

begin;

select pg_advisory_xact_lock(119622343);

create type companion_memory_status as enum ('active', 'superseded', 'withdrawn');

-- The four escapes of interaction-model.md 4.3, spelled as the runtime spells them, because
-- `EscapeKind` in `web/packages/companion-runtime/src/turn.ts` is the vocabulary a browser sends
-- and a second spelling here would be a mapping table nobody maintains.
create type companion_escape_kind as enum ('not_sure', 'skip', 'later', 'wrong_question');

-- 'asked' is a question the person typed and the answer they received. 'correction' is the
-- person's own words about an answer that was wrong. Both are answers in this table because a
-- correction is the answer that stands afterwards; the difference is who wrote it, which is
-- exactly what `origin` says.
create type companion_answer_origin as enum ('asked', 'correction');

-- --------------------------------------------------------------------------------------------
-- 1. What was asked, and what came back
-- --------------------------------------------------------------------------------------------

create table companion_answer (
  answer_id    uuid primary key default uuidv7(),
  workspace_id uuid not null,
  -- Memory is per person, not per workspace. Two people sharing a workspace have not had the
  -- same conversation, and merging their memories would let one of them see what the other
  -- typed. RLS below scopes to the workspace; the actor clause is the repository's and every
  -- query in `exulanica/world/companion_memory.py` carries it, the same belt-and-braces the
  -- three world repositories use for `world_id`.
  actor_id     uuid not null,
  asked_at     timestamptz not null default now(),

  -- Bounded on purpose. `world_write.py` records the rule: an unbounded stored text field is "a
  -- permanent per-read cost that no later change can take back", and these two are read on every
  -- session open.
  question     text not null check (length(question) between 1 and 2000),
  answer_text  text not null check (length(answer_text) <= 8000),

  -- The four abstention codes, carried through rather than collapsed into a boolean.
  -- `evaluation-methodology.md` M3: merging them "lets a system that always says 'I don't know'
  -- score perfectly". NULL means the question was answered.
  abstained    text check (abstained in ('UNANSWERABLE_NOT_CAPTURED',
                                         'UNANSWERABLE_AMBIGUOUS',
                                         'UNANSWERABLE_NOT_IN_MODALITY',
                                         'UNANSWERABLE_NOT_UNDERSTOOD')),
  deterministic boolean not null default false,
  repaired      boolean not null default false,

  -- Read off the response body, never off the manifest. `companion-question.md` 4: "Every field
  -- is read off the response and none is read off the manifest", because a record derived from
  -- configuration reports a fallback wrongly and silently. NULL served_model is not missing
  -- data: it is the `discarded`, `search` and `unreadable` provenance cases, where a sentence
  -- reached the screen that no model wrote.
  served_model   text check (served_model is null or length(served_model) between 1 and 200),
  planned_by     text check (planned_by is null or length(planned_by) between 1 and 200),
  prompt_version text not null check (length(prompt_version) between 1 and 64),
  -- A whole number of milliseconds. A float rewrites its own last digits on a JSON round trip
  -- and every evaluation record in this repository refuses one; the column that feeds them
  -- refuses one too.
  latency_ms     integer not null check (latency_ms >= 0),

  origin       companion_answer_origin not null default 'asked',
  -- The lineage. Composite so the reference cannot cross a workspace, which a bare
  -- `references companion_answer(answer_id)` would permit.
  supersedes   uuid,
  -- The person's own words about why the answer was wrong. Present only on a correction.
  correction_note text check (length(correction_note) <= 2000),

  status       companion_memory_status not null default 'active',
  superseded_at timestamptz,
  withdrawn_at  timestamptz,
  -- Which tombstone reached it, and NULL is a fact rather than missing data: it means the person
  -- deleted this memory themselves through `/companion/memory`, where a value means a withdrawal
  -- of their photographs reached it. Both are withdrawals and neither comes back, but only one of
  -- them is a thing the person did to their own conversation, and a later reader who could not
  -- tell them apart would be unable to say whether an absent answer was deleted or deleted-by.
  withdrawn_by uuid references tombstone(tombstone_id),

  constraint companion_answer_workspace_answer_uniq unique (workspace_id, answer_id),
  foreign key (workspace_id, supersedes)
    references companion_answer(workspace_id, answer_id),
  -- A correction names what it corrects; an asked answer corrects nothing. Without this, a
  -- correction with a null `supersedes` would be an orphan claiming to replace something.
  constraint correction_names_what_it_supersedes check (
    (origin = 'correction') = (supersedes is not null)),
  constraint only_a_correction_carries_a_note check (
    origin = 'correction' or correction_note is null),
  -- Not an equivalence, and the difference is the whole lifecycle. `superseded_at` records that
  -- a correction replaced this answer, which is a thing that HAPPENED; withdrawing the lineage
  -- afterwards moves `status` to 'withdrawn' and must not erase it. An equivalence here refused
  -- exactly that: correct an answer, then delete the memory, and the row could not move to
  -- 'withdrawn' without first lying about having been corrected. So the two halves are stated
  -- separately: being superseded implies an instant, and an instant implies the row is no longer
  -- the one that stands.
  constraint superseded_status_has_an_instant check (
    status <> 'superseded' or superseded_at is not null),
  constraint a_superseded_instant_means_it_was_replaced check (
    superseded_at is null or status in ('superseded', 'withdrawn')),
  -- This one IS an equivalence, because 'withdrawn' is terminal: the update trigger refuses to
  -- let a row leave it, so there is no later status for an instant to survive into.
  constraint withdrawn_status_has_an_instant check (
    (status = 'withdrawn') = (withdrawn_at is not null))
);

-- Session open reads the recent active memory for one person, newest first. This is THE query
-- this table exists to serve and it runs on every mount.
create index companion_answer_actor_idx
  on companion_answer (workspace_id, actor_id, asked_at desc)
  where status = 'active';

-- Walking a correction chain, and refusing a second correction of an already-superseded answer.
create index companion_answer_supersedes_idx
  on companion_answer (workspace_id, supersedes)
  where supersedes is not null;

comment on column companion_answer.served_model is
  'The identifier that WROTE the sentence, read from the response body. NULL when no model did: '
  'a discarded composer output, a deterministic answer rendered from the query result, or a '
  'question no model could turn into a search.';

-- --------------------------------------------------------------------------------------------
-- 2. What the answer quoted, which is the join a withdrawal travels along
-- --------------------------------------------------------------------------------------------

create table companion_answer_citation (
  workspace_id uuid not null,
  answer_id    uuid not null,
  -- Reading order: the order the clauses mentioned the photographs, which is not the order the
  -- packet minted their tokens in. `companion-ask-api.ts` already de-duplicates by permalink and
  -- orders by first mention before it renders a chip, and the stored set is what it rendered.
  ordinal      integer not null check (ordinal >= 0),

  -- The span is what the citation resolved to and what `/evidence/{span}/masked` opens. Stored
  -- rather than the per-request citation token, because token namespaces are random per request:
  -- a stored token resolves in no later request and would be a chip that opens nothing.
  span_id      uuid not null,
  -- Recorded at insert rather than derived at read. `evidence_span` carries `blob_sha256` and
  -- not a capture, so span-to-capture is a join through the blob, and the sweep below would have
  -- to run it over stored prose on every tombstone. This is 0024's argument for
  -- `reconstruction_scene_member.capture_id`, and its answer to the drift objection holds here
  -- unchanged: both columns are fixed at insert on an append-only row, so a mismatched pair is a
  -- row no read will ever produce rather than a row that changed its mind.
  capture_id   uuid not null,

  primary key (workspace_id, answer_id, ordinal),
  foreign key (workspace_id, answer_id)
    references companion_answer(workspace_id, answer_id),
  foreign key (workspace_id, span_id)
    references evidence_span(workspace_id, span_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id)
);

-- "Which answers quoted this photograph." The primary key cannot answer it: the capture is not
-- its leading column, and the sweep asks exactly this question once per tombstone.
create index companion_answer_citation_capture_idx
  on companion_answer_citation (workspace_id, capture_id, answer_id);

-- --------------------------------------------------------------------------------------------
-- 3. The escapes, which are the cooldowns that a reload used to discard
-- --------------------------------------------------------------------------------------------

create table companion_escape (
  escape_id    uuid primary key default uuidv7(),
  workspace_id uuid not null,
  actor_id     uuid not null,
  taken_at     timestamptz not null default now(),
  escape       companion_escape_kind not null,
  -- A question is a pair, not a subject: `questionKey(intent, entityId)` in memory.ts. The
  -- intent is the runtime's own closed set and is stored as its own spelling for the reason the
  -- escape enum is.
  intent       text not null check (length(intent) between 1 and 64),
  -- NULL when the turn had no subject to attach a signal to. `recordEscape` already treats that
  -- case as "no cooldown window", because a window keyed on nothing would suppress every entity.
  entity_id    uuid,
  -- Which turn it was taken on. Not a foreign key: a turn is generated per session and is not a
  -- durable row anywhere, which is precisely the fact this migration exists to change about the
  -- memory and deliberately does not change about the turn.
  turn_id      text not null check (length(turn_id) between 1 and 128),

  foreign key (workspace_id, entity_id) references entity(workspace_id, entity_id)
);

-- The suppression read at session open: every escape this person has taken recently, so
-- `hardSuppression` can be answered from durable state instead of an empty map.
create index companion_escape_actor_idx
  on companion_escape (workspace_id, actor_id, taken_at desc);

-- --------------------------------------------------------------------------------------------
-- 4. Append-only, with the one narrow lifecycle the correction and withdrawal models need
-- --------------------------------------------------------------------------------------------

-- The shape and the reasoning are `tg_assertion_no_in_place_rewrite` in 0002. Every column that
-- says what happened is frozen; the three that say what has happened SINCE are not. Listing the
-- frozen columns explicitly rather than testing a mutable allowlist is deliberate: a column added
-- by a later migration is frozen by omission from the mutable set only if somebody remembers to
-- add it here, and this way the failure is a permitted edit rather than a refused one. That is
-- the wrong direction, so the ELSE branch names the column and refuses it.
create function tg_companion_answer_no_in_place_rewrite() returns trigger
language plpgsql as $fn$
declare
  v_changed text;
begin
  v_changed := case
    when new.answer_id      is distinct from old.answer_id      then 'answer_id'
    when new.workspace_id   is distinct from old.workspace_id   then 'workspace_id'
    when new.actor_id       is distinct from old.actor_id       then 'actor_id'
    when new.asked_at       is distinct from old.asked_at       then 'asked_at'
    when new.question       is distinct from old.question       then 'question'
    when new.answer_text    is distinct from old.answer_text    then 'answer_text'
    when new.abstained      is distinct from old.abstained      then 'abstained'
    when new.deterministic  is distinct from old.deterministic  then 'deterministic'
    when new.repaired       is distinct from old.repaired       then 'repaired'
    when new.served_model   is distinct from old.served_model   then 'served_model'
    when new.planned_by     is distinct from old.planned_by     then 'planned_by'
    when new.prompt_version is distinct from old.prompt_version then 'prompt_version'
    when new.latency_ms     is distinct from old.latency_ms     then 'latency_ms'
    when new.origin         is distinct from old.origin         then 'origin'
    when new.supersedes     is distinct from old.supersedes     then 'supersedes'
    when new.correction_note is distinct from old.correction_note then 'correction_note'
    else null
  end;
  if v_changed is not null then
    raise exception
      'companion answer % is not editable: % may not be rewritten in place',
      old.answer_id, v_changed
      using errcode = 'integrity_constraint_violation',
            hint = 'Record a correction that supersedes it. Only status, superseded_at, '
                   'withdrawn_at and withdrawn_by are mutable.';
  end if;
  -- Monotonic. A withdrawal is a deletion and deletion does not run backwards (del-1); letting
  -- `status` leave 'withdrawn' would be an UPDATE that undoes a tombstone, which is the whole
  -- thing the citation table's append-only guard exists to prevent one table over.
  if old.status = 'withdrawn' and new.status is distinct from old.status then
    raise exception 'companion answer % is withdrawn and does not come back', old.answer_id
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_companion_answer_no_in_place_rewrite
  before update on companion_answer
  for each row execute function tg_companion_answer_no_in_place_rewrite();

-- A row here is a statement about what already happened, so there is no legitimate DELETE and no
-- legitimate UPDATE at all. Withdrawal is recorded on the answer, not by removing its citations:
-- an answer whose citations were deleted would still be readable and would no longer name the
-- photographs that would have withdrawn it.
create function tg_companion_memory_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only: conversation memory a withdrawal reaches is not editable',
    tg_table_name
    using errcode = 'integrity_constraint_violation',
          hint = 'Record a correction that supersedes the answer, or a tombstone that withdraws '
                 'it. Neither rewrites what was already said.';
end $fn$;

create trigger tg_companion_answer_citation_append_only
  before update or delete on companion_answer_citation
  for each row execute function tg_companion_memory_append_only();

create trigger tg_companion_escape_append_only
  before update or delete on companion_escape
  for each row execute function tg_companion_memory_append_only();

-- A DELETE on the answer is refused separately, because its BEFORE UPDATE trigger above must stay
-- an UPDATE trigger to permit the lifecycle columns.
create trigger tg_companion_answer_no_delete
  before delete on companion_answer
  for each row execute function tg_companion_memory_append_only();

-- --------------------------------------------------------------------------------------------
-- 5. The forward half: a new citation of withdrawn evidence is refused
-- --------------------------------------------------------------------------------------------

create function tg_companion_answer_citation_live() returns trigger
language plpgsql as $fn$
declare
  v_blob  bytea;
  v_track text;
  v_start bigint;
  v_end   bigint;
begin
  perform assert_workspace_context(new.workspace_id);

  -- Absent and deleted are split, where `tg_reconstruction_scene_member_live` merges them, and
  -- the split is what lets the surface above answer honestly. `app.py` fixes that "a tombstoned
  -- address is 410 Gone, not 404. The user deleted it, which is a different fact from it never
  -- having existed, and it is a fact they are entitled to." A caller who cited a photograph that
  -- was withdrawn between composing the answer and storing it is entitled to be told which of
  -- those two happened, and a merged message would make the repository guess.
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id) then
    raise exception 'a companion citation names a photograph that is not in this workspace'
      using errcode = 'foreign_key_violation';
  end if;

  if exists (select 1 from capture c
              where c.workspace_id = new.workspace_id
                and c.capture_id = new.capture_id
                and c.deleted_at is not null) then
    perform tombstone_refuse('companion_answer_citation');
  end if;

  if tombstone_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('companion_answer_citation');
  end if;

  -- The span predicate as well as the capture one, because they refuse different things: an
  -- interval tombstone covers part of one capture's timeline and leaves the capture live, and a
  -- blocklisted hash covers bytes rather than a capture id.
  select s.blob_sha256, s.track_key, s.t_start_ns, s.t_end_ns
    into v_blob, v_track, v_start, v_end
    from evidence_span s
   where s.workspace_id = new.workspace_id
     and s.span_id = new.span_id;
  if tombstone_blocks_span(new.workspace_id, v_blob, v_track, v_start, v_end) then
    perform tombstone_refuse('companion_answer_citation');
  end if;

  -- The recorded capture must actually be the one the span's bytes belong to. Nothing else
  -- checks this, and a citation whose capture_id named a different photograph would be an answer
  -- that the wrong withdrawal reaches: quoting one photograph, withdrawn by the deletion of
  -- another, and surviving the deletion of the one it quoted.
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id
                    and c.blob_sha256 = v_blob) then
    raise exception 'a companion citation names a photograph its span does not belong to'
      using errcode = 'integrity_constraint_violation';
  end if;

  return new;
end $fn$;

create trigger tg_guard_companion_answer_citation
  before insert on companion_answer_citation
  for each row execute function tg_companion_answer_citation_live();

create function tg_companion_escape_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.entity_id is not null
     and tombstone_blocks_entity(new.workspace_id, new.entity_id) then
    perform tombstone_refuse('companion_escape');
  end if;
  return new;
end $fn$;

create trigger tg_guard_companion_escape
  before insert on companion_escape
  for each row execute function tg_companion_escape_live();

create function tg_companion_answer_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  -- A correction may not supersede an answer a tombstone already withdrew. The withdrawn answer
  -- is gone as far as the person is concerned, and a correction of it would put its subject back
  -- on the screen inside the correction's own text.
  if new.supersedes is not null
     and exists (select 1 from companion_answer a
                  where a.workspace_id = new.workspace_id
                    and a.answer_id = new.supersedes
                    and a.status = 'withdrawn') then
    raise exception 'a withdrawn companion answer cannot be corrected'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_guard_companion_answer
  before insert on companion_answer
  for each row execute function tg_companion_answer_live();

-- --------------------------------------------------------------------------------------------
-- 6. The backwards half: a tombstone withdraws every answer that quoted what it deleted
-- --------------------------------------------------------------------------------------------

create function tg_tombstone_withdraws_companion_memory() returns trigger
language plpgsql as $fn$
begin
  -- Every scope is handled by asking the existing predicates rather than by branching on the
  -- scope name. `tombstone_blocks_capture` already answers 'workspace', 'capture' and 'interval'
  -- together, and `tombstone_blocks_span` adds the interval and blocklisted-hash precision that
  -- a capture id cannot express. Branching here would be a fourth place that has to be updated
  -- when a scope is added, and the two predicates are already the three places.
  --
  -- 'entity' scope is deliberately NOT handled and this is the one gap worth naming. Withdrawing
  -- a person does not withdraw the photographs they appear in, and the derivative cascade that
  -- 0030 and 0035 build for that case works on `person_derivative_dependency`, which a Companion
  -- answer has no row in. An answer that named a withdrawn person is a real problem and it is a
  -- different problem from this one: it needs the answer's text to be attributable to an entity,
  -- which nothing here records, because the composer is never told an entity id. Recorded rather
  -- than half-solved.
  update companion_answer a
     set status = 'withdrawn',
         withdrawn_at = new.effective_at,
         withdrawn_by = new.tombstone_id
   where a.workspace_id = new.workspace_id
     and a.status <> 'withdrawn'
     and exists (
           select 1
             from companion_answer_citation cc
             join evidence_span s on s.workspace_id = cc.workspace_id
                                 and s.span_id = cc.span_id
            where cc.workspace_id = a.workspace_id
              and cc.answer_id = a.answer_id
              and (tombstone_blocks_capture(cc.workspace_id, cc.capture_id)
                   or tombstone_blocks_span(cc.workspace_id, s.blob_sha256, s.track_key,
                                            s.t_start_ns, s.t_end_ns)));

  -- A workspace tombstone is the whole plane, including the answers that cited nothing. An
  -- abstention cites nothing by construction and is still a record of what somebody asked.
  if new.scope = 'workspace' then
    update companion_answer a
       set status = 'withdrawn',
           withdrawn_at = new.effective_at,
           withdrawn_by = new.tombstone_id
     where a.workspace_id = new.workspace_id
       and a.status <> 'withdrawn';
  end if;

  return new;
end $fn$;

create trigger tg_tombstone_withdraws_companion_memory
  after insert on tombstone
  for each row execute function tg_tombstone_withdraws_companion_memory();

-- --------------------------------------------------------------------------------------------
-- 7. Row-level security, on the same terms as every other workspace-scoped table
-- --------------------------------------------------------------------------------------------

do $$
declare
  t text;
begin
  foreach t in array array[
    'companion_answer',
    'companion_answer_citation',
    'companion_escape'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

commit;
