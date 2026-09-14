begin;
select pg_advisory_xact_lock(119622309);

-- Authentication precedes workspace resolution. These global tables are restricted to a
-- dedicated auth role, never granted through the workspace app/read role's generic grants.
-- No email/name/picture, Google token, password, or client-supplied workspace authority.
create table account_user (
  user_id uuid primary key,
  actor_id uuid not null unique,
  created_at timestamptz not null default now(),
  disabled_at timestamptz
);
create table account_identity (
  issuer text not null check(issuer='https://accounts.google.com'),
  subject text not null check(length(subject) between 1 and 255),
  user_id uuid not null references account_user(user_id),
  created_at timestamptz not null default now(),
  primary key(issuer,subject),
  unique(user_id,issuer)
);
create table account_workspace (
  workspace_id uuid primary key,
  owner_user_id uuid not null unique references account_user(user_id),
  created_at timestamptz not null default now(),
  disabled_at timestamptz
);
create table account_membership (
  workspace_id uuid not null references account_workspace(workspace_id),
  user_id uuid not null references account_user(user_id),
  membership_role text not null check(membership_role='owner'),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  primary key(workspace_id,user_id)
);
create table account_login_attempt (
  state_sha256 text primary key check(state_sha256 ~ '^[0-9a-f]{64}$'),
  browser_sha256 text not null check(browser_sha256 ~ '^[0-9a-f]{64}$'),
  config_sha256 text not null check(config_sha256 ~ '^[0-9a-f]{64}$'),
  nonce text,
  verifier text,
  callback_uri text not null,
  return_uri text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null check(expires_at>created_at),
  claimed_at timestamptz,
  outcome text not null default 'pending' check(outcome in ('pending','claimed','failed','succeeded','expired')),
  check((outcome='pending')=(nonce is not null and verifier is not null))
);
create index account_login_expiry on account_login_attempt(expires_at) where outcome='pending';
create table account_browser_session (
  session_sha256 text primary key check(session_sha256 ~ '^[0-9a-f]{64}$'),
  user_id uuid not null references account_user(user_id),
  workspace_id uuid not null,
  csrf_token text not null check(length(csrf_token) between 32 and 128),
  login_state_sha256 text not null unique references account_login_attempt(state_sha256),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null check(expires_at>created_at),
  revoked_at timestamptz,
  foreign key(workspace_id,user_id) references account_membership(workspace_id,user_id)
);
create index account_session_user on account_browser_session(user_id);

create function tg_account_immutable() returns trigger language plpgsql as $fn$
declare mutable text;
begin
  if tg_op='DELETE' then
    raise exception 'account identities and session audit rows are retained' using errcode='23514';
  end if;
  mutable := case tg_table_name
    when 'account_user' then 'disabled_at'
    when 'account_workspace' then 'disabled_at'
    when 'account_membership' then 'revoked_at'
    when 'account_browser_session' then 'revoked_at'
    else '' end;
  if mutable='' or (to_jsonb(new)-mutable) is distinct from (to_jsonb(old)-mutable)
      or (to_jsonb(old)->mutable <> 'null'::jsonb and to_jsonb(new) is distinct from to_jsonb(old)) then
    raise exception 'account bindings are immutable; disabling is irreversible here' using errcode='23514';
  end if;
  return new;
end $fn$;
revoke all on function tg_account_immutable() from public;
do $$ declare t text; begin
  foreach t in array array['account_user','account_identity','account_workspace',
    'account_membership','account_browser_session'] loop
    execute format('create trigger account_immutable before update or delete on %I '
      'for each row execute function tg_account_immutable()',t);
  end loop;
end $$;

create function tg_account_login_transition() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'login audit rows are retained' using errcode='23514';
  end if;
  if (to_jsonb(new)-'nonce'-'verifier'-'claimed_at'-'outcome') is distinct from
     (to_jsonb(old)-'nonce'-'verifier'-'claimed_at'-'outcome') or
     not ((old.outcome='pending' and new.outcome in ('claimed','expired')) or
          (old.outcome='claimed' and new.outcome in ('failed','succeeded','expired'))) or
     new.nonce is not null or new.verifier is not null then
    raise exception 'login attempt cannot be rebound or replayed' using errcode='23514';
  end if;
  return new;
end $fn$;
revoke all on function tg_account_login_transition() from public;
create trigger account_login_transition before update or delete on account_login_attempt
for each row execute function tg_account_login_transition();
do $$ declare t text; begin
  foreach t in array array['account_user','account_identity','account_workspace',
    'account_membership','account_login_attempt','account_browser_session'] loop
    execute format('revoke all privileges on table %I from public',t);
  end loop;
end $$;
-- Existing runtime provisioners grant default privileges on future tables. Strip every
-- inherited non-owner table grant, including custom app/read roles, before auth provisioning.
do $$ declare held record; begin
  for held in select distinct c.relname,a.grantee from pg_class c
    join pg_namespace n on n.oid=c.relnamespace,
    lateral aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
    where n.nspname=current_schema() and c.relname in
      ('account_user','account_identity','account_workspace','account_membership',
       'account_login_attempt','account_browser_session') and a.grantee<>c.relowner
  loop
    execute format('revoke all privileges on table %I from %s cascade',held.relname,
      case when held.grantee=0 then 'PUBLIC' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

-- Forward privilege correction: these existing private boolean capabilities were PUBLIC.
-- The root role provisioners regrant them explicitly to application/read/purge callers.
revoke all on function caption_vector_purge_is_authorized(uuid,uuid,uuid) from public;
revoke all on function caption_vector_purge_is_complete(uuid,uuid) from public;
commit;
