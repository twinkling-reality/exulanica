# ADR-0004: Normalise EXIF orientation at ingest, and record that it happened

- Status: Accepted
- Date: 2026-08-27
- Deciders: Exulanica build

## Context

`docs/domain-and-evidence-model.md` section 1.5 records an **OPEN** item that blocks the v1 freeze:

> EXIF Orientation has **eight** values, including four mirrored variants. The `media_track` schema
> carries `rotation smallint` constrained to `0 | 90 | 180 | 270`, which cannot express a flip. A
> mirrored original would place normalized regions on the wrong side of the image. [...] Settling it
> is an inspection, not an experiment: read EXIF Orientation across the actual corpus, then either
> widen the field to the eight EXIF values or normalize pixels at ingest and record that the
> normalization happened.

This is blocking because `region.display` is an input to `span_digest`. A wrong region is not a
display bug; it is baked into a permanent citation address and cannot be corrected without
invalidating every citation token, permalink and archived answer that already contains it.

It is also not hypothetical. Phone cameras write the sensor readout unrotated and record how to
display it in one tag. A pipeline that decodes pixels and ignores the tag sends portrait photographs
to the vision model sideways, and every box that model returns lands on the wrong axis.

## Options considered

**A. Widen `media_track.rotation` to the eight EXIF values.** Keeps original pixel geometry as the
reference frame and records the transform for consumers to apply.

**B. Normalise pixels at ingest and record that it happened.** Orientation is applied once, at
intake, by the same transform a correct viewer would apply. Display space becomes the upright pixel
space. Every region is normalised against it.

## Decision

**Option B.** Ingest applies the transform, and every downstream stage works from upright pixels.

Concretely, as implemented in `exulanica/ingest/exif.py`:

- `normalise_orientation` applies `PIL.ImageOps.exif_transpose`, the reference implementation of the
  eight-value table, and returns a record of what it applied.
- `DisplayGeometry.rotation` is `0` for photographs, because display space *is* the upright pixel
  space and there is no second transform for a consumer to apply.
- The EXIF value, the clockwise rotation component, whether a mirror was applied, and the flag
  `normalised_at_ingest` are recorded on `media_track.probe_json`, which is outside `span_digest`.
- `exulanica/ingest/derivatives.py` writes the model rendition with **no EXIF at all**, so no surviving
  orientation tag can cause a second rotation.

## Rationale

Option A leaves every downstream consumer responsible for applying a transform correctly. A consumer
that forgets produces a *wrong citation* rather than a wrong-looking picture, and a wrong citation is
the one failure this architecture exists to prevent. It also cannot be expressed in the digest as it
stands: `DisplayGeometry.as_digest_input` has no field for a mirror, and adding one is not an
additive change, because it alters the digest of every region already issued.

Option B moves the ambiguity to the one place it can be resolved once: the pixels. A region then
means the same thing to every reader forever, in every language, with no transform to reapply.

The cost is honest and small: a stored rendition is not a byte-for-byte copy of the original sensor
readout. It does not touch the evidence, because the **original bytes are unchanged and remain the
only thing a citation resolves to**. `exulanica/ingest/resolve.py` re-applies the same normalisation
when cropping a region out of the original, so the crop and the address agree.

## Consequences

- `media_track.rotation` stays constrained to four values and needs no migration.
- The mirrored case is exercised rather than refused. `exulanica/evidence/region.py`
  `rotation_for_exif_orientation` still refuses mirrored values, correctly: it assumes pixels were
  *not* normalised. `tests/test_exif_orientation.py` asserts the two agree wherever both have an
  opinion, so the ingest table and the evidence layer cannot silently drift.
- `tests/test_exif_orientation.py` asserts all eight orientations normalise to the same upright
  image, and that the rendition a model actually sees is upright. That is the test that fails when a
  pipeline processes photographs sideways.
- Verified end to end on 2026-08-27 against the live vision model: a photograph stored 600x900 with
  Orientation 6 was ingested, and `MiniMaxAI/MiniMax-M3` transcribed the sign in it correctly, with
  `pixel_size_is` recorded as 900x600 in display space.

## Still open

*Closed 2026-09-04.* Whether OCR text spans over photographs reuse `modality = 'transcript_text'` or
take their own modality value was **OPEN** and blocking for the same reason. This ADR did not settle
it; [0016-ocr-is-a-region.md](0016-ocr-is-a-region.md) does, and it ratifies exactly the behaviour
described here: the ingest path attaches OCR text to a `frame_region` or `still_image` span and
stores the text as an `ocr_text_is` assertion, which needs no new modality value.

The consequences of this ADR that were left conventional rather than enforced are closed by
[0012-upright-display-space.md](0012-upright-display-space.md).
