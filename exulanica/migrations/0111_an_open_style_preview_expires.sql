-- 0111_an_open_style_preview_expires.sql
-- An appearance preview nobody decides within its lifetime closes as expired, and says so.
--
-- A preview stays open until a person applies or discards it or a new proposal replaces it, and a
-- page that reloads or closes without deciding leaves its last one open. The world closes one that
-- outlives OPEN_PREVIEW_LIFETIME (exulanica/world/repository.py) under the lock every Apply and new
-- preview of that world takes first, and Apply refuses one past it by name (preview_expired).
--
-- Closing it as 'discarded' would tell the proposal read (GET /world/styles/proposals/{id}) and the
-- Companion that a person threw the change away, and 'stale' that a later version exists. So the
-- lifecycle 0017 declared gains its own value: 'expired' for the preview and its proposal, and a
-- 'preview_expired' audit event. The checks are 0017's inline column checks, under the names
-- PostgreSQL gave them.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_style_preview drop constraint world_style_preview_status_check;
alter table world_style_preview add constraint world_style_preview_status_check
  check (status in ('open','applied','discarded','stale','expired'));

alter table world_style_proposal drop constraint world_style_proposal_status_check;
alter table world_style_proposal add constraint world_style_proposal_status_check
  check (status in ('previewed','rejected','applied','discarded','stale','expired'));

alter table world_style_audit_event drop constraint world_style_audit_event_event_type_check;
alter table world_style_audit_event add constraint world_style_audit_event_event_type_check
  check (event_type in ('proposal_rejected','preview_created','preview_applied',
                        'preview_discarded','preview_stale','preview_expired',
                        'style_rolled_back'));

commit;
