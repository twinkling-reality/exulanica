begin;
select pg_advisory_xact_lock(119622309);

-- Independent authored appearance history. No mutation of identity or simulation history.
-- Current state is the last revision; no second mutable pointer can disagree with history.
create table world_character_appearance_revision (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  subject_kind text not null check(subject_kind in ('avatar','synthetic-inhabitant')),
  subject_id uuid not null,
  society_id uuid,
  revision bigint not null check(revision > 0),
  operation text not null check(operation in ('save','reset')),
  restored_from_revision bigint check(restored_from_revision > 0),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,world_id,version_id,subject_kind,subject_id,revision),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  check((subject_kind='synthetic-inhabitant') = (society_id is not null)),
  check(restored_from_revision is null or (operation='reset' and restored_from_revision < revision))
);

create function tg_character_appearance_revision() returns trigger language plpgsql as $fn$
declare last_revision bigint;
begin
  if tg_op <> 'INSERT' then
    raise exception 'character appearance revisions are append-only' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select coalesce(max(revision),0) into last_revision
    from world_character_appearance_revision
    where workspace_id=new.workspace_id and world_id=new.world_id
      and version_id=new.version_id and subject_kind=new.subject_kind and subject_id=new.subject_id;
  if new.revision <> last_revision+1 then
    raise exception 'character appearance revision is not the next revision' using errcode='23514';
  end if;
  if new.subject_kind='synthetic-inhabitant' and not exists (
    select 1 from world_society where workspace_id=new.workspace_id
      and world_id=new.world_id and version_id=new.version_id and society_id=new.society_id
  ) then
    raise exception 'character subject belongs to another branch' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger character_appearance_revision_guard
before insert or update or delete on world_character_appearance_revision
for each row execute function tg_character_appearance_revision();
alter table world_character_appearance_revision enable row level security;
alter table world_character_appearance_revision force row level security;
create policy ws_isolation on world_character_appearance_revision
using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());
commit;
