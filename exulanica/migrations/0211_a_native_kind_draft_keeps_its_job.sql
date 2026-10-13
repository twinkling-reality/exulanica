-- Native kind drafts keep their request and outcome under the existing job authority.
begin;
select pg_advisory_xact_lock(119622309);

create table kind_draft_start (
 workspace_id uuid not null, draft_id uuid not null, actor_id uuid not null,
 job_id uuid not null unique references job(job_id), guest boolean not null,
 started_at timestamptz not null default statement_timestamp(),
 deadline_seconds integer not null check(deadline_seconds between 1 and 86400),
 manifest_sha256 text not null check(manifest_sha256 ~ '^[0-9a-f]{64}$'),
 prompt_version text not null check(length(prompt_version) between 1 and 128),
 primary key(workspace_id,draft_id)
);
create table kind_draft_input (
 workspace_id uuid not null, draft_id uuid not null, description text not null,
 primary key(workspace_id,draft_id), check(length(description) between 1 and 4096),
 foreign key(workspace_id,draft_id) references kind_draft_start(workspace_id,draft_id)
);
create table kind_draft_attempt (
 workspace_id uuid not null, draft_id uuid not null, event_seq integer not null check(event_seq>0),
 claim_token uuid not null, document jsonb not null,
 primary key(workspace_id,draft_id,event_seq),
 foreign key(workspace_id,draft_id) references kind_draft_start(workspace_id,draft_id),
 check(jsonb_typeof(document)='object' and octet_length(document::text)<=65536)
);
create table kind_draft_outcome (
 workspace_id uuid not null, draft_id uuid not null, claim_token uuid not null,
 document jsonb not null, completed_at timestamptz not null default statement_timestamp(),
 primary key(workspace_id,draft_id),
 foreign key(workspace_id,draft_id) references kind_draft_start(workspace_id,draft_id),
 check(jsonb_typeof(document)='object' and octet_length(document::text)<=262144),
 check(document->>'state' in ('ready','refused'))
);

create function tg_kind_draft_binding() returns trigger language plpgsql as $fn$
declare s kind_draft_start%rowtype; j job%rowtype;
begin
 perform assert_workspace_context(new.workspace_id);
 perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
 if exists(select 1 from tombstone where workspace_id=new.workspace_id and scope::text='workspace') then
  raise exception 'an erased workspace holds no kind draft' using errcode='23514';
 end if;
 if tg_table_name='kind_draft_start' then
  if exists(select 1 from world_kind_erasure where workspace_id=new.workspace_id
   and kind_draft_id=new.draft_id) then
   raise exception 'an erased kind draft cannot start again' using errcode='23514';
  end if;
  select * into j from job where job_id=new.job_id and workspace_id=new.workspace_id;
  if j.kind is distinct from 'kind_draft' or j.state<>'queued' or j.attempts<>0
   or j.payload is distinct from jsonb_build_object('draft_id',new.draft_id::text) then
   raise exception 'a kind draft names its own unstarted job' using errcode='23514';
  end if;
 else
  select * into s from kind_draft_start where workspace_id=new.workspace_id and draft_id=new.draft_id;
  select * into j from job where workspace_id=new.workspace_id and job_id=s.job_id for update;
  if j.job_id is null then raise exception 'a draft has a start and job' using errcode='23514'; end if;
  if tg_table_name='kind_draft_input' then
   if j.state<>'queued' or j.attempts<>0 then
    raise exception 'a started draft accepts no input' using errcode='23514';
   end if;
  else
   if j.state<>'running' or j.claim_token is distinct from new.claim_token
    or j.lease_expires_at is null or j.lease_expires_at<=clock_timestamp() then
    raise exception 'a kind draft record belongs to its live claim' using errcode='23514';
   end if;
   if tg_table_name='kind_draft_outcome' and new.document->>'state'='ready' and not exists(
     select 1 from world_kind_version k where k.workspace_id=new.workspace_id
      and k.kind=new.document->>'kind' and k.version=(new.document->>'version')::integer
      and k.document_sha256=new.document->>'kind_sha256' and k.created_by=s.actor_id) then
    raise exception 'a ready draft names its kept kind' using errcode='23514';
   end if;
  end if;
 end if;
 return new;
end $fn$;

