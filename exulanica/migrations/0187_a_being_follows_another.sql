-- 0187_a_being_follows_another.sql
-- A being follows another.
--
-- A society of things whose first input records the follow module
-- (exulanica/abilities/ability-modules.v1.json, exulanica-ability/follow/v2) records when one of its
-- beings begins to follow another and when it stops, with why (exulanica/world/society_things.py):
-- its decider chose to stop or chose something else, the one it followed left, or it could come near
-- it nowhere for the module's minutes. 0166's check on a society event's kind is replaced, by its
-- name, with the same kinds and these two. Nothing stored is rewritten.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked',
    'observed','communicated','decision_applied','user_action_requested',
    'thing_arrived','thing_moved','thing_departed','arrival_refused','departure_refused',
    'said','picked_up','put_down','gave','took','hands_missed',
    'followed','stopped_following'));

commit;
