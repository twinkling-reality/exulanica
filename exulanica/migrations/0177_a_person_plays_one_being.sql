-- A person plays one being of a society of things ("Play this one").
--
-- A choice may now name one person playing its subject: the decider {"kind": "person",
-- "account_id": ...}, beside 0146's routine, model and outside program (exulanica/world/deciders.py).
-- The play route records it alone. Giving the being back records a choice naming the same person with
-- `ended` (given_back, or player_left when the host gives back a being its player stopped answering
-- for): the being is then decided for as it was before the play began. 0146 stated the decider check
-- by name; it is replaced by name here with the same rule and the person who plays, and `ended` only
-- beside such a person. Every stored choice reads as it was written.
--
-- What the person answers for the being each minute is kept in world_society_person_answer, one row
-- per answer posted, the latest for a subject and a minute taken when the minute comes. A row names
-- the account that posted it, which no read shows. It is appended and never changed, under the
-- workspace's row security, as the society's other records are.

begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_model_choice drop constraint world_society_model_choice_names_its_decider;
alter table world_society_model_choice add constraint world_society_model_choice_names_its_decider
  check (((document ? 'model' and not document ? 'decider' and not document ? 'ended'
           and jsonb_typeof(document->'model') in ('object', 'null'))
          or (document ? 'decider' and not document ? 'model'
              and jsonb_typeof(document->'decider') = 'object'
              and ((document->'decider'->>'kind' in ('routine', 'model', 'external')
                    and not document ? 'ended')
                   or (document->'decider'->>'kind' = 'person'
                       and document->'decider'->>'account_id'
                           ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                       and (not document ? 'ended'
                            or document->>'ended' in ('given_back', 'player_left')))))) is true);

create table world_society_person_answer (
  workspace_id uuid not null,
  world_id text not null,
  society_id uuid not null,
  subject_id uuid not null,
  base_tick bigint not null check (base_tick >= 0),
  answer_seq bigint not null check (answer_seq > 0),
  account_id uuid not null,
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, subject_id, base_tick, answer_seq),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  check (document->>'profile' is not distinct from 'exulanica.person-answer/v1'),
  check (document->>'subject_id' is not distinct from subject_id::text),
  check ((document->>'base_tick')::bigint is not distinct from base_tick),
  check (octet_length(document::text) <= 4096)
);

create trigger world_society_person_answer_append_only
  before update or delete on world_society_person_answer
  for each row execute function tg_world_society_event_append_only();

alter table world_society_person_answer enable row level security;
alter table world_society_person_answer force row level security;
create policy ws_isolation on world_society_person_answer
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- The application appends and reads answers; read-only roles read them. Provisioning applies the
-- same shape through exulanica.db.roles.
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'exulanica_app') then
    grant select, insert on world_society_person_answer to exulanica_app;
  end if;
  if exists (select 1 from pg_roles where rolname = 'exulanica_ro') then
    grant select on world_society_person_answer to exulanica_ro;
  end if;
end $$;

commit;
