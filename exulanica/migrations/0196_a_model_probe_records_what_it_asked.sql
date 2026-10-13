-- Prepared probes, explicit bounded starts, per-case receipts and terminal outcomes.
-- The existing job queue holds leases. Its payload contains only the probe UUID, never text.
-- These records are workspace facts, erased with their workspace. The spending ledger keeps
-- its existing financial retention. No record here changes a catalog licence or a manifest.
begin;
select pg_advisory_xact_lock(119622309);

create table model_probe (
  workspace_id uuid not null,
  probe_id uuid not null,
  job_id uuid not null unique references job(job_id),
  request_id uuid not null,
  recorded_by uuid not null,
  provider text not null check (provider ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_id text not null check (model_id ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$'),
  added_seq bigint not null check (added_seq > 0),
  added_sha256 text not null check (added_sha256 ~ '^[0-9a-f]{64}$'),
  definition jsonb not null check (jsonb_typeof(definition)='object'
                                  and octet_length(definition::text)<=65536),
  definition_sha256 text not null check (definition_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,probe_id),
  unique(workspace_id,request_id),
  check ((definition->>'profile'='exulanica.model-probe-definition/v1') is true
    and (definition->>'provider'=provider) is true
    and (definition->>'model_id'=model_id) is true
    and ((definition->>'added_seq')::bigint=added_seq) is true
    and (definition->>'added_sha256'=added_sha256) is true
    and (definition->>'document_sha256'=definition_sha256) is true)
);

create table model_probe_start (
  workspace_id uuid not null,
  probe_id uuid not null,
  request_id uuid not null,
  recorded_by uuid not null,
  bound_id uuid not null,
  ceiling_usd numeric not null check (ceiling_usd > 0 and ceiling_usd <= 1000),
  definition_sha256 text not null check (definition_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,probe_id),
  unique(workspace_id,request_id),
  foreign key(workspace_id,probe_id) references model_probe(workspace_id,probe_id)
);

create table model_probe_receipt (
  workspace_id uuid not null,
  probe_id uuid not null,
  case_seq integer not null check (case_seq between 1 and 44),
  document jsonb not null check (jsonb_typeof(document)='object'
                                and octet_length(document::text)<=65536),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,probe_id,case_seq),
  foreign key(workspace_id,probe_id) references model_probe(workspace_id,probe_id),
  check ((document->>'profile'='exulanica.model-probe-receipt/v1') is true
    and ((document->'request'->>'case_seq')::integer=case_seq) is true
    and (document->>'document_sha256'=document_sha256) is true)
);

create table model_probe_outcome (
  workspace_id uuid not null,
  probe_id uuid not null,
  code text not null check (code in ('completed','not_finished','cancelled','stale')),
  document jsonb not null check (jsonb_typeof(document)='object'
                                and octet_length(document::text)<=65536),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,probe_id),
  foreign key(workspace_id,probe_id) references model_probe(workspace_id,probe_id),
  check ((document->>'profile'='exulanica.model-probe-outcome/v1') is true
    and (document->>'document_sha256'=document_sha256) is true)
);

create function tg_model_probe_binding() returns trigger language plpgsql as $fn$
declare
  definition_digest text;
  latest_added workspace_model%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  if exists(select 1 from tombstone where workspace_id=new.workspace_id and scope='workspace') then
    raise exception 'an erased workspace holds no model probe' using errcode='23514';
  end if;
  if tg_table_name='model_probe' then
    perform pg_advisory_xact_lock(hashtext(new.workspace_id::text),
      hashtext(new.provider || '|workspace-model|' || new.model_id));
    select * into latest_added from workspace_model
      where workspace_id=new.workspace_id and provider=new.provider and model_id=new.model_id
        and kind='added' order by model_seq desc limit 1;
    if latest_added.model_seq is null or latest_added.model_seq<>new.added_seq
      or latest_added.document_sha256<>new.added_sha256
      or (select kind from workspace_model where workspace_id=new.workspace_id
            and provider=new.provider and model_id=new.model_id order by model_seq desc limit 1)='removed'
    then
      raise exception 'a probe binds to the model''s current adding' using errcode='23514';
    end if;
    if not exists(select 1 from job where job_id=new.job_id and workspace_id=new.workspace_id
      and kind='model_probe' and payload=jsonb_build_object('probe_id',new.probe_id::text)) then
      raise exception 'a probe names its own workspace job' using errcode='23514';
    end if;
  else
    select definition_sha256 into definition_digest from model_probe
      where workspace_id=new.workspace_id and probe_id=new.probe_id;
    if tg_table_name='model_probe_start' then
      if definition_digest is distinct from new.definition_sha256 then
        raise exception 'a start names its prepared definition' using errcode='23514';
      end if;
    elsif tg_table_name='model_probe_receipt' then
      if definition_digest is distinct from new.document->'request'->>'definition_sha256'
        or new.case_seq<>(select count(*)+1 from model_probe_receipt
          where workspace_id=new.workspace_id and probe_id=new.probe_id) then
        raise exception 'a receipt binds to its definition and follows prior receipts' using errcode='23514';
      end if;
    elsif definition_digest is distinct from new.document->>'definition_sha256' then
      raise exception 'an outcome names its prepared definition' using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;

