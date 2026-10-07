-- 0149_an_outside_program_decides_for_a_thing_only_under_its_owner_s_grant.sql
-- The door: an outside program, a bridge the deployment admits, decides for things in a world only
-- under a grant the world's owner issued, and only through the decision host's receipts.
--
-- door_grant, one row per grant: which world and which bridge, who issued it and when.
-- door_grant_revision, the grant's scope as it stands after each change: how many visitors its
-- bridge may bring in, which of the world's own things it decides for, what may be carried and
-- said, and when it ends. Appended, never changed; the newest revision is the grant, and every
-- request asked under it records the revision's number.
-- door_grant_revocation, the owner ending a grant: one row, after which nothing is asked or
-- answered under it and nothing revises it. It is a withdrawal of permission, so a restore from an
-- older backup writes it again (exulanica/deletion/withdrawals.v2.json) and a sealed restore
-- checkpoint refuses it (0107's trigger).
-- door_presence, one row per grant whose bridge has said hello: the adapter's version, the mapping
-- it presented, what the program behind it declared itself to be, and when it last polled. The one
-- workspace table the application updates.
-- door_mapping, each mapping document a bridge presented in this workspace, by its digest, so every
-- crossing and receipt that names a mapping can be read back with it. Appended, never changed.
-- door_declaration, each {name, maker, mind} a program declared at hello in this workspace (mind
-- optional), by its digest, so an answer that names one can be read back with the words. Words for
-- a person reading a card: they never enter a society record or any model's context. Appended,
-- never changed.
-- door_ask, the channel's outbox: one row per decision request the host reserved for a thing this
-- grant decides for, in order. It names the stored request and holds nothing else; the frame a
-- bridge reads is projected from the request itself. Appended, never changed.
-- door_answer, the channel's inbox: the one answer a bridge gave to an ask, as it sent it, with the
-- adapter version, mapping and declaration its grant's presence named when it answered, which is
-- what the receipt and the card record of who answered. It is tied to its ask by all four of the ask's names and is
-- accepted only under a grant that stands, under the lock revoking takes. The host turns it into
-- the receipt; nothing here is a receipt. Appended, never changed.
-- door_secret, global: the SHA-256 of each invite code and channel credential the door issued, with
-- the grant it opens. Read before any workspace is known, so it carries no row-level security and
-- holds nothing but digests and identifiers: a channel credential is 256 random bits and an invite
-- 80, single use and gone in fifteen minutes. A row may only gain the time an invite was used and
-- the time the secret was revoked, each once; what a secret opens ends with its grant. A secret's
-- revocation is a withdrawal a restore writes again (exulanica/deletion/withdrawals.v2.json).
-- door_redemption_refusal, global: one row per refused invite redemption, by bridge and by the
-- digest the bridge states for who typed the code, which is what limits one requester's guesses
-- without locking anybody else out. Appended, never changed.
--
-- The runtime deletes nothing. door_prune, a function with its owner's rights and EXECUTE for the
-- application alone, removes refusals a day old and secrets thirty days past their end, a bounded
-- batch at a time; the two global tables' triggers refuse every other delete, whoever asks.
--
-- The workspace tables are kept to their workspace by row-level security and, on insert, by
-- assert_workspace_context; door_secret's rows are inserted and changed only by a session of the
-- workspace they open. The refusal ledger's closed permission list names door.grant, the owner
-- permission that issues and revokes grants, from migration 0154, which restates that list once for
-- every permission added since 0061; the door lands after it. Every function here runs with its
-- search path pinned to this schema, pg_catalog and pg_temp, so no session's temporary table stands
-- in for one of these.
begin;
select pg_advisory_xact_lock(119622309);

create table door_grant (
  workspace_id uuid not null,
  grant_id uuid not null,
  world_id text not null,
  bridge text not null check (bridge ~ '^[a-z][a-z0-9_-]{0,31}$'),
  issued_by uuid not null,
  issued_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id),
  constraint door_grant_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id)
);
create index door_grant_by_world on door_grant (workspace_id, world_id);

create table door_grant_revision (
  workspace_id uuid not null,
  grant_id uuid not null,
  grant_seq integer not null check (grant_seq between 1 and 1000),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id, grant_seq),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id),
  check (document->>'profile' is not distinct from 'exulanica.door-grant/v1'),
  check (document->>'grant_id' is not distinct from grant_id::text),
  check (document->>'grant_seq' is not distinct from grant_seq::text),
  check (jsonb_typeof(document->'expires_at') is not distinct from 'string'),
  check (octet_length(document::text) <= 16384)
);

