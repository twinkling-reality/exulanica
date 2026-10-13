-- Browser-bound human invitations. No existing account receives host workspace authority.
begin;
select pg_advisory_xact_lock(119622309);
alter type tombstone_scope add value if not exists 'participation';

alter table route_permission_refusal
  drop constraint route_permission_refusal_missing_permissions_check;
alter table route_permission_refusal
  add constraint route_permission_refusal_missing_permissions_check check (
    array_ndims(missing_permissions)=1
    and cardinality(missing_permissions) between 1 and 18
    and array_position(missing_permissions,null) is null
    and missing_permissions <@ array[
      'admission.read','admission.write','being.act','consent.read','consent.write',
      'deletion.write','door.grant','intake.write','library.read','library.write','model.invoke',
      'operations.read','operations.write','references.request','tiles.materialise',
      'world.enter','world.read','world.write'
    ]::text[]
  );

create table world_grant (
  workspace_id uuid not null,
  grant_id uuid not null unique,
  world_id text not null,
  issued_by uuid not null,
  issued_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id,grant_id),
  foreign key (workspace_id,world_id) references world_identity(workspace_id,world_id)
);
create index world_grant_by_world on world_grant(workspace_id,world_id);
create table world_grant_revision (
  workspace_id uuid not null,
  grant_id uuid not null,
  grant_seq integer not null check (grant_seq > 0),
  version_id uuid not null,
  expires_at timestamptz not null,
  document jsonb not null check (jsonb_typeof(document)='object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id,grant_id,grant_seq),
  foreign key (workspace_id,grant_id) references world_grant(workspace_id,grant_id),
  check (document->>'profile' is not distinct from 'exulanica.world-grant/v1'),
  check (document->>'grant_id' is not distinct from grant_id::text),
  check (document->>'grant_seq' is not distinct from grant_seq::text),
  check (document->>'version_id' is not distinct from version_id::text),
  check (octet_length(document::text) <= 16384)
);
create table world_grant_principal (
  workspace_id uuid not null,
  grant_id uuid not null,
  principal_sha256 text not null check (principal_sha256 ~ '^[0-9a-f]{64}$'),
  notice_sha256 text not null check (notice_sha256 ~ '^[0-9a-f]{64}$'),
  bound_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id,grant_id),
  foreign key (workspace_id,grant_id) references world_grant(workspace_id,grant_id)
);
create table world_grant_revocation (
  workspace_id uuid not null,
  grant_id uuid not null,
  revoked_by uuid not null,
  revoked_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id,grant_id),
  foreign key (workspace_id,grant_id) references world_grant(workspace_id,grant_id)
);
create table world_grant_departure (
  workspace_id uuid not null,
  grant_id uuid not null,
  tombstone_id uuid not null,
  departed_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id,grant_id),
  foreign key (workspace_id,grant_id) references world_grant(workspace_id,grant_id)
);
-- Directory only. Its rows never enter a backup set, so restore cannot reopen any grant.
create table world_grant_entry (
  grant_id uuid primary key,
  workspace_id uuid not null,
  secret_sha256 text not null unique check (secret_sha256 ~ '^[0-9a-f]{64}$'),
  expires_at timestamptz not null,
  used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default statement_timestamp(),
  unique (workspace_id,grant_id),
  foreign key (workspace_id,grant_id) references world_grant(workspace_id,grant_id)
);
create table participation_redemption_refusal (
  workspace_id uuid not null,
  requester_sha256 text not null check (requester_sha256 ~ '^[0-9a-f]{64}$'),
  refused_at timestamptz not null default statement_timestamp()
);
create index participation_refusal_window
  on participation_redemption_refusal(workspace_id,requester_sha256,refused_at);

create function tg_participation_record_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    if current_user <> 'exulanica_definer' then
      raise exception 'participation records are erased by their erasure authority' using errcode='23514';
    end if;
    return old;
  end if;
  perform assert_workspace_context(new.workspace_id);
  if tg_op='UPDATE' then
    if tg_table_name <> 'world_grant_entry'
       or (to_jsonb(new)-'used_at'-'revoked_at') <> (to_jsonb(old)-'used_at'-'revoked_at')
       or (old.used_at is not null and new.used_at is distinct from old.used_at)
       or (old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at) then
      raise exception 'participation records are appended, and entry timestamps set once' using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;

