-- A visitor whose arrival said the world decides for it may be directed by a person's request.
--
-- 0151 refused every visitor a direct request: its own program decides for it. A visitor whose
-- arrival said the world decides for it (decided_by world, kept in its crossing record) is decided
-- for as any being here, so a person's request may direct it as one; exulanica/world/
-- society_actions.py's may_be_directed says the same, and tests/test_society_request_rule_parity.py
-- holds the two equal. society_person_may_be_directed is 0151's with that one clause added. No
-- stored row changes: a request is checked when it is recorded.
begin;
select pg_advisory_xact_lock(119622309);

create or replace function society_person_may_be_directed(person jsonb, input jsonb) returns boolean
  language sql immutable parallel safe as $fn$
  select ((coalesce(person->>'came_by','') <> 'crossed'
      or person->'crossing'->>'decided_by' = 'world')
    and (person->'goal'='null'::jsonb
      or person->'action'->>'status' in ('completed','blocked')
      or (input ? 'routine'
        and person->'action'->>'status'='active'
        and person->'action'->>'kind' not in ('move','idle')
        and person->'location'->'edge'='null'::jsonb))) is true
$fn$;

commit;