create table door_grant_revocation (
  workspace_id uuid not null,
  grant_id uuid not null,
  revoked_by uuid not null,
  revoked_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id)
);

create table door_mapping (
  workspace_id uuid not null,
  mapping_sha256 text not null check (mapping_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, mapping_sha256),
  check (document->>'profile' is not distinct from 'exulanica.bridge-mapping/v1'),
  check (octet_length(document::text) <= 65536)
);

create table door_declaration (
  workspace_id uuid not null,
  declared_sha256 text not null check (declared_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, declared_sha256),
  check (jsonb_typeof(document->'name') is not distinct from 'string'),
  check (jsonb_typeof(document->'maker') is not distinct from 'string'),
  check (not document ? 'mind' or jsonb_typeof(document->'mind') = 'string'),
  check (document - array['name', 'maker', 'mind'] = '{}'::jsonb),
  check (octet_length(document::text) <= 1024)
);

create table door_presence (
  workspace_id uuid not null,
  grant_id uuid not null,
  adapter_version text not null check (adapter_version ~ '^[0-9]{1,6}(\.[0-9]{1,6}){0,3}$'),
  mapping_sha256 text not null check (mapping_sha256 ~ '^[0-9a-f]{64}$'),
  declared_sha256 text check (declared_sha256 ~ '^[0-9a-f]{64}$'),
  hello_at timestamptz not null default statement_timestamp(),
  polled_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id),
  foreign key (workspace_id, mapping_sha256) references door_mapping (workspace_id, mapping_sha256),
  foreign key (workspace_id, declared_sha256)
    references door_declaration (workspace_id, declared_sha256),
  check (polled_at >= hello_at)
);

create table door_ask (
  workspace_id uuid not null,
  grant_id uuid not null,
  ask_seq bigint not null check (ask_seq > 0),
  society_id uuid not null,
  request_id uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, grant_id, ask_seq),
  unique (workspace_id, request_id),
  unique (workspace_id, grant_id, ask_seq, request_id),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id),
  foreign key (workspace_id, society_id, request_id)
    references world_society_decision_request (workspace_id, society_id, request_id)
);

create table door_answer (
  workspace_id uuid not null,
  request_id uuid not null,
  grant_id uuid not null,
  ask_seq bigint not null,
  adapter_version text not null check (adapter_version ~ '^[0-9]{1,6}(\.[0-9]{1,6}){0,3}$'),
  mapping_sha256 text not null check (mapping_sha256 ~ '^[0-9a-f]{64}$'),
  declared_sha256 text check (declared_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  answer_sha256 text not null check (answer_sha256 ~ '^[0-9a-f]{64}$'),
  received_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, request_id),
  foreign key (workspace_id, grant_id, ask_seq, request_id)
    references door_ask (workspace_id, grant_id, ask_seq, request_id),
  foreign key (workspace_id, mapping_sha256) references door_mapping (workspace_id, mapping_sha256),
  foreign key (workspace_id, declared_sha256)
    references door_declaration (workspace_id, declared_sha256),
  check (document->>'request_id' is not distinct from request_id::text),
  check (jsonb_typeof(document->'label') is not distinct from 'string'),
  check (octet_length(document::text) <= 2048)
);

create table door_secret (
  secret_sha256 text primary key check (secret_sha256 ~ '^[0-9a-f]{64}$'),
  kind text not null check (kind in ('invite', 'channel')),
  bridge text not null check (bridge ~ '^[a-z][a-z0-9_-]{0,31}$'),
  workspace_id uuid not null,
  grant_id uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  expires_at timestamptz not null,
  used_at timestamptz,
  revoked_at timestamptz,
  check (expires_at > created_at),
  check (kind = 'invite' or used_at is null),
  check (revoked_at is null or revoked_at >= created_at),
  foreign key (workspace_id, grant_id) references door_grant (workspace_id, grant_id)
);
create index door_secret_by_grant on door_secret (workspace_id, grant_id);
create index door_secret_by_end on door_secret (expires_at);

create table door_redemption_refusal (
  bridge text not null check (bridge ~ '^[a-z][a-z0-9_-]{0,31}$'),
  requester_sha256 text not null check (requester_sha256 ~ '^[0-9a-f]{64}$'),
  refused_at timestamptz not null default statement_timestamp()
);
create index door_redemption_refusal_by_requester
  on door_redemption_refusal (bridge, requester_sha256, refused_at);
create index door_redemption_refusal_by_time on door_redemption_refusal (refused_at);

