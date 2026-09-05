-- An offline restore must replay a sealed external deletion checkpoint before serving.
-- The checkpoint writer is administrative; neither the runtime nor the purger may certify it.
begin;
select pg_advisory_xact_lock(119622309);

create table restore_control (
  singleton boolean primary key default true check (singleton),
  checkpoint_id uuid not null,
  checkpoint_sha256 text not null check (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
  state text not null check (state in ('sealed','replaying','complete')),
  restore_id uuid,
  updated_at timestamptz not null default now()
);
create table restore_replay_receipt (
  restore_id uuid primary key,
  checkpoint_id uuid not null,
  checkpoint_sha256 text not null check (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
  tombstone_count integer not null check (tombstone_count >= 0),
  completed_at timestamptz not null default now()
);

create function tg_sealed_checkpoint_refuses_tombstones() returns trigger
language plpgsql as $fn$
begin
  -- The row lock also closes the lock-free INSERT race against checkpoint creation:
  -- checkpoint holds ACCESS EXCLUSIVE on tombstone until its seal commits.
  if exists (select 1 from restore_control where state = 'sealed') then
    raise exception 'restore checkpoint is sealed; offline replay is required before writes'
      using errcode = '55000';
  end if;
  return new;
end $fn$;
create trigger tg_sealed_checkpoint_refuses_tombstones before insert on tombstone
  for each row execute function tg_sealed_checkpoint_refuses_tombstones();

comment on table restore_control is
  'Administrative offline restore gate. No row means no declared restore. A sealed checkpoint '
  'refuses new tombstones; replaying refuses API startup. External pending state survives restore.';
comment on table restore_replay_receipt is
  'Completion certified only after replayed tombstones and their object-store purge are verified. '
  'An external restore attempt UUID prevents a receipt restored from backup authorizing traffic.';
-- pg_dump restores COPY with an empty search_path. Recursive validators used by CHECK
-- constraints must therefore carry their own schema, rather than relying on a caller path.
do $restore_path$
begin
  execute format('alter function %I.jsonschema_unsupported_keyword(jsonb) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema(), current_schema());
  execute format('alter function %I.jsonschema_violation(jsonb,jsonb,text) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema(), current_schema());
end $restore_path$;
commit;
