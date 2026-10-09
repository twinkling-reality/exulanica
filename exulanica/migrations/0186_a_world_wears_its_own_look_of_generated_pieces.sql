-- 0186_a_world_wears_its_own_look_of_generated_pieces.sql
-- A world wears its own look: a version of its workspace's own style pack, such as the look the
-- generation worker makes of a world's passed generated pieces, and each step of taking pieces in
-- or back is recorded.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
--   world_style_version.style_pack_source
--                           which pack a version's style_pack_* columns name: 'library' (the host's
--                           committed library, as every version written before this migration
--                           names) or 'workspace' (a version of the world's workspace's own pack,
--                           workspace_style_pack_version). A constant default, so no stored row is
--                           rewritten and every one reads 'library'. A version naming no pack
--                           states 'library', which names nothing.
--   tg_world_style_version_wears_its_own_pack
--                           a version naming its workspace's own pack is written only for a look
--                           of generated pieces (origin generated: a creator's own pack id would
--                           outlive the erasure that rewrites pack ids, so none is worn yet), and
--                           only while workspace_style_pack_wearable says it may be worn (ready,
--                           neither it nor its chain withdrawn, the workspace not erased, every
--                           file held), and only naming it by its own id, version and digest. A
--                           version naming a library pack is checked by the domain against the
--                           library, as before. History is never rewritten: a version already
--                           written keeps naming what it named when the pack is later withdrawn,
--                           and the reader draws the world in that version's library base.
--   piece_look_step         each step of a world's look taking a request's generated pieces in, or
--                           back: applied (the world's appearance version written, naming the
--                           derived look by its manifest digest, or the base itself), not_applied
--                           (with its reason: the world wears another look, the look's check
--                           refused it, its chain is full, nothing passed, the write stayed busy
--                           for a day, the workspace holds as many generated looks as it may),
--                           take_back_asked (by whom), taken_back (the version written, or none
--                           when the world no longer wore the request's pieces), not_taken_back
--                           (with the permanent reason the look without them could not be made;
--                           a passing one leaves the take-back asked) and fell_back (the world's
--                           own look that held the request's pieces may no longer be worn, so its
--                           library base was written in its place). Appended once, never changed.
--                           A request is applied or not once, asked back once, taken back or not
--                           once, and falls back once. It holds ids, digests,
--                           instants and catalog codes, no person's text, and is kept with its
--                           request after the workspace's tombstone, as the request is: the
--                           tombstone refuses every new step.
--
-- Under forced row-level security keyed on the workspace. The runtime appends steps and reads them;
-- the read-only role reads them.

begin;
select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. A world's appearance may name its workspace's own pack
-- --------------------------------------------------------------------------------------------

alter table world_style_version
  add column style_pack_source text not null default 'library'
    check (style_pack_source in ('library', 'workspace'));
alter table world_style_version add constraint world_style_version_own_pack_is_named
  check (style_pack_source = 'library' or style_pack_id is not null);

create function tg_world_style_version_wears_its_own_pack() returns trigger
language plpgsql as $fn$
begin
  if new.style_pack_source <> 'workspace' then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from workspace_style_pack_version v
                  where v.workspace_id = new.workspace_id
                    and v.manifest_sha256 = new.style_pack_manifest_sha256
                    and v.pack_id = new.style_pack_id
                    and v.version = new.style_pack_version
                    and v.origin = 'generated'
                    and v.erased_at is null)
     or workspace_style_pack_wearable(new.workspace_id, new.style_pack_manifest_sha256)
          is not true then
    raise exception 'own_pack_not_wearable: a world wears a version of its workspace''s own pack '
                    'only while that version may be worn'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;
