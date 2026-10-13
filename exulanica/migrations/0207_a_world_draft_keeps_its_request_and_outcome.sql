-- World drafts use the normal job lifecycle and retain request/outcome identity through restart.
begin;
select pg_advisory_xact_lock(119622309);

create table world_draft_start (
 workspace_id uuid not null, draft_id uuid not null, request_id uuid not null,
 actor_id uuid not null, job_id uuid not null references job(job_id), world_id text not null,
 guest boolean not null, started_at timestamptz not null default statement_timestamp(),
 primary key(workspace_id,draft_id), unique(workspace_id,actor_id,request_id),
 unique(workspace_id,world_id), check(world_id='world:generated:' || draft_id::text)
);
create table world_draft_request (
 workspace_id uuid not null, draft_id uuid not null,
 terms_sha256 text not null check(terms_sha256 ~ '^[0-9a-f]{64}$'),
 document jsonb not null check(jsonb_typeof(document)='object' and octet_length(document::text)<=131072),
 primary key(workspace_id,draft_id),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id)
);
create table world_draft_input (
 workspace_id uuid not null, draft_id uuid not null, description text not null,
 primary key(workspace_id,draft_id), check(length(description) between 1 and 4096),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id)
);
create table world_draft_bound (
 workspace_id uuid not null, draft_id uuid not null, provider text not null, bound_id uuid not null,
 primary key(workspace_id,draft_id,provider), unique(workspace_id,bound_id),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id)
);
create table world_draft_bound_closed (
 workspace_id uuid not null, draft_id uuid not null, provider text not null,
 primary key(workspace_id,draft_id,provider),
 foreign key(workspace_id,draft_id,provider)
  references world_draft_bound(workspace_id,draft_id,provider)
);
create table world_draft_progress (
 workspace_id uuid not null, draft_id uuid not null, event_seq integer not null check(event_seq>0),
 claim_token uuid not null, document jsonb not null,
 primary key(workspace_id,draft_id,event_seq),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id),
 check(jsonb_typeof(document)='object' and octet_length(document::text)<=262144)
);
create table world_draft_attempt (
 workspace_id uuid not null, draft_id uuid not null, event_seq integer not null check(event_seq>0),
 claim_token uuid not null, document jsonb not null,
 primary key(workspace_id,draft_id,event_seq),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id),
 check(jsonb_typeof(document)='object' and octet_length(document::text)<=65536)
);
create table world_draft_outcome (
 workspace_id uuid not null, draft_id uuid not null, claim_token uuid not null,
 document jsonb not null, document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
 primary key(workspace_id,draft_id),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id),
 check(jsonb_typeof(document)='object' and octet_length(document::text)<=262144),
 check((document->>'document_sha256'=document_sha256) is true)
);

create function tg_world_draft_binding() returns trigger language plpgsql as $fn$
declare s world_draft_start%rowtype; j job%rowtype;
begin
 perform assert_workspace_context(new.workspace_id);
 perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
 if tg_table_name='world_draft_bound_closed' then return new; end if;
 if exists(select 1 from tombstone where workspace_id=new.workspace_id and scope::text='workspace') then
  raise exception 'an erased workspace holds no new world draft' using errcode='23514';
 end if;
 if tg_table_name='world_draft_start' then
  if exists(select 1 from world_erasure where workspace_id=new.workspace_id and world_id=new.world_id) then
   raise exception 'a removed world cannot be drafted again' using errcode='23514';
  end if;
  if not exists(select 1 from job where workspace_id=new.workspace_id and job_id=new.job_id
   and kind='world_draft' and payload=jsonb_build_object('draft_id',new.draft_id::text,
                                                       'world_id',new.world_id)) then
   raise exception 'a draft names its own workspace job' using errcode='23514';
  end if;
 else
  select * into s from world_draft_start where workspace_id=new.workspace_id and draft_id=new.draft_id;
  select * into j from job where workspace_id=new.workspace_id and job_id=s.job_id;
  if s.draft_id is null or j.job_id is null then
   raise exception 'a world draft has its start and job' using errcode='23514';
  end if;
  if tg_table_name in ('world_draft_request','world_draft_input','world_draft_bound') then
   if j.state<>'queued' or j.attempts<>0 then
    raise exception 'a started draft accepts no new request or bound' using errcode='23514';
   end if;
  elsif tg_table_name='world_draft_outcome' and new.document->>'state'='ready' and not exists(
    select 1 from saved_world_entry e where e.workspace_id=new.workspace_id
      and e.world_id=s.world_id and e.entry_id::text=new.document->>'entry_id') then
   raise exception 'a ready world draft names its saved world' using errcode='23514';
  elsif j.state<>'running' or j.claim_token is distinct from new.claim_token
        or j.lease_expires_at<=statement_timestamp() then
   raise exception 'a world draft record belongs to its live claim' using errcode='23514';
  end if;
  if tg_table_name='world_draft_outcome' then
   if j.state<>'running' or j.claim_token is distinct from new.claim_token
     or j.lease_expires_at<=statement_timestamp() then
    raise exception 'a world draft outcome belongs to its live claim' using errcode='23514';
   end if;
  end if;
 end if;
 return new;
