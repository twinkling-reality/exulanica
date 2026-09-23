-- 0095_a_saved_world_starts_with_a_few_inhabitants.sql
-- A society on a saved world's own ground starts with a handful of people.
--
-- 0075 held every society other than the living one to 100 to 512 inhabitants, the population a
-- district was sized for. A saved world's walkable area is a square about 23 metres across with
-- 121 places to stand, and 128 people there overlap from the first minute, so its society starts
-- with a few. The profiles that read inputs, v2 and v3, may now hold 1 to 512. A row does not say
-- which kind of ground its society stands on, so the district's own floor of 100 is kept by the
-- initializer every creation and every replay passes through, not by this check. The legacy v1
-- society and the living v4 society keep exactly the bounds they had.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_population_size_check;
alter table world_society add constraint world_society_population_size_check
  check((engine_version='exulanica-society/v4' and population_size between 1 and 65536)
    or (engine_version in ('exulanica-society/v2','exulanica-society/v3')
        and population_size between 1 and 512)
    or (engine_version='exulanica-society/v1' and population_size between 100 and 512));

commit;
