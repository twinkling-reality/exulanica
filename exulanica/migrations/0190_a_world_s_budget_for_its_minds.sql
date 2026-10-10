-- 0190_a_world_s_budget_for_its_minds.sql
-- What a world may spend on the model minds of its beings, set by a person, appended and never
-- changed.
--
-- A BUDGET IS THE WORLD'S, NOT A CHOICE OF WHO DECIDES. A model choice says which model decides
-- for which beings (0110). This says how much the world may ask of models in any hour of real
-- time, in US dollars and in decisions, for one decision role. The playback host reads the newest
-- row of a world and a role before it asks; a world with none is asked under the two figures its
-- role's policy catalog states, as every world was before this table, so no world changes by it.
--
-- IT CAN ONLY LOWER WHAT THE HOST ALLOWS. The process's own budget, a deployment's guest
-- allowance and the durable spending authority's grants bound every call whatever a row here
-- says; a row is the most a person lets their world ask inside those.
--
-- WHO SET IT, AND WHEN. Each row names the account that set it and is recorded under the caller's
-- request id once: the same request asked again answers the row it recorded. Rows are appended in
-- order and never changed; the newest per world and role is the budget, and the history stays.
--
-- EVERY ROW NAMES A REGISTERED WORLD (0099), by key. It names no society: a budget outlives the
-- society of the day, and erasing a society erases nothing here. The document holds two figures,
-- the role, the world and the account; nothing a person wrote.
begin;
select pg_advisory_xact_lock(119622309);

create table world_minds_budget (
  workspace_id uuid not null,
  world_id text not null,
  role_key text not null check (role_key ~ '^[a-z][a-z0-9_]{0,62}$'),
  budget_seq bigint not null check (budget_seq > 0),
  request_id uuid not null,
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  set_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, role_key, budget_seq),
  unique (workspace_id, world_id, role_key, request_id),
  foreign key (workspace_id, world_id) references world_identity(workspace_id, world_id),
  constraint world_minds_budget_document check (
    (document->>'profile' = 'exulanica.world-minds-budget/v1') is true
    and (document->>'world_id' = world_id) is true
    and (document->>'role_key' = role_key) is true
    and ((document->>'budget_seq')::bigint = budget_seq) is true
    and (document->>'request_id' = request_id::text) is true
    and (document->>'set_by' = set_by::text) is true
    and (document->>'document_sha256' = document_sha256) is true
    and (document->>'usd_per_hour' ~ '^(0|[1-9][0-9]{0,5})\.[0-9]{6}$') is true
    and (jsonb_typeof(document->'decisions_per_hour') = 'number') is true
    and ((document->>'decisions_per_hour')::bigint between 0 and 2147483647) is true
  )
);

create function tg_world_minds_budget_binding() returns trigger language plpgsql as $fn$
declare
  latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  -- One writer a world and role at a time, so the sequence has no gap and no fork.
  perform pg_advisory_xact_lock(
    hashtext(new.workspace_id::text), hashtext(new.world_id || '|minds-budget|' || new.role_key)
  );
  select coalesce(max(budget_seq), 0) into latest_seq
    from world_minds_budget
   where workspace_id = new.workspace_id and world_id = new.world_id and role_key = new.role_key;
  if new.budget_seq <> latest_seq + 1 then
    raise exception 'a world''s budgets for its minds are appended in order' using errcode='23514';
  end if;
  return new;
end $fn$;

create trigger tg_world_minds_budget_binding
before insert on world_minds_budget
for each row execute function tg_world_minds_budget_binding();

create function tg_world_minds_budget_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'a world''s budget for its minds is appended and never changed'
    using errcode='23514';
end $fn$;

create trigger tg_world_minds_budget_append_only
before update or delete on world_minds_budget
for each row execute function tg_world_minds_budget_append_only();

alter table world_minds_budget enable row level security;
alter table world_minds_budget force row level security;
create policy ws_isolation on world_minds_budget
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

commit;
