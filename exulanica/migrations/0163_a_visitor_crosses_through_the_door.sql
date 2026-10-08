-- 0163_a_visitor_crosses_through_the_door.sql
-- Crossings: a visitor an outside program sends arrives in a society of things through the door and
-- leaves the same way. Each crossing is handed to the society's next minute, which takes it under
-- the society's lock and binds it once to the event it recorded, so replay reads every arrival and
-- departure back and never asks the door again (exulanica/world/crossings.py, the port; the door's
-- side is exulanica/door/crossings.py).
--
-- door_crossing, the door's outbox to one society: an arrival (exulanica.thing-arrival/v1) or a
-- departure (exulanica.thing-departure/v1), under the grant it came through, in the order the door
-- wrote them (crossing_seq, per society), named by its own id and the thing it moves; an arrival
-- also keeps which game item each carried thing was, which the society never reads and the bridge
-- is told back, and the look its visitor arrives in (a shipped look's reference, recorded as the
-- thing's look when the minute takes the arrival). An arrival is named by the bridge's own random
-- id, a version 4 UUID, and a departure by the id the door derives (version 5), so no arrival can
-- hold the id a departure will be written under. An arrival is written only under a grant that
-- stands. The door writes crossings only to a society whose engine holds things, as the engine
-- table says (exulanica/world/society_engines.py); only such an engine reads them.
-- Appended, never changed.
-- door_manifest, each translation manifest a crossing names, by its digest, so a thing's card reads
-- what came across and what stayed behind. Appended, never changed.
-- door_crossing_binding, what the minute that consumed a crossing did with it: an arrival arrived
-- or was refused, a departure departed, found nobody of that id here or was refused, with the
-- refusal's reason and the event recorded for it, bound once, the minute's transition and event
-- named by foreign key. The event's subject is the thing the crossing moves, except for a crossing
-- the society could not read (malformed_crossing), whose event names the crossing's own id.
-- Appended, never changed.
-- door_delivery, a bridge's report that its game delivered what a departing visitor carried home,
-- once for each departure. Appended, never changed.
-- door_visitor_gone, a bridge's word that the person behind one of its visitors left the game: the
-- visitor is not asked again, so its kind's quiet minutes pass and the society sends it home
-- (decider_lost). Appended, never changed.
--
-- door_mapping (0149) takes a mapping of either profile now read side by side:
-- exulanica.bridge-mapping/v1, naming a visitor's look by its digest, and
-- exulanica.bridge-mapping/v2, naming it by the thing library's key, version and digest. Its
-- profile check is replaced to name both; nothing else of 0149 changes.
--
-- world_society_event gains an index of the things that departed, by thing: the door looks a
-- visitor's departure up by the thing it names (whether a visitor is still present, a poll's head,
-- departures and their delivery reports), never by tick.
--
-- Every table is kept to its workspace by row-level security and, on insert, by
-- assert_workspace_context. Nothing here is a withdrawal: a departure is an event of the world, and
-- the grant's own revocation (0149) is what a restore carries.
begin;
select pg_advisory_xact_lock(119622309);

-- 0149's unnamed profile check on door_mapping, found by what it says, gives way to a named one.
do $profile$
declare
  held record;
begin
  for held in
    select c.conname from pg_constraint c
     where c.conrelid = 'door_mapping'::regclass and c.contype = 'c'
       and pg_get_constraintdef(c.oid) like '%exulanica.bridge-mapping/v1%'
  loop
    execute format('alter table door_mapping drop constraint %I', held.conname);
  end loop;
end $profile$;
alter table door_mapping add constraint door_mapping_profile
  check (coalesce(document->>'profile', '')
         in ('exulanica.bridge-mapping/v1', 'exulanica.bridge-mapping/v2'));

create table door_crossing (
  workspace_id uuid not null,
  society_id uuid not null,
  crossing_id uuid not null,
  crossing_seq bigint not null check (crossing_seq > 0),
  grant_id uuid not null,
  kind text not null check (kind in ('arrival', 'departure')),
  thing_id uuid not null,
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  game_items jsonb,
  look jsonb,
  recorded_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, crossing_id),
  unique (workspace_id, society_id, crossing_seq),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id),
  check ((kind = 'arrival')
         = (document->>'profile' is not distinct from 'exulanica.thing-arrival/v1')),
  check ((kind = 'departure')
         = (document->>'profile' is not distinct from 'exulanica.thing-departure/v1')),
  check (document->>(case kind when 'arrival' then 'arrival_id' else 'departure_id' end)
         is not distinct from crossing_id::text),
  -- An arrival's id is a random version 4 UUID and a departure's never is.
  check ((kind = 'arrival') = (substr(crossing_id::text, 15, 1) = '4')),
  check (document->>'thing_id' is not distinct from thing_id::text),
  check (kind = 'departure' or document->>'grant_id' is not distinct from grant_id::text),
  check ((kind = 'arrival') = (jsonb_typeof(game_items) is not distinct from 'array')),
  check (kind = 'arrival' or game_items is null),
  check ((kind = 'arrival') = (jsonb_typeof(look) is not distinct from 'object')),
  check (look is null or octet_length(look::text) <= 512),
  check (octet_length(document::text) <= 32768),
  check (game_items is null or octet_length(game_items::text) <= 8192)
);
create index door_crossing_by_grant on door_crossing (workspace_id, grant_id, crossing_seq);
create index door_crossing_by_thing on door_crossing (workspace_id, grant_id, thing_id);
create index world_society_event_departed_thing on world_society_event
  (workspace_id, society_id, subject_id) where event_kind = 'thing_departed';

