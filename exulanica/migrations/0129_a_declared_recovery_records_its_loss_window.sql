-- A crash recovery replays a withdrawal export under an operator's declaration, and withdrawals
-- the source accepted after that export are not recovered. The completion receipt records that
-- declared window beside the attempt it certifies, so the database that serves afterwards says
-- what it may be missing, not only the external marker. A planned restore from a sealed
-- checkpoint loses nothing and leaves every new column null. Existing receipts are unchanged.
begin;
select pg_advisory_xact_lock(119622309);

alter table restore_replay_receipt
  add column recovery_mode text check (recovery_mode = 'declared'),
  add column covered_through timestamptz,
  add column incident_at timestamptz,
  add column loss_window_microseconds bigint check (loss_window_microseconds >= 0),
  add column max_export_lag_microseconds bigint check (max_export_lag_microseconds > 0),
  -- Every term is either null-tested or guarded by one, so the check is true or false and never
  -- null: a check that evaluates to null passes, and a half-stated window must not.
  add constraint restore_replay_receipt_declared_window check (
    (recovery_mode is null and covered_through is null and incident_at is null
     and loss_window_microseconds is null and max_export_lag_microseconds is null)
    or (recovery_mode is not null and covered_through is not null and incident_at is not null
        and loss_window_microseconds is not null and max_export_lag_microseconds is not null
        and recovery_mode = 'declared' and incident_at >= covered_through
        and loss_window_microseconds
            = (extract(epoch from incident_at - covered_through) * 1000000)::bigint
        and max_export_lag_microseconds >= loss_window_microseconds)
  );

comment on column restore_replay_receipt.recovery_mode is
  'declared for a crash recovery that replayed a withdrawal export; null for a planned restore.';
comment on column restore_replay_receipt.loss_window_microseconds is
  'incident_at minus covered_through: withdrawals committed in this window are not restored.';

commit;
