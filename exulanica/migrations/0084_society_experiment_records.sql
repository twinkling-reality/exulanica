-- Immutable, workspace-scoped records for controlled living-v4 society experiments.
-- An attempt is reserved before simulation work. A missing outcome therefore means incomplete;
-- completion and failure are terminal append-only facts rather than mutable status labels.
begin;
select pg_advisory_xact_lock(119622309);

create table society_experiment_definition (
  workspace_id uuid not null,
  experiment_id uuid not null,
  source_society_id uuid not null,
  world_id text not null,
  authored_version_id uuid not null,
  authored_state_sha256 text not null check(authored_state_sha256 ~ '^[0-9a-f]{64}$'),
  authored_edit_seq bigint not null check(authored_edit_seq>=0),
  baseline_input_seq bigint not null check(baseline_input_seq>0),
  baseline_input_sha256 text not null check(baseline_input_sha256 ~ '^[0-9a-f]{64}$'),
  treatment_input_seq bigint not null check(treatment_input_seq>0),
  treatment_input_sha256 text not null check(treatment_input_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,experiment_id),
  foreign key(workspace_id,source_society_id)
    references world_society(workspace_id,society_id),
  foreign key(workspace_id,world_id,authored_version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,source_society_id,baseline_input_seq)
    references world_society_input(workspace_id,society_id,input_seq),
  foreign key(workspace_id,source_society_id,treatment_input_seq)
    references world_society_input(workspace_id,society_id,input_seq),
  check(document->>'profile' is not distinct from
    'exulanica.society-experiment/rest-amenity/v1'),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check(document->'baseline_input'->>'input_seq' is not distinct from
    baseline_input_seq::text),
  check(document->'baseline_input'->>'document_sha256' is not distinct from
    baseline_input_sha256),
  check(document->'treatment_input'->>'input_seq' is not distinct from
    treatment_input_seq::text),
  check(document->'treatment_input'->>'document_sha256' is not distinct from
    treatment_input_sha256)
);

create table society_experiment_attempt (
  workspace_id uuid not null,
  attempt_id uuid not null,
  experiment_id uuid not null,
  phase text not null check(phase in ('development','held_out')),
  seed_sha256 text not null check(seed_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,attempt_id),
  unique(workspace_id,experiment_id,attempt_id),
  foreign key(workspace_id,experiment_id)
    references society_experiment_definition(workspace_id,experiment_id)
);

create table society_experiment_checkpoint (
  workspace_id uuid not null,
  experiment_id uuid not null,
  attempt_id uuid not null,
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,attempt_id),
  foreign key(workspace_id,experiment_id,attempt_id)
    references society_experiment_attempt(workspace_id,experiment_id,attempt_id),
  check(document->>'profile' is not distinct from
    'exulanica.society-experiment-checkpoint/v1'),
  check(document->>'document_sha256' is not distinct from document_sha256)
);

create table society_experiment_outcome (
  workspace_id uuid not null,
  experiment_id uuid not null,
  attempt_id uuid not null,
  status text not null check(status in ('completed','failed')),
  checkpoint_sha256 text check(checkpoint_sha256 is null or
    checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
  evidence jsonb check(evidence is null or jsonb_typeof(evidence)='object'),
  evidence_sha256 text check(evidence_sha256 is null or
    evidence_sha256 ~ '^[0-9a-f]{64}$'),
  result jsonb check(result is null or jsonb_typeof(result)='object'),
  result_sha256 text check(result_sha256 is null or result_sha256 ~ '^[0-9a-f]{64}$'),
  failure jsonb check(failure is null or jsonb_typeof(failure)='object'),
  failure_sha256 text check(failure_sha256 is null or failure_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,attempt_id),
  foreign key(workspace_id,experiment_id,attempt_id)
    references society_experiment_attempt(workspace_id,experiment_id,attempt_id),
  check((status='completed' and checkpoint_sha256 is not null and evidence is not null
      and evidence_sha256 is not null and result is not null and result_sha256 is not null
      and failure is null and failure_sha256 is null)
    or (status='failed' and evidence is null and evidence_sha256 is null and result is null
      and result_sha256 is null and failure is not null and failure_sha256 is not null)),
  check(evidence is null or evidence->>'document_sha256' is not distinct from evidence_sha256),
  check(result is null or result->>'document_sha256' is not distinct from result_sha256),
  check(failure is null or failure->>'document_sha256' is not distinct from failure_sha256)
);

create function tg_society_experiment_definition_binding() returns trigger language plpgsql as $fn$
declare s world_society%rowtype; v world_alternate_version%rowtype;
  baseline world_society_input%rowtype; treatment world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into s from world_society where workspace_id=new.workspace_id
    and society_id=new.source_society_id;
  select * into v from world_alternate_version where workspace_id=new.workspace_id
    and world_id=new.world_id and version_id=new.authored_version_id;
  select * into baseline from world_society_input where workspace_id=new.workspace_id
    and society_id=new.source_society_id and input_seq=new.baseline_input_seq;
  select * into treatment from world_society_input where workspace_id=new.workspace_id
    and society_id=new.source_society_id and input_seq=new.treatment_input_seq;
  if s.society_id is null or s.engine_version<>'exulanica-society/v4'
    or s.world_id<>new.world_id or s.version_id<>new.authored_version_id
    or v.version_id is null or treatment.input_seq is null or baseline.input_seq is null
    or baseline.document_sha256<>new.baseline_input_sha256
    or treatment.document_sha256<>new.treatment_input_sha256
    or treatment.document->'authored_state'->>'edit_seq' is distinct from
      new.authored_edit_seq::text
    or treatment.document->'authored_state'->>'delta_sha256' is distinct from
      new.authored_state_sha256 then
    raise exception 'experiment definition authority binding mismatch' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_experiment_definition_binding before insert
  on society_experiment_definition for each row
  execute function tg_society_experiment_definition_binding();

create function tg_society_experiment_attempt_binding() returns trigger language plpgsql as $fn$
declare d society_experiment_definition%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into d from society_experiment_definition where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id;
  if d.experiment_id is null or not exists (
    select 1 from jsonb_array_elements_text((d.document->'seed_commitment')->(new.phase)) seed
      where seed.value=new.seed_sha256
  ) then
    raise exception 'experiment attempt seed is not committed to its phase' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_experiment_attempt_binding before insert
  on society_experiment_attempt for each row
  execute function tg_society_experiment_attempt_binding();

create function tg_society_experiment_checkpoint_binding() returns trigger language plpgsql as $fn$
declare a society_experiment_attempt%rowtype; d society_experiment_definition%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(
    new.workspace_id::text||':'||new.attempt_id::text,880084));
  select * into a from society_experiment_attempt where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id and attempt_id=new.attempt_id;
  select * into d from society_experiment_definition where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id;
  if a.attempt_id is null or d.experiment_id is null
    or exists (select 1 from society_experiment_outcome where workspace_id=new.workspace_id
      and attempt_id=new.attempt_id)
    or new.document->>'definition_sha256' is distinct from d.document_sha256
    or new.document->>'phase' is distinct from a.phase
    or new.document->>'seed_sha256' is distinct from a.seed_sha256 then
    raise exception 'experiment checkpoint authority binding mismatch' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_experiment_checkpoint_binding before insert
  on society_experiment_checkpoint for each row
  execute function tg_society_experiment_checkpoint_binding();