-- A revision follows the one before it, names its grant's world and bridge, and is recorded by a
-- session of its workspace.
create function tg_door_grant_revision_binding() returns trigger language plpgsql as $fn$
declare held door_grant%rowtype; latest integer;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.grant_id::text, 149001));
  select * into held from door_grant
    where workspace_id = new.workspace_id and grant_id = new.grant_id;
  select coalesce(max(grant_seq), 0) into latest from door_grant_revision
    where workspace_id = new.workspace_id and grant_id = new.grant_id;
  if new.grant_seq <> latest + 1
     or new.document->>'world_id' is distinct from held.world_id
     or new.document->>'bridge' is distinct from held.bridge then
    raise exception 'a grant revision follows the last and names its grant''s world and bridge'
      using errcode = '23514';
  end if;
  if exists (
    select 1 from door_grant_revocation
    where workspace_id = new.workspace_id and grant_id = new.grant_id) then
    raise exception 'an ended grant is not revised again' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_grant_revision_binding before insert on door_grant_revision
  for each row execute function tg_door_grant_revision_binding();

-- Whether a grant stands now: it has a revision, is not revoked and is not past its end. A
-- revision with no readable end is ended.
create function door_grant_stands(p_workspace_id uuid, p_grant_id uuid) returns boolean
language plpgsql stable as $fn$
declare scope jsonb;
begin
  select document into scope from door_grant_revision
    where workspace_id = p_workspace_id and grant_id = p_grant_id
    order by grant_seq desc limit 1;
  return scope is not null
     and not exists (select 1 from door_grant_revocation
                     where workspace_id = p_workspace_id and grant_id = p_grant_id)
     and coalesce((scope->>'expires_at')::timestamptz, '-infinity'::timestamptz)
         > statement_timestamp();
end $fn$;

-- An ask follows the grant's last ask, under a grant that stands.
create function tg_door_ask_binding() returns trigger language plpgsql as $fn$
declare latest bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.grant_id::text, 149002));
  if not door_grant_stands(new.workspace_id, new.grant_id) then
    raise exception 'an ask is made only under a grant that stands' using errcode = '23514';
  end if;
  select coalesce(max(ask_seq), 0) into latest from door_ask
    where workspace_id = new.workspace_id and grant_id = new.grant_id;
  if new.ask_seq <> latest + 1 then
    raise exception 'an ask follows its grant''s last ask' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_ask_binding before insert on door_ask
  for each row execute function tg_door_ask_binding();

-- An answer is given only under a grant that stands, read under the lock revoking takes, so a
-- revocation and an answer never both commit as if the other had not.
create function tg_door_answer_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.grant_id::text, 149001));
  if not door_grant_stands(new.workspace_id, new.grant_id) then
    raise exception 'an answer is given only under a grant that stands' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_answer_binding before insert on door_answer
  for each row execute function tg_door_answer_binding();

create function tg_door_scoped_insert() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;
do $$ declare t text; begin
  foreach t in array array['door_grant', 'door_grant_revocation', 'door_presence', 'door_mapping',
                           'door_declaration']
  loop
    execute format('create trigger %I before insert on %I for each row '
      'execute function tg_door_scoped_insert()', t || '_scoped_insert', t);
  end loop;
end $$;

