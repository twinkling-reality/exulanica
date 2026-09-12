-- Register the already-reviewed source-light renderer module without changing saved receipts.
begin;
select pg_advisory_xact_lock(119622309);

insert into world_style_capability_registry
  (capability_key, capability_version, parameter_kind, parameter_group, minimum_value, maximum_value)
values
  ('interface.hue',1,'range','world',0,1),
  ('interface.warmth',1,'range','world',0,1),
  ('interface.depth',1,'range','world',0,1),
  ('interface.light',1,'range','world',0,1);

insert into world_style_module_registry (module_id) values ('source-light-v1');
insert into world_style_module_capability (module_id, capability_key, application_order)
values
  ('source-light-v1','interface.hue',0),
  ('source-light-v1','interface.warmth',1),
  ('source-light-v1','interface.depth',2),
  ('source-light-v1','interface.light',3);
insert into world_art_profile_module (profile_id, profile_version, module_id, application_order)
values ('origin-landscape',1,'source-light-v1',3);

insert into world_art_profile_parameter
  (profile_id, profile_version, parameter_key, capability_key, label, description,
   minimum_value, maximum_value, step_value, default_value, choice_values)
values
  ('origin-landscape',1,'source-hue','interface.hue','Interface hue','The colour the interface is built from. Reading it from your photographs sets this.',0,1,0.01,'0.6',null),
  ('origin-landscape',1,'source-warmth','interface.warmth','Evidence warmth','How warm the mark for your own words and your own photographs runs.',0,1,0.01,'0.19',null),
  ('origin-landscape',1,'source-depth','interface.depth','Reading depth','How deep the reading colour sits. It never goes light enough to be hard to read.',0,1,0.01,'0.36',null),
  ('origin-landscape',1,'source-light','interface.light','Plate light','How much light the summoned surfaces hold.',0,1,0.01,'0.86',null);

update world_art_profile_parameter
set description='Tunes the colour of the memory field itself.'
where profile_id='origin-landscape' and profile_version=1 and parameter_key='vitality';
commit;
