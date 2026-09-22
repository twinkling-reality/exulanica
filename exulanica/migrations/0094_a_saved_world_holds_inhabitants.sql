-- 0094_a_saved_world_holds_inhabitants.sql
-- The third society input profile: a saved world's own authored ground.
--
-- 0053 and 0057 admit society inputs composed from an admitted district interpretation, whose
-- walkable area comes from real city sources and whose frame is surveyed. A world a person
-- saved has neither. Its spatial authority is the flat authored ground its own structural
-- snapshot declares, and the only activities in it are the reviewed objects the person placed.
-- That is a different composition, so it carries a different profile rather than borrowing one
-- and leaving a reader to guess which kind of area a stored input describes.
--
-- The shape check moves with it. Both later profiles publish `unavailable_affordances`, so the
-- rule 0057 wrote for input/v2 applies unchanged to this one: a bounded list, and empty
-- whenever the input as a whole is unavailable, so that losing an area never becomes a licence
-- to keep showing what could once be reached in it. Retained input/v1 documents still carry no
-- such list at all, and this migration does not touch them.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1')) is true);

alter table world_society_input drop constraint world_society_input_local_shape_check;
alter table world_society_input add constraint world_society_input_local_shape_check
  check (
    case when document->>'profile'='exulanica.society-input/v1'
      then not (document ? 'unavailable_affordances')
    when jsonb_typeof(document->'unavailable_affordances')='array'
      then jsonb_array_length(document->'unavailable_affordances')<=4096
        and (document->>'availability'='available'
          or document->'unavailable_affordances'='[]'::jsonb)
    else false end
  );

commit;
