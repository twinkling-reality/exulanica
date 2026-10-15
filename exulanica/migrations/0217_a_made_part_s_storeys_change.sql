-- 0217_a_made_part_s_storeys_change.sql
-- A change a person makes to a made part of a site world may state how many storeys a building
-- stands, taller or lower than it was made.
--
-- A CHANGE TO A MADE PART IS AN ELEMENT OVERRIDE THAT NAMES THE PART. Since G1 a move, a turn or a
-- removal of a building, a fixture or an area of a site world is a row of this table whose
-- element_id is `part:<identity>` (exulanica/world/site_parts.py), with the edit log, undo and
-- redo every override has. A building's storeys are one more thing such a change may state, so
-- they are a column of the same row rather than a table of their own: one row per part, one
-- document per edit, one undo.
--
-- NULLABLE, AND STATED ONLY WHEN SET. Every existing row keeps null, the override document states
-- `storeys` only when it is set, and so no stored version's state digest moves. The bound is the
-- site records' own (1 to 64, exulanica/grammar/grammars/site/records.py); the bound a world's kind
-- states (its bounds catalog) is held by the server before a row is written.
--
-- GRANTS. The roles that read and write this table hold table privileges (the runtime's blanket
-- grant, the definer's erasure privileges in exulanica/db/definer_role.py), so the new column needs
-- no grant of its own.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_alternate_element_override
  add column storeys smallint check (storeys between 1 and 64);

-- An override says something: it suppresses, moves, or states storeys.
alter table world_alternate_element_override
  drop constraint world_alternate_override_says_something,
  add constraint world_alternate_override_says_something check (
    suppressed or x_mm is not null or storeys is not null);

comment on column world_alternate_element_override.storeys is
  'How many storeys a made building stands as a person changed it, or null where the change states none. Set only on a row whose element_id names a made part (part:<identity>).';

commit;
