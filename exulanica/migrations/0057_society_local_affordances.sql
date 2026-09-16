-- Opt-in local activity failures without rewriting retained input/v1 semantics.
begin;
select pg_advisory_xact_lock(119622309);

do $$ declare held record; begin
  for held in select conname from pg_constraint
    where conrelid='world_society_input'::regclass and contype='c'
      and pg_get_constraintdef(oid) like '%exulanica.society-input/v1%'
  loop
    execute format('alter table world_society_input drop constraint %I', held.conname);
  end loop;
end $$;

alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2')) is true);
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
