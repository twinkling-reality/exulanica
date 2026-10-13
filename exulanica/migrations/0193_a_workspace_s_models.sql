-- 0193_a_workspace_s_models.sql
-- The models a workspace added to those that may decide for a being: what was read of each when
-- it was added, how it did when it was tried, and whether it was removed. Appended, never
-- changed.
--
-- BESIDE THE SHIPPED MANIFEST, NEVER IN IT. The manifest states the models every installation
-- has. A row here is one fact about one model of one provider in one workspace: that it was
-- added (with the provider's own statement of it and its price as read that day, by digest), that
-- it was tried (the verdict of the product's own probe), that a try was cut short (which is no
-- verdict), or that it was removed. The newest row of a model is its state; the history stays.
--
-- NOTHING A PERSON WROTE. A row holds a provider's identifier, a model's identifier, figures the
-- provider or the probe stated, digests, and the account that asked. No sentence, no name of a
-- person, no answer a model gave.
--
-- REMOVED IS ORDINARY STATE, NOT A WITHDRAWAL. Taking a model off the list, or the provider no
-- longer listing it, takes back no permission and no consent: whether a model's licence lets
-- this product call it is the class the shipped catalog gives its identifier, read whenever a
-- model is added, tried or offered, never a row here. So a restore carries nothing of this table:
-- a model removed after a backup comes back listed, and is held to the catalog again before it
-- is offered.
--
-- ERASED WITH ITS WORKSPACE, AND SO IS THE BUDGET OF 0190. Each row names the account that asked
-- (`recorded_by` here, `set_by` in `world_minds_budget`), so both tables go when their workspace
-- is erased: a workspace tombstone deletes the workspace's rows of both, by a trigger that runs as
-- exulanica_definer in the tombstone's own workspace, which it asserts first. Nobody else deletes
-- a row of either: each table's guard refuses every update, and every delete but that role's.
--
-- THE ONE EXISTING OBJECT THIS MIGRATION RESTATES is 0190's guard function,
-- tg_world_minds_budget_append_only, so that it lets the definers' owner delete. It is restated
-- here and nowhere else: a later migration that deletes a budget's rows (one removed world's, for
-- one) deletes them through this guard as exulanica_definer and does not restate the function.
--
-- THE ORDER OF THE FACTS IS THE TABLE'S, not only the repository's: the first fact about a model
-- is that it was added, and after it was removed the next is that it was added again.
--
-- WHO, AND ONCE. Each row names the account that asked and is recorded under the caller's request
-- id once for its model: the same request asked again answers the row it recorded. Rows of one
-- model are appended in order.
begin;
select pg_advisory_xact_lock(119622309);

