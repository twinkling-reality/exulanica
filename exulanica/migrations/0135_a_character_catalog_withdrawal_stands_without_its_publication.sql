-- 0135_a_character_catalog_withdrawal_stands_without_its_publication.sql
-- A character catalog withdrawal names a digest, whether or not this database holds its
-- publication.
--
-- 0131 tied each withdrawal to its publication by a foreign key. A catalog published and withdrawn
-- after the last backup then left a restore of that backup nothing to tie the carried withdrawal
-- to, so replay skipped it. The host's catalogs job, which publishes what the image carries on
-- every start, then published the catalog again with no withdrawal: it was served again, and the
-- custody rule refused every export of the recovered installation, because the newest export
-- holds a withdrawal the database no longer honoured.
--
-- A withdrawal is the host's final decision about one document, and the image can publish that
-- document again at any start, so the decision stands on its own. The restore withdrawal catalog
-- carries it whether or not the backup holds the publication (kind character_catalog,
-- "absent": "carry"), and publishing a withdrawn digest records the publication and leaves it
-- withdrawn (exulanica/world/character_catalog_publication.py). Serving already asks only whether
-- a withdrawal names the digest.
--
-- The digest keeps the shape the publication's own column checks. The primary key, 0131's
-- host-data trigger and 0107's seal are unchanged.

begin;

select pg_advisory_xact_lock(119622309);

alter table character_catalog_withdrawal
  drop constraint character_catalog_withdrawal_catalog_sha256_fkey;

alter table character_catalog_withdrawal
  add constraint character_catalog_withdrawal_catalog_sha256_check
  check (catalog_sha256 ~ '^[0-9a-f]{64}$');

commit;
