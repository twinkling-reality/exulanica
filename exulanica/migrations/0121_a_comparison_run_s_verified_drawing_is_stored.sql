-- 0121_a_comparison_run_s_verified_drawing_is_stored.sql
-- A completed comparison run's drawing, verified once against what the run recorded, is stored.
--
-- Every read of a run replays it from its stored requests and receipts and holds the replay to the
-- digests its outcome recorded, which takes seconds for a town. The host that played the run
-- replays it once, after its outcome is recorded, verifies it the same way, and appends here the
-- document the page draws: society_comparison_replay, keyed by the run and the digest of the code
-- that draws it (drawing_sha256), compressed with gzip, beside the SHA-256 of its uncompressed
-- bytes. A read serves the row whose drawing digest is the code's own, and replays as before where
-- there is none, so a change of the drawing code is read as a replay until a host stores its
-- drawing again, under the new digest, beside the old. The inputs' rights are asked on every read,
-- before anything drawn from them is answered, whichever way the drawing was found.
--
-- A drawing names a registered world (society_comparison_replay_world_is_registered) and a run of
-- a comparison of it that completed. It is appended and never changed, as the records it is drawn
-- from are: a store of the same run under the same drawing digest again is a conflict the writer
-- does nothing on, so the application only inserts and reads.
begin;
select pg_advisory_xact_lock(119622309);

create table society_comparison_replay (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  drawing_sha256 text not null check (drawing_sha256 ~ '^[0-9a-f]{64}$'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  document_bytes integer not null check (document_bytes > 0),
  document_gzip bytea not null check (octet_length(document_gzip) > 0),
  stored_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id, drawing_sha256),
  constraint society_comparison_replay_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references society_comparison_run (workspace_id, world_id, comparison_id, run_id)
);

-- A drawing is of a run whose outcome is recorded and completed.
create function tg_society_comparison_replay_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (
    select 1 from society_comparison_outcome
    where workspace_id = new.workspace_id and world_id = new.world_id
      and comparison_id = new.comparison_id and run_id = new.run_id
      and status = 'completed') then
    raise exception 'a comparison run is drawn once its completed outcome is recorded'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_replay_binding before insert on society_comparison_replay
  for each row execute function tg_society_comparison_replay_binding();

create trigger society_comparison_replay_append_only before update or delete
  on society_comparison_replay for each row execute function tg_society_comparison_append_only();

alter table society_comparison_replay enable row level security;
alter table society_comparison_replay force row level security;
create policy ws_isolation on society_comparison_replay
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- The application appends and reads drawings; read-only roles only read them. Provisioning
-- applies the same shape through exulanica.db.roles, where the table is insert-only.
do $$ declare r text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert on society_comparison_replay to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on society_comparison_replay to %I', r);
    end if;
  end loop;
end $$;

commit;
