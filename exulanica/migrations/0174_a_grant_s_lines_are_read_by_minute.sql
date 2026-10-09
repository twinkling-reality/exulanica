-- 0174_a_grant_s_lines_are_read_by_minute.sql
-- Indexes the door reads by (exulanica/door/channel.py and exulanica/door/grants.py); no table,
-- column or rule changes.
--
-- world_society_event_said: the lines a society recorded, by minute. A poll asks whether a line one
-- of its grant's visitors said or heard came after the place it was told up to, and reads them from
-- there, only within the minutes its visitors were present; without this index each read visited
-- every event of those minutes, whatever its kind.
-- world_society_decision_line_refused: the receipts that refused a program's line because it
-- carried a name the account holder saved (line_refused_by_rules). A grant's first such refusal
-- closes its lines, so every answer that says a line asks whether one exists for the grant.
-- world_society_model_choice_by_group_grant: a gate's traveller choices by the grant they belong
-- to, which the door's finder of grants left to settle reads for each grant it considers.
-- door_grant_by_issue and door_grant_by_workspace_issue: grants by when they were issued. A grant
-- ends at most a day after it is issued, so the finder reads only the grants issued recently enough
-- to have ended within its window, and a workspace's daily bound counts only its last day.
begin;

create index world_society_event_said on world_society_event (workspace_id, society_id, tick)
  where event_kind = 'said';
create index world_society_decision_line_refused on world_society_decision
  (workspace_id, request_id) where document->>'reason' = 'line_refused_by_rules';
create index world_society_model_choice_by_group_grant on world_society_model_choice
  (workspace_id, (document->'group'->>'grant_id')) where document ? 'group';
create index door_grant_by_issue on door_grant (issued_at);
create index door_grant_by_workspace_issue on door_grant (workspace_id, issued_at);

commit;
