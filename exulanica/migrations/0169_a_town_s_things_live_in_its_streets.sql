-- 0169_a_town_s_things_live_in_its_streets.sql
-- A society of things over a generated town: its input is the town's walking surfaces with the things
-- placed in its region (exulanica.society-input/walking-surfaces-v3, composed by
-- exulanica/world/society_walking_surfaces.py). The input checks admit the profile beside the ones
-- they admit already; each check is restated with the new profile added and nothing removed, and no
-- other object changes. Its population is the town's residents, its routine the purposeful one, its
-- placements unread as walking-surfaces-v1's are, and its things listed as the authored ground's
-- things composition lists them.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3',
     'exulanica.society-input/authored-ground-v4',
     'exulanica.society-input/authored-ground-v5',
     'exulanica.society-input/walking-surfaces-v1',
     'exulanica.society-input/walking-surfaces-v2',
     'exulanica.society-input/walking-surfaces-v3')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/authored-ground-v5',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2',
                                       'exulanica.society-input/walking-surfaces-v3')
      then (jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)) is true
    else not (document ? 'unread_placements') end
  );

alter table world_society_input drop constraint world_society_input_routine_check;
alter table world_society_input add constraint world_society_input_routine_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/authored-ground-v5',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2',
                                       'exulanica.society-input/walking-surfaces-v3')
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

alter table world_society_input drop constraint world_society_input_population_check;
alter table world_society_input add constraint world_society_input_population_check
  check (
    case when document->>'profile' in ('exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2',
                                       'exulanica.society-input/walking-surfaces-v3')
      then (jsonb_typeof(document->'population')='object'
        and ((document->'population') - 'rule' - 'size') = '{}'::jsonb
        and jsonb_typeof(document->'population'->'rule')='string'
        and length(document->'population'->>'rule') between 1 and 1000
        and case when jsonb_typeof(document->'population'->'size')='number'
              then (document->'population'->>'size') ~ '^[0-9]+$'
                and (document->'population'->>'size')::numeric between 0 and 512
              else false end) is true
    else not (document ? 'population') end
  );

-- The things compositions list placed things, and an unavailable input lists none.
alter table world_society_input drop constraint world_society_input_things_check;
alter table world_society_input add constraint world_society_input_things_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v5',
                                       'exulanica.society-input/walking-surfaces-v3')
      then (jsonb_typeof(document->'things')='array'
        and jsonb_array_length(document->'things')<=4096
        and (document->>'availability'='available'
          or document->'things'='[]'::jsonb)) is true
    else not (document ? 'things') end
  );

commit;
