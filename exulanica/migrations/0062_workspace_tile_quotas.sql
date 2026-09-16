-- Per-workspace tile quotas: the ceiling an on-demand tile route is charged against.
--
-- No tile route exists when this lands, deliberately. The ceiling comes first, and a route whose
-- declaration requires tiles.materialise is charged here before it runs, by
-- exulanica.api.dependencies.authorise_route. A workspace with no row may materialise nothing.
--
-- Both counters are integers. tiles_used only rises; the operator raises tiles_limit instead of
-- refunding, and a limit below what is already used is refused by the check. declared_at is audit
-- only and is never a digest input.
begin;
select pg_advisory_xact_lock(119622309);

create table workspace_tile_quota (
  workspace_id uuid primary key,
  tiles_limit bigint not null check(tiles_limit>=0),
  tiles_used bigint not null default 0 check(tiles_used>=0),
  declared_by uuid not null,
  declared_at timestamptz not null default statement_timestamp(),
  constraint workspace_tile_quota_within_limit check(tiles_used<=tiles_limit)
);

create function tg_workspace_tile_quota_guard() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op='INSERT' then
    if new.tiles_used<>0 then
      raise exception 'a tile quota starts with nothing used' using errcode='23514';
    end if;
    return new;
  end if;
  if new.workspace_id is distinct from old.workspace_id then
    raise exception 'a tile quota belongs to one workspace for good' using errcode='23514';
  end if;
  if new.tiles_used<old.tiles_used then
    raise exception 'tiles used never falls; raise the ceiling instead' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger workspace_tile_quota_guard
before insert or update on workspace_tile_quota
for each row execute function tg_workspace_tile_quota_guard();

do $$ declare t text; begin
  foreach t in array array['workspace_tile_quota'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t
    );
  end loop;
end $$;

commit;
