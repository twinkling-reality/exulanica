-- A choice names its decider.
--
-- 0110 holds a person's model choices, each naming `model`: a model the manifest declares, or
-- none for the world's own routine. From the decision role registry's third version a choice
-- names `decider` instead, the descriptor `exulanica.decider/v1`: the routine, a model, or an
-- outside program deciding under a grant the world's owner issued, whose kind it states
-- (exulanica/world/deciders.py). A choice of either shape stays as it was written and is read as
-- it was written: every first choice keeps its `model`, and the application reads it as the
-- routine or the model it names.
--
-- So the check 0110 stated inline, that `model` is an object or null, becomes: a choice names
-- exactly one of `model` (an object or null) and `decider` (an object of a kind a choice may bind:
-- routine, model or external). A person decides through direct requests and is never a choice's
-- decider. 0110 stated the check inline, so PostgreSQL named it; it is found by what it checks,
-- as 0117 found the others, rather than by a name this file would have to guess.

begin;
select pg_advisory_xact_lock(119622309);

do $$ declare held text; begin
  for held in select conname from pg_constraint
      where conrelid = 'world_society_model_choice'::regclass and contype = 'c'
        and pg_get_constraintdef(oid) like '%''model''%' loop
    execute format('alter table world_society_model_choice drop constraint %I', held);
  end loop;
end $$;
alter table world_society_model_choice add constraint world_society_model_choice_names_its_decider
  check (((document ? 'model' and not document ? 'decider'
           and jsonb_typeof(document->'model') in ('object', 'null'))
          or (document ? 'decider' and not document ? 'model'
              and jsonb_typeof(document->'decider') = 'object'
              and document->'decider'->>'kind' in ('routine', 'model', 'external'))) is true);

commit;
