-- 0222: A world made from a person's words keeps the sentence it was made from, with that world.
--
-- 0207 forgets a draft's sentence (world_draft_input) once the draft ends. A draft that made its
-- world now keeps the sentence first, with that world, so the world's History can quote back what
-- the person typed to make it. It is the person's own words: kept per workspace, read by that
-- workspace alone, erased whenever the world is erased or the workspace is withdrawn (restore
-- replays the tombstone), and never part of an export or a world's project. A draft that never
-- became a world forgets its sentence as before.
begin;
select pg_advisory_xact_lock(119622309);

create table world_made_from (
 workspace_id uuid not null, draft_id uuid not null, world_id text not null,
 sentence text not null check(length(sentence) between 1 and 4096),
 kept_at timestamptz not null default statement_timestamp(),
 primary key(workspace_id,draft_id), unique(workspace_id,world_id),
 check(world_id='world:generated:' || draft_id::text),
 foreign key(workspace_id,draft_id) references world_draft_start(workspace_id,draft_id)
);
alter table world_made_from enable row level security;
alter table world_made_from force row level security;
create policy ws_isolation on world_made_from using(workspace_id=current_workspace())
 with check(workspace_id=current_workspace());
-- Written once by the definer; never updated; deleted only by the definer's erasure.
create trigger tg_world_made_from_immutable before update or delete on world_made_from
 for each row execute function tg_world_draft_immutable();

-- Called as a draft that made its world ends, just before world_draft_forget_input: copies the
-- sentence of a ready draft of the current workspace, and nothing of any other draft.
create function world_draft_keep_sentence(p_draft uuid) returns void
language plpgsql security definer as $fn$
begin
 insert into world_made_from(workspace_id,draft_id,world_id,sentence)
 select s.workspace_id,s.draft_id,s.world_id,i.description
 from world_draft_start s
 join world_draft_input i on i.workspace_id=s.workspace_id and i.draft_id=s.draft_id
 join world_draft_outcome o on o.workspace_id=s.workspace_id and o.draft_id=s.draft_id
 where s.workspace_id=current_workspace() and s.draft_id=p_draft
   and o.document->>'state'='ready'
 on conflict do nothing;
end $fn$;

-- The world's erasure (world_erasure) takes that world's sentence; a workspace tombstone takes
-- every one of the workspace.
create function tg_world_made_from_erasure() returns trigger
language plpgsql security definer as $fn$
declare w uuid; wanted text;
begin
 w:=new.workspace_id;
 if tg_table_name='tombstone' then
  if new.scope::text<>'workspace' then return new; end if;
  wanted:=null;
 else wanted:=new.world_id; end if;
 perform assert_workspace_context(w);
 delete from world_made_from where workspace_id=w and (wanted is null or world_id=wanted);
 return new;
end $fn$;
create trigger tg_world_made_from_workspace_erasure after insert on tombstone
 for each row execute function tg_world_made_from_erasure();
create trigger tg_world_made_from_world_erasure before insert on world_erasure
 for each row execute function tg_world_made_from_erasure();

do $rights$ begin
 execute format('alter function world_draft_keep_sentence(uuid) '
   'set search_path=pg_catalog,%I,pg_temp',current_schema());
 execute format('alter function tg_world_made_from_erasure() '
   'set search_path=pg_catalog,%I,pg_temp',current_schema());
 revoke all on function world_draft_keep_sentence(uuid),tg_world_made_from_erasure() from public;
 alter function world_draft_keep_sentence(uuid) owner to exulanica_definer;
 alter function tg_world_made_from_erasure() owner to exulanica_definer;
 grant select,insert,delete on world_made_from to exulanica_definer;
end $rights$;
commit;
