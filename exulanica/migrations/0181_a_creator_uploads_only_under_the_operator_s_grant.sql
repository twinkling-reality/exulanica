-- 0181_a_creator_uploads_only_under_the_operator_s_grant.sql
-- A browser session admits a creator's bytes (a style pack or a workspace asset) only while its
-- account holds the operator's creator grant. The operator grants and revokes it with a host
-- command (`exulanica-creator-grant`) through the account role, and the account role reads it
-- where it already resolves the session (`AccountRepository.session`).
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- WHY. Sign-in makes any Google identity the owner of a new workspace, and an owner holds
-- `admission.write`, so where sign-in is open anyone could upload. Until now the only guard was
-- the installation's switch for style pack uploads, all or nothing, and workspace assets had none.
-- The grant is the operator's decision per account. A bearer token is the operator's own grant to
-- a program, so the permission floor asks a browser session alone (exulanica/api/permissions.py,
-- CREATOR_GRANT_ROUTES).
--
-- THE SHAPE CHOSEN. One table of events. Each account's events are a chain numbered from 1 with
-- no gap, a grant first and the kinds alternating, so the chain's newest event says whether the
-- account holds the grant. Nothing is updated or deleted (0058's tg_account_immutable, which names
-- no column of this table as mutable). Why and by whom are codes, never words. Installation-wide:
-- no workspace, beside the account tables, which the runtime role never reads; no definer.
--
-- RESTORES. A revocation is a withdrawal: a restore from a backup older than it would hand the
-- grant back. exulanica/deletion/withdrawals.v2.json carries the `creator_grant` kind, a chained
-- event as a person's consents are, and 0107's sealed-checkpoint trigger refuses a new event while
-- a checkpoint is sealed. The catalog's identity changes, so the operator seals a fresh checkpoint
-- after deploying (docs/deployment.md).

begin;
select pg_advisory_xact_lock(119622309);

create table account_creator_grant_event (
  event_id    uuid primary key,
  user_id     uuid not null references account_user(user_id),
  sequence    integer not null check (sequence > 0),
  kind        text not null check (kind in ('grant', 'revoke')),
  reason      text not null check (reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  operator    text not null check (operator ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  recorded_at timestamptz not null default now(),
  unique (user_id, sequence)
);

-- The chain's rule, read from the table itself: the next number, and the other kind than the
-- newest event's (a grant when there is none). Two writers racing for one account meet the unique
-- key. An invoker: it reads only this table, which the account role that writes it selects.
create function tg_account_creator_grant_chain() returns trigger language plpgsql as $fn$
declare
  last_sequence integer;
  last_kind text;
begin
  select e.sequence, e.kind into last_sequence, last_kind from account_creator_grant_event e
   where e.user_id = new.user_id order by e.sequence desc limit 1;
  if new.sequence <> coalesce(last_sequence, 0) + 1 or new.kind = coalesce(last_kind, 'revoke') then
    raise exception 'an account''s creator grant events alternate from a grant, numbered from 1'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
revoke all on function tg_account_creator_grant_chain() from public;

create trigger account_creator_grant_chain before insert on account_creator_grant_event
  for each row execute function tg_account_creator_grant_chain();
create trigger account_immutable before update or delete on account_creator_grant_event
  for each row execute function tg_account_immutable();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on account_creator_grant_event
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- As 0058 and 0139 do for their tables: no grant a provisioner's default privileges gave survives,
-- for any grantee. `exulanica-db` grants the account role what it needs
-- (exulanica/db/account_roles.py).
revoke all privileges on table account_creator_grant_event from public;
do $$ declare held record; begin
  for held in select distinct c.relname, a.grantee from pg_class c
    join pg_namespace n on n.oid = c.relnamespace,
    lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    where n.nspname = current_schema()
      and c.relname = 'account_creator_grant_event' and a.grantee <> c.relowner
  loop
    execute format('revoke all privileges on table %I from %s cascade', held.relname,
      case when held.grantee = 0 then 'PUBLIC' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

commit;
