-- 0109_a_sealed_checkpoint_refuses_retractions.sql
-- A sealed restore checkpoint refuses a person's retraction as it refuses every other withdrawal.
--
-- A person who withdraws a claim they made writes a retraction row and sets the claim's status to
-- 'retracted' (exulanica/epistemics/assertions.py retract). Retracting a name takes it off the
-- place or person (0002), and a place-name right rests on an active naming claim (0097), so a
-- retraction can end a right. A restore checkpoint therefore carries it
-- (`exulanica/deletion/withdrawals.v2.json`, kind retraction), and replay writes it again with the
-- product's retract.
--
-- 0107 sealed every other catalog table. This seals the retraction row, with 0107's function:
-- once a checkpoint is sealed, no retraction is written, direct SQL included, so none the
-- checkpoint misses can be written after it. The claim's status is not sealed. A retraction writes
-- its row first, and a status set by a tombstone's cascade is refused already, because the seal
-- refuses the tombstone (0036).
--
-- `tests/test_restore_replay_withdrawal_catalog.py` holds the sealed tables equal to the catalog's.

begin;
select pg_advisory_xact_lock(119622309);

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on retraction
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

commit;
