-- Route permission refusals: the durable record behind the route permission floor.
--
-- What a route requires is declared once, in exulanica/api/permissions.py, and what a token may
-- do is part of its grant. Neither is data a workspace owns, so neither is stored here. What is
-- stored is the one fact the floor produces at run time: a credential for this workspace asked
-- for a route its grant does not cover. One row per actor and route, with a count, so a
-- credential hammering a route it may not call grows a number rather than a table.
--
-- The trigger owns both timestamps, so a caller cannot backdate a sighting, and nothing here is a
-- digest input. The permission list is closed by a check that names the same vocabulary as
-- exulanica.api.permissions.Permission; tests/test_route_permissions.py fails when they differ.
begin;
select pg_advisory_xact_lock(119622309);

create table route_permission_refusal (
  workspace_id uuid not null,
  actor uuid not null,
  http_method text not null check(http_method in ('GET','POST','PUT','PATCH','DELETE')),
  route_path text not null
    check(length(route_path)<=300 and route_path ~ '^/[A-Za-z0-9_./{}-]*$'),
  missing_permissions text[] not null check(
    array_ndims(missing_permissions)=1
    and cardinality(missing_permissions) between 1 and 14
    and array_position(missing_permissions, null) is null
    and missing_permissions <@ array[
      'admission.read','admission.write','consent.read','consent.write','deletion.write',
      'intake.write','library.read','library.write','model.invoke','operations.read',
      'operations.write','tiles.materialise','world.read','world.write'
    ]::text[]
  ),
  refusals bigint not null default 1 check(refusals>=1),
  first_refused_at timestamptz not null default statement_timestamp(),
  last_refused_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,actor,http_method,route_path)
);

create function tg_route_permission_refusal_guard() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op='INSERT' then
    if new.refusals<>1 then
      raise exception 'a refusal record starts at one refusal' using errcode='23514';
    end if;
    new.first_refused_at := statement_timestamp();
    new.last_refused_at := new.first_refused_at;
    return new;
  end if;
  if (new.workspace_id,new.actor,new.http_method,new.route_path,new.first_refused_at)
     is distinct from
     (old.workspace_id,old.actor,old.http_method,old.route_path,old.first_refused_at)
  then
    raise exception 'a refusal record keeps its identity and its first sighting'
      using errcode='23514';
  end if;
  if new.refusals<>old.refusals+1 then
    raise exception 'a refusal count rises by exactly one per refusal' using errcode='23514';
  end if;
  new.last_refused_at := greatest(old.last_refused_at, statement_timestamp());
  return new;
end $fn$;
create trigger route_permission_refusal_guard
before insert or update on route_permission_refusal
for each row execute function tg_route_permission_refusal_guard();

do $$ declare t text; begin
  foreach t in array array['route_permission_refusal'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t
    );
  end loop;
end $$;

commit;
