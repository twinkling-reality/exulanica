-- 0032_upright_display_space.sql
-- Close the mirrored-EXIF-orientation item that 0001 recorded as OPEN and blocking.
--
-- ADR-0004 chose the second branch the domain model allowed: normalise pixels at ingest and
-- record that it happened. ADR-0012 finishes the job by making the consequence durable rather
-- than conventional, because two facts in 0001 still describe the branch that was NOT taken:
--
--   * the comment on `rotation` says ingest refuses mirrored orientations. It has not since the
--     ingest pipeline was written: all eight values are admitted and normalised.
--   * `rotation` was written as the rotation that was APPLIED, next to `disp_w`/`disp_h` that
--     already have it baked in. Those two readings cannot both be right, and a consumer that
--     took the ffprobe reading of the column ("rotation still to apply") and rotated the stored
--     pixels again would place every region a right angle away from its evidence.
--
-- Nothing reads the column today, so setting it to its correct value costs one update. The
-- EXIF value, the applied rotation and the mirror stay in `probe_json -> 'orientation'`, which
-- is outside every digest and is where ADR-0004 put them.
--
-- No digest changes. `probe_json` is untouched, so the intake artifact's `content_sha256` is
-- untouched; `region` is untouched, so every `span_digest` is untouched.

begin;

select pg_advisory_xact_lock(119622309);

comment on column media_track.rotation is
  'Clockwise degrees still to APPLY to the stored pixels for display. Always 0 on an image '
  'track: ADR-0004 normalises orientation at ingest, so disp_w/disp_h are already upright and '
  'a consumer that rotated again would be wrong. What was applied, including whether a mirror '
  'was applied, lives in probe_json -> ''orientation'', outside every digest.';

update media_track
   set rotation = 0
 where kind = 'image'
   and rotation is distinct from 0
   and probe_json #>> '{orientation,normalised_at_ingest}' = 'true';

-- An image track that does not record the normalisation is refused outright. Without the flag a
-- later reader cannot tell whether a region is in sensor space or display space, and the two
-- differ by a right angle and possibly a mirror.
alter table media_track
  add constraint media_track_image_is_upright check (
    kind <> 'image' or (
      rotation = 0
      and probe_json #>> '{orientation,normalised_at_ingest}' = 'true'
      and probe_json #>> '{orientation,exif_orientation}' is not null
      and probe_json #>> '{orientation,mirrored}' in ('true', 'false')
    )
  );

-- The same invariant on the side that is inside span_digest. A photograph's display space IS
-- its upright pixel space, so a region on the `img` track that claims a rotated display space
-- is not a stale row to be repaired later: it is an address that denotes the wrong pixels, and
-- it may not be written at all.
alter table evidence_span
  add constraint evidence_span_image_region_is_upright check (
    region is null
    or track_key <> 'img'
    or region #>> '{display,rotation}' = '0'
  );

commit;
