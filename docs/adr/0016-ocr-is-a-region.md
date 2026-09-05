# ADR-0016: OCR text over a photograph is a region span, not a transcript

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build
- Closes the item ADR-0004 left under "Still open"

## Context

`docs/domain-and-evidence-model.md` sections 1.5 and 9.1 recorded as **OPEN and blocking the v1
freeze**: whether OCR text spans over photographs reuse `modality = 'transcript_text'` with the
`text_anchor` pointing at an OCR artifact, or take their own modality value. `modality` is a digest
input, so adding a value is additive and free, and **re-labelling spans already written under one
value is not**: it changes their digests, which is a v2 span format rather than a rename. The
document is explicit that this has to be decided before OCR spans are written, not before they are
read.

The ambiguity came from the research, which named the field `transcript_artifact_id` in an
audio-first context.

The audit found that the implementation had already answered the question and that nothing recorded
or enforced the answer:

- `exulanica/ingest/stages/vision.py` emits every piece of legible text as an `ocr_text_is`
  assertion whose support span is a `frame_region` span, or the whole-image `still_image` span when
  the model returned no usable box;
- `transcript_text` is written by nothing, anywhere, and `ocr_text_is` is one of the four searchable
  predicates in `exulanica/selection/executor.py`;
- nothing prevented a `transcript_text` span on the `img` track, so the ambiguity was reachable.

## Decision

**Neither of the two options as posed. Text read off a photograph is addressed by the pixels it was
read from.** That is a `frame_region` span, and the text itself is the object value of an
`ocr_text_is` assertion supported by that span.

`transcript_text` is **reserved for time-anchored transcripts** and is now refused on the `img`
track, in `EvidenceAddress._validate_shape` and by the `transcript_is_not_an_image_track` check
constraint in migration `0034_ocr_is_a_region_not_a_transcript.sql`.

### Why not `transcript_text` with a `text_anchor`

A `text_anchor` is a character range in a versioned text artifact. Audio needs it because the media
axis alone cannot locate a word: "seconds 12 to 18" does not say which word. A photograph does not
have that problem. Its text is at a place in the frame, and a region says exactly where, in a form
that resolves against the original bytes.

Using a text anchor here would also make the address of a piece of OCR text depend on an offset into
a **derivative**, which spine-1 forbids as identity: regenerate the OCR artifact at a new model
version and the character offsets move while the pixels do not.

### Why not a new `ocr_text` modality

It would be additive and would cost nothing to add. It would also be a **second name for an address
shape that already exists**: a rectangle in a photograph's display space. Two names for one shape
means two code paths in every consumer, two branches in the selection executor, and a normalisation
migration on the day somebody notices. The modality set stays at five.

The path is not closed. If a text-anchored OCR artifact is ever genuinely needed, for a document
photograph where character offsets carry meaning the region cannot, it takes its own additive
modality value at that point. It does not reuse `transcript_text`, and this ADR is what stops it
being reused by default.

## Source-coordinate semantics

Settled here because "which modality" is unanswerable without it. A box from the vision model is:

1. **relative to the upright display space** of ADR-0012, which is what the model is shown: the
   rendition carries no EXIF at all, so no orientation tag can cause a second rotation;
2. **clamped into the unit square**, because models routinely emit `1.02` for an edge. The span is
   built from the clamped box. The unclamped box is not lost: the vision artifact stores what the
   model wrote verbatim, so the difference between artifact and span **is** the record that clamping
   happened. There is deliberately no second flag saying so, because two records of one fact drift;
3. **refused when degenerate**, falling back to the whole-image `still_image` span. A zero-area
   region overlaps nothing, so every overlap guard would pass it. The claim that the pixels say this
   still stands; only its location is missing;
4. **quantised to parts per million** by ADR-0013, through `Fraction` and the one rounding rule, so
   the digest is exact rather than platform dependent.

`exulanica/ingest/resolve.py` re-applies the same orientation normalisation when cropping the region
out of the original, so the crop and the address agree.

## Compatibility impact

None. No span carries `transcript_text`, so the constraint validates against an empty set and no
digest changes. The five `modality` values are unchanged.

## Failure behaviour

A `transcript_text` address on the `img` track raises `InvalidAddressError` naming the correct shape,
and the same write through raw SQL raises SQLSTATE 23514 from `transcript_is_not_an_image_track`.

## What this touches

| Surface | Change |
| --- | --- |
| Schema | `0034_ocr_is_a_region_not_a_transcript.sql`: one check constraint, one column comment |
| Evidence | `EvidenceAddress._validate_shape` refuses `transcript_text` on `img` |
| Workers | None. `exulanica/ingest/stages/vision.py` already wrote the decided shape |
| APIs and browser | None. `CitationModality` in `graph-client` already carries all five values and the app renders regions, not anchors |
| Exports, deletion | None |
| Selection | None. `ocr_text_is` is already searchable alongside `caption_is` and `place_is` |

## Tests

`tests/test_ocr_span_modality.py`: the refusal in both layers, the audio transcript that must keep
working, and the four coordinate rules exercised through a real ingest.