create function tg_society_experiment_outcome_binding() returns trigger language plpgsql as $fn$
declare a society_experiment_attempt%rowtype; d society_experiment_definition%rowtype;
  c society_experiment_checkpoint%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(
    new.workspace_id::text||':'||new.attempt_id::text,880084));
  select * into a from society_experiment_attempt where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id and attempt_id=new.attempt_id;
  select * into d from society_experiment_definition where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id;
  select * into c from society_experiment_checkpoint where workspace_id=new.workspace_id
    and experiment_id=new.experiment_id and attempt_id=new.attempt_id;
  if a.attempt_id is null or d.experiment_id is null then
    raise exception 'experiment outcome has no scoped attempt' using errcode='23514';
  end if;
  if new.status='completed' and (c.attempt_id is null
    or new.checkpoint_sha256<>c.document_sha256
    or new.evidence->>'definition_sha256' is distinct from d.document_sha256
    or new.evidence->>'checkpoint_sha256' is distinct from c.document_sha256
    or new.evidence->>'seed_sha256' is distinct from a.seed_sha256
    or new.result->>'definition_sha256' is distinct from d.document_sha256
    or new.result->>'checkpoint_sha256' is distinct from c.document_sha256
    or new.result->>'seed_sha256' is distinct from a.seed_sha256) then
    raise exception 'completed experiment outcome binding mismatch' using errcode='23514';
  end if;
  if new.status='failed' and (new.failure->>'profile' is distinct from
      'exulanica.society-experiment-failure/v1'
    or new.failure->>'attempt_id' is distinct from new.attempt_id::text
    or new.failure->>'definition_sha256' is distinct from d.document_sha256
    or new.failure->>'checkpoint_sha256' is distinct from coalesce(c.document_sha256,'')) then
    raise exception 'failed experiment outcome binding mismatch' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_experiment_outcome_binding before insert
  on society_experiment_outcome for each row
  execute function tg_society_experiment_outcome_binding();

create function tg_society_experiment_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'society experiment records are append-only' using errcode='23514';
end $fn$;

do $$ declare t text; begin
  foreach t in array array['society_experiment_definition','society_experiment_attempt',
    'society_experiment_checkpoint','society_experiment_outcome'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_society_experiment_append_only()', t||'_append_only', t);
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
  end loop;
end $$;

-- The application can append and read records. Read-only roles cannot mutate the ledger.
do $$ declare r text; t text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname=r) then
      foreach t in array array['society_experiment_definition','society_experiment_attempt',
        'society_experiment_checkpoint','society_experiment_outcome'] loop
        execute format('grant select,insert on %I to %I',t,r);
      end loop;
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname=r) then
      foreach t in array array['society_experiment_definition','society_experiment_attempt',
        'society_experiment_checkpoint','society_experiment_outcome'] loop
        execute format('grant select on %I to %I',t,r);
      end loop;
    end if;
  end loop;
end $$;

commit;