end $fn$;
create function tg_world_draft_immutable() returns trigger language plpgsql as $fn$
begin
 if tg_op='DELETE' and current_user='exulanica_definer' then return old; end if;
 raise exception 'world draft records are immutable' using errcode='23514';
end $fn$;

do $tables$ declare t text; begin
 foreach t in array array['world_draft_start','world_draft_request','world_draft_input',
   'world_draft_bound','world_draft_bound_closed','world_draft_progress',
   'world_draft_attempt','world_draft_outcome'] loop
  execute format('alter table %I enable row level security',t);
  execute format('alter table %I force row level security',t);
  execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
    'with check(workspace_id=current_workspace())',t);
  execute format('create trigger tg_world_draft_binding before insert on %I '
    'for each row execute function tg_world_draft_binding()',t);
  execute format('create trigger tg_world_draft_immutable before update or delete on %I '
    'for each row execute function tg_world_draft_immutable()',t);
 end loop;
end $tables$;

-- Only the non-login definer can aggregate another workspace's starts, and only for the
-- authenticated actor bound to this submit transaction. Runtime/read-only rows stay scoped.
create policy person_start_budget on world_draft_start for select to exulanica_definer
 using(actor_id=nullif(current_setting('exulanica.world_draft_actor',true),'')::uuid);

-- The person quota is submit-only. No aggregate is exposed to a reader. Session.actor and
-- deployment policy values are bound by the API on its trusted workspace connection, never
-- taken from the request body; the trigger also refuses missing/mismatched actor context.
create function tg_world_draft_person_quota() returns trigger
language plpgsql security definer as $fn$
declare maximum integer; already bigint; native_kinds integer; retry integer;
begin
 perform assert_workspace_context(new.workspace_id);
 if current_setting('exulanica.world_draft_actor',true) is distinct from new.actor_id::text then
  raise exception 'a world draft starts for its authenticated actor' using errcode='23514';
 end if;
 maximum:=nullif(current_setting('exulanica.world_draft_starts_maximum',true),'')::integer;
 native_kinds:=coalesce(nullif(current_setting('exulanica.world_draft_kind_starts',true),'')::integer,0);
 if maximum is null or maximum<1 or native_kinds<0 then
  raise exception 'a world draft has a valid deployment start limit' using errcode='23514';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('world-draft-person:' || new.actor_id::text,0));
 select count(*),greatest(1,ceil(extract(epoch from min(started_at)+interval '1 hour'
     -statement_timestamp()))::integer) into already,retry
 from world_draft_start where actor_id=new.actor_id
   and started_at>statement_timestamp()-interval '1 hour';
 if already+native_kinds>=maximum then
  raise exception 'kind_draft_limit' using errcode='P0001',
   detail=jsonb_build_object('retry_after_seconds',coalesce(retry,60))::text;
 end if;
 return new;
end $fn$;
create trigger tg_world_draft_person_quota before insert on world_draft_start
 for each row execute function tg_world_draft_person_quota();

-- Saving through the native creation authority is fenced at the actual SQL insertion,
-- including a composer that ran past its lease while its opening transaction stayed open.
create function tg_world_draft_save_claim() returns trigger language plpgsql as $fn$
declare s world_draft_start%rowtype; j job%rowtype; made_by uuid;
begin
 if tg_table_name<>'world_identity' and
    coalesce(current_setting('exulanica.world_draft_claim',true),'')='' then return new; end if;
 select * into s from world_draft_start where workspace_id=new.workspace_id and world_id=new.world_id;
 if s.draft_id is null then return new; end if;
 perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
 select * into j from job where job_id=s.job_id and workspace_id=new.workspace_id for update;
 if tg_table_name='world_identity' then made_by:=new.created_by;
 elsif tg_table_name='world_style_version' then
  made_by:=case when new.revision=0 then s.actor_id else new.actor end;
 else made_by:=new.actor; end if;
 if j.state<>'running' or j.claim_token::text is distinct from
     current_setting('exulanica.world_draft_claim',true)
    or j.lease_expires_at<=clock_timestamp() or made_by is distinct from s.actor_id then
  raise exception 'a drafted world is saved under its live claim' using errcode='23514';
 end if;
 return new;
