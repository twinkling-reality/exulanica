-- 0191_a_town_holds_the_people_its_homes_house.sql
-- A town's society holds as many people as its homes house and its host runs: the schema states
-- no maximum for the engines a town's society is made with.
--
-- The purposeful society, the living town and the society of things (exulanica-society/v2, v5 and
-- v7) were held to 512 people by two checks: the society row's population (0151) and the
-- population a town's input records (0169). The figure came with the first stored district
-- society (0052) and no measurement stood behind it for a town. How many people a town holds is
-- now its homes' own number, admitted where the society is made by the measured cost of a minute
-- on the host that makes it (the society ground catalog's minute_cost,
-- exulanica/world/society_grounds.py), so the engine table states no maximum for those engines
-- (exulanica/world/society-engines.v4.json, held to this schema by
-- tests/test_society_engine_table.py) and these checks hold them to their minimum alone.
--
-- Every other engine keeps the bounds it had: the living society over a district one to 65,536,
-- the retired exulanica-society/v3 one to 512 (no society is made with it), the first engine 100
-- to 512. An input still records a rule and a whole number of people, nobody included, in exactly
-- those two keys; a society that would hold nobody is refused by name before a row is written.
--
-- Both checks only widen: every stored row passes the check it passed before, and no row is
-- rewritten.
--
-- Touches: world_society (constraint world_society_population_size_check) and world_society_input
-- (constraint world_society_input_population_check). No table, column, index, trigger, function,
-- grant or policy is added, removed or altered.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_population_size_check;
alter table world_society add constraint world_society_population_size_check
  check((engine_version='exulanica-society/v4' and population_size between 1 and 65536)
    or (engine_version in ('exulanica-society/v2','exulanica-society/v5','exulanica-society/v7')
        and population_size >= 1)
    or (engine_version='exulanica-society/v3' and population_size between 1 and 512)
    or (engine_version='exulanica-society/v1' and population_size between 100 and 512));

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
              else false end) is true
    else not (document ? 'population') end
  );

commit;
