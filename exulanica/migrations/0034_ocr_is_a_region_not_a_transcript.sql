-- 0034_ocr_is_a_region_not_a_transcript.sql
-- Close the second freeze blocker 0001 left open: whether OCR text over a photograph reuses
-- `modality = 'transcript_text'` or takes its own value. ADR-0016 answers neither.
--
-- Text read off a surface in a photograph is addressed by the pixels it was read from. That is a
-- region, and the pipeline already writes it as a `frame_region` span carrying an `ocr_text_is`
-- assertion. `transcript_text` addresses a character range in a versioned text artifact, which is
-- what an audio transcript needs because the media axis alone cannot locate a word. A photograph
-- does not have that problem and does not have a transcript.
--
-- `modality` is inside `span_digest`, so this has to be settled before OCR spans are written
-- rather than before they are read: re-labelling spans already issued under one value changes
-- their digests, which is a v2 span format rather than a rename. Nothing has written
-- `transcript_text` yet, so the constraint below validates against an empty set and closes the
-- ambiguity permanently.

begin;

select pg_advisory_xact_lock(119622309);

comment on column evidence_span.modality is
  'One of the five citation kinds, and inside span_digest, so these spellings are frozen and a '
  'sixth value would be additive. Text read off a photograph is frame_region plus an '
  'ocr_text_is assertion, never transcript_text: transcript_text addresses a character range in '
  'a versioned text artifact, which is what an audio transcript needs and a photograph does '
  'not. A text-anchored OCR artifact, if one is ever needed, takes its own additive value.';

alter table evidence_span
  add constraint transcript_is_not_an_image_track check (
    modality <> 'transcript_text' or track_key <> 'img'
  );

commit;
