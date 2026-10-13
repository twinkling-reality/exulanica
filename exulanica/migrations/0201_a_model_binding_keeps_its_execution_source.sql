-- A runtime binding source retains the complete manifest, proof identities and actual rates.
-- It grants no execution permission. Execution reconstructs current proof and authorization.
begin;
select pg_advisory_xact_lock(119622309);
create table workspace_model_binding_snapshot (
  workspace_id uuid not null,
  binding_sha256 text not null check(binding_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check(jsonb_typeof(document)='object'
    and octet_length(document::text)<=1048576),
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,binding_sha256),
  check((document->>'profile'='exulanica.workspace-model-binding/v1') is true
    and (document->>'document_sha256'=binding_sha256) is true)
);
alter table workspace_model_binding_snapshot enable row level security;
alter table workspace_model_binding_snapshot force row level security;
create policy ws_isolation on workspace_model_binding_snapshot
  using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());
create function tg_workspace_model_binding_live() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  if exists(select 1 from tombstone where workspace_id=new.workspace_id and scope='workspace') then
    raise exception 'an erased workspace holds no binding source' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_workspace_model_binding_live before insert on workspace_model_binding_snapshot
  for each row execute function tg_workspace_model_binding_live();
create trigger tg_model_probe_append_only before update or delete on workspace_model_binding_snapshot
  for each row execute function tg_model_probe_append_only();
create function tg_workspace_model_binding_erases() returns trigger language plpgsql security definer as $fn$
begin
  if new.scope::text='workspace' then
    perform assert_workspace_context(new.workspace_id);
    delete from workspace_model_binding_snapshot where workspace_id=new.workspace_id;
  end if;
  return new;
end $fn$;
create trigger tg_workspace_model_binding_erases after insert on tombstone
  for each row execute function tg_workspace_model_binding_erases();
do $definer$ begin
  execute format('alter function tg_workspace_model_binding_erases() set search_path=pg_catalog,%I,pg_temp',current_schema());
  revoke all on function tg_workspace_model_binding_erases() from public;
  alter function tg_workspace_model_binding_erases() owner to exulanica_definer;
  grant select,delete on workspace_model_binding_snapshot to exulanica_definer;
end $definer$;
commit;
