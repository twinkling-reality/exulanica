-- A place's saved name reaches a model only while the account holder allows it, for that place,
-- that model and that destination. A name exists here only because the account holder typed it.
-- Their rules: a person's name never goes to a hosted model, with or without a right, and a
-- confirmed place name goes only where they allowed it, asked for each place. Nothing here can
-- name a person: the table admits a place alone, at the grant and again at every read.
--
-- personal_model_right (0073) cannot carry this. It is a right over one photograph's bytes. A
-- place name is an annotation on an entity that many photographs link to, so borrowing one
-- photograph's right would let that photograph's permission release a name the account holder
-- never allowed on its own, and withdrawing it would not stop the name leaving through another.
--
-- The right is a sequence of decisions, never a row that changes. Each allow and each withdrawal
-- is a new event, appended after the last one for the same place, model and destination, and
-- chained to it by digest, as rule P5 of the consent principles asks. A withdrawal ends the right
-- from the next read and leaves the grant it ended readable, so "what was allowed on date X" has
-- an answer. The last event decides. Four terms make a grant exact:
--   * The place is live, not merged and not deleted, when the grant is recorded AND when it is
--     read. A deletion ends the right. A merge suspends it: undoing the merge restores a grant
--     that was never withdrawn, and a withdrawal recorded in between holds.
--   * The grant rests on one naming assertion: the active user assertion the place's current name
--     is the cache of, stated by the account holder who grants. A rename supersedes that assertion,
--     so the right stops at the rename, including a rename back to the same words; the account
--     holder allows the new naming again or it stays here.
--   * It binds the digest of the exact name, not the text, so an ended right does not keep a
--     withdrawn name alive.
--   * The model and destination are spelled and checked exactly as 0073 spells them, so one
--     hand-over is compared the same way whether it carries a photograph or a name. The grant keeps
--     the exact notice the account holder was shown (rule P6) and a term that ends (rule P3).
begin;
select pg_advisory_xact_lock(119622309);

