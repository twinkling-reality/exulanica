-- 0157_a_revoked_door_secret_is_kept_and_a_secret_is_stamped.sql
-- The door's secrets (migration 0149), as the door now relies on them.
--
-- A revoked secret is a withdrawal of the permission it held, written once and never undone, so it
-- is kept: door_prune removes only secrets thirty days past their end that nobody revoked, and the
-- secret's own trigger refuses deleting a revoked one, whoever asks. A database that keeps door rows
-- therefore never meets a revocation its later checkpoint lacks. Backup sets carry no door secret at
-- all (exulanica/orchestration/installation/backup_set.py), so a restore from one voids every
-- credential; 0149's notes that a restore writes a secret's revocation again describe neither.
--
-- A secret's created_at is stamped at insert, whatever the writer states: a grant answers to the
-- one program holding its live channel credential, and the channel counts a hello only when it was
-- said after that credential was created (exulanica/door/channel.py, presence_of).
--
-- A secret's revocation is carried by a restore in its own workspace's session, so what a
-- checkpoint holds of it names the workspace: the catalog's identity for a secret is its workspace
-- and its digest (exulanica/deletion/withdrawals.v2.json), a key this states.
--
-- The read-only role reads neither global door table, as provisioning already withholds them
-- (exulanica/db/roles.py, READ_ONLY_WITHHELD_TABLES): 0149 granted it neither, and this revokes any
-- grant a default privilege gave it between 0149 and the next provisioning.
--
-- Both functions are replaced in place, so each keeps its owner and its privileges: door_prune
-- stays owned by exulanica_definer where the migration handing every definer to that role has run,
-- with the same select and delete on the two tables, still the only ones its body reads or deletes.
begin;
select pg_advisory_xact_lock(119622309);

do $replace$
begin
  execute format($body$
create or replace function %1$I.tg_door_secret_change() returns trigger
language plpgsql
set search_path = %1$I, pg_catalog, pg_temp
as $fn$
begin
  if tg_op = 'DELETE' then
    if old.revoked_at is not null then
      raise exception 'a revoked door secret is kept' using errcode = '23514';
    end if;
    if old.expires_at > statement_timestamp() - interval '30 days' then
      raise exception 'a door secret is kept for thirty days after its end'
        using errcode = '23514';
    end if;
    return old;
  end if;
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    if new.used_at is not null or new.revoked_at is not null then
      raise exception 'a door secret is issued unused and unrevoked' using errcode = '23514';
    end if;
    new.created_at := statement_timestamp();
    return new;
  end if;
  perform assert_workspace_context(old.workspace_id);
  if (new.secret_sha256, new.kind, new.bridge, new.workspace_id, new.grant_id, new.created_at,
      new.expires_at)
     is distinct from
     (old.secret_sha256, old.kind, old.bridge, old.workspace_id, old.grant_id, old.created_at,
      old.expires_at)
     or (old.used_at is not null and new.used_at is distinct from old.used_at)
     or (old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at) then
    raise exception 'a door secret only gains the time it was used and the time it was revoked'
      using errcode = '23514';
  end if;
  return new;
end $fn$;

create or replace function %1$I.door_prune(p_batch integer) returns integer
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $fn$
declare
  pruned integer := 0;
  counted integer;
begin
  if p_batch is null or p_batch < 1 or p_batch > 1000 then
    raise exception 'a prune removes 1 to 1000 rows of each table' using errcode = '22023';
  end if;
  delete from %1$I.door_redemption_refusal
   where ctid in (select ctid from %1$I.door_redemption_refusal
                   where refused_at < pg_catalog.statement_timestamp() - interval '1 day'
                   limit p_batch);
  get diagnostics counted = row_count;
  pruned := pruned + counted;
  delete from %1$I.door_secret
   where secret_sha256 in (select secret_sha256 from %1$I.door_secret
                            where revoked_at is null
                              and expires_at < pg_catalog.statement_timestamp() - interval '30 days'
                            limit p_batch);
  get diagnostics counted = row_count;
  return pruned + counted;
end $fn$;
$body$, current_schema());
end $replace$;

alter table door_secret add constraint door_secret_workspace_secret
  unique (workspace_id, secret_sha256);

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'exulanica_ro') then
    revoke all on door_secret, door_redemption_refusal from exulanica_ro;
  end if;
end $$;

commit;
