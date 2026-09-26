-- 0112_a_remembered_answer_keeps_what_kind_of_answer_it_was.sql
-- A remembered Companion answer keeps what kind of answer it was, so it is drawn again under the
-- line it was first drawn under.
--
-- The line under a Companion answer says who wrote it: a model that answered, the search itself, a
-- model that drew a change to the world, the world refusing that change, and so on
-- (`COMPOSED_KINDS` in web/packages/companion-runtime/src/memory.ts, `AnswerComposed` in
-- exulanica/world/companion_memory.py). `companion_answer` (0043) kept the model identifiers and
-- not the kind, and the page rebuilt the kind from the model identifier alone, so a proposed change
-- came back after a reload as an answer ("Answered by ...") and the record of what became of a
-- proposal as the line of a search. The kind is kept here with the two facts the same line states
-- beside it: whether the model that answered was a fallback, and how many requests returned no
-- answer, with whether the cost of any of them is unknown.
--
-- `composed` is null only on a row kept before this migration: the route requires it on every new
-- one. A correction is the kind 'corrected', and nothing else is.
--
-- 0043 names the columns an update may not rewrite and lets any column it does not name change, so
-- a column added later could be rewritten in place until somebody named it. The function is
-- replaced here by one that names the other way round: the four columns that record what has
-- happened to an answer since it was kept (a correction's `status` and `superseded_at`, a
-- withdrawal's `withdrawn_at` and `withdrawn_by`) may change, and every other column, including
-- one a later migration adds, is refused, as 0052's `tg_world_society_binding` compares its rows.

begin;

select pg_advisory_xact_lock(119622309);

alter table companion_answer
  add column composed text,
  add column used_fallback boolean not null default false,
  add column unanswered_attempts integer not null default 0,
  add column unanswered_cost_unknown boolean not null default false,
  add constraint companion_answer_composed_known check (composed in (
    'model', 'discarded', 'search', 'unreadable', 'proposed', 'refused', 'undrafted',
    'unshown', 'none', 'outcome', 'corrected')),
  add constraint only_a_correction_is_corrected check (
    composed is null or ((origin = 'correction') = (composed = 'corrected'))),
  add constraint unanswered_attempts_are_counted check (unanswered_attempts >= 0),
  add constraint an_unknown_cost_needs_an_unanswered_attempt check (
    unanswered_attempts > 0 or not unanswered_cost_unknown);

comment on column companion_answer.composed is
  'What kind of answer this was, which decides the line it is drawn under. NULL only on a row '
  'kept before 0112, whose kind the page derives from the columns it has.';

create or replace function tg_companion_answer_no_in_place_rewrite() returns trigger
language plpgsql as $fn$
declare
  -- What has happened to the answer since it was kept. Nothing else about a kept answer changes.
  v_lifecycle constant text[] := array['status', 'superseded_at', 'withdrawn_at', 'withdrawn_by'];
  v_new constant jsonb := to_jsonb(new) - v_lifecycle;
  v_old constant jsonb := to_jsonb(old) - v_lifecycle;
  v_changed text;
begin
  if v_new is distinct from v_old then
    -- Named for the message, first in name order when several changed.
    select column_name into v_changed
      from jsonb_each(v_new) as rewritten(column_name, value)
     where rewritten.value is distinct from v_old -> rewritten.column_name
     order by column_name
     limit 1;
    raise exception
      'companion answer % is not editable: % may not be rewritten in place',
      old.answer_id, v_changed
      using errcode = 'integrity_constraint_violation',
            hint = 'Record a correction that supersedes it. Only status, superseded_at, '
                   'withdrawn_at and withdrawn_by are mutable.';
  end if;
  -- Monotonic, as 0043 made it: a withdrawal is a deletion and deletion does not run backwards.
  if old.status = 'withdrawn' and new.status is distinct from old.status then
    raise exception 'companion answer % is withdrawn and does not come back', old.answer_id
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

commit;