do $$ declare t text; begin
  foreach t in array array['world_grant','world_grant_revision','world_grant_principal',
    'world_grant_revocation','world_grant_departure','participation_redemption_refusal'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using (workspace_id=current_workspace()) '
                   'with check (workspace_id=current_workspace())',t);
  end loop;
  foreach t in array array['world_grant','world_grant_revision','world_grant_principal',
    'world_grant_revocation','world_grant_departure','world_grant_entry',
    'participation_redemption_refusal'] loop
    execute format('create trigger tg_participation_record_guard before insert or update or delete '
                   'on %I for each row execute function tg_participation_record_guard()',t);
  end loop;
  foreach t in array array['world_grant_revocation','world_grant_departure'] loop
    execute format('create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on %I '
                   'for each row execute function tg_sealed_checkpoint_refuses_withdrawals()',t);
  end loop;
end $$;

create trigger tg_sealed_checkpoint_refuses_withdrawals
  before update of revoked_at on world_grant_entry
  for each row when (old.revoked_at is distinct from new.revoked_at)
  execute function tg_sealed_checkpoint_refuses_withdrawals();

create function participation_erase(p_workspace uuid,p_world text) returns void
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(p_workspace);
  perform pg_advisory_xact_lock(hashtextextended(p_workspace::text,880024));
  delete from world_grant_entry e using world_grant g
   where e.workspace_id=p_workspace and g.workspace_id=e.workspace_id and g.grant_id=e.grant_id
     and (p_world is null or g.world_id=p_world);
  delete from world_grant_principal e using world_grant g
   where e.workspace_id=p_workspace and g.workspace_id=e.workspace_id and g.grant_id=e.grant_id
     and (p_world is null or g.world_id=p_world);
  delete from world_grant_departure e using world_grant g
   where e.workspace_id=p_workspace and g.workspace_id=e.workspace_id and g.grant_id=e.grant_id
     and (p_world is null or g.world_id=p_world);
  delete from world_grant_revocation e using world_grant g
   where e.workspace_id=p_workspace and g.workspace_id=e.workspace_id and g.grant_id=e.grant_id
     and (p_world is null or g.world_id=p_world);
  delete from world_grant_revision e using world_grant g
   where e.workspace_id=p_workspace and g.workspace_id=e.workspace_id and g.grant_id=e.grant_id
     and (p_world is null or g.world_id=p_world);
  delete from world_grant where workspace_id=p_workspace and (p_world is null or world_id=p_world);
  if p_world is null then
    delete from participation_redemption_refusal where workspace_id=p_workspace;
  end if;
end $fn$;
create function tg_participation_erasure() returns trigger
language plpgsql security definer as $fn$
begin
  if tg_table_name='world_erasure' then
    perform participation_erase(new.workspace_id,new.world_id);
  elsif new.scope::text='workspace' then
    perform participation_erase(new.workspace_id,null);
  end if;
  return new;
end $fn$;
-- AFTER triggers run by name. Both execute after the shared workspace-lock guard and before
-- tg_world_erasure_erases / tg_world_erases_on_tombstone delete world_identity.
create trigger tg_b_participation_erasure after insert on world_erasure
  for each row execute function tg_participation_erasure();
create trigger tg_b_participation_erasure after insert on tombstone
  for each row execute function tg_participation_erasure();

create function tg_participation_departure() returns trigger
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  if not exists (select 1 from tombstone t where t.tombstone_id=new.tombstone_id
                 and t.workspace_id=new.workspace_id and t.scope::text='participation')
     and not exists (select 1 from restore_control where state='replaying') then
    raise exception 'a departure names its participation tombstone or is carried by restore'
      using errcode='23514';
  end if;
  delete from world_grant_principal where workspace_id=new.workspace_id and grant_id=new.grant_id;
  delete from world_grant_entry where workspace_id=new.workspace_id and grant_id=new.grant_id;
  return new;
