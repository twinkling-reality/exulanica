-- A gate's choice names its grant and a mind.
--
-- The migration "a choice may name a gate's visitors" admits a choice naming a group instead of
-- subjects, holding only that the group is an object. A gate's choice is always one shape
-- (exulanica/world/society_model_choice_repository.py, record_traveller_choice): the group {kind:
-- arrivals_under_grant, grant_id, ends_at} with the grant's id a UUID in its canonical lowercase
-- text and its end, every grant having one, an instant in UTC to the second that exists on the
-- calendar (the choice decides strictly before it), and a decider that is the world's own (the routine, or a model); never an outside
-- program, which decides only for the subjects its grant names. A group of another shape would be
-- read by every minute's host and every models read of its society.
--
-- So the check is replaced, by its name, with the same rule on subjects and, where a group is
-- stated, that shape. Nothing stored is rewritten: no stored choice states a group yet.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_model_choice
  drop constraint world_society_model_choice_names_its_subjects;
alter table world_society_model_choice add constraint world_society_model_choice_names_its_subjects
  check ((((jsonb_typeof(document->'people') = 'array' and not document ? 'subjects'
            and ((not document ? 'group'
                  and jsonb_array_length(document->'people') between 1 and 512)
                 or (jsonb_typeof(document->'group') = 'object'
                     and jsonb_array_length(document->'people') = 0)))
           or (jsonb_typeof(document->'subjects') = 'array' and not document ? 'people'
               and ((not document ? 'group'
                     and jsonb_array_length(document->'subjects') between 1 and 512)
                    or (jsonb_typeof(document->'group') = 'object'
                        and jsonb_array_length(document->'subjects') = 0))))
          and (not document ? 'group'
               or ((document->'group') - 'kind' - 'grant_id' - 'ends_at' = '{}'::jsonb
                   and case
                         when document->'group'->>'ends_at'
                              ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$'
                         then substr(document->'group'->>'ends_at', 9, 2)::int
                              <= case
                                   when substr(document->'group'->>'ends_at', 6, 2) = '02' then
                                     case
                                       when substr(document->'group'->>'ends_at', 1, 4)::int % 400 = 0
                                         or (substr(document->'group'->>'ends_at', 1, 4)::int % 4 = 0
                                             and substr(document->'group'->>'ends_at', 1, 4)::int % 100 <> 0)
                                       then 29 else 28
                                     end
                                   when substr(document->'group'->>'ends_at', 6, 2)
                                        in ('04', '06', '09', '11') then 30
                                   else 31
                                 end
                         else false
                       end
                   and document->'group'->>'kind' = 'arrivals_under_grant'
                   and document->'group'->>'grant_id'
                       ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                   and document->'decider'->>'kind' in ('routine', 'model')))) is true);

commit;
