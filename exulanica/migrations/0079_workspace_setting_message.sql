-- 0079_workspace_setting_message.sql
-- The workspace guard told a writer to set a setting nothing has read since 0028.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- WHAT WAS WRONG. Migration 0001 wrote both halves of this in one section: current_workspace()
-- read `orimera.workspace_id`, and assert_workspace_context() named that same setting in its
-- refusal. 0028 was the pre-release cutover to the Exulanica namespace and redefined the reader to
-- take `exulanica.workspace_id`, which was the whole point of that migration, and left the message
-- as 0001 wrote it.
--
-- WHY IT SURVIVED. Nothing breaks when a refusal names the wrong setting. The refusal is still
-- correct that the session declared no workspace, it still carries insufficient_privilege, and
-- every caller in this repository sets the setting the reader takes, so the sentence is only read
-- by somebody who has already hit the guard. Following it exactly set a setting nothing reads, and
-- the next write failed with the same sentence, which is the worst shape an instruction can have:
-- it is not ignored, it is obeyed and it does not work.
--
-- WHAT THIS CHANGES. The words, and only the words. The condition is the one 0001 wrote and 0028
-- left alone: the session's declared workspace must equal the workspace of the row being written.
-- Same conditions raise, same conditions pass, same errcode, same trigger wiring. Held to that by
-- tests/test_workspace_context_message.py, which checks both the missing and the mismatched case
-- against this function and against a guarded table.

begin;

select pg_advisory_xact_lock(119622309);

create or replace function assert_workspace_context(p_workspace uuid) returns void
language plpgsql as $fn$
begin
  if current_workspace() is distinct from p_workspace then
    raise exception
      'workspace context missing or mismatched: set exulanica.workspace_id to % before writing',
      p_workspace
      using errcode = 'insufficient_privilege';
  end if;
end $fn$;

commit;