end $fn$;
create trigger tg_participation_departure after insert on world_grant_departure
  for each row execute function tg_participation_departure();

-- A revoke closes both a bound entry and an unused invitation in the withdrawal's transaction.
create function tg_participation_revocation() returns trigger
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  update world_grant_entry set revoked_at=coalesce(revoked_at,new.revoked_at)
   where workspace_id=new.workspace_id and grant_id=new.grant_id;
  return new;
end $fn$;
create trigger tg_participation_revocation after insert on world_grant_revocation
  for each row execute function tg_participation_revocation();

-- Bounded housekeeping; account request serialization keeps its one-minute refusal budget exact.
create function participation_prune(p_limit integer) returns integer
language plpgsql security definer as $fn$
declare removed integer; n integer;
begin
  if p_limit < 1 or p_limit > 1000 then
    raise exception 'participation pruning limit is between one and one thousand' using errcode='22023';
  end if;
  delete from participation_redemption_refusal where ctid in (
    select ctid from participation_redemption_refusal where workspace_id=current_workspace()
      and refused_at < statement_timestamp()-interval '1 day' order by refused_at limit p_limit
  );
  get diagnostics removed = row_count;
  -- Unused expired invitations never represented a principal or withdrawal.
  delete from world_grant_entry where grant_id in (
    select grant_id from world_grant_entry where workspace_id=current_workspace()
      and used_at is null and revoked_at is null
      and expires_at < statement_timestamp()-interval '1 day' order by expires_at limit p_limit
  );
  get diagnostics n = row_count;
  removed := removed+n;
  -- Retire the account-link hash after the end; retained revocation rows remain restore evidence.
  delete from world_grant_principal where (workspace_id,grant_id) in (
    select p.workspace_id,p.grant_id from world_grant_principal p
    join lateral (select r.expires_at from world_grant_revision r
      where r.workspace_id=p.workspace_id and r.grant_id=p.grant_id
      order by r.grant_seq desc limit 1) r on true
    left join world_grant_revocation v on v.workspace_id=p.workspace_id and v.grant_id=p.grant_id
    where p.workspace_id=current_workspace()
      and least(r.expires_at,v.revoked_at) < statement_timestamp()-interval '1 day'
    order by p.bound_at limit p_limit
  );
  get diagnostics n = row_count;
  return removed+n;
end $fn$;

do $$ declare f text; begin
  foreach f in array array['participation_erase(uuid,text)','tg_participation_erasure()',
    'tg_participation_departure()','tg_participation_revocation()','participation_prune(integer)'] loop
    execute format('alter function %s set search_path=pg_catalog,%I,pg_temp',f,current_schema());
    execute format('revoke all on function %s from public',f);
    execute format('alter function %s owner to exulanica_definer',f);
  end loop;
end $$;
grant select,delete on world_grant,world_grant_revision,world_grant_principal,
  world_grant_revocation,world_grant_departure,world_grant_entry,
  participation_redemption_refusal to exulanica_definer;
grant update(revoked_at) on world_grant_entry to exulanica_definer;

do $$ declare r text; t text; begin
  foreach r in array array['exulanica_app','exulanica_ro'] loop
    if exists(select 1 from pg_roles where rolname=r) then
      foreach t in array array['world_grant','world_grant_revision','world_grant_revocation',
        'world_grant_departure','world_grant_principal'] loop
        execute format('grant select on %I to %I',t,r);
        if r='exulanica_app' then execute format('grant insert on %I to %I',t,r); end if;
      end loop;
      if r='exulanica_app' then
        grant select,insert on world_grant_entry,participation_redemption_refusal to exulanica_app;
        grant update(used_at,revoked_at) on world_grant_entry to exulanica_app;
        grant execute on function participation_prune(integer) to exulanica_app;
      end if;
    end if;
  end loop;
end $$;
commit;
