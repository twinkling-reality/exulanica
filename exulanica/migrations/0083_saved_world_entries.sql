-- 0083_saved_world_entries.sql
-- A workspace can resume a named personal world at a saved authored branch state and appearance.

begin;

select pg_advisory_xact_lock(119622309);

create table saved_world_entry (
  entry_id             uuid primary key default uuidv7(),
  workspace_id         uuid not null,
  world_id             text not null check (length(world_id) between 1 and 200),
  title                text not null check (length(btrim(title)) between 1 and 200),
  source_kind          text not null check (source_kind = 'personal'),
  authored_version_id  uuid not null,
  authored_state_sha256 text not null check (authored_state_sha256 ~ '^[0-9a-f]{64}$'),
  authored_edit_seq    bigint not null check (authored_edit_seq >= 0),
  style_version_id     uuid not null,
  revision             bigint not null default 1 check (revision >= 1),
  created_by           uuid not null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (workspace_id, world_id),
  unique (workspace_id, entry_id),
  foreign key (workspace_id, world_id, authored_version_id)
    references world_alternate_version(workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, style_version_id)
    references world_style_version(workspace_id, world_id, version_id)
);

create index saved_world_entry_updated_idx
  on saved_world_entry (workspace_id, updated_at desc, entry_id);

alter table saved_world_entry enable row level security;
alter table saved_world_entry force row level security;
create policy ws_isolation on saved_world_entry
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on saved_world_entry to %I', r);
      if r in ('exulanica_app','orimera_app') then
        execute format('grant insert,update on saved_world_entry to %I', r);
      else
        execute format('revoke insert,update,delete on saved_world_entry from %I', r);
      end if;
    end if;
  end loop;
end $$;

commit;
