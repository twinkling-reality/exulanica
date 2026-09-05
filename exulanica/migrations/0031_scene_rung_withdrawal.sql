-- 0031_scene_rung_withdrawal.sql
-- A scene rung claim is a fact about its complete member set. When a capture, interval, or
-- workspace tombstone reaches that set, retain an explicit retraction and change the claim's
-- durable status. Read filters still fail closed, but no withdrawn claim remains labelled active.

begin;

select pg_advisory_xact_lock(119622309);

create function retract_scene_rungs_for_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope not in ('capture', 'interval', 'workspace') then
    return new;
  end if;

  insert into retraction (workspace_id, assertion_id, retracted_by, reason, retracted_at)
  select a.workspace_id, a.assertion_id, new.requested_by,
         'scene membership withdrawn by tombstone ' || new.tombstone_id::text,
         new.effective_at
    from assertion a
    join predicate p on p.predicate_id = a.predicate_id
    join reconstruction_scene s
      on s.workspace_id = a.workspace_id
     and a.subject_ref ->> 'type' = 'scene'
     and a.subject_ref ->> 'id' = s.scene_id::text
   where a.workspace_id = new.workspace_id
     and a.status = 'active'
     and p.key = 'reconstruction_scene_rung_is'
     and (new.scope = 'workspace' or exists (
       select 1
         from reconstruction_scene_member m
        where m.workspace_id = s.workspace_id
          and m.scene_id = s.scene_id
          and m.capture_id = new.capture_id));

  update assertion a
     set status = 'retracted'
    from predicate p, reconstruction_scene s
   where p.predicate_id = a.predicate_id
     and p.key = 'reconstruction_scene_rung_is'
     and s.workspace_id = a.workspace_id
     and a.subject_ref ->> 'type' = 'scene'
     and a.subject_ref ->> 'id' = s.scene_id::text
     and a.workspace_id = new.workspace_id
     and a.status = 'active'
     and (new.scope = 'workspace' or exists (
       select 1
         from reconstruction_scene_member m
        where m.workspace_id = s.workspace_id
          and m.scene_id = s.scene_id
          and m.capture_id = new.capture_id));

  return new;
end $fn$;

create trigger tg_tombstone_retracts_scene_rungs
  after insert on tombstone
  for each row execute function retract_scene_rungs_for_tombstone();

-- Repair claims hidden by tombstones written before this migration. The earliest relevant
-- capture, interval, or workspace tombstone supplies the durable retraction actor and time. Set
-- each workspace explicitly because assertion lifecycle triggers fail closed without that scope.
do $fn$
declare
  v_workspace uuid;
begin
  for v_workspace in
    select distinct a.workspace_id
      from assertion a
      join predicate p on p.predicate_id = a.predicate_id
      join reconstruction_scene s
        on s.workspace_id = a.workspace_id
       and a.subject_ref ->> 'type' = 'scene'
       and a.subject_ref ->> 'id' = s.scene_id::text
     where a.status = 'active'
       and p.key = 'reconstruction_scene_rung_is'
       and exists (
         select 1
           from tombstone t
          where t.workspace_id = s.workspace_id
            and t.scope in ('capture', 'interval', 'workspace')
            and (t.scope = 'workspace' or exists (
              select 1
                from reconstruction_scene_member m
               where m.workspace_id = s.workspace_id
                 and m.scene_id = s.scene_id
                 and m.capture_id = t.capture_id)))
  loop
    perform set_config('exulanica.workspace_id', v_workspace::text, true);

    with targets as (
      select distinct on (a.assertion_id)
             a.workspace_id, a.assertion_id, t.requested_by, t.effective_at, t.tombstone_id
        from assertion a
        join predicate p on p.predicate_id = a.predicate_id
        join reconstruction_scene s
          on s.workspace_id = a.workspace_id
         and a.subject_ref ->> 'type' = 'scene'
         and a.subject_ref ->> 'id' = s.scene_id::text
        join tombstone t
          on t.workspace_id = s.workspace_id
         and t.scope in ('capture', 'interval', 'workspace')
         and (t.scope = 'workspace' or exists (
           select 1
             from reconstruction_scene_member m
            where m.workspace_id = s.workspace_id
              and m.scene_id = s.scene_id
              and m.capture_id = t.capture_id))
       where a.workspace_id = v_workspace
         and a.status = 'active'
         and p.key = 'reconstruction_scene_rung_is'
       order by a.assertion_id, t.effective_at, t.tombstone_id
    )
    insert into retraction (workspace_id, assertion_id, retracted_by, reason, retracted_at)
    select workspace_id, assertion_id, requested_by,
           'scene membership withdrawn by tombstone ' || tombstone_id::text,
           effective_at
      from targets;

    update assertion a
       set status = 'retracted'
      from predicate p, reconstruction_scene s
     where p.predicate_id = a.predicate_id
       and p.key = 'reconstruction_scene_rung_is'
       and s.workspace_id = a.workspace_id
       and a.subject_ref ->> 'type' = 'scene'
       and a.subject_ref ->> 'id' = s.scene_id::text
       and a.workspace_id = v_workspace
       and a.status = 'active'
       and exists (
         select 1
           from tombstone t
          where t.workspace_id = s.workspace_id
            and t.scope in ('capture', 'interval', 'workspace')
            and (t.scope = 'workspace' or exists (
              select 1
                from reconstruction_scene_member m
               where m.workspace_id = s.workspace_id
                 and m.scene_id = s.scene_id
                 and m.capture_id = t.capture_id)));
  end loop;
end $fn$;

commit;
