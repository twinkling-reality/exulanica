-- 0225_a_part_edit_states_a_turn_in_place.sql
-- A made part's change says whether it turned the part where it stood.
--
-- A placed thing's turn is told from its edit's own documents (the version read compares the poses
-- before and after). A made part's first change cannot be: its before document is null, since the
-- part stood as the world was made, and the made pose is in the world's records, which only the kind
-- worker generates. The parts route knows that pose when it writes the change, so the change states
-- the turn: true where it kept the part's centre and changed its quarter turns, null everywhere else.
-- Edits written before this, and every other kind, stay null, so the version read says "moved" for
-- them and never guesses a turn. Nothing here is part of a version's state or its digest.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_version_edit add column turned_in_place boolean;
-- Only a made part's change states a turn, and only as true.
alter table world_alternate_version_edit add constraint world_alternate_edit_turn_is_a_part_s check(
  turned_in_place is null or (turned_in_place and kind = 'transform_element')
);

commit;
