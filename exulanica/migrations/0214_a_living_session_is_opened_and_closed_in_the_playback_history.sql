-- 0214_a_living_session_is_opened_and_closed_in_the_playback_history.sql
-- A living session, one bounded stretch of a society's playback, is two receipts of the playback
-- history 0059 keeps: session_opened and session_closed.
--
-- A SESSION IS RECEIPTS, NOT A TABLE. A session states who opened it, its limits (seconds of wall
-- time, simulated minutes, decisions, US dollars and model calls), and the tick and state digest it
-- started from; its closing states why it closed, who closed it (none for the system), and the tick
-- and state digest it ended at. Written into world_society_control_event, a session is erased with
-- the society's playback history by the society's erasure (0182, 0183) and the workspace's (0195),
-- read under the same grants and participant scope (0200), digest-chained in the same sequence, and
-- interleaved with the receipts of the minutes it played, so a stretch replays in one ordered
-- history. The alternative, a table of its own, would have had to join every one of those by hand.
--
-- WHAT THIS CHANGES. 0059's check on a receipt's kind is replaced by one that also admits the two
-- session kinds; the receipts 0059 admits are admitted as before. A session receipt must carry its
-- session's identity and its shape below. One session is open at a time per society: the
-- application holds that under the workspace lock every playback write takes (0059's
-- tg_society_control_event_guard takes it too). A partial index finds a society's newest session
-- receipt without walking its minutes.
begin;
select pg_advisory_xact_lock(119622309);

do $$
declare
  found text;
begin
  -- 0059 named no constraint; the one listing the kinds is found by what it lists.
  select c.conname into found
    from pg_constraint c
   where c.conrelid = 'world_society_control_event'::regclass
     and c.contype = 'c'
     and pg_get_constraintdef(c.oid) like '%lease_recovery_exhausted%';
  if found is null then
    raise exception 'the playback history''s check on a receipt''s kind was not found';
  end if;
  execute format('alter table world_society_control_event drop constraint %I', found);
end $$;

alter table world_society_control_event
  add constraint world_society_control_event_kind check (
    (document->>'kind' in ('configured', 'claimed', 'reclaimed', 'advanced', 'manual_step',
      'paused_due_to_error', 'lease_recovery_exhausted', 'session_opened', 'session_closed')) is true
  );

alter table world_society_control_event
  add constraint world_society_control_event_session_opened check (
    document->>'kind' is distinct from 'session_opened' or (
      (document->>'session_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        is true
      and (document->>'request_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        is true
      and (jsonb_typeof(document->'limits') = 'object') is true
      and (jsonb_typeof(document->'start_tick') = 'number') is true
      and (document->>'start_state_sha256' ~ '^[0-9a-f]{64}$') is true
    )
  );

alter table world_society_control_event
  add constraint world_society_control_event_session_closed check (
    document->>'kind' is distinct from 'session_closed' or (
      (document->>'session_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        is true
      and (document->>'reason' ~ '^[a-z][a-z_]{0,62}$') is true
      and (jsonb_typeof(document->'end_tick') = 'number') is true
      and (document->>'end_state_sha256' ~ '^[0-9a-f]{64}$') is true
    )
  );

create index world_society_control_session on world_society_control_event
  (workspace_id, society_id, event_seq desc)
  where document->>'kind' in ('session_opened', 'session_closed');

commit;
