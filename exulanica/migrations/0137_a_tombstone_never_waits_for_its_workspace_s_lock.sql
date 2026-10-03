-- 0137_a_tombstone_never_waits_for_its_workspace_s_lock.sql
-- A tombstone never waits for its workspace's lock: while another transaction holds it, the
-- tombstone is refused, retryably, and the transaction that wrote it writes nothing.
--
-- A tombstone takes migration 0041's asset read barrier on its shared side first
-- (aaa_asset_read_mutation, the first of its BEFORE triggers), and 0020's
-- tg_world_structure_invalidate_on_tombstone then takes the workspace's lock,
-- hashtextextended(workspace_id::text, 880024). A stopped search or training right writes its
-- tombstone from a trigger on its own guarded row (0104, 0082), so it holds the shared side before
-- its tombstone does. A transaction that reads assets as it writes takes the two locks the other
-- way round: the workspace's lock, then the barrier's exclusive side (a society's playback round
-- and its runtime, an object edit, a version branch; docs/asset-read-currency.md). A tombstone
-- written between a reader's two locks held what the reader waited for and waited for what the
-- reader held, until PostgreSQL ended one of them after deadlock_timeout (40P01): the deletion,
-- answered busy late, or the reader, a playback round whose society then waited out its lease.
--
-- This trigger fires first of the tombstone's AFTER triggers, before 0020's, and takes the
-- workspace's lock without waiting. A transaction that already holds it takes it again. One that
-- finds it held by another transaction is refused with 40001, which the API answers 409 busy:
-- the tombstone, the change it records and every row its triggers wrote roll back with it, and
-- the deletion is to be sent again. No other lock moves and nothing waits that did not before;
-- the waits a tombstone's BEFORE triggers make are unchanged.

begin;

select pg_advisory_xact_lock(119622309);

create function tg_a_tombstone_never_waits_for_its_workspace_s_lock() returns trigger
language plpgsql as $fn$
begin
  if not pg_try_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024)) then
    raise exception 'workspace in use; retry the deletion' using errcode = '40001';
  end if;
  return new;
end $fn$;

-- Named to sort first: AFTER ROW triggers on one event fire in name order.
create trigger tg_a_tombstone_never_waits_for_its_workspace_s_lock
  after insert on tombstone
  for each row execute function tg_a_tombstone_never_waits_for_its_workspace_s_lock();

commit;
