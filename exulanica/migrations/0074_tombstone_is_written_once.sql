-- A tombstone is written once. Its scope, its subject, who asked and when it takes effect never
-- change after insert, and the only column anything may move afterwards is purge_completed_at,
-- which the purge worker sets when the deletion has actually happened and an offline restore
-- clears when it replays one.
--
-- Until now nothing enforced that. Provisioning granted the runtime role UPDATE on every table,
-- tombstone included, so the process that serves requests could push a tombstone's effective_at a
-- year out (tombstone_blocks_derivative filters effective_at <= clock_timestamp(), so every
-- tombstone would stop blocking derivatives, which reopens what 0011 closed), rewrite its scope or
-- subject, or mark a purge complete over bytes still on disk. The purge role's grant is column by
-- column; the runtime's was not. Provisioning now revokes that UPDATE. This trigger is the second
-- wall, for a role provisioned before that revoke and for any role granted UPDATE by hand:
--
--   * any change to a column other than purge_completed_at is refused, for every role; and
--   * purge_completed_at may change only for the table owner or a member of it, a superuser or
--     BYPASSRLS administrator (the offline restore requires one), or a role whose only write on
--     this table is UPDATE of purge_completed_at itself, which is the shape provisioning gives the
--     purge role and nothing else. Role names are deployment configuration, so the grant shape is
--     what is checked, not a name.
begin;
select pg_advisory_xact_lock(119622309);

create function tg_tombstone_is_written_once() returns trigger
language plpgsql as $fn$
declare
  v_owner oid;
begin
  -- Every column but one, compared whole, so a column added later is covered without an edit.
  if (to_jsonb(new) - 'purge_completed_at') is distinct from
     (to_jsonb(old) - 'purge_completed_at') then
    raise exception 'a tombstone is written once; only its purge completion may change'
      using errcode = '23514';
  end if;
  if new.purge_completed_at is distinct from old.purge_completed_at then
    select c.relowner into v_owner from pg_class c where c.oid = tg_relid;
    if not (
      pg_has_role(current_user, v_owner, 'MEMBER')
      or exists (select 1 from pg_roles r
                 where r.rolname = current_user and (r.rolsuper or r.rolbypassrls))
      or (has_column_privilege(current_user, tg_relid, 'purge_completed_at', 'UPDATE')
          and not has_table_privilege(current_user, tg_relid, 'UPDATE')
          and not has_table_privilege(current_user, tg_relid, 'INSERT'))
    ) then
      raise exception 'only the purge worker or an administrator records a purge completion'
        using errcode = '42501';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_tombstone_is_written_once before update on tombstone
  for each row execute function tg_tombstone_is_written_once();

comment on function tg_tombstone_is_written_once() is
  'A tombstone changes only in purge_completed_at, and only for its owner, an administrator, or '
  'a role holding UPDATE on that column alone.';

commit;