create function tg_model_probe_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' and current_user='exulanica_definer' then return old; end if;
  raise exception 'a model probe record is immutable' using errcode='23514';
end $fn$;

do $tables$ declare t text; begin
  foreach t in array array['model_probe','model_probe_start','model_probe_receipt','model_probe_outcome'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
    execute format('create trigger tg_model_probe_binding before insert on %I '
      'for each row execute function tg_model_probe_binding()',t);
    execute format('create trigger tg_model_probe_append_only before update or delete on %I '
      'for each row execute function tg_model_probe_append_only()',t);
  end loop;
end $tables$;

-- New versioned probe facts must name the adding they measured. Older historical facts remain
-- readable; neither an old fact nor a new asserted verdict installs an executable binding.
create function tg_workspace_model_probe_epoch() returns trigger language plpgsql as $fn$
declare a workspace_model%rowtype;
begin
  if new.kind in ('probed','probe_not_finished') and new.document->'facts' ? 'added_seq' then
    select * into a from workspace_model where workspace_id=new.workspace_id
      and provider=new.provider and model_id=new.model_id and kind='added'
      order by model_seq desc limit 1;
    if ((new.document->'facts'->>'added_seq')::bigint=a.model_seq) is not true
      or (new.document->'facts'->>'added_sha256'=a.document_sha256) is not true then
      raise exception 'a probe fact belongs to the current adding' using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;
create trigger tg_workspace_model_probe_epoch before insert on workspace_model
  for each row execute function tg_workspace_model_probe_epoch();

create function tg_model_probe_erases_on_workspace_tombstone() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope::text='workspace' then
    perform assert_workspace_context(new.workspace_id);
    update job set state='cancelled',completed_at=now(),lease_expires_at=null,
      claim_token=null,claimed_by=null,last_error='workspace_erased',failure_class='workspace_erased'
      where workspace_id=new.workspace_id and kind='model_probe' and state in ('queued','running');
    delete from model_probe_outcome where workspace_id=new.workspace_id;
    delete from model_probe_receipt where workspace_id=new.workspace_id;
    delete from model_probe_start where workspace_id=new.workspace_id;
    delete from model_probe where workspace_id=new.workspace_id;
  end if;
  return new;
end $fn$;
create trigger tg_model_probe_erases_on_workspace_tombstone after insert on tombstone
  for each row execute function tg_model_probe_erases_on_workspace_tombstone();

do $definer$ begin
  execute format('alter function tg_model_probe_erases_on_workspace_tombstone() '
    'set search_path=pg_catalog,%I,pg_temp',current_schema());
  revoke all on function tg_model_probe_erases_on_workspace_tombstone() from public;
  alter function tg_model_probe_erases_on_workspace_tombstone() owner to exulanica_definer;
  grant select,delete on model_probe,model_probe_start,model_probe_receipt,model_probe_outcome to exulanica_definer;
  grant select on job to exulanica_definer;
  grant update(state,completed_at,lease_expires_at,claim_token,claimed_by,last_error,failure_class)
    on job to exulanica_definer;
end $definer$;
commit;
