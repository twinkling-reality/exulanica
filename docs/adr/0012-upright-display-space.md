# ADR-0012: A photograph's display space is its upright pixel space, and the schema says so

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build
- Extends: [0004-exif-orientation-normalisation.md](0004-exif-orientation-normalisation.md)

## Context

ADR-0004 settled which of the two branches `docs/domain-and-evidence-model.md` section 1.5 offered
would be taken: normalise pixels at ingest rather than widen `media_track.rotation` to the eight
EXIF values. It has been implemented and tested since 2026-08-27.

The **item was still recorded as OPEN and blocking the v1 freeze** in three places, and two facts in
the live system still described the branch that was not taken. The audit found:

1. `docs/domain-and-evidence-model.md` sections 1.5, 9.1 and 9.2 say the question is unresolved, and
   9.1 states that "Ingest currently **refuses** mirrored orientations rather than guessing, so this
   blocks ingesting any corpus that contains one". That has not been true since
   `exulanica/ingest/exif.py` was written. `normalise_orientation` admits all eight values,
   `tests/test_exif_orientation.py` asserts that all eight produce the same upright image, and the
   ETH3D benchmark scene was ingested through that path.
2. `exulanica/migrations/0001_spine.sql` carries the same claim in a comment on the column.
3. `media_track.rotation` was written as the rotation that **was applied**, sitting in the same row
   as `disp_w`/`disp_h`, which already have that rotation baked in. Those two readings cannot both
   be right. The ordinary reading of a `(coded_w, coded_h, disp_w, disp_h, rotation, sar)` group,
   the one ffprobe establishes, is "rotation still to apply for display".
4. Nothing prevented an `img`-track region from carrying a rotated `display` geometry, even though
   ingest never produces one. `region` is inside `span_digest`, so such a row would not be a stale
   value to repair later: it would be a permanent citation address naming the wrong pixels.

Item 3 is currently harmless because no code reads the column back. That is exactly why it is cheap
to fix now and expensive to fix after the first consumer appears.

## Decision

**The invariant.** Every `img` track is stored with its pixels already normalised to upright display
space. Three things follow, and all three are now enforced rather than conventional:

- `media_track.rotation` means *clockwise degrees still to apply*, and is therefore `0` on every
  image track. What was applied, including whether a mirror was applied, lives in
  `probe_json -> 'orientation'`, which is outside every digest.
- Every image track records `probe_json -> 'orientation' -> 'normalised_at_ingest' = true`, together
  with the EXIF value and the mirror flag. An image track that does not record the normalisation is
  refused: without the flag a later reader cannot tell sensor space from display space, and the two
  differ by a right angle and possibly a mirror.
- A region on the `img` track carries `display.rotation = 0`. There is no second transform for a
  consumer to apply, in any language, ever.

**Mirrored EXIF Orientation values (2, 4, 5, 7) are admitted, not refused.** They are ordinary
inputs. The refusal in `exulanica/evidence/region.py::rotation_for_exif_orientation` is retained and
re-documented as what it now is: the guard on the branch that was rejected. Nothing in the pipeline
calls it. It exists so that the plausible-looking shortcut of turning an EXIF tag straight into a
display rotation, which is correct for exactly four of the eight values, fails loudly for the other
four instead of silently dropping a mirror.

**Canonical representation.** `probe_json -> 'orientation'` is
`{exif_orientation: 1..8, rotation_degrees_clockwise: 0|90|180|270, mirrored: bool,
normalised_at_ingest: true}`. `region.display` is `{w, h, rotation: 0, sar_num, sar_den}`.

## Compatibility impact

**No digest changes.** `probe_json` is untouched, so the intake artifact's `content_sha256` is
untouched. `region` is untouched, so every `span_digest` already issued is untouched. Migration
`0032_upright_display_space.sql` rewrites `media_track.rotation` to `0` for image tracks that
already record the normalisation, and nothing reads that column, so no consumer observes the change.

`media_track.rotation` has recorded `normalised_at_ingest` since `exulanica/ingest/exif.py` was
introduced (commit `a6b70ee`), so no row written by any released version of this pipeline can
violate the new constraint.

## Failure behaviour

- An image track without the normalisation record, or with a non-zero `rotation`, is refused by
  `media_track_image_is_upright` (SQLSTATE 23514). Ingest fails closed and reports the error.
- An `img` region with a rotated display geometry is refused twice: by `InvalidAddressError` in
  `EvidenceAddress._validate_shape` with a sentence naming the rule, and by
  `evidence_span_image_region_is_upright` on a route that never touches that class.
- A caller that asks `rotation_for_exif_orientation` for a mirrored value gets `InvalidAddressError`
  naming the normalisation path, as before.

## What this touches

| Surface | Change |
| --- | --- |
| Schema | `0032_upright_display_space.sql`: two check constraints, one column comment, one value repair |
| Migrations | Forward only. `0001` through `0031` are byte identical |
| Workers | `exulanica/ingest/stages/intake.py` writes `rotation=0` |
| Evidence | `EvidenceAddress._validate_shape` refuses a rotated `img` display space |
| APIs and exports | None. `media_track.rotation` is not read by any route, worker, export or renderer |
| Browser | None. `graph-client` carries regions as ppm integers and never a display rotation |
| Deletion | None |

## Tests

`tests/test_upright_display_space.py`. Each test fails when the invariant is violated, verified by
reverting `intake.py` to the previous value: six of the eight orientations then fail, and they fail
at the database as well as at the assertion.

## Consequences

The v1 freeze blocker recorded in `domain-and-evidence-model.md` section 9.1 for EXIF orientation is
**closed**. Personal-media ingest no longer has an orientation precondition: a corpus containing
mirrored originals is admissible.
