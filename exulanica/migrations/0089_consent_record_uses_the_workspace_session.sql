-- 0089_consent_record_uses_the_workspace_session.sql
-- consent_record isolation uses the same session workspace as every other forced table.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- The table's isolation column is still tenant_id, the name 0001 gave the workspace
-- on this table. The session identity is current_workspace(), which reads
-- exulanica.workspace_id. The policy 0001 wrote compared tenant_id to
-- orimera.tenant_id, a setting no session setter writes. A session that declares
-- its workspace therefore saw no consent rows and could not write them.
--
-- This replaces the policy expressions so the owning workspace can read and write
-- its rows, another workspace cannot, and the historical orimera.tenant_id
-- setting is not part of the predicate. PostgreSQL has no CREATE OR REPLACE
-- POLICY; ALTER POLICY is the replacement. FORCE row-level security remains.
-- Held by tests/test_row_level_security.py.

begin;

select pg_advisory_xact_lock(119622309);

alter table consent_record enable row level security;
alter table consent_record force  row level security;

alter policy tenant_isolation on consent_record
  using (tenant_id = current_workspace())
  with check (tenant_id = current_workspace());

commit;
