-- Selected picture notes have their own closed bundle and fresh, explicitly bound consent.
begin;
select pg_advisory_xact_lock(119622309);
alter table reference_request drop constraint reference_request_bundle_check;
alter table reference_request add constraint reference_request_bundle_check check (
  bundle is null or (
    bundle->>'profile' = 'exulanica.reference-bundle/v1'
    or (bundle->>'profile' in ('exulanica.reference-bundle/v2','exulanica.reference-bundle/v3')
        and purpose = 'things' and bundle->>'purpose' = purpose)
  ) is true
);
alter table creature_draft drop constraint creature_draft_reference_usage;
alter table creature_draft add constraint creature_draft_reference_usage check (
    reference_usage is null or (
      reference_id is not null
      and jsonb_typeof(reference_usage) = 'object'
      and reference_usage ?& array['state','code','bundle_sha256','notes','basis']
      and reference_usage - array['state','code','bundle_sha256','notes','basis'] = '{}'::jsonb
      and (
        (
          reference_usage->>'state' in ('used','unknown')
          and jsonb_typeof(reference_usage->'bundle_sha256') = 'string'
          and reference_usage->>'bundle_sha256' ~ '^[0-9a-f]{64}$'
          and jsonb_typeof(reference_usage->'notes') = 'number'
          and reference_usage->>'notes' ~ '^([1-9]|1[0-9]|2[0-4])$'
          and reference_usage->'basis' in ('["web_description"]'::jsonb, '["own_picture"]'::jsonb, '["web_description","own_picture"]'::jsonb)
          and (
            (reference_usage->>'state' = 'used' and reference_usage->'code' = 'null'::jsonb)
            or (reference_usage->>'state' = 'unknown'
                and reference_usage->>'code' = 'reference_delivery_unknown')
          )
        )
        or (
          reference_usage->>'state' = 'not_used'
          and reference_usage->>'code' in (
            'reference_unknown', 'reference_not_finished', 'reference_purpose_differs',
            'reference_has_no_notes', 'reference_withdrawn', 'reference_not_sent')
          and reference_usage->'bundle_sha256' = 'null'::jsonb
          and reference_usage->'notes' = '0'::jsonb
          and reference_usage->'basis' = '[]'::jsonb
        )
      )
    ) is true
  );

create table personal_model_right_use (
  workspace_id uuid not null,
  right_id uuid not null,
  use_context jsonb not null,
  context_sha256 bytea not null,
  primary key(workspace_id,right_id),
  foreign key(workspace_id,right_id) references personal_model_right(workspace_id,right_id)
    on delete cascade,
  check (jsonb_typeof(use_context)='object'
    and use_context ?& array['profile','use','role','destination','models','notice']
    and use_context - array['profile','use','role','destination','models','notice']='{}'::jsonb
    and use_context->>'profile'='exulanica.model-right-use/v1'
    and use_context->>'use'='creature_picture_notes/v1'
    and use_context->>'role'='creature_drafter'
    and jsonb_typeof(use_context->'models')='array'
    and jsonb_array_length(use_context->'models') between 1 and 8
    and jsonb_typeof(use_context->'notice')='string'
    and length(use_context->>'notice') between 1 and 2000),
  check(context_sha256=sha256(convert_to(privacy_canonical(use_context),'UTF8')))
);
alter table personal_model_right_use enable row level security;
alter table personal_model_right_use force row level security;
create policy ws_isolation on personal_model_right_use
  using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());

create function tg_personal_model_right_use_immutable() returns trigger
language plpgsql as $fn$
begin
  -- Parent-right deletion belongs to existing erasure authorities. Only that cascade may
  -- remove this binding; normal rights stop without removing their immutable consent evidence.
  if tg_op='DELETE' and not exists(select 1 from personal_model_right r
      where r.workspace_id=old.workspace_id and r.right_id=old.right_id) then return old; end if;
  if tg_op <> 'INSERT' or current_user <> 'exulanica_definer' then
    raise exception 'a use binding is recorded only with its fresh typed grant' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;
create trigger tg_personal_model_right_use_immutable
before insert or update or delete on personal_model_right_use
for each row execute function tg_personal_model_right_use_immutable();

-- The authenticated API validates actual notice equality against the server's current offer.
-- SQL enforces a fresh right, existing source/actor authority, model/destination membership and
-- the same notice in that authority. SQL cannot prove a human read it or resolve a Python manifest.
-- It computes both digests itself. This function cannot attach consent to a preexisting right.
create function grant_creature_note_model_right(
  p_workspace uuid,p_right uuid,p_receipt jsonb,p_context jsonb) returns void
