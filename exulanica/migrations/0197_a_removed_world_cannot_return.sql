-- A generated world's erasure is carried through backup restore. The retained record has
-- identities and budget figures only; no title, sentence, document or digest of typed content.
begin;
select pg_advisory_xact_lock(119622309);
alter type tombstone_scope add value if not exists 'world';

create table world_erasure (
  workspace_id uuid not null,
  erasure_id uuid not null default uuidv7(),
  world_id text not null check (length(world_id) between 1 and 200),
  tombstone_id uuid not null unique,
  erased_by uuid not null,
  erased_at timestamptz not null default statement_timestamp(),
  made_at timestamptz not null,
  tiles integer not null check (tiles >= 0),
  primary key (workspace_id, erasure_id),
  unique (workspace_id, world_id)
);
comment on table world_erasure is
  'An irreversible generated-world erasure. Retained identities and creation budget figures '
  'prevent restoration or re-registration from recreating content or resetting its tile budget.';
alter table world_erasure enable row level security;
alter table world_erasure force row level security;
create policy ws_isolation on world_erasure
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
create trigger tg_world_erasure_append_only before update or delete on world_erasure
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on world_erasure
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

create function tg_world_erasure_erases() returns trigger
language plpgsql security definer as $fn$
declare
  v_anchor text;
  v_world world_identity%rowtype;
  v_tiles integer;
begin
  perform assert_workspace_context(new.workspace_id);
  -- Serializes creation, edits and deletion before locking a world's parents.
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
  select case when t.workspace_id = new.workspace_id and t.scope::text = 'world'
                   and t.requested_by = new.erased_by then 'held' else 'another' end
    into v_anchor from tombstone t where t.tombstone_id = new.tombstone_id;
  if v_anchor = 'another' or (v_anchor is null and not exists (
      select 1 from restore_control where state = 'replaying')) then
    raise exception 'a world erasure names its own world tombstone, or is carried by restore'
      using errcode = '23514';
  end if;
  select * into v_world from world_identity
   where workspace_id = new.workspace_id and world_id = new.world_id;
  if found then
    if v_world.kind <> 'generated' then
      raise exception 'only a generated world may be erased through a world erasure'
        using errcode = '23514';
    end if;
    select coalesce(max(jsonb_array_length(receipt->'tiles')), 0) into v_tiles
      from world_generation_receipt
     where workspace_id = new.workspace_id and world_id = new.world_id
       and jsonb_typeof(receipt->'tiles') = 'array';
    if v_anchor = 'held' and (new.made_at <> v_world.created_at or new.tiles <> v_tiles) then
      raise exception 'a world erasure preserves its actual creation budget figures'
        using errcode = '23514';
    end if;
  elsif v_anchor = 'held' then
    raise exception 'a world erasure names a registered world' using errcode = '23514';
  end if;
  update job set state = 'cancelled', completed_at = statement_timestamp(),
    lease_expires_at = null, claim_token = null, claimed_by = null,
    last_error = 'world_removed', failure_class = 'world_removed'
   where workspace_id = new.workspace_id and kind = 'bake_generated_tile'
     and payload->>'world_id' = new.world_id and state in ('queued', 'running');
  perform world_erase_rows(new.workspace_id, new.world_id);
  return null;
end $fn$;
create trigger tg_world_erasure_erases after insert on world_erasure
  for each row execute function tg_world_erasure_erases();

create function tg_removed_world_stays_removed() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
  if exists (select 1 from world_erasure e
             where e.workspace_id = new.workspace_id and e.world_id = new.world_id) then
    raise exception 'a removed world cannot be registered again' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_removed_world_stays_removed before insert on world_identity
  for each row execute function tg_removed_world_stays_removed();

do $$ begin
  execute format('alter function tg_world_erasure_erases() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function tg_world_erasure_erases() from public;
grant select on world_erasure, job to exulanica_definer;
grant update (state, completed_at, lease_expires_at, claim_token, claimed_by, last_error,
              failure_class) on job to exulanica_definer;
alter function tg_world_erasure_erases() owner to exulanica_definer;
commit;