end $fn$;
create trigger tg_world_draft_save_claim before insert on world_identity
 for each row execute function tg_world_draft_save_claim();
create trigger tg_world_draft_style_proposal_claim before insert on world_style_proposal
 for each row execute function tg_world_draft_save_claim();
create trigger tg_world_draft_style_version_claim before insert on world_style_version
 for each row execute function tg_world_draft_save_claim();

-- A terminal result forgets the full sentence, as the native holder does. This function grants
-- no other deletion and only operates after an outcome under the current workspace exists.
create function world_draft_forget_input(p_draft uuid) returns void
language plpgsql security definer as $fn$
begin
 if exists(select 1 from world_draft_outcome where workspace_id=current_workspace()
             and draft_id=p_draft) then
  delete from world_draft_input where workspace_id=current_workspace() and draft_id=p_draft;
 end if;
end $fn$;

-- Financial identities and start timing contain no content fingerprint and remain for cleanup
-- and starts-per-hour accounting. Typed content, progress and outcome are deleted together.
create function tg_world_draft_erasure() returns trigger
language plpgsql security definer as $fn$
declare w uuid; wanted text;
begin
 w:=new.workspace_id;
 if tg_table_name='tombstone' then
  if new.scope::text<>'workspace' then return new; end if;
  wanted:=null;
 else wanted:=new.world_id; end if;
 perform assert_workspace_context(w);
 perform pg_advisory_xact_lock(hashtextextended(w::text,880024));
 update job j set state=case when state in ('queued','running') then 'cancelled' else state end,
  payload='{}',completed_at=coalesce(completed_at,statement_timestamp()),
  claim_token=null,lease_expires_at=null,claimed_by=null,
  failure_class='world_draft_erased',last_error='world_draft_bound_close_due'
 where j.workspace_id=w and j.kind='world_draft' and exists(
  select 1 from world_draft_start s where s.workspace_id=w and s.job_id=j.job_id
   and (wanted is null or s.world_id=wanted));
 delete from world_draft_outcome d using world_draft_start s
  where d.workspace_id=w and s.workspace_id=w and s.draft_id=d.draft_id
    and (wanted is null or s.world_id=wanted);
 delete from world_draft_attempt d using world_draft_start s
  where d.workspace_id=w and s.workspace_id=w and s.draft_id=d.draft_id
    and (wanted is null or s.world_id=wanted);
 delete from world_draft_progress d using world_draft_start s
  where d.workspace_id=w and s.workspace_id=w and s.draft_id=d.draft_id
    and (wanted is null or s.world_id=wanted);
 delete from world_draft_input d using world_draft_start s
  where d.workspace_id=w and s.workspace_id=w and s.draft_id=d.draft_id
    and (wanted is null or s.world_id=wanted);
 delete from world_draft_request d using world_draft_start s
  where d.workspace_id=w and s.workspace_id=w and s.draft_id=d.draft_id
    and (wanted is null or s.world_id=wanted);
 return new;
end $fn$;
create trigger tg_world_draft_workspace_erasure after insert on tombstone
 for each row execute function tg_world_draft_erasure();
create trigger tg_world_draft_world_erasure before insert on world_erasure
 for each row execute function tg_world_draft_erasure();

do $rights$ declare t text; begin
 execute format('alter function world_draft_forget_input(uuid) '
   'set search_path=pg_catalog,%I,pg_temp',current_schema());
 execute format('alter function tg_world_draft_person_quota() '
   'set search_path=pg_catalog,%I,pg_temp',current_schema());
 execute format('alter function tg_world_draft_erasure() '
   'set search_path=pg_catalog,%I,pg_temp',current_schema());
 revoke all on function world_draft_forget_input(uuid),tg_world_draft_erasure(),
   tg_world_draft_person_quota() from public;
 alter function world_draft_forget_input(uuid) owner to exulanica_definer;
 alter function tg_world_draft_person_quota() owner to exulanica_definer;
 alter function tg_world_draft_erasure() owner to exulanica_definer;
 grant select on world_draft_start to exulanica_definer;
 foreach t in array array['world_draft_request','world_draft_input',
   'world_draft_progress','world_draft_attempt','world_draft_outcome'] loop
  execute format('grant select,delete on %I to exulanica_definer',t);
 end loop;
 grant select on job to exulanica_definer;
 grant update(state,payload,completed_at,claim_token,lease_expires_at,claimed_by,
              failure_class,last_error) on job to exulanica_definer;
end $rights$;
commit;
