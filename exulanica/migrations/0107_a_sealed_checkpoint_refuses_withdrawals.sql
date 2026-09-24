-- 0107_a_sealed_checkpoint_refuses_withdrawals.sql
-- A sealed restore checkpoint refuses withdrawals as it refuses tombstones.
--
-- A tombstone is not the only way a person ends something. Stopping a model right, withdrawing a
-- consent, deleting a Companion memory or logging out is recorded in the row it ends or as a row of
-- its own, and a database restored from a backup taken before it holds the thing as current again.
-- So a restore checkpoint of profile exulanica.restore-tombstone-checkpoint/v2 carries every
-- withdrawal `exulanica/deletion/withdrawals.v1.json` names, and replay writes each one again
-- before any tombstone (`exulanica/deletion/restore.py`).
--
-- 0036 made the checkpoint authoritative for tombstones by sealing them at the database boundary:
-- once a checkpoint is sealed, no tombstone insert succeeds, direct SQL included, so nothing the
-- checkpoint misses can be written after it. This does the same for withdrawals. Every table the
-- catalog names gets one trigger: before an update of the columns a withdrawal sets, for a row
-- that records its own withdrawal, and before an insert, for a withdrawal that is a row. While
-- `restore_control` says sealed, it refuses with 0036's words and state. The two withdrawals that
-- also write a tombstone by trigger (0082, 0104) were refused by 0036's seal already; now so is
-- every other.
--
-- The table list below is the catalog's, stated a second time because a migration cannot read the
-- catalog. `tests/test_restore_replay_withdrawal_catalog.py` fails when the two differ.

begin;
select pg_advisory_xact_lock(119622309);

-- With its owner's rights, because the roles that write these tables are not all roles that read
-- restore_control: the account role writes sessions and nothing else, so an invoker's trigger
-- refused every sign-in with "permission denied for table restore_control". The path is pinned and
-- no role may call it, as 0090 does for its trigger functions; a trigger fires without EXECUTE.
create function tg_sealed_checkpoint_refuses_withdrawals() returns trigger
language plpgsql security definer as $fn$
begin
  if exists (select 1 from restore_control where state = 'sealed') then
    raise exception 'restore checkpoint is sealed; offline replay is required before writes'
      using errcode = '55000';
  end if;
  return new;
end $fn$;
do $pin$ begin
  execute format('alter function tg_sealed_checkpoint_refuses_withdrawals() '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $pin$;
revoke all on function tg_sealed_checkpoint_refuses_withdrawals() from public;

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at, withdrawn_by on personal_model_right
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at, withdrawn_by on scene_training_right
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of status, withdrawn_at on companion_answer
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at on environment_source_admission
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of withdrawn_at on derived_environment_asset
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of disabled_at on account_user
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of disabled_at on account_workspace
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of revoked_at on account_membership
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of revoked_at on account_browser_session
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on place_name_right_event
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on person_presentation_consent
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on training_use_consent
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals
  before insert on material_recipe_withdrawal
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

commit;
