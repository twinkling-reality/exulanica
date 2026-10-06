-- 0140_a_world_kind_is_kept_in_its_workspace.sql
-- A world kind a workspace holds is kept as the document it was admitted as, and a world made from
-- a world kind keeps the receipt that says how.
--
-- world_kind_version holds a workspace's own world kinds (exulanica.world-kind/v1): a kind a
-- creator uploaded or a model drafted and the person accepted, each version once, with its
-- document, the digest of its canonical JSON, its origin and the validation report its sample
-- worlds passed (exulanica.world-kind-validation/v1, verdict passed). A version names itself: its
-- document's kind, version and origin are the row's own. A version is appended once and never
-- changed or deleted, with the refusal 0029 gives every receipt; an edit is a new version.
-- Row-level security keeps it inside its workspace. The kinds the product ships are files under
-- assets/catalogs/world-kinds and are not rows here.
--
-- world_generation_receipt (0118) also holds the receipt of a world made from a world kind by the
-- site grammar: the same profile, naming its composer (site-plan), carrying the whole kind
-- document it was made from and the values it was made with, its seed and its output digest, and
-- no tiles, because a site world is drawn from its records and never baked. A town's receipt is
-- held to exactly the rule 0118 states.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

create table world_kind_version (
  workspace_id    uuid not null,
  kind            text not null check (kind ~ '^[a-z][a-z0-9_]{0,31}$'),
  version         integer not null check (version between 1 and 9999),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  origin          text not null check (origin in ('authored', 'drafted', 'uploaded', 'imported')),
  validation      jsonb not null check (jsonb_typeof(validation) = 'object'),
  created_by      uuid not null,
  created_at      timestamptz not null default statement_timestamp(),
  primary key (workspace_id, kind, version),
  constraint world_kind_version_is_one_document unique (workspace_id, document_sha256),
  constraint world_kind_version_names_itself check (
    (document->>'profile' = 'exulanica.world-kind/v1'
      and document->>'kind' = kind
      and document->>'version' = version::text
      and document->>'origin' = origin) is true),
  constraint world_kind_version_passed_its_checks check (
    (validation->>'profile' = 'exulanica.world-kind-validation/v1'
      and validation->>'verdict' = 'passed'
      and validation->'kind'->>'sha256' = document_sha256) is true)
);

comment on table world_kind_version is
  'A workspace''s own world kinds, each version as admitted with the report its sample worlds '
  'passed. Appended once; never updated or deleted by the runtime.';

create trigger tg_world_kind_version_append_only
before update or delete on world_kind_version
for each row execute function tg_reconstruction_privacy_append_only();

alter table world_kind_version enable row level security;
alter table world_kind_version force row level security;
create policy ws_isolation on world_kind_version
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- The application appends and reads world kinds; read-only roles only read them. Provisioning
-- applies the same shape through exulanica.db.roles, where the table is insert-only. Whatever a
-- default privilege granted is revoked, as 0118 does for the receipt.
do $$ declare r text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert on world_kind_version to %I', r);
      execute format('revoke update, delete on world_kind_version from %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on world_kind_version to %I', r);
      execute format('revoke insert, update, delete on world_kind_version from %I', r);
    end if;
  end loop;
end $$;

alter table world_generation_receipt
  drop constraint world_generation_receipt_states_its_generation;
alter table world_generation_receipt
  add constraint world_generation_receipt_states_its_generation check (
    (receipt->>'profile' = 'exulanica.generated-world/v1'
      and receipt->>'seed' ~ '^[0-9a-f]{64}$'
      and receipt->>'output_digest' ~ '^[0-9a-f]{64}$'
      and case when receipt->'composer'->>'key' = 'site-plan'
        then jsonb_typeof(receipt->'kind') = 'object'
          and jsonb_typeof(receipt->'kind'->'document') = 'object'
          and receipt->'kind'->>'sha256' ~ '^[0-9a-f]{64}$'
          and jsonb_typeof(receipt->'values') = 'object'
          and not (receipt ? 'tiles')
        else jsonb_typeof(receipt->'recipe') = 'object'
          and jsonb_typeof(receipt->'specification') = 'object'
          and jsonb_typeof(receipt->'tiles') = 'array'
          and jsonb_array_length(receipt->'tiles') between 1 and 256
      end) is true);

commit;