create table place_name_right_event (
  workspace_id uuid not null,
  event_id uuid not null,
  entity_id uuid not null,
  model_provider text not null check(model_provider ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_role text not null check(model_role ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_id text not null check(model_id ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$'),
  model_revision text check(model_revision is null or model_revision ~ '^[0-9a-f]{40}$'),
  -- Spelled exactly as personal_model_right spells it; see 0073 for each clause.
  destination text not null check(
    length(destination)<=270
    and (destination='local-process'
      or (destination ~ '^https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+(:[1-9][0-9]{0,4})?$'
          and destination !~ '\.([0-9]+|0x[0-9a-f]*)(:[0-9]+)?$')
      or destination ~ '^https?://localhost(:[1-9][0-9]{0,4})?$')
    and destination !~ '^https://[^/]*:443$' and destination !~ '^http://[^/]*:80$'
    and coalesce(substring(destination from ':([0-9]+)$')::integer,1) between 1 and 65535),
  -- The position of this decision among every decision for this place, model and destination,
  -- from 0, and the receipt digest of the one before it.
  sequence integer not null check(sequence>=0),
  previous_sha256 bytea check(previous_sha256 is null or octet_length(previous_sha256)=32),
  event text not null check(event in ('granted','withdrawn')),
  -- A grant only: the naming it rests on, the digest of the UTF-8 name at the grant, the notice
  -- the account holder was shown, and when the right ends.
  naming_assertion_id uuid,
  name_sha256 bytea check(name_sha256 is null or octet_length(name_sha256)=32),
  notice text check(
    notice is null or (notice=btrim(notice) and length(notice) between 1 and 2000
      and notice !~ '[\x01-\x1f\x7f-\x9f]')),
  valid_until timestamptz,
  decided_by uuid not null,
  decided_at timestamptz not null,
  receipt_record jsonb not null check(jsonb_typeof(receipt_record)='object'),
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  primary key(workspace_id,event_id),
  unique(workspace_id,receipt_sha256),
  -- One decision per position. A hosted model has no revision, so null is one value here.
  unique nulls not distinct(
    workspace_id,entity_id,model_provider,model_role,model_id,model_revision,destination,sequence),
  foreign key(workspace_id,entity_id) references entity(workspace_id,entity_id),
  foreign key(workspace_id,naming_assertion_id) references assertion(workspace_id,assertion_id),
  check((sequence=0)=(previous_sha256 is null)),
  check((event='granted')=(naming_assertion_id is not null)),
  check((event='granted')=(name_sha256 is not null)),
  check((event='granted')=(notice is not null)),
  check((event='granted')=(valid_until is not null)),
  check(valid_until is null or valid_until>decided_at),
  check(model_provider<>'local' or model_revision is not null),
  check(destination<>'local-process' or model_provider='local'),
  check(receipt_record->>'profile'='exulanica.place-name-right-event/v1'),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
-- The read asks for the last decision per model and destination for one place.
create index place_name_right_event_key_idx on place_name_right_event(
  workspace_id,entity_id,model_provider,model_role,model_id,destination,sequence desc);

alter table place_name_right_event enable row level security;
alter table place_name_right_event force row level security;
create policy ws_isolation on place_name_right_event
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- The same two locks 0073 takes, in the same order: a decision serializes with privacy decisions
-- in its workspace, and cannot commit while a final read check holds the asset read lock, so a
-- withdrawal is either seen by that check or refused until it has finished. entity and assertion
-- carry the second lock already (0041), so a merge, a rename or a deletion cannot commit under a
-- final read check either.
create trigger aa_privacy_currency_lock before insert on place_name_right_event
for each row execute function tg_privacy_currency_lock();
create trigger aaa_asset_read_mutation before insert or update or delete on place_name_right_event
for each row execute function tg_asset_read_mutation();

-- The naming a live, unmerged place's current name rests on: each active user assertion under a
-- naming predicate whose object is that exact name (0002 makes the name their cache), and who
-- stated it. No row for anything that is not such a place. A grant is recorded against one of
-- these, and is read against them again every time.
create function place_naming(p_workspace uuid,p_entity uuid)
returns table(display_name text,naming_assertion_id uuid,stated_by uuid)
language sql stable as $fn$
  select e.display_name,a.assertion_id,a.stated_by_user
  from entity e
  join assertion a on a.workspace_id=e.workspace_id and a.kind='user' and a.status='active'
    and a.subject_ref=jsonb_build_object('type','entity','id',e.entity_id::text)
    and a.object_value=to_jsonb(e.display_name)
  join predicate p on p.predicate_id=a.predicate_id and p.writes_a_name
  where e.workspace_id=p_workspace and p_workspace=current_workspace() and e.entity_id=p_entity
    and e.class='place' and e.merged_into is null and e.deleted_at is null
    and e.display_name is not null;
$fn$;

-- Whether this naming still names this place for this account holder, at this instant: the place's
-- current name has this digest and rests on this assertion, stated by this account holder.
create function place_name_is_stated(
  p_workspace uuid,p_entity uuid,p_assertion uuid,p_name_sha256 bytea,p_stated_by uuid)
returns boolean language sql stable as $fn$
  select exists(
    select 1 from place_naming(p_workspace,p_entity) n
    where n.naming_assertion_id=p_assertion and n.stated_by=p_stated_by
      and digest(convert_to(n.display_name,'UTF8'),'sha256')=p_name_sha256);
$fn$;

-- A decision is the next one in its sequence and chained to the one before; a withdrawal follows a
-- grant; a grant rests on a naming that holds now; and the receipt says exactly what the columns
-- say, with instants in 0073's one spelling.
create function tg_place_name_right_event_receipt() returns trigger
language plpgsql as $fn$
declare
  previous place_name_right_event%rowtype;
  expected jsonb;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into previous from place_name_right_event r
   where r.workspace_id=new.workspace_id and r.entity_id=new.entity_id
     and r.model_provider=new.model_provider and r.model_role=new.model_role
     and r.model_id=new.model_id and r.model_revision is not distinct from new.model_revision
     and r.destination=new.destination
   order by r.sequence desc limit 1;
  if found then
    if new.sequence<>previous.sequence+1 or new.previous_sha256 is distinct from previous.receipt_sha256
    then
      raise exception 'a place name decision follows the last one for its place, model and destination'
        using errcode='40001';
    end if;
    if new.decided_at<previous.decided_at then
      raise exception 'a place name decision is recorded after the one it follows'
        using errcode='23514';
    end if;
  elsif new.sequence<>0 then
    raise exception 'the first place name decision for a place, model and destination is number 0'
      using errcode='40001';
  end if;
  if new.event='withdrawn' and (previous.event_id is null or previous.event<>'granted') then
    raise exception 'a place name right is withdrawn only after it was granted'
      using errcode='23514';
  end if;
  if new.event='granted'
    and not place_name_is_stated(new.workspace_id,new.entity_id,new.naming_assertion_id,
      new.name_sha256,new.decided_by)
  then
    raise exception 'a place name right is granted by the account holder who stated that exact name, for a live place that is not merged'
      using errcode='23514';
  end if;
  if new.decided_at>clock_timestamp() then
    raise exception 'a place name decision is recorded now or earlier, never ahead of time'
      using errcode='23514';
  end if;
  expected:=jsonb_build_object(
    'profile','exulanica.place-name-right-event/v1',
    'event',new.event,
    'entity_id',new.entity_id,
    'model',jsonb_build_object(
      'provider',new.model_provider,'role',new.model_role,
      'model_id',new.model_id,'revision',new.model_revision),
    'destination',new.destination,
    'sequence',new.sequence,
    'previous_sha256',encode(new.previous_sha256,'hex'),
    'decided_by',new.decided_by,
    'decided_at',personal_model_right_instant(new.decided_at));
  if new.event='granted' then
    expected:=expected||jsonb_build_object(
      'naming_assertion_id',new.naming_assertion_id,
      'name_sha256',encode(new.name_sha256,'hex'),
      'notice',new.notice,
      'valid_until',personal_model_right_instant(new.valid_until));
  end if;
  if new.receipt_record is distinct from expected then
    raise exception 'place name decision receipt disagrees with the decision it records'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_place_name_right_event_receipt
before insert on place_name_right_event
for each row execute function tg_place_name_right_event_receipt();

-- Appended, never changed and never deleted, with the refusal 0029 gives every privacy receipt. A
-- withdrawal is the next event, not an edit.
create trigger tg_place_name_right_event_append_only
before update or delete on place_name_right_event
for each row execute function tg_reconstruction_privacy_append_only();

-- The last decision recorded at an instant for each place, model and destination, with whether the
-- naming a grant rests on still holds then. Every place when p_entities is null. What a decision
-- means is decided in one place, exulanica.consent.place_names; this reads the facts it needs,
-- under the final read check, so like the 0041 and 0073 predicates it takes an explicit instant
-- and acquires no lock.
create function place_name_right_last_decisions(
  p_workspace uuid,p_entities uuid[],p_at timestamptz)
returns table(
  entity_id uuid,model_provider text,model_role text,model_id text,model_revision text,
  destination text,sequence integer,event text,decided_at timestamptz,valid_until timestamptz,
  notice text,naming_holds boolean,receipt_sha256 bytea)
language sql stable as $fn$
  select distinct on (
      r.entity_id,r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination)
    r.entity_id,r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination,
    r.sequence,r.event,r.decided_at,r.valid_until,r.notice,
    r.event='granted' and place_name_is_stated(r.workspace_id,r.entity_id,
      r.naming_assertion_id,r.name_sha256,r.decided_by),
    r.receipt_sha256
  from place_name_right_event r
  where r.workspace_id=p_workspace and p_workspace=current_workspace()
    and (p_entities is null or r.entity_id=any(p_entities)) and r.decided_at<=p_at
  order by r.entity_id,r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination,
    r.sequence desc;
$fn$;

commit;