create table workspace_model (
  workspace_id uuid not null,
  provider text not null check (provider ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_id text not null check (model_id ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$'),
  model_seq bigint not null check (model_seq > 0),
  request_id uuid not null,
  kind text not null check (kind in ('added', 'probed', 'probe_not_finished', 'removed')),
  -- Bounded in octets (64 KiB): a provider's statement of a model, or a probe's verdict by
  -- mechanism, is a few hundred; nothing a row may hold comes near it, and no row holds more.
  document jsonb not null check (
    jsonb_typeof(document) = 'object' and octet_length(document::text) <= 65536
  ),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, provider, model_id, model_seq),
  unique (workspace_id, provider, model_id, request_id),
  constraint workspace_model_document check (
    (document->>'profile' = 'exulanica.workspace-model/v1') is true
    and (document->>'provider' = provider) is true
    and (document->>'model_id' = model_id) is true
    and ((document->>'model_seq')::bigint = model_seq) is true
    and (document->>'request_id' = request_id::text) is true
    and (document->>'kind' = kind) is true
    and (document->>'recorded_by' = recorded_by::text) is true
    and (document->>'document_sha256' = document_sha256) is true
    and (jsonb_typeof(document->'facts') = 'object') is true
  )
);

create function tg_workspace_model_binding() returns trigger language plpgsql as $fn$
declare
  latest_seq bigint;
  latest_kind text;
begin
  perform assert_workspace_context(new.workspace_id);
  -- One writer a workspace and model at a time, so the sequence has no gap and no fork.
  perform pg_advisory_xact_lock(
    hashtext(new.workspace_id::text), hashtext(new.provider || '|workspace-model|' || new.model_id)
  );
  select model_seq, kind into latest_seq, latest_kind
    from workspace_model
   where workspace_id = new.workspace_id and provider = new.provider and model_id = new.model_id
   order by model_seq desc
   limit 1;
  if new.model_seq <> coalesce(latest_seq, 0) + 1 then
    raise exception 'a workspace''s facts about a model are appended in order' using errcode='23514';
  end if;
  -- A fact follows the facts before it: a model is tried or removed only after it was added and
  -- while it is not removed. It may be added at any time.
  if new.kind <> 'added' and (latest_kind is null or latest_kind = 'removed') then
    raise exception 'a model is tried or removed only after it was added and while it is listed'
      using errcode='23514';
  end if;
  return new;
end $fn$;

create trigger tg_workspace_model_binding
before insert on workspace_model
for each row execute function tg_workspace_model_binding();

create function tg_workspace_model_append_only() returns trigger language plpgsql as $fn$
begin
  -- Only its workspace's erasure deletes a row, as the definers' owner (below).
  if tg_op = 'DELETE' and current_user = 'exulanica_definer' then
    return old;
  end if;
  raise exception 'a workspace''s fact about a model is appended and never changed'
    using errcode='23514';
end $fn$;

create trigger tg_workspace_model_append_only
before update or delete on workspace_model
for each row execute function tg_workspace_model_append_only();

alter table workspace_model enable row level security;
alter table workspace_model force row level security;
create policy ws_isolation on workspace_model
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- 0190's guard, restated to let the definers' owner delete: its one change.
create or replace function tg_world_minds_budget_append_only() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'DELETE' and current_user = 'exulanica_definer' then
    return old;
  end if;
  raise exception 'a world''s budget for its minds is appended and never changed'
    using errcode='23514';
end $fn$;

-- A workspace tombstone erases the workspace's models and its worlds' budgets for their minds.
create function tg_tombstone_erases_models_and_minds_budgets() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope::text = 'workspace' then
    perform assert_workspace_context(new.workspace_id);
    delete from workspace_model m where m.workspace_id = new.workspace_id;
    delete from world_minds_budget b where b.workspace_id = new.workspace_id;
  end if;
  return new;
end $fn$;

comment on function tg_tombstone_erases_models_and_minds_budgets() is
  'A workspace tombstone''s erasure of the facts the workspace holds about the models it added '
  'and of every budget set for the minds of its worlds, each of which names an account. Runs as '
  'exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_tombstone_erases_models_and_minds_budgets
  after insert on tombstone
  for each row execute function tg_tombstone_erases_models_and_minds_budgets();

-- WORKSPACES ERASED BEFORE THIS MIGRATION lose their worlds' budgets now (0190 has had a writer
-- since it landed; `workspace_model` is new and holds nothing). This statement reads every
-- workspace: row_security is off and FORCE is lifted on the two tables it reads, so filtering
-- would raise rather than skip a row, and the delete guard is disabled for this delete alone.
-- Nothing else is deleted, and the budget rows go before anything that names their worlds.
-- (one-off: begin)
set local row_security = off;
alter table tombstone no force row level security;
alter table world_minds_budget no force row level security;
alter table world_minds_budget disable trigger tg_world_minds_budget_append_only;
delete from world_minds_budget b
 where exists (select 1 from tombstone tb
                where tb.workspace_id = b.workspace_id and tb.scope = 'workspace'
                  and tb.effective_at <= now());
alter table world_minds_budget enable trigger tg_world_minds_budget_append_only;
alter table world_minds_budget force row level security;
alter table tombstone force row level security;
set local row_security = on;
-- (one-off: end)

do $definer$ begin
  execute format('alter function tg_tombstone_erases_models_and_minds_budgets() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  revoke all on function tg_tombstone_erases_models_and_minds_budgets() from public;
  -- 0161: every SECURITY DEFINER function belongs to exulanica_definer, which this function's
  -- body needs to read and delete the two tables below and nothing else.
  alter function tg_tombstone_erases_models_and_minds_budgets() owner to exulanica_definer;
  grant select, delete on workspace_model, world_minds_budget to exulanica_definer;
end $definer$;

commit;
