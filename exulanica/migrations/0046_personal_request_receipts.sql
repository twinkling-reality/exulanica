-- Personal operations retain identity-only replay receipts, never original media or request bodies.
begin;
select pg_advisory_xact_lock(119622309);

create table personal_request_receipt (
  workspace_id uuid not null,
  actor_id uuid not null,
  request_id uuid not null,
  operation text not null,
  request_sha256 bytea not null check (octet_length(request_sha256)=32),
  capture_ids uuid[] not null,
  subject_ids uuid[] not null,
  response_refs jsonb not null check (jsonb_typeof(response_refs)='object'),
  recorded_at timestamptz not null default clock_timestamp(),
  primary key (workspace_id, actor_id, request_id)
);
alter table personal_request_receipt enable row level security;
alter table personal_request_receipt force row level security;
create policy ws_isolation on personal_request_receipt
  using (workspace_id=current_workspace()) with check (workspace_id=current_workspace());
create trigger tg_personal_request_receipt_append_only before update or delete
  on personal_request_receipt for each row execute function tg_reconstruction_privacy_append_only();

-- Same retention as existing immutable consent receipts. Tombstones suppress replay/status
-- through current access checks; the minimal identity/digest audit stub survives deletion.
-- Runtime grants are supplied by the existing schema-wide role provisioning, not SECURITY DEFINER.
commit;