do $tables$ declare t text; begin
 foreach t in array array['kind_draft_start','kind_draft_input','kind_draft_attempt','kind_draft_outcome'] loop
  execute format('alter table %I enable row level security',t);
  execute format('alter table %I force row level security',t);
  execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
   'with check(workspace_id=current_workspace())',t);
  execute format('create trigger tg_kind_draft_binding before insert on %I '
   'for each row execute function tg_kind_draft_binding()',t);
  execute format('create trigger tg_kind_draft_immutable before update or delete on %I '
   'for each row execute function tg_world_draft_immutable()',t);
 end loop;
end $tables$;
create policy person_start_budget on kind_draft_start for select to exulanica_definer
 using(actor_id=nullif(current_setting('exulanica.world_draft_actor',true),'')::uuid);

-- Aggregate only the authenticated actor's starts. No foreign-workspace identity is returned.
create function draft_person_allowance(p_actor uuid,p_maximum integer) returns jsonb
language plpgsql security definer as $fn$
declare n bigint; retry integer;
begin
 if current_setting('exulanica.world_draft_actor',true) is distinct from p_actor::text
  or p_maximum<1 then raise exception 'invalid draft actor or limit' using errcode='23514'; end if;
 select count(*),greatest(1,ceil(extract(epoch from min(started_at)+interval '1 hour'
   -statement_timestamp()))::integer) into n,retry from (
  select started_at from world_draft_start where actor_id=p_actor
  union all select started_at from kind_draft_start where actor_id=p_actor
 ) s where started_at>statement_timestamp()-interval '1 hour';
 return jsonb_build_object('left',greatest(0,p_maximum-n),
  'retry_after_seconds',case when n>=p_maximum then coalesce(retry,60) else null end);
end $fn$;

-- Both purposes enter the same workspace and actor gates. The process capacity is separate.
create or replace function tg_world_draft_person_quota() returns trigger
language plpgsql security definer as $fn$
declare maximum integer; workspace_maximum integer; allowance jsonb; active bigint;
begin
 perform assert_workspace_context(new.workspace_id);
 perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
 if current_setting('exulanica.world_draft_actor',true) is distinct from new.actor_id::text then
  raise exception 'a draft starts for its authenticated actor' using errcode='23514';
 end if;
 maximum:=nullif(current_setting('exulanica.world_draft_starts_maximum',true),'')::integer;
 workspace_maximum:=coalesce(nullif(current_setting('exulanica.draft_workspace_maximum',true),'')::integer,1);
 if maximum is null or maximum<1 or workspace_maximum<1 then
  raise exception 'a draft has valid deployment limits' using errcode='23514';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('world-draft-person:' || new.actor_id::text,0));
 select count(*) into active from (
  select job_id from world_draft_start where workspace_id=new.workspace_id
  union all select job_id from kind_draft_start where workspace_id=new.workspace_id
 ) s join job j using(job_id) where j.state in ('queued','running');
 if active>=workspace_maximum then raise exception 'kind_draft_busy' using errcode='P0001'; end if;
 allowance:=draft_person_allowance(new.actor_id,maximum);
 if (allowance->>'left')::integer=0 then
  raise exception 'kind_draft_limit' using errcode='P0001',detail=allowance::text;
 end if;
 return new;
end $fn$;
create trigger tg_kind_draft_person_quota before insert on kind_draft_start
 for each row execute function tg_world_draft_person_quota();

alter table world_kind_version add column kind_draft_id uuid;

create function tg_kind_draft_save_claim() returns trigger language plpgsql as $fn$
declare token uuid; s kind_draft_start%rowtype; j job%rowtype;
begin
 token:=nullif(current_setting('exulanica.kind_draft_claim',true),'')::uuid;
 if token is null then
  if new.kind_draft_id is not null then
   raise exception 'a kind draft identity requires a live claim' using errcode='23514';
  end if;
  return new;
 end if;
 perform assert_workspace_context(new.workspace_id);
 perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
 select * into j from job where workspace_id=new.workspace_id and claim_token=token for update;
 select * into s from kind_draft_start where workspace_id=new.workspace_id and job_id=j.job_id;
 if s.job_id is null or j.state<>'running' or j.lease_expires_at is null
  or j.lease_expires_at<=clock_timestamp() or new.created_by is distinct from s.actor_id then
  raise exception 'a kind save belongs to its live draft claim' using errcode='23514';
 end if;
 if new.kind_draft_id is not null and new.kind_draft_id<>s.draft_id then
  raise exception 'a kind save names its own draft' using errcode='23514';
 end if;
 new.kind_draft_id:=s.draft_id;
 return new;