language plpgsql security definer as $fn$
declare canonical bytea; authority jsonb; member jsonb;
begin
  perform assert_workspace_context(p_workspace);
  if jsonb_typeof(p_context) is distinct from 'object'
    or p_context - array['profile','use','role','destination','models','notice'] <> '{}'::jsonb
    or not (p_context ?& array['profile','use','role','destination','models','notice'])
    or p_context->>'profile' is distinct from 'exulanica.model-right-use/v1'
    or p_context->>'use' is distinct from 'creature_picture_notes/v1'
    or p_context->>'role' is distinct from 'creature_drafter'
    or p_receipt->'model'->>'role' is distinct from 'creature_drafter'
    or p_context->>'destination' is distinct from p_receipt->>'destination'
    or jsonb_typeof(p_context->'models') is distinct from 'array'
    or jsonb_typeof(p_context->'notice') is distinct from 'string'
    or length(p_context->>'notice') not between 1 and 2000 then
    raise exception 'the fresh right must name the declared creature picture-note use' using errcode='23514';
  end if;
  for member in select value from jsonb_array_elements(p_context->'models') loop
    if member - array['provider','role','model_id','revision'] <> '{}'::jsonb
      or not (member ?& array['provider','role','model_id','revision'])
      or member->>'role' is distinct from 'creature_drafter' then
      raise exception 'every use-context member names the creature role' using errcode='23514';
    end if;
  end loop;
  if not p_context->'models' @> jsonb_build_array(p_receipt->'model') then
    raise exception 'the granted model is absent from the use context' using errcode='23514';
  end if;
  select authorization_scope into authority from capture_reconstruction_authorization
    where workspace_id=p_workspace
      and authorization_id=(p_receipt->'authorization'->>'authorization_id')::uuid;
  if not exists(select 1 from jsonb_array_elements(coalesce(authority->'model_rights','[]'::jsonb)) item
      where item->>'role'='creature_drafter' and item->>'notice'=p_context->>'notice'
        and (item->>'valid_until')::timestamptz=(p_receipt->>'valid_until')::timestamptz) then
    raise exception 'the source authority does not carry this exact creature notice and term' using errcode='23514';
  end if;
  canonical := convert_to(privacy_canonical(p_receipt),'UTF8');
  insert into personal_model_right(workspace_id,right_id,capture_id,source_sha256,
    authorization_id,operation,model_provider,model_role,model_id,model_revision,destination,
    purpose,granted_by,granted_at,valid_until,receipt_record,receipt_canonical,receipt_sha256)
  values(p_workspace,p_right,(p_receipt->>'capture_id')::uuid,
    decode(p_receipt->>'source_sha256','hex'),
    (p_receipt->'authorization'->>'authorization_id')::uuid,p_receipt->>'operation',
    p_receipt->'model'->>'provider',p_receipt->'model'->>'role',p_receipt->'model'->>'model_id',
    p_receipt->'model'->>'revision',p_receipt->>'destination',p_receipt->>'purpose',
    (p_receipt->>'granted_by')::uuid,(p_receipt->>'granted_at')::timestamptz,
    (p_receipt->>'valid_until')::timestamptz,p_receipt,canonical,sha256(canonical));
  insert into personal_model_right_use(workspace_id,right_id,use_context,context_sha256)
    values(p_workspace,p_right,p_context,sha256(convert_to(privacy_canonical(p_context),'UTF8')));
end $fn$;

do $$ begin
  execute format('alter function grant_creature_note_model_right(uuid,uuid,jsonb,jsonb) '
    'set search_path=pg_catalog,%I,pg_temp',current_schema());
end $$;
revoke all on function grant_creature_note_model_right(uuid,uuid,jsonb,jsonb) from public;
alter function grant_creature_note_model_right(uuid,uuid,jsonb,jsonb) owner to exulanica_definer;
grant select on capture,capture_reconstruction_authorization,personal_model_right_use to exulanica_definer;
grant insert on personal_model_right,personal_model_right_use to exulanica_definer;
-- Provisioned runtime gets only SELECT on the binding and EXECUTE on the typed grant; readonly
-- gets SELECT only. Provisioning's explicit lists repeat these grants for custom role names.
do $$ declare r text; begin
  foreach r in array array['exulanica_app','exulanica_ro'] loop
    if exists(select 1 from pg_roles where rolname=r) then
      execute format('revoke all on personal_model_right_use from %I',r);
      execute format('grant select on personal_model_right_use to %I',r);
      if r='exulanica_app' then
        execute format('grant execute on function grant_creature_note_model_right(uuid,uuid,jsonb,jsonb) to %I',r);
      end if;
    end if;
  end loop;
end $$;
commit;
