-- A being's hands act.
--
-- A society of things whose first input records the hands module
-- (exulanica/abilities/ability-modules.v1.json, exulanica-ability/hands/v1) records what its beings'
-- hands do: a thing picked up, put down, given to another being or taken from one, each in the
-- minute the being stands within reach (exulanica/world/society_things.py), and a hands act
-- dropped because the thing or the other being was gone or never came within reach. 0151's check
-- on a society event's kind is replaced, by its name, with the same kinds and these five. Nothing
-- stored is rewritten.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked',
    'observed','communicated','decision_applied','user_action_requested',
    'thing_arrived','thing_moved','thing_departed','arrival_refused','departure_refused',
    'said','picked_up','put_down','gave','took','hands_missed'));

commit;
