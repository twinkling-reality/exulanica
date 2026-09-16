
begin;
select pg_advisory_xact_lock(119622309);

-- Public reusable assets have immutable import receipts separate from current availability.
-- No FK deletion cascade: withdrawing an asset must not erase its original provenance.
create table world_reviewed_asset_import (
  asset_key text primary key check (asset_key ~ '^[a-z][a-z0-9.-]*$'),
  content_sha256 text not null unique check (content_sha256 ~ '^[0-9a-f]{64}$'),
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  imported_at timestamptz not null default now()
);

create function tg_reviewed_asset_import_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'reviewed asset import receipts are append-only' using errcode='23514';
end;
$fn$;
create trigger reviewed_asset_import_append_only before update or delete
on world_reviewed_asset_import for each row execute function tg_reviewed_asset_import_append_only();

commit;
