-- 0103_a_remembered_answer_keeps_whom_its_placeholders_stood_for.sql
-- A remembered Companion answer keeps which entity each of its placeholders stood for, as ids.
--
-- A person's saved name never goes to a hosted model, and a place's goes only under the account
-- holder's right for that place and model, so the Companion's answer names them by placeholder,
-- `[person A]` or `[place A]`, and the answer's `names` says which entity each placeholder stands
-- for. The browser draws the name from the account holder's own library when the answer is drawn.
-- `companion_answer` (0043) kept the answer's text and not that map, so an answer shown again after
-- a reload said "a person this answer does not name" where the fresh answer had said the name.
--
-- The map is kept here, one row per placeholder. It holds the entity id and never the name text,
-- which is what makes a rename, a deletion or a withdrawn consent carry through: the name is read
-- from the library each time the answer is drawn, where each of those changes already is.
--
-- Deletion reaches this plane as 0043's header requires, along the same paths:
--   * A tombstone that withdraws an answer (0043's `tg_tombstone_withdraws_companion_memory`)
--     withdraws the map with it, because every read of the map goes through the answer's status.
--   * An entity tombstone does not withdraw the answer. The answer's text holds no name of the
--     entity, only its placeholder, and the browser says the placeholder in words for a deleted
--     entity. 0043 recorded that an answer naming a withdrawn person needed its text attributable
--     to an entity; this table is that attribution, and what it makes possible is a name that is
--     no longer shown rather than an answer that is no longer kept.
--   * The forward half: a new row naming an entity a tombstone already covers is refused, as a new
--     escape naming one is (0043's `tg_companion_escape_live`).
--   * Entity rows are never removed, so the foreign key below cannot hold a purge back.
--
-- Append-only, for 0043's reason about citations: a map an UPDATE can re-point is an answer that
-- names somebody else afterwards.

begin;

select pg_advisory_xact_lock(119622309);

create table companion_answer_name (
  workspace_id uuid not null,
  answer_id    uuid not null,
  -- The placeholder as the server wrote it into the answer. Its shape only; the class must be the
  -- entity's own, which the guard below reads from the entity rather than from a list here.
  label        text not null check (label ~ '^\[[a-z]+ [A-Z]+\]$'),
  entity_id    uuid not null,

  primary key (workspace_id, answer_id, label),
  foreign key (workspace_id, answer_id)
    references companion_answer(workspace_id, answer_id),
  foreign key (workspace_id, entity_id)
    references entity(workspace_id, entity_id)
);

create trigger tg_companion_answer_name_append_only
  before update or delete on companion_answer_name
  for each row execute function tg_companion_memory_append_only();

create function tg_companion_answer_name_live() returns trigger
language plpgsql as $fn$
declare
  v_class text;
begin
  perform assert_workspace_context(new.workspace_id);
  select e.class::text into v_class
    from entity e
   where e.workspace_id = new.workspace_id
     and e.entity_id = new.entity_id;
  -- Split from the foreign key's own refusal so the repository can say "not in this library"
  -- without parsing a constraint name, as 0043's citation guard does.
  if v_class is null then
    raise exception 'a companion answer names an entity that is not in this workspace'
      using errcode = 'foreign_key_violation';
  end if;
  -- Never quotes the label: one that is not a placeholder may be a name. The table's check
  -- refuses a label of no placeholder's shape too, after this trigger has run.
  if split_part(substr(new.label, 2), ' ', 1) <> v_class then
    raise exception 'a companion answer gives a % a label that is not a % placeholder',
      v_class, v_class
      using errcode = 'integrity_constraint_violation';
  end if;
  if tombstone_blocks_entity(new.workspace_id, new.entity_id) then
    perform tombstone_refuse('companion_answer_name');
  end if;
  return new;
end $fn$;

create trigger tg_guard_companion_answer_name
  before insert on companion_answer_name
  for each row execute function tg_companion_answer_name_live();

alter table companion_answer_name enable row level security;
alter table companion_answer_name force row level security;
create policy ws_isolation on companion_answer_name
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

commit;
