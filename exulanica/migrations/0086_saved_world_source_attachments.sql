-- Append reviewed personal photographs to a saved world without changing its authored scene.

begin;

select pg_advisory_xact_lock(119622309);

create table saved_world_source_attachment_operation (
  workspace_id          uuid not null,
  operation_id          uuid not null,
  entry_id              uuid not null,
  request_sha256        bytea not null check (octet_length(request_sha256) = 32),
  base_entry_revision   bigint not null check (base_entry_revision >= 1),
  result_entry_revision bigint not null check (result_entry_revision = base_entry_revision + 1),
  authored_version_id   uuid not null,
  authored_state_sha256 text not null check (authored_state_sha256 ~ '^[0-9a-f]{64}$'),
  authored_edit_seq     bigint not null check (authored_edit_seq >= 0),
  style_version_id      uuid not null,
  created_by            uuid not null,
  created_at            timestamptz not null default statement_timestamp(),
  primary key (workspace_id, operation_id),
  unique (workspace_id, entry_id, operation_id),
  foreign key (workspace_id, entry_id)
    references saved_world_entry(workspace_id, entry_id)
);

create table saved_world_source_attachment (
  attachment_id          uuid primary key default uuidv7(),
  workspace_id           uuid not null,
  entry_id               uuid not null,
  operation_id           uuid not null,
  capture_id             uuid not null,
  evidence_span_id       uuid not null,
  source_sha256          bytea not null check (octet_length(source_sha256) = 32),
  authorization_id       uuid not null,
  screening_id           uuid not null,
  role                    text not null default 'reference' check (role = 'reference'),
  attached_entry_revision bigint not null check (attached_entry_revision >= 2),
  attached_by            uuid not null,
  attached_at            timestamptz not null default statement_timestamp(),
  unique (workspace_id, attachment_id),
  unique (workspace_id, entry_id, capture_id),
  foreign key (workspace_id, entry_id, operation_id)
    references saved_world_source_attachment_operation(workspace_id, entry_id, operation_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id),
  foreign key (workspace_id, evidence_span_id)
    references evidence_span(workspace_id, span_id),
  foreign key (workspace_id, authorization_id)
    references capture_reconstruction_authorization(workspace_id, authorization_id),
  foreign key (workspace_id, screening_id)
    references reconstruction_privacy_screening(workspace_id, screening_id)
);

create index saved_world_source_attachment_entry_idx
  on saved_world_source_attachment(workspace_id, entry_id, attached_at, attachment_id);

create function tg_saved_world_source_attachment_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create function tg_saved_world_source_attachment_valid() returns trigger
language plpgsql volatile as $fn$
declare op saved_world_source_attachment_operation%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into op from saved_world_source_attachment_operation
    where workspace_id=new.workspace_id and operation_id=new.operation_id;
  if op.operation_id is null or op.entry_id<>new.entry_id
    or op.result_entry_revision<>new.attached_entry_revision
    or op.created_by<>new.attached_by then
    raise exception 'source attachment does not match its exact saved-world operation'
      using errcode='integrity_constraint_violation';
  end if;
  if not exists (
    select 1 from capture c
    join evidence_span s on s.workspace_id=c.workspace_id
      and s.span_id=new.evidence_span_id and s.blob_sha256=c.blob_sha256
      and s.modality='still_image' and s.track_key='img'
      and s.t_start_ns=0 and s.t_end_ns=1 and s.region is null and s.text_anchor is null
    join blob b on b.blob_sha256=c.blob_sha256 and b.media_type like 'image/%'
    join capture_reconstruction_authorization a on a.workspace_id=c.workspace_id
      and a.authorization_id=new.authorization_id and a.capture_id=c.capture_id
      and a.source_sha256=c.blob_sha256 and a.corpus_class='personal'
      and a.authorized_by=new.attached_by
    join reconstruction_privacy_screening p on p.workspace_id=c.workspace_id
      and p.screening_id=new.screening_id and p.authorization_id=a.authorization_id
      and p.capture_id=c.capture_id and p.source_sha256=c.blob_sha256
      and p.screening_method='human_review' and p.eligibility_state='eligible'
      and p.reviewed_by is not null
    where c.workspace_id=new.workspace_id and c.capture_id=new.capture_id
      and c.blob_sha256=new.source_sha256 and c.deleted_at is null
      and not tombstone_blocks_capture(c.workspace_id,c.capture_id)
      and not tombstone_blocks_span(c.workspace_id,s.blob_sha256,s.track_key,
        s.t_start_ns,s.t_end_ns)
      and privacy_screening_allows_capture(c.workspace_id,c.capture_id,p.screening_id)
  ) then
    raise exception 'source attachment requires an exact current reviewed personal photograph'
      using errcode='integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_saved_world_source_attachment_valid before insert
  on saved_world_source_attachment for each row
  execute function tg_saved_world_source_attachment_valid();

create function tg_saved_world_source_attachment_operation_committed() returns trigger
language plpgsql as $fn$
begin
  if not exists (
    select 1 from saved_world_entry e
    where e.workspace_id=new.workspace_id and e.entry_id=new.entry_id
      and e.revision=new.result_entry_revision
      and e.authored_version_id=new.authored_version_id
      and e.authored_state_sha256=new.authored_state_sha256
      and e.authored_edit_seq=new.authored_edit_seq
      and e.style_version_id=new.style_version_id
      and exists (
        select 1 from saved_world_source_attachment a
        where a.workspace_id=new.workspace_id and a.operation_id=new.operation_id)
  ) then
    raise exception 'source attachment operation did not preserve and advance its exact cursor'
      using errcode='integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_saved_world_source_attachment_operation_committed
  after insert on saved_world_source_attachment_operation deferrable initially deferred
  for each row execute function tg_saved_world_source_attachment_operation_committed();

do $$
declare t text;
begin
  foreach t in array array[
    'saved_world_source_attachment_operation',
    'saved_world_source_attachment'] loop
    execute format(
      'create trigger %I before update or delete on %I for each row '
      'execute function tg_saved_world_source_attachment_append_only()',
      'tg_' || t || '_append_only',t);
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id=current_workspace()) '
      'with check (workspace_id=current_workspace())',t);
  end loop;
end $$;

do $$
declare r text; t text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname=r) then
      foreach t in array array[
        'saved_world_source_attachment_operation',
        'saved_world_source_attachment'] loop
        execute format('grant select on %I to %I',t,r);
        if r in ('exulanica_app','orimera_app') then
          execute format('grant insert on %I to %I',t,r);
          execute format('revoke update,delete on %I from %I',t,r);
        else
          execute format('revoke insert,update,delete on %I from %I',t,r);
        end if;
      end loop;
    end if;
  end loop;
end $$;

commit;
