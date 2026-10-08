-- A thing may wear a look its workspace keeps, named by the look's digest alone.
--
-- 0156 records the look a thing wears as a shipped look by key, version and digest. A workspace
-- also keeps looks of its own (0159: a creature's sketch, a look a deployment built or imported),
-- which a world names only by the SHA-256 of the look's document, never by a key a person's words
-- made. So a choice now states where its look comes from (source): 'shipped', named by key,
-- version and digest as before, or 'workspace', named by its digest alone, its key and version
-- left null. Whether that digest is a look the workspace still holds, and not withdrawn, is read
-- when a choice is made and again whenever the choices are read
-- (exulanica/world/thing_looks.py): a choice naming a look the workspace no longer holds stays
-- (choices are appended and never changed) and is passed by.
--
-- Every stored choice names a shipped look, so it reads 'shipped'; nothing stored is rewritten.
--
-- A thing's card shows the lines a being said lately (exulanica/api/thing_card.py), read by the
-- speaker. Every earlier index on the event table leads with the workspace, the society and the
-- minute, so that read would walk a society's whole history for a being that never spoke; said
-- events are indexed by their speaker here, and only they.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_thing_look
  add column source text not null default 'shipped'
    check (source in ('shipped', 'workspace'));

alter table world_thing_look alter column look drop not null;
alter table world_thing_look alter column look_version drop not null;

-- A shipped look is named by key and version beside its digest; a workspace's by its digest alone.
alter table world_thing_look add constraint world_thing_look_names_its_source check (
  ((source = 'shipped') = (look is not null and look_version is not null)
   and (source = 'workspace') = (look is null and look_version is null)) is true
);

create index world_society_event_said_by_speaker
  on world_society_event(workspace_id,society_id,subject_id,tick)
  where event_kind = 'said';

commit;