do $pin$ begin
  execute format('alter function tg_world_style_version_wears_its_own_pack() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $pin$;
create trigger tg_world_style_version_wears_its_own_pack
  before insert on world_style_version
  for each row execute function tg_world_style_version_wears_its_own_pack();

-- --------------------------------------------------------------------------------------------
-- 2. Each step of a world's look taking generated pieces in or back
-- --------------------------------------------------------------------------------------------

create table piece_look_step (
  workspace_id uuid not null,
  piece_look_step_id uuid not null default uuidv7(),
  piece_request_id uuid not null,
  world_id text not null,
  kind text not null
    check (kind in ('applied', 'not_applied', 'take_back_asked', 'taken_back', 'not_taken_back',
                    'fell_back')),
  reason text check (reason is null or reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  manifest_sha256 text check (manifest_sha256 is null or manifest_sha256 ~ '^[0-9a-f]{64}$'),
  style_version_id uuid,
  asked_by uuid,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, piece_look_step_id),
  foreign key (workspace_id, piece_request_id)
    references piece_request (workspace_id, piece_request_id),
  foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  constraint piece_look_step_reason
    check ((kind in ('not_applied', 'not_taken_back', 'fell_back')) <= (reason is not null)
           and (kind in ('applied', 'take_back_asked')) <= (reason is null)),
  constraint piece_look_step_written
    check ((kind in ('applied', 'fell_back')) <= (style_version_id is not null)
           and (kind in ('not_applied', 'take_back_asked', 'not_taken_back'))
                 <= (style_version_id is null and manifest_sha256 is null)
           and (style_version_id is null) <= (manifest_sha256 is null)),
  constraint piece_look_step_asker
    check ((kind = 'take_back_asked') = (asked_by is not null))
);

create unique index piece_look_step_decided_once on piece_look_step (workspace_id, piece_request_id)
  where kind in ('applied', 'not_applied');
create unique index piece_look_step_asked_once on piece_look_step (workspace_id, piece_request_id)
  where kind = 'take_back_asked';
create unique index piece_look_step_taken_once on piece_look_step (workspace_id, piece_request_id)
  where kind in ('taken_back', 'not_taken_back');
create unique index piece_look_step_fell_back_once
  on piece_look_step (workspace_id, piece_request_id) where kind = 'fell_back';
create index piece_look_step_world on piece_look_step (workspace_id, world_id, recorded_at);

-- Appended under the workspace's context, for the world the request names, in order: decided once
-- the request is made, asked back once it was applied, taken back or not once asked, fallen back
-- from once it was applied. Never changed; the runtime holds no delete.
create function tg_piece_look_step_append_only() returns trigger language plpgsql as $fn$
declare
  v_request record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'a piece look step is recorded once and never changed'
      using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  if exists (select 1 from tombstone t
              where t.workspace_id = new.workspace_id and t.scope = 'workspace') then
    perform tombstone_refuse('piece_look_step');
  end if;
  select p.world_id, p.state into v_request
    from piece_request p
   where p.workspace_id = new.workspace_id and p.piece_request_id = new.piece_request_id;
  if v_request.world_id is distinct from new.world_id then
    raise exception 'a piece look step names its request''s own world' using errcode = '23514';
  end if;
  if new.kind in ('applied', 'not_applied') and v_request.state <> 'made' then
    raise exception 'a request''s pieces are taken into a look only once it is made'
      using errcode = '23514';
  end if;
  if new.kind in ('take_back_asked', 'fell_back')
     and not exists (select 1 from piece_look_step s
                      where s.workspace_id = new.workspace_id
                        and s.piece_request_id = new.piece_request_id and s.kind = 'applied') then
    raise exception 'only pieces a world took in are asked back' using errcode = '23514';
  end if;
  if new.kind in ('taken_back', 'not_taken_back')
     and not exists (select 1 from piece_look_step s
                      where s.workspace_id = new.workspace_id
                        and s.piece_request_id = new.piece_request_id
                        and s.kind = 'take_back_asked') then
    raise exception 'pieces are taken back only once asked' using errcode = '23514';
  end if;
  new.recorded_at := statement_timestamp();
  return new;
end $fn$;
do $pin$ begin
  execute format('alter function tg_piece_look_step_append_only() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $pin$;
create trigger tg_piece_look_step_append_only before insert or update on piece_look_step
  for each row execute function tg_piece_look_step_append_only();

alter table piece_look_step enable row level security;
alter table piece_look_step force row level security;
create policy ws_isolation on piece_look_step
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert on piece_look_step to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on piece_look_step to %I', r);
    end if;
  end loop;
end $$;

commit;
