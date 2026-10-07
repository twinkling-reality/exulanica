-- A choice may name a gate's visitors.
--
-- 0110 holds the world's owner's choices of who decides for a society's subjects, and 0117 holds
-- each to naming 1 to 512 of them under the one field its role names, people or subjects
-- (world_society_model_choice_names_its_subjects). A visitor whose arrival says the world decides
-- for it (exulanica/world/crossings.py, `decided_by`) is decided for as any being there is, and
-- the owner names the mind every visitor arriving under one grant gets once, when opening the
-- gate, before any of them has arrived: a choice naming a group rather than subjects. Such a
-- choice states `group`, {kind: arrivals_under_grant, grant_id}, and names no subjects
-- (exulanica/world/society_model_choice_repository.py); a choice stating no group keeps 0117's
-- meaning and its bound.
--
-- So 0117's check becomes: the choice names its subjects under one of the two fields, 1 to 512 of
-- them with no `group`, or none with a `group` object. Nothing stored is rewritten: no stored
-- choice states a group.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_model_choice
  drop constraint world_society_model_choice_names_its_subjects;
alter table world_society_model_choice add constraint world_society_model_choice_names_its_subjects
  check (((jsonb_typeof(document->'people') = 'array' and not document ? 'subjects'
           and ((not document ? 'group'
                 and jsonb_array_length(document->'people') between 1 and 512)
                or (jsonb_typeof(document->'group') = 'object'
                    and jsonb_array_length(document->'people') = 0)))
          or (jsonb_typeof(document->'subjects') = 'array' and not document ? 'people'
              and ((not document ? 'group'
                    and jsonb_array_length(document->'subjects') between 1 and 512)
                   or (jsonb_typeof(document->'group') = 'object'
                       and jsonb_array_length(document->'subjects') = 0)))) is true);

commit;