end $fn$;
create trigger tg_kind_draft_save_claim before insert on world_kind_version
 for each row execute function tg_kind_draft_save_claim();

create function kind_draft_forget_input(p_draft uuid) returns void
language plpgsql security definer as $fn$
begin
 perform assert_workspace_context(current_workspace());
 perform pg_advisory_xact_lock(hashtextextended(current_workspace()::text,880024));
 if exists(select 1 from kind_draft_start s join job j using(job_id)
   where s.workspace_id=current_workspace() and s.draft_id=p_draft
    and j.state in ('done','failed','cancelled')) then
  delete from kind_draft_input where workspace_id=current_workspace() and draft_id=p_draft;
 end if;
end $fn$;

create function kind_draft_prune() returns void language plpgsql security definer as $fn$
begin
 perform assert_workspace_context(current_workspace());
 perform pg_advisory_xact_lock(hashtextextended(current_workspace()::text,880024));
 delete from kind_draft_input i using kind_draft_start s,job j
  where i.workspace_id=current_workspace() and i.workspace_id=s.workspace_id and i.draft_id=s.draft_id
   and s.job_id=j.job_id and j.state in ('done','failed','cancelled');
 delete from kind_draft_attempt a using kind_draft_start s,job j
  where a.workspace_id=current_workspace() and a.workspace_id=s.workspace_id and a.draft_id=s.draft_id
   and s.job_id=j.job_id and j.completed_at<statement_timestamp()-interval '1 hour';
 delete from kind_draft_outcome o where o.workspace_id=current_workspace()
  and o.completed_at<statement_timestamp()-interval '1 hour';
end $fn$;

alter table world_kind_erasure add column kind_draft_id uuid;

create function tg_kind_draft_erasure() returns trigger language plpgsql security definer as $fn$
declare w uuid; ids uuid[]; actual_draft uuid;
begin
 w:=new.workspace_id;
 if tg_table_name='tombstone' then
  if new.scope::text<>'workspace' then return new; end if;
 end if;
 perform assert_workspace_context(w);
 perform pg_advisory_xact_lock(hashtextextended(w::text,880024));
 if tg_table_name='tombstone' then
  select array_agg(draft_id) into ids from kind_draft_start where workspace_id=w;
 else
  select kind_draft_id into actual_draft from world_kind_version where workspace_id=w
   and document_sha256=new.document_sha256;
  if new.kind_draft_id is not null and new.kind_draft_id is distinct from actual_draft
   and not exists(select 1 from restore_control where state='replaying') then
   raise exception 'kind erasure draft provenance requires its outcome or sealed replay'
    using errcode='23514';
  end if;
  if actual_draft is not null then new.kind_draft_id:=actual_draft; end if;
  ids:=array[new.kind_draft_id];
 end if;
 update job j set state='cancelled',payload='{}',completed_at=coalesce(completed_at,clock_timestamp()),
  claim_token=null,lease_expires_at=null,claimed_by=null,failure_class='kind_draft_erased',last_error=null
 where j.workspace_id=w and exists(select 1 from kind_draft_start s
  where s.workspace_id=w and s.job_id=j.job_id and s.draft_id=any(ids));
 delete from kind_draft_outcome where workspace_id=w and draft_id=any(ids);
 delete from kind_draft_attempt where workspace_id=w and draft_id=any(ids);
 delete from kind_draft_input where workspace_id=w and draft_id=any(ids);
 return new;
end $fn$;
create trigger tg_kind_draft_workspace_erasure after insert on tombstone
 for each row execute function tg_kind_draft_erasure();
create trigger tg_kind_draft_kind_erasure before insert on world_kind_erasure
 for each row execute function tg_kind_draft_erasure();

do $rights$ declare t text; f text; begin
 foreach f in array array['draft_person_allowance(uuid,integer)','tg_world_draft_person_quota()',
  'kind_draft_forget_input(uuid)','kind_draft_prune()','tg_kind_draft_erasure()'] loop
  execute format('alter function %s set search_path=pg_catalog,%I,pg_temp',f,current_schema());
  execute format('revoke all on function %s from public',f);
  execute format('alter function %s owner to exulanica_definer',f);
 end loop;
 grant select on kind_draft_start to exulanica_definer;
 foreach t in array array['kind_draft_input','kind_draft_attempt','kind_draft_outcome'] loop
  execute format('grant select,delete on %I to exulanica_definer',t);
 end loop;
end $rights$;
commit;