-- The application only appends these.
create function tg_door_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception '% is appended, never changed', tg_table_name using errcode = '23514';
end $fn$;
do $$ declare t text; begin
  foreach t in array array['door_grant', 'door_grant_revision', 'door_grant_revocation',
                           'door_mapping', 'door_declaration', 'door_ask', 'door_answer'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_door_append_only()', t || '_append_only', t);
  end loop;
end $$;

-- Presence changes only its poll time, or its hello as a whole, and never leaves its workspace.
create function tg_door_presence_change() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a grant''s presence is never deleted' using errcode = '23514';
  end if;
  perform assert_workspace_context(old.workspace_id);
  if new.workspace_id <> old.workspace_id or new.grant_id <> old.grant_id
     or new.polled_at < old.polled_at then
    raise exception 'a grant''s presence only moves forward' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_presence_change before update or delete on door_presence
  for each row execute function tg_door_presence_change();

-- A secret is issued unused and unrevoked by a session of the workspace it opens. Afterwards an
-- invite may gain the time it was used and any secret the time it was revoked, each once, from a
-- session of its workspace; and a secret is deleted only thirty days after its end.
create function tg_door_secret_change() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    if old.expires_at > statement_timestamp() - interval '30 days' then
      raise exception 'a door secret is kept for thirty days after its end'
        using errcode = '23514';
    end if;
    return old;
  end if;
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    if new.used_at is not null or new.revoked_at is not null then
      raise exception 'a door secret is issued unused and unrevoked' using errcode = '23514';
    end if;
    return new;
  end if;
  perform assert_workspace_context(old.workspace_id);
  if (new.secret_sha256, new.kind, new.bridge, new.workspace_id, new.grant_id, new.created_at,
      new.expires_at)
     is distinct from
     (old.secret_sha256, old.kind, old.bridge, old.workspace_id, old.grant_id, old.created_at,
      old.expires_at)
     or (old.used_at is not null and new.used_at is distinct from old.used_at)
     or (old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at) then
    raise exception 'a door secret only gains the time it was used and the time it was revoked'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_door_secret_change before insert or update or delete on door_secret
  for each row execute function tg_door_secret_change();

-- A refused redemption is never changed, and is deleted only once it is a day old.
create function tg_door_redemption_refusal_change() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'UPDATE' then
    raise exception 'a refused redemption is appended, never changed' using errcode = '23514';
  end if;
  if old.refused_at > statement_timestamp() - interval '1 day' then
    raise exception 'a refused redemption is kept for a day' using errcode = '23514';
  end if;
  return old;
end $fn$;
create trigger tg_door_redemption_refusal_change before update or delete
  on door_redemption_refusal
  for each row execute function tg_door_redemption_refusal_change();

-- The two global tables' retention, a bounded batch of each at a time, with its owner's rights:
-- the runtime holds no DELETE, and this deletes nothing the triggers above would keep.
do $create$
begin
  execute format($body$
create function %1$I.door_prune(p_batch integer) returns integer
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $fn$
declare
  pruned integer := 0;
  counted integer;
begin
  if p_batch is null or p_batch < 1 or p_batch > 1000 then
    raise exception 'a prune removes 1 to 1000 rows of each table' using errcode = '22023';
  end if;
  delete from %1$I.door_redemption_refusal
   where ctid in (select ctid from %1$I.door_redemption_refusal
                   where refused_at < pg_catalog.statement_timestamp() - interval '1 day'
                   limit p_batch);
  get diagnostics counted = row_count;
  pruned := pruned + counted;
  delete from %1$I.door_secret
   where secret_sha256 in (select secret_sha256 from %1$I.door_secret
                            where expires_at < pg_catalog.statement_timestamp() - interval '30 days'
                            limit p_batch);
  get diagnostics counted = row_count;
  return pruned + counted;
end $fn$
$body$, current_schema());
end $create$;

-- Trigger functions are not executed by name, so nobody is granted them; door_grant_stands is read
-- by the triggers as whoever writes, so it stays executable, and reads only what that writer may.
do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature, p.proname from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('tg_door_grant_revision_binding', 'door_grant_stands',
                         'tg_door_ask_binding', 'tg_door_answer_binding',
                         'tg_door_scoped_insert', 'tg_door_append_only',
                         'tg_door_presence_change', 'tg_door_secret_change',
                         'tg_door_redemption_refusal_change')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    if f.proname <> 'door_grant_stands' then
      execute format('revoke all on function %s from public', f.signature);
    end if;
  end loop;
  execute format('revoke all on function %I.door_prune(integer) from public', current_schema());
end $pin$;

do $$ declare t text; begin
  foreach t in array array['door_grant', 'door_grant_revision', 'door_grant_revocation',
                           'door_presence', 'door_mapping', 'door_declaration', 'door_ask',
                           'door_answer'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- The application appends and reads the workspace tables and updates presence; it appends and reads
-- the two global tables, may change only door_secret's used_at and revoked_at, and prunes through
-- door_prune. Read-only roles read the workspace tables. Provisioning applies the same shape through
-- exulanica.db.roles.
do $$ declare r text; t text; begin
  foreach r in array array['exulanica_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['door_grant', 'door_grant_revision', 'door_grant_revocation',
                               'door_mapping', 'door_declaration', 'door_ask', 'door_answer',
                               'door_redemption_refusal'] loop
        execute format('grant select, insert on %I to %I', t, r);
      end loop;
      execute format('grant select, insert, update on door_presence to %I', r);
      execute format('grant select, insert on door_secret to %I', r);
      execute format('grant update (used_at, revoked_at) on door_secret to %I', r);
      execute format('grant execute on function %I.door_prune(integer) to %I',
                     current_schema(), r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['door_grant', 'door_grant_revision', 'door_grant_revocation',
                               'door_presence', 'door_mapping', 'door_declaration', 'door_ask',
                               'door_answer'] loop
        execute format('grant select on %I to %I', t, r);
      end loop;
    end if;
  end loop;
end $$;

-- A grant's revocation, and a secret's, are withdrawals a restore writes again, so a sealed
-- checkpoint refuses either (0107).
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on door_grant_revocation
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
create trigger tg_sealed_checkpoint_refuses_withdrawals before update of revoked_at on door_secret
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

commit;
