-- 0096_a_placed_object_s_behaviour_can_change.sql
-- Giving an object that is already in a world a bounded motion, changing it, or taking it away,
-- as one reversible edit.
--
-- Until now a behaviour could be named only in the add_object edit that created the object. A
-- person who placed an object and then wanted it to move had no edit to make, and the only undo
-- that touched its motion was the one that took the whole object away. The first milestone asks
-- for one reversible interaction, and removing the object does not reverse the interaction.
--
-- set_object_behaviour is an OBJECT edit: it names object_id and nothing else, and it stores the
-- whole object document on both sides like move_object does, so undo restores the previous
-- behaviour, parameters included, from the log rather than from a client's memory of it.
-- world_alternate_object needs no change. Its behaviour columns, their completeness check and
-- their foreign key to world_object_behaviour_registry already hold for every row, which is what
-- makes an unreviewed behaviour unwritable by any edit.
--
-- A CHECK cannot be altered in place, so both constraints are restated from 0093 with the one
-- new kind added to the object edits.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_version_edit
  drop constraint world_alternate_version_edit_kind_check;
alter table world_alternate_version_edit
  add constraint world_alternate_version_edit_kind_check check(
    kind in ('add_object','move_object','remove_object','set_object_behaviour',
             'suppress_element','transform_element',
             'add_environment','move_environment','remove_environment',
             'add_point_map','move_point_map','remove_point_map','undo')
  );
alter table world_alternate_version_edit
  drop constraint world_alternate_edit_names_its_subject;
alter table world_alternate_version_edit
  add constraint world_alternate_edit_names_its_subject check(
    (kind in ('add_object','move_object','remove_object','set_object_behaviour')
      and object_id is not null and element_id is null and environment_instance_id is null
      and point_map_instance_id is null)
    or
    (kind in ('suppress_element','transform_element')
      and element_id is not null and object_id is null and environment_instance_id is null
      and point_map_instance_id is null)
    or
    (kind in ('add_environment','move_environment','remove_environment')
      and environment_instance_id is not null and object_id is null and element_id is null
      and point_map_instance_id is null)
    or
    (kind in ('add_point_map','move_point_map','remove_point_map')
      and point_map_instance_id is not null and object_id is null and element_id is null
      and environment_instance_id is null)
    or kind='undo'
  );

commit;
