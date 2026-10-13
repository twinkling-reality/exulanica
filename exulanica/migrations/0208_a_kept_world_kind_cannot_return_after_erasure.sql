-- Erase one unused kept world-kind version. Digests retire its content and key/version;
-- they are fingerprints, not anonymization. Receipts copy the document and therefore block
-- erasure. Their insertion guard closes composition that started before erasure.
-- Inline worlds have no library binding and can independently use the same key/version with
-- different bytes, so their receipt guard matches the document fingerprint alone.
begin;
select pg_advisory_xact_lock(119622309);
alter type tombstone_scope add value if not exists 'world_kind';

create table world_kind_erasure (
  workspace_id uuid not null,
  erasure_id uuid not null default uuidv7(),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  kind_key_sha256 text not null check (kind_key_sha256 ~ '^[0-9a-f]{64}$'),
  version integer not null check (version between 1 and 9999),
  tombstone_id uuid not null unique,
  erased_by uuid not null,
  erased_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, erasure_id),
  unique (workspace_id, document_sha256),
  unique (workspace_id, kind_key_sha256, version)
);
comment on table world_kind_erasure is
  'Permanent retirement of a kept world-kind document and key/version. Content and key '
  'fingerprints support restore and stale-writer refusal; no document or human words remain.';
alter table world_kind_erasure enable row level security;
alter table world_kind_erasure force row level security;
create policy ws_isolation on world_kind_erasure
  using (workspace_id=current_workspace()) with check (workspace_id=current_workspace());
create trigger tg_world_kind_erasure_append_only before update or delete on world_kind_erasure
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on world_kind_erasure
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

create function tg_world_kind_erasure_erases() returns trigger
language plpgsql security definer as $fn$
declare
  v_anchor text;
  v_kind world_kind_version%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select case when t.workspace_id=new.workspace_id and t.scope::text='world_kind'
                   and t.requested_by=new.erased_by then 'held' else 'another' end
    into v_anchor from tombstone t where t.tombstone_id=new.tombstone_id;
  if v_anchor='another' or (v_anchor is null and not exists (
      select 1 from restore_control where state='replaying')) then
    raise exception 'a kind erasure requires its tombstone or restore replay'
      using errcode='23514';
  end if;
  select * into v_kind from world_kind_version
    where workspace_id=new.workspace_id and document_sha256=new.document_sha256;
  if found then
    if v_kind.version<>new.version or
       encode(sha256(convert_to(v_kind.kind,'UTF8')),'hex')<>new.kind_key_sha256 then
      raise exception 'a kind erasure must retain the actual kind identity' using errcode='23514';
    end if;
  elsif v_anchor='held' then
    raise exception 'a kind erasure names a kept version' using errcode='23514';
  end if;
  if exists (select 1 from world_generation_receipt r where r.workspace_id=new.workspace_id
      and r.receipt->'kind'->>'sha256'=new.document_sha256) then
    raise exception 'a retained world receipt still uses this kind'
      using errcode='23514', constraint='world_kind_in_use';
  end if;
  delete from world_kind_version where workspace_id=new.workspace_id
    and document_sha256=new.document_sha256;
  return null;
end $fn$;
create trigger tg_world_kind_erasure_erases after insert on world_kind_erasure
  for each row execute function tg_world_kind_erasure_erases();

create function tg_erased_world_kind_stays_erased() returns trigger
language plpgsql as $fn$
declare v_digest text; v_key text; v_version text;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  if tg_table_name='world_kind_version' then
    v_digest := new.document_sha256; v_key := new.kind; v_version := new.version::text;
  else
    v_digest := new.receipt->'kind'->>'sha256';
    v_key := new.receipt->'kind'->>'kind'; v_version := new.receipt->'kind'->>'version';
  end if;
  if exists (select 1 from world_kind_erasure e where e.workspace_id=new.workspace_id
      and (e.document_sha256=v_digest or
           (tg_table_name='world_kind_version'
            and e.kind_key_sha256=encode(sha256(convert_to(v_key,'UTF8')),'hex')
            and e.version::text=v_version))) then
    raise exception 'an erased world kind cannot be kept or used again'
      using errcode='23514', constraint='world_kind_erased';
  end if;
  if exists (select 1 from tombstone t where t.workspace_id=new.workspace_id
      and t.scope::text='workspace' and t.effective_at<=now()) then
    raise exception 'an erased workspace cannot keep world kinds or receipts'
      using errcode='23514', constraint='world_kind_erased';
  end if;
  return new;
end $fn$;
create trigger tg_erased_world_kind_stays_erased before insert on world_kind_version
  for each row execute function tg_erased_world_kind_stays_erased();
create trigger tg_erased_world_kind_stays_erased before insert on world_generation_receipt
  for each row execute function tg_erased_world_kind_stays_erased();

do $$ begin
  execute format('alter function tg_world_kind_erasure_erases() '
                 'set search_path=pg_catalog,%I,pg_temp',current_schema());
end $$;
revoke all on function tg_world_kind_erasure_erases() from public;
-- Existing0195 grants already supply the definer's target deletion and receipt reads.
alter function tg_world_kind_erasure_erases() owner to exulanica_definer;
commit;
