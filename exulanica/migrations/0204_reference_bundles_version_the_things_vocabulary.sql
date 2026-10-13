-- Reference bundle v2 names the expanded vocabulary for things. Existing v1
-- bundles, canonical bytes and digests are unchanged. No privilege changes.
begin;
select pg_advisory_xact_lock(119622309);

alter table reference_request drop constraint reference_request_bundle_check;
alter table reference_request add constraint reference_request_bundle_check check (
  bundle is null or (
    bundle->>'profile' = 'exulanica.reference-bundle/v1'
    or (bundle->>'profile' = 'exulanica.reference-bundle/v2'
        and purpose = 'things' and bundle->>'purpose' = purpose)
  ) is true
);

commit;