create table door_crossing_binding (
  workspace_id uuid not null,
  society_id uuid not null,
  crossing_id uuid not null,
  tick bigint not null check (tick > 0),
  disposition text not null,
  reason text,
  event_id uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, crossing_id),
  unique (workspace_id, society_id, event_id),
  foreign key (workspace_id, society_id, crossing_id)
    references door_crossing (workspace_id, society_id, crossing_id),
  foreign key (workspace_id, society_id, tick)
    references world_society_transition (workspace_id, society_id, tick),
  foreign key (workspace_id, society_id, event_id)
    references world_society_event (workspace_id, society_id, event_id),
  check ((disposition in ('arrived', 'departed') and reason is null)
         or (disposition = 'refused'
             and reason in ('no_arrival_place', 'visitor_limit', 'unknown_kind', 'already_here',
                            'malformed_crossing'))
         or (disposition = 'not_here' and reason = 'not_here'))
);
create index door_crossing_binding_by_tick
  on door_crossing_binding (workspace_id, society_id, tick);

create table door_manifest (
  workspace_id uuid not null,
  manifest_sha256 text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, manifest_sha256),
  check (document->>'profile' is not distinct from 'exulanica.translation-manifest/v2'),
  check (octet_length(document::text) <= 65536)
);

create table door_delivery (
  workspace_id uuid not null,
  grant_id uuid not null,
  departure_id uuid not null,
  thing_id uuid not null,
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, departure_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id),
  check (octet_length(document::text) <= 16384)
);

create table door_visitor_gone (
  workspace_id uuid not null,
  grant_id uuid not null,
  thing_id uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id, thing_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id)
);

-- A crossing follows its society's last crossing, and an arrival crosses only under a grant that
-- stands. Which engines hold things is the engine table's to say, not this trigger's.
create function tg_door_crossing_binding() returns trigger language plpgsql as $fn$
declare latest bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.society_id::text, 153001));
  if new.kind = 'arrival' and not door_grant_stands(new.workspace_id, new.grant_id) then
    raise exception 'an arrival crosses only under a grant that stands' using errcode = '23514';
  end if;
  select coalesce(max(crossing_seq), 0) into latest from door_crossing
    where workspace_id = new.workspace_id and society_id = new.society_id;
  if new.crossing_seq <> latest + 1 then
    raise exception 'a crossing follows its society''s last crossing' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_crossing_binding before insert on door_crossing
  for each row execute function tg_door_crossing_binding();

-- A binding states what its own kind of crossing can become, for the thing the crossing names, or
-- for the crossing itself when the society could not read it.
create function tg_door_crossing_bound() returns trigger language plpgsql as $fn$
declare crossed door_crossing%rowtype; subject uuid;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into crossed from door_crossing
    where workspace_id = new.workspace_id and society_id = new.society_id
      and crossing_id = new.crossing_id;
  select subject_id into subject from world_society_event
    where workspace_id = new.workspace_id and society_id = new.society_id
      and event_id = new.event_id;
  if (crossed.kind = 'arrival' and new.disposition not in ('arrived', 'refused'))
     or (crossed.kind = 'departure' and new.disposition not in ('departed', 'not_here', 'refused'))
     or subject is distinct from (case when new.reason = 'malformed_crossing'
                                       then crossed.crossing_id else crossed.thing_id end) then
    raise exception 'a crossing is bound to what its kind can become, for the thing it names'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_crossing_bound before insert on door_crossing_binding
  for each row execute function tg_door_crossing_bound();

create function tg_door_crossing_scoped_insert() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;
create trigger door_manifest_scoped_insert before insert on door_manifest
  for each row execute function tg_door_crossing_scoped_insert();
create trigger door_delivery_scoped_insert before insert on door_delivery
  for each row execute function tg_door_crossing_scoped_insert();
create trigger door_visitor_gone_scoped_insert before insert on door_visitor_gone
  for each row execute function tg_door_crossing_scoped_insert();

do $$ declare t text; begin
  foreach t in array array['door_crossing', 'door_crossing_binding', 'door_manifest',
                           'door_delivery', 'door_visitor_gone'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_door_append_only()', t || '_append_only', t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- Trigger functions are not executed by name, so nobody is granted them.
do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('tg_door_crossing_binding', 'tg_door_crossing_bound',
                         'tg_door_crossing_scoped_insert')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- The application appends and reads these; read-only roles read them. Provisioning applies the
-- same shape through exulanica.db.roles.
do $$ declare t text; begin
  foreach t in array array['door_crossing', 'door_crossing_binding', 'door_manifest',
                           'door_delivery', 'door_visitor_gone'] loop
    if exists (select 1 from pg_roles where rolname = 'exulanica_app') then
      execute format('grant select, insert on %I to exulanica_app', t);
    end if;
    if exists (select 1 from pg_roles where rolname = 'exulanica_ro') then
      execute format('grant select on %I to exulanica_ro', t);
    end if;
  end loop;
end $$;

commit;
