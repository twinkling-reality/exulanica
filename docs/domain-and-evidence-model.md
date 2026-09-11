# Domain and evidence model

Status: mixed. Every claim below carries exactly one status label, and a claim that was rewritten
against what was actually built also carries **CORRECTED**.
Retrieval date for every VERIFIED external source: **2026-08-27**.

This is the core contract of the product. Everything else in Exulanica (the Atlas, the Companion, the
reconstruction ladder, the query layer) is a view over what is defined here. The spine described in
section 1 is intended to be frozen at v1 and extended additively only.

Label convention is the one in [README.md](README.md):

- **VERIFIED** cites a primary source URL and a retrieval date.
- **DECISION** records a choice and the strongest alternative rejected.
- **ASSUMPTION** is unvalidated and names the experiment that settles it.
- **OPEN** is unresolved. Nothing marked OPEN may be relied on.
- **CLOSED** marks an item that was OPEN and no longer is. Each one names the ADR that settled it,
  the artefact that enforces it, and the test that fails when it is violated. A decision recorded
  only in prose is not CLOSED.
- **CORRECTED** marks a claim that was wrong in an earlier version of this document and has been
  rewritten against what was actually built. Each one names the artefact and the test.

**Corrections against the implementation, 2026-08-27.** Migration
`exulanica/migrations/0001_spine.sql` and the `exulanica/evidence/` modules were built from this
document, and building them found errors in it. Where this document disagreed with what runs, the
built artefact wins and the paragraph is marked **CORRECTED**; where it disagreed with
[runtime-verification.md](runtime-verification.md), that document wins, as its own header says. None of these
corrections is a redesign.

**The caveat this header used to carry is withdrawn, 2026-09-04.** It said no PostgreSQL server had
executed the migration in this environment and that every SQL claim below was therefore text-level.
That has not been true for some time: the suite applies all thirty-four migrations to a real
PostgreSQL 18 server with pgvector on every run that sets `EXULANICA_TEST_DATABASE_URL`, and 1445 of
1447 tests pass that way, with nothing substituted. A claim below about a trigger, a check
constraint or a row-level-security policy is executed unless the paragraph says otherwise.

Corpus context that shapes this document, already settled in
[product-specification.md](product-specification.md) section 2: **the capture corpus is still
photographs, not video, and there is no audio.** Section 1.5 is the load-bearing consequence.

---

## 1. The evidence address

### 1.1 The invariant

**DECISION (spine-1).** An evidence address resolves against **immutable original bytes plus an exact
rational time interval**, optionally refined by a normalized spatial region and a character range in a
versioned text artifact. It never resolves against a transcript, a segmentation, a reconstruction, an
embedding, a frame number, or a byte offset.

Corollary, and it is a hard gate: if a claim cannot be expressed as
`(content hash, track key, time interval [, region] [, text range])`, it is not a citation, and it may
not support a historical factual clause.

*Rejected alternative:* address derivatives directly, that is, cite "transcript v3, characters 4120 to
4190" or "segment 17 of the keyframe index". This is the design that falls out naturally from the
pipeline, and it breaks on the first regeneration. Every derivative in this system will be regenerated,
some of them weekly during development.

*Consequence, stated so it is not discovered later:* a full pipeline regeneration changes **zero**
evidence spans. That property is what makes the rest of the architecture safe to iterate on.

**DECISION (spine-1b).** The original media is the evidence. A Gaussian splat, a depth card, a
thumbnail, or any other rendered geometry is a **view**, never a source. Splat delivery is lossy by
construction (quantized positions, codebooked scales and colours), so no factual claim may depend on
splat geometry or splat colour. Cross-island spatial questions refuse rather than estimate.

### 1.2 Content addressing

**DECISION (spine-2).** Every ingested byte sequence gets a `blob_id` that is the **SHA-256 of the
file**, rendered canonically in RFC 6920 `ni` form and stored as `bytea(32)` for indexing.

**VERIFIED.** RFC 6920 "Naming Things with Hashes" is an IETF Standards Track RFC (April 2013)
defining `ni:///<alg>;<base64url-digest>` with an IANA registry whose mandatory-to-implement algorithm
is `sha-256`. Source: <https://www.rfc-editor.org/rfc/rfc6920.html> (2026-08-27).

*Rejected alternative:* BLAKE3, which is faster. Rejected because SHA-256 has the RFC 6920 registry
entry, is what C2PA hard bindings use, and is available in Postgres via `pgcrypto` and in every
runtime. Hashing speed is not the bottleneck for a one-shot ingest hash.

Deduplication falls out for free: re-uploading identical bytes yields the same `blob_id`, so
derivatives are already computed. Note that the *tombstone* key is deliberately **not** the blob hash;
see section 6.5.

**ASSUMPTION.** Streaming SHA-256 at ingest does not add unacceptable latency for large captures.
Settled by experiment **X-33** (ingest-time streaming hash throughput on the target instance, about 1
hour). At photograph scale this is not in doubt; it becomes a question only if video arrives.

**DECISION.** "Immutable" is not a claim this platform can back. Nebius Object Storage states plainly
that "Write-once-read-many (WORM) retention policies are not supported", and it supports no Object Lock
and no Legal Hold. Source: <https://docs.nebius.com/object-storage/interfaces/s3-api-compatibility>
(VERIFIED 2026-08-27). Product copy says **"append-only by policy"**, enforced by bucket versioning
enabled at bucket creation plus a bucket policy denying `DeleteObject` and `DeleteObjectVersion` to the
runtime service account. Never "immutable", "WORM", or "tamper-proof".

### 1.3 Why frame indices and byte offsets are unusable

**VERIFIED (local, ffprobe 8.1.1, 2026-08-27).** Per video stream, `ffprobe` exposes `time_base` as a
rational (for example `1/15360`), plus `start_pts`, `start_time`, `r_frame_rate`, `avg_frame_rate` and
`nb_frames`. Per frame it exposes `pts` in `time_base` ticks, `best_effort_timestamp`, `duration_time`
and `key_frame`. **The only per-frame quantity intrinsic to the bytes is `pts` in ticks.**

From that, three concrete failures:

| Candidate address | Why it fails |
| --- | --- |
| Frame ordinal ("frame 900") | A frame index is a function of the decoder, the filter graph, the container edit list, and whether frames were dropped or duplicated. Two decodes of the same file with different `-vsync` or filter settings produce different numbering. Under variable frame rate, "frame 900" has no fixed relationship to any media-time offset at all. |
| `avg_frame_rate` arithmetic | `avg_frame_rate` is a lie under VFR by construction, and `nb_frames` is a container hint that is frequently absent or wrong. Any ordinal-to-time conversion built on either is wrong in exactly the cases that matter. |
| Byte offset | Breaks on remux. A remux changes byte layout while preserving samples, and a re-encode changes both. Byte ranges survive only as a **prefetch hint**, never as identity. |

**DECISION (spine-4): deterministic frame selection.** `frame_at(t_ns)` is defined as the frame whose
half-open interval `[best_effort_timestamp, best_effort_timestamp + duration)` contains `t_ns`, decoded
from the preceding keyframe. This is a pure function of the bytes and needs no stored frame numbers.
`frame_ordinal` may be cached as a **non-authoritative UI scrub hint** and is recomputed, never trusted.

### 1.4 The canonical timebase

**DECISION (spine-3): dual timebase.**

1. **Canonical axis:** signed **int64 nanoseconds since track zero**, `t_ns`. Every evidence span,
   every query and every UI element uses this. It is comparable across track types and it indexes as a
   plain `int8range`.
2. **Exact anchor:** each `media_track` row stores `time_base_num`, `time_base_den` and `start_pts`.
   The mapping is deterministic and frozen:

   ```
   ticks(t_ns) = floor( (t_ns * time_base_den) / (time_base_num * 1_000_000_000) )
   t_ns(ticks) = round_half_down( ticks * time_base_num * 1_000_000_000 / time_base_den )
   ```

   Nanoseconds cannot exactly represent every 1/48000 s audio tick (20833.333... ns), which is
   precisely why the rational anchor is stored rather than discarded. **The rounding rule is part of
   the frozen contract** and may not change without a `span_format_version` bump (section 5.4). The
   rule itself was never defined in this document, and the two formulas do not compose. Both are
   corrected immediately below.
3. **Track zero:** `t_ns = 0` corresponds to `start_pts` as observed at ingest, recorded on the track
   row. If a file is remuxed and `start_time` shifts (edit lists do this routinely, and rotation
   metadata compounds it), the shift is detectable by comparing stored to observed `start_pts`, and the
   remuxed file is a **different blob** anyway, so existing spans are untouched.

#### What `round_half_down` means

**DECISION (spine-3a), CORRECTED, CLOSED 2026-09-04.** Earlier versions of this document named
`round_half_down` in the frozen formula and never defined it anywhere. The implemented meaning, in
`exulanica/canonical.py`: round the exact rational `numerator / denominator` to the nearest integer,
and resolve an exact tie **toward zero**. That is the standard reading of the name, the one
`decimal.ROUND_HALF_DOWN` and Java's `RoundingMode.HALF_DOWN` take. It is computed in exact integer
arithmetic, and `exulanica.canonical` refuses a float outright, so no float can reach a digest input
by accident.

**Ratified by [adr/0015-timebase-rounding.md](adr/0015-timebase-rounding.md)**, with the negative
exact halves that are the only place the two readings differ pinned by
`tests/test_blob_and_canonical.py::test_round_half_down_is_ties_toward_zero`.

The same ADR removed this rule from the timebase. `round_half_down` is now the rule for **quantising
a measured value**: the region ppm grid in section 1.5 and the EXIF GPS and altitude conversions.
Placing a tick on the nanosecond axis is a different job, described immediately below, and it has its
own rule, `ceil_div`. Two rules with stated and disjoint purposes, not one per call site.

#### The two formulas now compose

**DEFECT CORRECTED 2026-09-04 (spine-3b), inside its decision window.
See [adr/0015-timebase-rounding.md](adr/0015-timebase-rounding.md).**

`ns_from_ticks` used to round to nearest while `ticks_from_ns` floors, so tick to ns to tick was
**not** the identity. At 48 kHz one tick is 20833.333... ns: tick 1 rendered as 20833 ns, and 20833
ns floored back to tick 0. A citation stored in nanoseconds and converted back to a tick for a seek
opened one sample early. That was a mismatch of rounding directions, not a precision limit: the
nanosecond axis is roughly 20833 times finer than a 48 kHz tick.

`ns_from_ticks` now rounds **up**, and `ticks(t_ns(k)) == k` for every `k` on every timebase whose
tick is at least one nanosecond, negative ticks included. Ceiling toward positive infinity, not away
from zero, because `ticks_from_ns` floors toward negative infinity and the inverse must round the
same direction to compose. `tests/test_timebase.py::test_tick_to_ns_to_tick_is_the_identity` pins it
across 48 kHz, 44.1 kHz, 90 kHz, 1/15360, NTSC 1001/30000 and the canonical axis.

**Why this was a patch and not a `span_format_version` event.** Earlier versions of this section said
correcting it would move `t_start_ns` and `t_end_ns` for spans derived through the conversion. The
2026-09-04 audit established that there were none: both conversions had no callers outside the
package's own tests, no `video` or `audio` `media_track` row had ever been written, and every span in
existence is a photograph carrying `[0, 1)` directly, on a timebase where ceiling and nearest agree
on every value. Not one stored digest moved. A v2 written alongside v1 would have produced two
formats agreeing on every span that exists, so `span_format_version` stays at 1. This argument was
available exactly once and has now been used.

Two further refusals close the same family of failures: a timebase with a tick finer than one
nanosecond is refused, because two ticks would share a `t_ns` and could not both round trip; and a
tick whose nanosecond value leaves int64 is refused at the conversion rather than at the `bigint`
column.

**VERIFIED.** Intervals are **half-open**, matching Media Fragments URI 1.0 (W3C Recommendation,
2012-09-25): "the begin time is considered part of the interval whereas the end time is considered to
be the first time point that is not part of the interval." The same spec states that the h:m:s NPT form
"does not signal frame accuracy", which is exactly why the *stored* representation is `t_ns` plus the
rational anchor and the fragment URI is a **rendering** of a span, not its identity.
Source: <https://www.w3.org/TR/media-frags/> (2026-08-27).

Canonical rendered form, used for permalinks and the "open at the exact moment" control.
**CORRECTED:** the single example previously given here combined a region with no display geometry,
and `parse_uri` refuses exactly that string, because the display space a region is normalised
against is inside `span_digest` and a URI that dropped it would parse back to a different address.
The implemented forms are:

```
exulanica://blob/ni:///sha-256;<base64url>/v:0#v=1&m=video_time&t=12.5,18.25

exulanica://blob/ni:///sha-256;<base64url>/img#v=1&m=frame_region&t=0,0.000000001
  &xywh=percent:31.2000,22.0000,18.4000,40.1000&disp=4032x3024,0,1:1
```

The second is one line in use and is wrapped here for the page. `v=` and `m=` are optional on read: a
URI carrying neither is read as span format v1 with the modality inferred from the address shape,
which the shape rules in section 1.6 make unambiguous. The short form `.../v:0#t=12.5,18.25` printed
in earlier drafts therefore still resolves, pinned by
`tests/test_evidence_address.py::test_the_documented_short_uri_form_still_parses`. Writers always
emit the long form, and a region URI without `disp=` is refused, pinned by
`::test_a_region_uri_without_its_display_space_is_refused`.

**DECISION (spine-5): wall clock is a separate axis.** Media time answers "where in the file". Wall
clock answers "when in the user's life". They are joined by `clock_anchor` rows carrying
`(track_id, t_ns, utc_instant, source, uncertainty_ms)` with `source` drawn from
`container_creation_time | device_rtc | gps | ntp | user_stated | inferred`. Never store a single
capture timestamp and treat it as exact: device clocks drift. Wall-clock queries are translated through
the anchor table and **the uncertainty of that translation is carried into the answer** rather than
rounded away.

**ASSUMPTION (A-31).** Evidence addresses resolve to a seekable media position with sub-second accuracy
in the browser. Settled by experiment **X-3**: compare ffmpeg PTS-selected frames against browser
`HTMLMediaElement.currentTime` seeks across CFR H.264, VFR H.264, 90-degree-rotated video and video with
a non-zero edit list, and measure the offset distribution (about 2 hours once real captures exist). If a
systematic offset exists, citation playback becomes server-side deterministic clip extraction, which
costs latency and preserves the guarantee. This experiment does not apply to the photograph corpus and
becomes live only when video arrives.

### 1.5 Photographs are the degenerate case, and the interval still exists

The corpus is still photographs. A photograph has no duration, no frame rate, no PTS, and no edit list.
The temptation is obvious: give images their own address shape, `(blob_id, region)`, and leave time out.

**DECISION (spine-9): a photograph is modelled as a single-sample track, and its span carries a real,
non-empty, half-open interval from day one.**

Concretely:

| Field | Value for a still photograph |
| --- | --- |
| `track_key` | `img` |
| `time_base_num` / `time_base_den` | `1 / 1_000_000_000` (the canonical axis is its own timebase) |
| `start_pts` | `0` |
| `duration_ns` | `1` |
| `t_start_ns` | `0` |
| `t_end_ns` | `1` |
| `modality` | `still_image`, or `frame_region` when a region refines it |
| `region` | normalised to the unit square in **display** space, after orientation is applied, encoded as integer parts per million (see below) |

**DECISION (spine-9a), CORRECTED.** "Normalized to `[0,1]`" did not say how the number is
encoded, and that gap is load bearing: `region` is inside `span_digest`, and no two JSON writers
agree on how to render a float. Implemented in `exulanica/evidence/region.py`: coordinates are
integers in parts per million of the unit square, `0 .. 1_000_000`, quantised from an exact
`Fraction` through the one project rounding rule defined in section 1.4. One ppm of a 6000 pixel
wide photograph is 0.006 px, far below any detector's own precision. The region digest tuple is
`{kind, rect:{x, y, w, h}, display:{w, h, rotation, sar_num, sar_den}}`, integers throughout, with
`kind` present as a discriminator so a polygon kind can be added later without changing the digest
of any rectangle already issued. A zero-area region is refused for the same reason an empty interval
is: it overlaps nothing, so every overlap guard would pass it.

The interval is `[0, 1)` nanoseconds: the smallest non-empty half-open interval. It is a structural
placeholder that carries no semantics. Wall clock for a photograph lives where it belongs, in a
`clock_anchor` row with `source = 'container_creation_time'` derived from EXIF, with an explicit
`uncertainty_ms`, not smuggled into the media axis.

*Rejected alternative A: a NULL or empty interval for images.* This is the honest-looking option and it
is the expensive one. `t_end_ns > t_start_ns` is a table check constraint; an empty range `[0,0)`
contains nothing, so `@>` and `&&` are false against it and the interval never matches. Making the
columns nullable pushes a three-valued branch into: the GiST index on `(blob_sha256, t_range)`, the
tombstone interval guard trigger, the co-presence multirange math (`range_agg` then
`range_intersect_agg`), the occurrence `identity_key` quantization, and the span digest canonicalization.
Six code paths, each with a NULL branch that is never exercised by the photograph corpus, waiting to be
found wrong the week video is added. That is the failure this decision exists to prevent.

*Rejected alternative B: use the EXIF exposure duration as the interval.* Superficially more truthful.
Rejected because it makes the address depend on a parsed optional metadata field that may be absent,
wrong, or written by an editor, and because it invites the false reading that the interval means
something about the content. For a still, it does not.

**Why the interval must be in the schema on day one, stated as the actual argument:**

1. `modality` and the interval bounds are inputs to `span_digest`, which is a SHA-256 over the
   canonical span tuple. The digest is what the citation token in an answer packet is verified against
   (section 2.5). Changing the tuple shape later changes every digest, which invalidates every stored
   citation token, every permalink, and every archived answer.
2. `span_format_version` is frozen at v1 and extended **additively only**. Adding a required field to
   the address later is not additive: it is a v2 span format, written alongside v1, requiring a
   documented and verified migration of every existing span. Adding the field now costs one integer
   column and two zeroes per row.
3. The interval is what the interval tombstone matches on. Redacting a whole photograph is exactly the
   degenerate interval redaction `[0, 1)` covering the track, so the photograph corpus **exercises the
   interval deletion path** rather than leaving it untested until it protects something that matters.
4. Occurrence `presence` is an `int8multirange` and co-presence is an interval-overlap join. With a
   point interval, "these two people appear in the same photograph" is the same query as "these two
   people appear in the same 4 seconds of video", with no special case.

**Consequences specific to photographs, recorded so they are not rediscovered:**

- `frame_region` becomes the dominant modality, not a refinement of a rare case. A face in a photograph
  is `still_image` interval plus `region`. The citation kinds in section 1.6 do not change shape.
- `frame_at(t_ns)` degenerates to "the single sample". `spine-4` is satisfied trivially.
- `audio_time` and ASR-backed `transcript_text` spans have **no source material and no platform path**
  at MVP. They stay in the schema, unused. The reason is the same as above: their absence from the type
  is not free, and their presence costs nothing.
- The `capture` assertion class is thin for a photograph corpus: file hash, byte size, pixel dimensions,
  EXIF device model, EXIF GPS, EXIF timestamps. Everything else a photograph "says" is inference.

**CLOSED 2026-09-04, ADR-0004 and [adr/0012-upright-display-space.md](adr/0012-upright-display-space.md).**
EXIF Orientation has **eight** values, including four mirrored variants, and `media_track.rotation`
cannot express a flip. Of the two resolutions this document offered, the second was taken:
**pixels are normalised at ingest and the normalisation is recorded.** All eight values are
admitted; none is refused. The consequences are enforced rather than conventional:

- a photograph's display space **is** its upright pixel space, so every `img` region carries
  `display.rotation = 0`, refused by `EvidenceAddress._validate_shape` and by the check constraint
  `evidence_span_image_region_is_upright` otherwise;
- `media_track.rotation` means *clockwise degrees still to apply*, and is therefore `0` on every
  image track. The comment in `0001_spine.sql` saying ingest refuses mirrored orientations described
  the branch that was **not** taken and was superseded by migration `0032_upright_display_space.sql`;
- the EXIF value, the applied rotation, the mirror flag and `normalised_at_ingest` live in
  `media_track.probe_json -> 'orientation'`, outside every digest. An image track that does not
  record the normalisation is refused by `media_track_image_is_upright`.

No `span_digest` changed: `region` and `probe_json` were both untouched. Pinned by
`tests/test_upright_display_space.py` and `tests/test_exif_orientation.py`.

**CLOSED 2026-09-04, [adr/0016-ocr-is-a-region.md](adr/0016-ocr-is-a-region.md).** Neither of the two
options as posed. **Text read off a photograph is addressed by the pixels it was read from**: a
`frame_region` span carrying an `ocr_text_is` assertion, which is what the ingest pipeline has always
written. A `text_anchor` is a character range in a versioned text artifact, which audio needs because
the media axis alone cannot locate a word; a photograph does not have that problem, and an offset
into an OCR artifact would make the address depend on a derivative, which spine-1 forbids. A new
`ocr_text` value would be additive and free, and would also be a second name for an address shape
that already exists.

`transcript_text` is reserved for time-anchored transcripts and is now **refused on the `img`
track**, by `EvidenceAddress._validate_shape` and by the `transcript_is_not_an_image_track` check
constraint in `0034_ocr_is_a_region_not_a_transcript.sql`. No span carries it, so no digest changed.
A text-anchored OCR artifact, if one is ever genuinely needed, takes its own additive modality value
rather than reusing this one.

**CLOSED 2026-09-04 by refusing, not by inspecting.** Whether the corpus contains motion photographs
or bursts is still unestablished, and it no longer has to be established before ingest, because a
container holding more than one frame is now **refused** by `exulanica/ingest/decode.py`, at the
header probe and again at the decode.

The alternative was worse than it looked. Nothing checked frame count, so an animated GIF, a
multi-frame WebP or a motion photograph would have been ingested as its **first frame**, under a
`capture` whose EXIF and `pixel_size_is` describe the whole file, with every span addressed at `img`
on a blob whose other frames nothing can cite. That is wrong evidence rather than missing evidence.

The refusal names the video path rather than calling the file corrupt, because an operator told
"unreadable" will re-export and try again. Those files carry a genuine `v:0` track with genuine PTS
alongside the `img` track and the general video path applies to them unchanged, which is what the
video-ingest gate in the readiness report exists to open. Pinned by
`tests/test_ingest_preconditions.py`.

### 1.6 The five citation kinds

**CORRECTED:** this section was headed "the four citation kinds" while listing five rows. There are
five `modality` values, they are a closed set, and they are inside `span_digest`, so the count is
not a cosmetic detail: adding a sixth is additive, re-spelling one of these five is not.

| Kind | `modality` | Fields that constitute the address |
| --- | --- | --- |
| Still photograph | `still_image` | `blob_id`, `img`, `[0, 1)` |
| Region in a photograph or frame | `frame_region` | as above (or a video interval), plus `region` |
| Video time range | `video_time` | `blob_id`, `v:N`, `t_start_ns`, `t_end_ns` |
| Audio interval | `audio_time` | `blob_id`, `a:N`, `t_start_ns`, `t_end_ns` |
| Text span | `transcript_text` | **all of** the media time range **and** `text_anchor` |

**DECISION (spine-7).** A text span is required to carry a media time range **in addition to** its
character range. The character range is a highlight convenience; the time range is the address. If the
text artifact is regenerated at a new model version, the span still resolves.

**DECISION (spine-10).** A span never crosses a blob boundary. A logically continuous citation over a
chunked capture is an **ordered list of spans**, and the UI stitches playback.

**DECISION.** Citations open at `max(0, span_start - 0.75 s)` with the target highlighted, deliberately
early. This is forced by measurement, not taste: on conversational audio roughly 35 to 40 percent of
words lack a correct-within-200 ms timestamp (WhisperX word segmentation at a 200 ms collar reports
Switchboard 93.2 percent precision / 65.4 percent recall, AMI 84.1 / 60.3;
<https://www.isca-archive.org/interspeech_2023/bain23_interspeech.pdf>, VERIFIED 2026-08-27). The
padding is inert for the photograph corpus and is specified now so the claim wording never has to
change: *"we always open slightly early on purpose."*

### 1.7 Re-anchoring across derivative regeneration

**DECISION (spine-8).** Regenerating a derivative never rewrites a span. A separate lazy table maps a
span onto each new artifact version.

```sql
create table anchor_resolution (
  span_id     uuid not null references evidence_span(span_id),
  artifact_id uuid not null references artifact(artifact_id),
  char_start  int,
  char_end    int,
  method      text not null,   -- 'exact_quote' | 'fuzzy_quote' | 'time_overlap' | 'failed'
  score       real,
  resolved_at timestamptz not null default now(),
  primary key (span_id, artifact_id)
);
```

Resolution order: exact quote match inside the time window, then fuzzy quote match (normalized
Levenshtein above a threshold), then pure time overlap, then `failed`. A `failed` re-anchor **does not
invalidate the citation**, because the citation was never the character range. The highlight degrades;
the address does not.

The quote-plus-prefix-plus-suffix pattern is taken from the W3C Web Annotation Data Model, a
Recommendation dated 2017-02-23 defining `TextQuoteSelector` (quote plus prefix and suffix),
`TextPositionSelector`, `DataPositionSelector`, `FragmentSelector` and a `refinedBy` chaining
mechanism. Source: <https://www.w3.org/TR/annotation-model/> (VERIFIED 2026-08-27).

**ASSUMPTION.** Exact plus fuzzy re-anchoring succeeds often enough that the highlight UX survives a
model upgrade. Settled by experiment **X-19**: regenerate a text artifact at a second model version and
measure exact-quote and fuzzy-quote re-anchor rates (about 3 hours). Below roughly 90 percent combined,
the UX degrades to time-only citation and the documentation says so up front.

---

## 2. The epistemic model

### 2.1 Four provenance classes

```sql
create type assertion_kind as enum (
  'capture',    -- deterministic property of the recording: byte size, dimensions, container and EXIF
                -- timestamps, EXIF GPS, device model, file hash. Support = the bytes and their metadata.
  'inference',  -- ANY model output over a capture: object label, scene caption, face embedding,
                -- OCR text, place recognition, transcript text.
  'user',       -- stated by the human: names, corrections, context the capture could not know.
  'external'    -- live-web lookup about a PUBLIC entity. Never a claim about the user's past.
);

create type assertion_status as enum (
  'active','superseded','retracted','disputed','rejected'
);
```

**DECISION (epi-1).** *A detection is an inference no matter how confident it is.* "Capture-supported
observation" means a property of the recording itself, not "a model looked at the recording". This is
the distinction that is normally collapsed, and collapsing it is what lets a guess be rendered as a
fact.

**DECISION (epi-2).** `external` assertions are **structurally barred** from supporting a historical
clause. They may support only a present-tense claim about a public entity, they must carry `url`,
`retrieved_at` and `snapshot_hash`, and they render in a visually distinct block labelled "as of
&lt;date&gt;". Enforcement is in the answer validator, not in a prompt: the evidence resolver accepts
only capture-backed pointers.

### 2.2 The assertion record

```sql
create table assertion (
  assertion_id     uuid primary key default uuidv7(),
  workspace_id     uuid not null,

  kind             assertion_kind not null,
  predicate_id     int  not null references predicate(predicate_id),
  subject_ref      jsonb not null,   -- {type:'entity'|'occurrence'|'capture'|'span', id:...}
  object_ref       jsonb,            -- same shape, for relational predicates
  object_value     jsonb,            -- for literal predicates, typed by predicate.value_schema

  -- bitemporality: when the claim is ABOUT, versus when we RECORDED it
  valid_time       tstzrange,        -- may be unbounded, or NULL for timeless claims
  asserted_at      timestamptz not null default now(),

  -- support
  support_span_ids uuid[] not null default '{}',
  produced_by_run  uuid references pipeline_run(run_id),  -- required when kind='inference'
  stated_by_user   uuid,                                  -- required when kind='user'
  external_source  jsonb,   -- {url, retrieved_at, snapshot_hash, tool} when kind='external'

  -- confidence: two separate numbers, deliberately
  raw_score        real,             -- whatever the model emitted. NOT a probability.
  calibration_id   int references calibration(calibration_id),
  calibrated_p     real,             -- NULL until a calibration bin has enough observations

  status           assertion_status not null default 'active',
  supersedes       uuid references assertion(assertion_id),

  emit_key         text not null,    -- idempotency, section 5
  constraint assertion_emit_key_uniq unique (workspace_id, emit_key),

  constraint inference_support_required check (
    kind <> 'inference' or cardinality(support_span_ids) > 0),
  constraint capture_support_required check (
    kind <> 'capture'   or cardinality(support_span_ids) > 0),
  constraint external_no_history check (
    kind <> 'external' or valid_time is null
      or lower(valid_time) >= asserted_at - interval '1 day')
);

create index on assertion (workspace_id, predicate_id, status);
create index on assertion using gin (support_span_ids);
create index on assertion using gist (workspace_id, valid_time);
```

```sql
create table predicate (
  predicate_id  serial primary key,
  key           text unique not null,   -- 'person_present','place_is','object_present','name_is', ...
  value_schema  jsonb not null,         -- JSON Schema for object_value
  functional    boolean not null default false,  -- at most one active object per subject+valid_time
  allows_kind   assertion_kind[] not null,       -- e.g. name_is: {'user'} only
  vocab_version int not null default 1
);
```

**DECISION (epi-3).** `predicate` is a lookup table, not a Postgres enum, because the vocabulary will
churn weekly during development and `ALTER TYPE ... ADD VALUE` has awkward transaction semantics. Only
genuinely closed sets stay enums: `assertion_kind`, `assertion_status`, `link_state`,
`occurrence_class`, `tombstone_scope`, `pipeline_event_type`.

Note `allows_kind` doing real work: `name_is` allows only `user`. There is no code path in which a
model writes a name.

### 2.3 Confidence, without pretending it is truth

**DECISION (epi-4).** Confidence splits into two fields that are never conflated.

- `raw_score` is whatever the model emitted. It is **never rendered to the user** and **never used as a
  threshold that decides a factual claim**.
- `calibrated_p` is NULL until a calibration bin has accumulated enough observed user confirm and reject
  decisions.

```sql
create table calibration (
  calibration_id serial primary key,
  model_ref      jsonb not null,
  predicate_id   int not null references predicate(predicate_id),
  bin_lo         real not null,
  bin_hi         real not null,
  n_confirmed    int not null default 0,
  n_rejected     int not null default 0,
  empirical_p    real,
  updated_at     timestamptz not null default now()
);
```

Three mechanisms, in order of strength:

1. **Calibration from observed decisions.** `empirical_p` comes from the user's own confirm and reject
   history, not from the model's self-report.
2. **Qualitative bands until calibration exists.** The UI shows `low | medium | high` and the copy says
   "the system thinks". A percentage implies a frequency guarantee that cannot be made.
3. **Eligibility gate.** An `inference` assertion may support a historical clause only if it is
   user-confirmed (which promotes it to a `user`-backed assertion), or is rendered as **explicitly
   uncertain** with its citation intact. There is no third option in which a high-scoring inference is
   stated as fact.

**ASSUMPTION (A-26).** A calibration bin needs at least 30 observed confirm or reject decisions before
`calibrated_p` is populated. Settled by computing the confidence-interval width on empirical p as a
function of n once real confirmation data exists.

### 2.4 Supersession, dispute, retraction

Append-only. Nothing is updated in place except `status` and `supersedes`.

| Operation | Mechanism | Why |
| --- | --- | --- |
| **Supersede** | New row with `supersedes = old.assertion_id`; old row `status = 'superseded'` | A better model version or a user correction replaces an earlier claim. The old row and its spans remain resolvable, so an old answer permalink still explains itself. |
| **Retract** | `status = 'retracted'` plus a `retraction` row recording who and why | The claim was wrong and there is no replacement. |
| **Dispute** | A `dispute(assertion_id, opened_by, reason, opened_at, resolved_at, resolution)` row; sets `status = 'disputed'` | The assertion becomes **ineligible for answer composition** while remaining visible in the Atlas with a conflict marker. Opened by a user, or automatically by a contradiction detector: two `active` assertions with the same subject, a `functional` predicate, different objects, and overlapping `valid_time`. |

**Precedence lattice when active assertions conflict: `user > capture > inference > external`.**

`user` outranks `capture` because a user can correct a wrong device clock or a wrong GPS fix and the
file cannot argue back. This matters more for a photograph corpus than for video, because a large part
of the `capture` class is EXIF, and EXIF is trivially editable by any tool in the chain. `external` sits
at the bottom and, per epi-2, cannot participate in a historical conflict at all.

### 2.5 How a citation survives the model

The epistemic model is only worth something if the answer layer cannot route around it. Two mechanisms,
both deterministic:

- **Packet-scoped citation tokens.** Each evidence item in a bounded evidence packet (maximum 24 items)
  carries a random 10-character token valid only inside that one packet, mapped server-side to
  `(span_id, assertion_id)` for the request lifetime. The model cannot construct a valid reference to
  anything outside the packet, so a hallucinated citation fails lookup deterministically rather than
  rendering as a plausible link. `span_digest` exists so the token can be verified without trusting a
  lookup table that a buggy or compromised path could have rewritten.
- **No uncited digits.** Generated clause text may contain no digit sequence unless it is covered by a
  `value_ref` pointing at a deterministic query result. This mechanically kills the highest-damage
  hallucination class in a memory product: a confidently wrong count, date, or duration.

**ASSUMPTION (A-32).** Constrained JSON decoding is reliable enough on the chosen model to emit
schema-valid structured answers. Settled by experiment **X-4** (about 200 real questions, 24-item
packets, measure schema-valid rate and validator pass rate, about 3 hours). If it fails, the fallback is
a **deterministic templated answer** rendered from the query result and its citations. That path is a
first-class output, not an error case, so a correct cited answer exists with zero model compliance.

---

## 3. Occurrence versus entity

### 3.1 The separation

**DECISION (id-1).** An **occurrence** is scene-local and **never carries a name, ever**. An **entity**
is workspace-global and carries the name. The link between them is a first-class, reversible, auditable
object.

If a detector is allowed to write a name onto a detection, undo becomes impossible and a model's guess
becomes indistinguishable from the user's knowledge. Every affordance in section 3.4 depends on this
separation holding without exception.

*Rejected alternative:* assign identity at detection time above a confidence threshold. Rejected on
evidence, not principle. **VERIFIED:** in open-set face identification the best method reaches only
about 60 percent identification rate at a false alarm rate of 0.01, and the paper explicitly warns that
thresholding verification-like scores is a widespread misconception as a solution to open-set
identification. Source: <https://ar5iv.labs.arxiv.org/html/1705.01567> (2026-08-27).

**DECISION (id-2).** `auto_provisional` links may drive **filtering, temporary emphasis and "maybe"
results**. They may **never** move persisted Atlas layout or support a historical factual clause.
This is the line that lets the system surface a guess while refusing to turn one into spatial memory
or an assertion.

**DECISION (id-6): the system never proposes a real-world identity.** It proposes only "the same person
as in these other captures". Names come solely from the account holder's own annotation. This also
defuses defamation-by-mismatch, which is a live risk at 60 percent open-set accuracy.

### 3.2 The promotion path

```
detector run
  -> occurrence (anonymous, evidence-bound, one or more spans on ONE blob)
  -> candidate generation: ANN over entity exemplars, plus hard constraints
  -> match_proposal rows, ranked
  -> gate:
       score >= HIGH, no rejection, no constraint violation -> entity_link(auto_provisional)
       LOW <= score < HIGH                                  -> surfaced as a user question
       score <  LOW                                         -> dropped, still logged
  -> user confirms      -> entity_link(confirmed) + a 'user' assertion
     user rejects       -> identity_rejection row (3.3); suppressed under the same basis
     user says "new"    -> new entity + confirmed link
```

Hard constraints applied **before** ranking:

- Two `person` occurrences whose `presence` multiranges overlap **on the same blob and track** cannot be
  the same entity. A person is not in two places in one photograph. Cheap and very effective as an
  anti-merge constraint, and it is fully live in a photograph corpus, where two faces in one image are
  the common case.
- An unrevoked rejection covering the pair (3.3).
- An explicit `never_same(entity_a, entity_b)` constraint recorded by a previous split.

**ASSUMPTION (A-18).** Single-signal cross-capture identity lands somewhere around Recall@1 of 40 to 65
percent and Recall@5 of 70 to 85 percent. This is **extrapolated, not measured**. Settled by experiment
**X-6**, a signal-ablation study over 50 to 100 labelled cross-capture pairs across different days,
clothing and lighting (about 2 days). **No recall number may appear in any public material until X-6 has
run.** If it fails, the product ships as proposal-only with nothing linking without confirmation, which
is a weaker product and a more honest one.

### 3.3 Rejection memory that survives regeneration

**This is the part that is normally got wrong.** If a rejection is keyed by `occurrence_id`, the next
detector run mints a new `occurrence_id` for the same face in the same photograph, and the rejected
proposal comes straight back. The user re-rejects the same match forever, and the product feels broken.

**DECISION (id-3).** Rejections are keyed by an **evidence-derived identity key**, never by a pipeline
row id.

```
identity_key(occurrence) = sha256(
    blob_sha256
  , track_key
  , floor(t_start_ns / 250_000_000)   -- 250 ms quantization bucket
  , floor(t_end_ns   / 250_000_000)
  , occurrence_class
  , region_bucket                     -- normalized rect quantized to a 16x16 grid, or 'null'
)
```

For a photograph both time buckets are `0`, so the key reduces to blob, track, class and region bucket:
stable across detector versions by construction, because it is derived from the evidence rather than
from the pipeline.

*Rejected alternative:* key rejections by pipeline row id. It is the obvious design and it resurrects
every rejected proposal on every re-run.

```sql
create table identity_rejection (
  rejection_id uuid primary key default uuidv7(),
  workspace_id uuid not null,
  scope        text  not null,   -- 'occurrence_entity' | 'entity_entity'
  key_a        bytea not null,   -- occurrence identity_key, or entity_id bytes
  key_b        bytea not null,   -- entity_id bytes
  basis_digest bytea not null,   -- WHICH modalities were shown when the user said no
  rejected_by  uuid  not null,
  rejected_at  timestamptz not null default now(),
  revoked_at   timestamptz,      -- undo is a revocation, never a DELETE
  unique (workspace_id, scope, key_a, key_b, basis_digest)
);
```

**DECISION (id-4): the re-proposal rule.** A proposal is suppressed if an unrevoked `identity_rejection`
matches `(scope, key_a, key_b)` and the new proposal's `basis_digest` is a **subset** of the rejected
basis. It may resurface only if the new basis contains a **materially new modality**, and then it must
be presented with an explicit "new information: &lt;modality&gt;" label. Same-basis re-proposal is never
allowed.

`basis_digest = sha256(sorted(modalities) || feature_extractor_versions)`, with `modalities` drawn from
the closed set `{face, voice, gait, context_place, context_cooccurrence, user_text}`. This gives "a
rejected match must never be re-proposed identically" a precise and testable meaning.

**ASSUMPTION (A-25).** 250 ms boundary quantization and a 16x16 region grid produce a re-run-stable
`identity_key`. Settled by running the detector twice at different versions over the same captures and
measuring the collision rate against the miss rate, then tuning from that curve (about half a day). For
the photograph corpus only the region grid is under test, since the time buckets are constant.

### 3.4 Merge, split, undo

**DECISION (id-7).** All four operations are **events, not mutations**. Nothing is deleted; the ledger
is the truth.

```sql
create type identity_event_type as enum (
  'link_confirmed','link_rejected','link_revoked','entity_created',
  'entities_merged','entity_split','event_undone'
);

create table identity_event (
  event_id     uuid primary key default uuidv7(),
  workspace_id uuid not null,
  type         identity_event_type not null,
  actor        uuid not null,
  payload      jsonb not null,   -- merge: {from:[a,b], into:c}
                                 -- split: the full partition of occurrence ids
  undoes       uuid references identity_event(event_id),
  created_at   timestamptz not null default now()
);
```

- **Merge (A, B -> C).** Create C, repoint all links, set `A.merged_into = C` and `B.merged_into = C`.
  A and B survive as **alias redirects** so old permalinks and old answers still resolve. The payload
  records the exact link set at merge time, which is what makes undo exact rather than approximate.
- **Split (C -> A', B').** The payload carries the explicit partition of C's occurrence links, chosen by
  the user. Creates A' and B', writes a `never_same(A', B')` constraint, clears `C.merged_into`, and
  marks C as a disambiguation node.
- **Undo.** Apply the inverse event and record it as a new `identity_event` with `undoes` set.

### 3.5 Recomputation triggered by each operation

**DECISION (id-5).** Every derived object records what it depends on, so invalidation is mechanical
rather than a hand-maintained list of things to remember.

```sql
create table derived_artifact (
  derived_id   uuid primary key default uuidv7(),
  workspace_id uuid not null,
  kind         text not null,  -- 'entity_exemplars'|'cooccurrence_edge'|'atlas_layout'
                               -- |'episode_summary'|'answer_cache'
  depends_on   jsonb not null, -- [{kind:'entity', id, v}, {kind:'occurrence', id, v}, ...]
  dep_index    text[] not null,-- flattened 'entity:<uuid>' strings, GIN-indexed
  payload      jsonb,
  computed_at  timestamptz not null default now(),
  stale        boolean not null default false
);
create index on derived_artifact using gin (dep_index);
```

| Operation | What must be recomputed | Cost class |
| --- | --- | --- |
| `link_confirmed` | entity occurrence set; entity exemplar set; co-occurrence edges touching the entity; Atlas placement for affected memory regions; any `answer_cache` whose `dep_index` names the entity; calibration bin counters | small, incremental |
| `link_rejected` | proposal suppression index only, nothing else. **Deliberately trivial**, because the user will do this often and it must never feel expensive | trivial |
| `entities_merged` | union of both aggregates; alias redirect table; deduplicate assertions whose subject was A or B; re-run the contradiction detector over the union; invalidate every `derived_artifact` naming A or B | medium |
| `entity_split` | recompute both new aggregates from their partitions; invalidate every `derived_artifact` and `answer_cache` naming C, because any prior answer about C may now be wrong. **Invalidated, never repaired** | medium |
| `event_undone` | the inverse of the original, plus invalidation of everything the original invalidated | same as the original |

**Nothing in this table touches the evidence spine.** Spans and blobs are unaffected by identity churn.
That is the entire point of separating them.

---

## 4. Core schema

PostgreSQL 18 with pgvector, native range and multirange types. No dedicated vector database, no graph
database.

**VERIFIED.** PostgreSQL 18 (18.6, released 2025-09-25) ships a built-in `uuidv7()` generating
time-ordered UUIDs. Source: <https://www.postgresql.org/docs/18/functions-uuid.html> (2026-08-27).
PostgreSQL provides a multirange type for every range type, indexable by GiST and SP-GiST for `=`, `&&`,
`<@`, `@>`, and usable in exclusion constraints. Source:
<https://www.postgresql.org/docs/18/rangetypes.html> (2026-08-27). pgvector's latest tag is **v0.8.6
dated 2026-07-29**; 0.8.3 (2026-06-17) "fixed possible HNSW index corruption during vacuuming", so the
floor is >= 0.8.6. Source: <https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md> (2026-08-27).
HNSW and IVFFlat index `vector` to at most 2,000 dimensions and `halfvec` to at most 4,000.
Source: <https://github.com/pgvector/pgvector/blob/master/README.md> (2026-08-27). **CORRECTED:**
the earlier conclusion drawn from that ceiling, "which is why all embeddings are `halfvec`", no
longer holds as stated. The embedding column is `halfvec(4096)`, which is above the ceiling, so it
carries no ANN index at all and search over it is exact. Section 4.4 records why.

### 4.1 Immutable media layer

**VERIFIED, CORRECTED.** `btree_gist` is required and was missing from this document. Core GiST
ships no operator class for `bytea` or `uuid`, and three indexes in this schema lead with one of
those: `gist (blob_sha256, t_range)` on `evidence_span`, `gist (capture_id, presence)` on
`occurrence`, and `gist (workspace_id, valid_time)` on `assertion`. Without the extension all three
`create index` statements fail outright, so the migration does not apply at all and the omission is
a build error rather than a style point. The module "provides GiST index operator classes that
implement B-tree equivalent behavior" for a type list that includes both `bytea` and `uuid`. Source:
<https://www.postgresql.org/docs/18/btree-gist.html> (2026-08-27). Declared in the migration and
pinned by `tests/test_migration.py::test_the_extensions_the_indexes_need_are_declared`.

```sql
create extension if not exists vector;   -- pgvector >= 0.8.6
create extension if not exists pgcrypto;
create extension if not exists pg_trgm;
create extension if not exists btree_gist;   -- CORRECTED: required by three GiST indexes

create table blob (
  blob_sha256   bytea primary key,                     -- 32 bytes
  ni_uri        text generated always as
                  ('ni:///sha-256;' ||
                   translate(encode(blob_sha256,'base64'),'+/=','-_')) stored,
  byte_size     bigint not null,
  media_type    text not null,
  storage_key   text,                                  -- object-store key; NULL once purged
  purged_at     timestamptz,                           -- stub row survives purge, see section 6
  first_seen_at timestamptz not null default now()
);

create table media_track (
  track_id      uuid primary key default uuidv7(),
  blob_sha256   bytea not null references blob(blob_sha256),
  track_key     text not null,          -- 'img' | 'v:0' | 'a:0'
  kind          text not null,          -- 'image' | 'video' | 'audio'
  time_base_num int  not null,          -- image: 1
  time_base_den int  not null,          -- image: 1000000000
  start_pts     bigint not null,        -- image: 0
  duration_ns   bigint not null,        -- image: 1
  -- visual only
  coded_w int, coded_h int, disp_w int, disp_h int,
  rotation smallint, sar_num int, sar_den int,
  codec text not null,
  probe_json    jsonb not null,         -- full ffprobe / EXIF output, kept verbatim
  unique (blob_sha256, track_key)
);

create table capture (
  capture_id   uuid primary key default uuidv7(),
  workspace_id uuid not null,
  blob_sha256  bytea not null references blob(blob_sha256),
  device_id    text,
  started_at   timestamptz,             -- best estimate only; clock_anchor is the real story
  created_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
-- CORRECTED: partial, not a total unique constraint. A live duplicate still collapses to one
-- capture; a deliberate re-import after a deletion gets a fresh capture_id, per del-3 in 6.5.
create unique index capture_live_bytes_uniq
  on capture (workspace_id, blob_sha256) where deleted_at is null;
create index capture_ws_idx on capture (workspace_id, deleted_at);

create table clock_anchor (
  anchor_id      uuid primary key default uuidv7(),
  track_id       uuid not null references media_track(track_id),
  t_ns           bigint not null,
  utc_instant    timestamptz not null,
  source         text not null,   -- 'container_creation_time'|'device_rtc'|'gps'|'ntp'
                                  -- |'user_stated'|'inferred'
  uncertainty_ms int not null,
  unique (track_id, t_ns, source)
);
```

**DECISION (spine-11), CORRECTED.** This document previously declared
`unique (workspace_id, blob_sha256)` on `capture`, commented "re-upload of identical bytes = the
same capture". That contradicts del-3 in section 6.5, which says a deliberate re-import after a
deletion creates a **new** `capture_id` and proceeds normally. Under a total unique constraint the
re-import collides with the soft-deleted row and cannot proceed at all, which is precisely the
silent blocklist del-3 exists to prevent. The implemented form is the partial unique index above,
`where deleted_at is null`, and it satisfies both readings: duplicate live uploads still collapse to
one capture, and a re-import after a deletion gets a fresh row. The tombstone remains keyed by
`(workspace_id, capture_id)` and never by the hash, and `blocklist_hash` remains the separate,
explicit opt-in for the other intent.

### 4.2 The spine

```sql
create table evidence_span (
  span_id             uuid primary key default uuidv7(),
  span_format_version smallint not null default 1,
  workspace_id        uuid not null,

  -- the address
  blob_sha256   bytea  not null references blob(blob_sha256),
  track_key     text   not null,
  t_start_ns    bigint not null,
  t_end_ns      bigint not null,
  t_range       int8range generated always as
                  (int8range(t_start_ns, t_end_ns, '[)')) stored,

  modality      text not null check (modality in
                  ('still_image','frame_region','video_time','audio_time','transcript_text')),
  region        jsonb,   -- {kind, rect|polygon, display:{w,h,rotation,sar_num,sar_den}}
  text_anchor   jsonb,   -- {artifact_id, char_start, char_end, exact, prefix, suffix}
  hint          jsonb,   -- {byte_start, byte_end, frame_ordinal} - CACHE ONLY, never the address

  span_digest   bytea not null,
  created_at    timestamptz not null default now(),

  check (t_end_ns > t_start_ns),                       -- half-open and never empty
  constraint text_span_needs_anchor check (
    modality <> 'transcript_text' or text_anchor is not null),
  constraint region_span_needs_region check (
    modality <> 'frame_region' or region is not null)
);

create index on evidence_span using gist (blob_sha256, t_range);
create index on evidence_span (workspace_id, blob_sha256, track_key);
create unique index on evidence_span (workspace_id, span_digest);
```

`span_digest = sha256(canonical_json({span_format_version, blob_sha256, track_key, t_start_ns,
t_end_ns, modality, region?, text_anchor?{artifact_id, char_start, char_end, exact}}))` with keys
sorted, and with `hint` and `span_id` **excluded**. `hint` is excluded because it is a cache; `span_id`
is excluded because the digest must be a function of the address, not of the row.

**CORRECTED, on the encodings the tuple did not specify.** A digest is only reproducible if every
value has one rendering, and three were left open here. As implemented in
`exulanica/evidence/address.py`: `blob_sha256` is lowercase hex, chosen over base64url so the value is
identical to what the database prints; `region` is the all-integer tuple of section 1.5; a key is
present only when its value is present, so an absent `region` is an absent key and not a null. The
canonical JSON is a strict subset of RFC 8785, sorted keys and no insignificant whitespace, and
floats are rejected at serialisation rather than rounded. `text_anchor` carries `artifact_id`,
`char_start`, `char_end` and `exact` only: the `prefix` and `suffix` of the Web Annotation
`TextQuoteSelector` are stored on the row for re-anchoring but are **not** digest inputs, because a
re-anchor may legitimately change them and must not change the address.

The implemented table also carries check constraints this document did not list, each of which
keeps the address shape unambiguous: `track_key` matched against `^(img|[va]:(0|[1-9][0-9]{0,3}))$`,
`octet_length(span_digest) = 32`, `region_only_on_frame_region`, `still_image_is_img_track`,
`video_time_is_video_track` and `audio_time_is_audio_track`. The exclusivity of `region` to
`frame_region` is what lets the permalink form recover the modality from the address shape when `m=`
is absent.

### 4.3 Occurrence, entity, link

```sql
create type occurrence_class as enum
  ('person','voice','place','object','conversation','event');

create table occurrence (
  occurrence_id    uuid primary key default uuidv7(),
  workspace_id     uuid not null,
  capture_id       uuid not null references capture(capture_id),
  class            occurrence_class not null,

  primary_span_id  uuid not null references evidence_span(span_id),
  span_ids         uuid[] not null,
  presence         int8multirange not null,  -- union of span intervals, for co-presence math

  produced_by_run  uuid not null references pipeline_run(run_id),
  detector_version text not null,
  quality          jsonb,      -- {blur, area_frac, n_frames, ...} - drives proposal ranking

  identity_key     bytea not null,           -- section 3.3, evidence-derived
  emit_key         text  not null,
  unique (workspace_id, emit_key)
);
create index on occurrence using gist (capture_id, presence);
create index on occurrence (workspace_id, class);
create index on occurrence (workspace_id, identity_key);

create table entity (
  entity_id    uuid primary key default uuidv7(),
  workspace_id uuid not null,
  class        occurrence_class not null,
  display_name text,                                   -- written ONLY by a 'user' assertion
  merged_into  uuid references entity(entity_id),      -- alias redirect after a merge
  created_at   timestamptz not null default now(),
  deleted_at   timestamptz
);

create type link_state as enum
  ('proposed','auto_provisional','confirmed','rejected','revoked');

create table entity_link (
  link_id       uuid primary key default uuidv7(),
  workspace_id  uuid not null,
  occurrence_id uuid not null references occurrence(occurrence_id),
  entity_id     uuid not null references entity(entity_id),
  state         link_state not null,
  method        text not null,   -- 'user_confirm'|'embedding_knn'|'voice_match'|'merge'
  score         real,
  basis_digest  bytea not null,
  decided_by    uuid,
  decided_at    timestamptz,
  created_at    timestamptz not null default now()
);
-- an occurrence may be confirmed to at most one entity
create unique index entity_link_one_confirmed
  on entity_link (occurrence_id) where state = 'confirmed';
create index on entity_link (workspace_id, entity_id, state);
```

### 4.4 Embeddings and the lexical arm

```sql
create table embedding (
  embedding_id     uuid not null default uuidv7(),
  workspace_id     uuid not null,
  family           text not null,   -- 'text_chunk'|'visual_segment'|'face'|'speaker'
  ref_type         text not null,   -- 'span'|'occurrence'|'entity'
  ref_id           uuid not null,
  model_ref        text not null,
  pipeline_version int  not null,
  dims             int  not null,             -- CORRECTED: the real output width, per row
  v                halfvec(4096) not null,    -- CORRECTED: was halfvec(1024)
  created_at       timestamptz not null default now(),
  primary key (workspace_id, embedding_id)
) partition by list (workspace_id);
-- Per partition, created by the workspace provisioning path. CORRECTED: there is no HNSW or
-- IVFFlat index here. 4096 dimensions is above pgvector's 4000 ceiling for halfvec, so search
-- over this column is exact.
--   create table embedding_ws_<slug> partition of embedding for values in ('<uuid>');
--   create index on embedding_ws_<slug> (family, ref_type, ref_id);

create table text_chunk (
  chunk_id     uuid primary key default uuidv7(),
  workspace_id uuid not null,
  span_id      uuid not null references evidence_span(span_id),
  artifact_id  uuid not null references artifact(artifact_id),
  body         text not null,
  tsv          tsvector generated always as (to_tsvector('simple', body)) stored
);
create index on text_chunk using gin (tsv);
create index on text_chunk using gin (body gin_trgm_ops);
```

**DECISION (emb-1), CORRECTED.** This document specified `halfvec(1024)`. Runtime verification
**measured**
`Qwen/Qwen3-Embedding-8B`, still the only embedding-typed model in the catalog, returning
**4096-dimensional** vectors ([runtime-verification.md](runtime-verification.md) section 7), and that document
overrides on conflict. pgvector indexes `halfvec` to at most 4000 dimensions, so a 4096-dimension
column cannot carry an HNSW or IVFFlat index at all. The real choice is therefore between truncating
the model's output to fit an index and storing the real width with exact search.

**Implemented: store the real width and search exactly.** At personal-library scale, thousands of
vectors rather than millions, exact search is fast enough and strictly more correct than an
approximate index, and it removes the overfiltering hazard described below rather than working
around it. If scale later demands ANN, the additive path is a second column holding a
Matryoshka-truncated and renormalised 1024-dimension prefix used for recall only, added by a later
migration; it is not added now because the truncation behaviour of this endpoint is unverified.
`dims` is stored per row so that a future model with a different width is a data question rather
than a schema migration. The 1024 figure in earlier drafts was never measured against this endpoint,
which is the general lesson: a dimension count is a property of the deployed model, not of the
document.

**DECISION.** Embeddings are partitioned by list on `workspace_id`, so tenancy is a **partition prune**
rather than a post-scan filter. This matters because pgvector documents that "with approximate indexes,
filtering is applied after the index is scanned", and with a filter matching 10 percent of rows at
default settings roughly 4 of 10 expected results are returned
(<https://github.com/pgvector/pgvector/blob/master/README.md>, VERIFIED 2026-08-27).
**CORRECTED:** with exact search there is no approximate index to overfilter, so that hazard is
currently dormant and the `hnsw.iterative_scan = relaxed_order` setting applies only if the recall
column described above is ever added. Partitioning is kept regardless, for the stronger reason: it
is the namespace isolation the privacy analysis requires, not a performance tactic.

**DECISION.** **ANN is used for recall and ranking only, never for set membership.** "Which people are
in this photograph" is answered relationally from confirmed `entity_link` rows, never from vector
similarity. An approximate index may not decide a factual claim.

**ASSUMPTION (A-30).** A workspace is a single user at MVP, so RLS on `workspace_id` suffices and
partition-per-workspace is tractable. This is a product decision rather than a technical one. If
workspaces become shared, the partition strategy and the RLS predicate both need rework.

### 4.5 Row-level security

```sql
alter table evidence_span enable row level security;
alter table evidence_span force  row level security;
create policy ws_isolation on evidence_span
  using      (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());   -- CORRECTED: with check, not using alone
```

The implemented migration applies that pair to every workspace-scoped table in a loop, to the
partitioned `embedding` parent so partitions inherit it, and a tenant-scoped variant to
`consent_record`. `using` alone filters reads; without `with check` a session can still **write** a
row belonging to another workspace, which is the half of isolation that matters for a write path
guarded by triggers.

**VERIFIED.** `ENABLE ROW LEVEL SECURITY` gives default-deny. **Table owners bypass RLS unless `FORCE
ROW LEVEL SECURITY` is set**, and "Superusers and roles with the `BYPASSRLS` attribute always bypass the
row security system." Source: <https://www.postgresql.org/docs/18/ddl-rowsecurity.html> (2026-08-27).

**DECISION.** The query executor connects as a dedicated `exulanica_ro` role that **owns nothing** and
does **not** hold `BYPASSRLS`. This is load-bearing, not hygiene: an executor connecting as the table
owner makes every isolation policy silently inert.

**DECISION (rls-2), CORRECTED.** Row-level security on its own leaves the tombstone guard **failing
open**, and this document did not say so. The guards in section 6.3 read `tombstone`,
`evidence_span` and `occurrence`, all of which carry `FORCE ROW LEVEL SECURITY`. A session that
never set `exulanica.workspace_id` sees those tables as **empty**, so a guard looking for a covering
tombstone finds none and permits the write. A `BYPASSRLS` role arrives at the same place from the
other side: the policy is skipped, and then nothing checks that the row belongs to the session's
workspace at all. For a deletion guard, permitting on absence of context is the worst available
failure direction, because the writes it lets through are exactly the ones a revocation was meant to
stop.

Implemented: every guarded insert asserts the session context before it trusts any lookup.

```sql
create or replace function current_workspace() returns uuid
language sql stable as $fn$
  select nullif(current_setting('exulanica.workspace_id', true), '')::uuid;
$fn$;

create or replace function assert_workspace_context(p_workspace uuid) returns void
language plpgsql as $fn$
begin
  if current_workspace() is distinct from p_workspace then
    raise exception
      'workspace context missing or mismatched: set exulanica.workspace_id to % before writing',
      p_workspace
      using errcode = 'insufficient_privilege';
  end if;
end $fn$;
```

Triggers are bypassed by neither the owner nor `BYPASSRLS`, so asserting the context inside the
trigger is strictly stronger than the `with check` clause on the policy: a guarded write now
requires the session to have declared which workspace it is writing for, and to be writing for that
one. `current_setting(..., true)` takes the missing-ok flag deliberately, so an unset variable yields
NULL rather than an error, and NULL matches no row, which is what makes both the policies and the
assertion default-deny. Pinned by
`tests/test_migration.py::test_every_guard_asserts_the_workspace_context_before_it_trusts_a_lookup`
and `::test_current_workspace_is_defined_before_anything_calls_it`.

---

## 5. Idempotency and versioning of derivatives

### 5.1 The derivative identity key

**DECISION (idem-1).** A derivative's identity is
`(source_blob_sha256, stage_key, stage_version, params_digest, input_digest)`. Not `capture_id`, because
two captures of the same bytes should share derivatives. Not wall-clock time, obviously.

**CORRECTED 2026-09-03. `source_blob_sha256` is no longer `not null`, and the block below still
says it is.** ADR-0009 D9 requires a subject for a fact about N photographs: a pose receipt, a
splat and a placement record are not derivatives of one blob, and keying them to whichever
member's bytes happened to land in the column would present a corridor as one photograph's
geometry. Migration 0024 adds `artifact.scene_id`, relaxes `source_blob_sha256`, and keeps the
guarantee with a check constraint rather than with a `not null`:

```sql
constraint an_artifact_names_one_subject check (
  (source_blob_sha256 is not null) <> (scene_id is not null))
```

So an artifact still names exactly one subject; it is no longer always the same kind of subject.
The identity key above is unchanged for a per-blob derivative and is not what identifies a scene
artifact: that is `reconstruction_scene.scene_id`, a uuid5 over the sorted member capture ids,
computed by `exulanica.evidence.scene`. The reduction over a scene INVERTS, and section 6.4 is
where that is written down.

```sql
create table artifact (
  artifact_id        uuid primary key,   -- DETERMINISTIC: uuid_v5(ns, idempotency_key)
  workspace_id       uuid not null,
  kind               text not null,      -- 'ocr','caption','keyframe_index','embedding_batch', ...
  source_blob_sha256 bytea not null references blob(blob_sha256),
  stage_key          text not null,
  stage_version      int  not null,
  params_digest      bytea not null,
  input_digest       bytea not null,     -- sha256 over sorted input artifact content hashes
  idempotency_key    text not null,
  content_sha256     bytea,              -- what the bytes TURNED OUT to be
  storage_key        text,
  byte_size          bigint,
  produced_by_event  uuid references pipeline_event(event_id),
  superseded_by      uuid references artifact(artifact_id),
  purged_at          timestamptz,
  created_at         timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);

create table stage_registry (
  stage_key       text primary key,
  current_version int  not null,
  model_ref       jsonb,
  params_schema   jsonb not null,
  deterministic   boolean not null default true,
  output_kind     text not null,
  updated_at      timestamptz not null default now()
);
```

```
idempotency_key = hex(sha256(frame("exulanica/idempotency-key") || frame(key_format_version)
                             || frame(source_blob_sha256) || frame(stage_key)
                             || frame(stage_version) || frame(params_digest)
                             || frame(input_digest) || frame(binding_digest)))

frame(x) = big_endian_uint64(len(x)) || x
```

Every field is **length-prefixed**. Plain concatenation of variable-length fields is not injective:
`stage_key || stage_version` gives the pair `("vision", 11)` and the pair `("vision1", 1)` the same
bytes, so two different stages compute one key, share one artifact row, and each reads the other's
output as its own cached result. `key_format_version` is 2; version 1 was the unframed encoding.

`binding_digest` is the canonical-JSON digest of the stage's **run-time binding**, which is the part of
its identity that is not declared in source. For a model-backed stage that is the resolved model
identifier, so swapping the model behind a role invalidates the corpus rather than silently serving the
previous model's answers under the new model's name. A stage that declares a `model_role` cannot have a
key computed without one; a stage that declares none may not carry a binding at all.

`stage_version` is bumped whenever **output semantics** change: a new model, a changed prompt, a changed
chunking rule, a changed threshold. It is not bumped for a pure performance change. The bump is the
trigger for regeneration. The bump is also not the only trigger, and deliberately so: the vision stage's
`params` carry `prompt_sha256`, the SHA-256 of the prompt text itself, so an edited prompt regenerates
whether or not anybody remembered to bump anything. A hand-maintained version integer is forgotten
exactly once, and the symptom is a corpus that never reprocesses after a prompt change.

The binding names the role's **primary** identifier, not its whole chain. Keying on the chain would
re-bill the entire corpus whenever the fallback was edited, and the fallback is a resilience backup that
in the normal case answers nothing. The cost of the choice is that an artifact produced by the fallback
during a withdrawal is keyed under the primary's name; what actually answered is recorded in the
artifact's `model_ref` and `models_tried` and in the ledger, which is the record that gets read.

### 5.1.1 Store writes happen after the commit, never before

The object store is not enrolled in the database transaction and cannot be. A payload written inside a
transaction therefore survives that transaction's rollback, and for a tombstoned import that is
resurrection: the job is correctly cancelled, the rows roll back, and the purged bytes are back on disk.

Two orderings prevent it, and both are needed:

1.  An ingest asks whether the content is admissible **before it writes anything anywhere**, under the
    assumption that it is about to register a live capture for those bytes. That assumption is what
    keeps a deliberate re-import after deletion working, since at that instant no live capture exists.
2.  Every payload produced inside a transaction is queued and flushed to the store only **after** that
    transaction commits, which covers the residual race where a tombstone is committed by another actor
    between the admission check and the guard inside the writing transaction.

No compensating cleanup is involved, because nothing is written that would need cleaning up. The failure
mode is inverted rather than merely narrowed: a crash between commit and flush leaves an artifact row
whose bytes are missing, which the pipeline already detects and heals by recomputing. A recoverable gap
is strictly better than an unrecoverable leak.

Note the deliberate separation of two hashes. `idempotency_key` is what the output *should* be, computed
before running. `content_sha256` is what it *turned out to be*. If two runs with the same
`idempotency_key` produce different `content_sha256`, the stage is nondeterministic, and that is worth
knowing rather than hiding: the pipeline emits a `nondeterminism_detected` event carrying both hashes.
Stages that are legitimately nondeterministic (sampled generation, GPU reduction order) carry
`deterministic = false` in `stage_registry`, so the event is informational rather than an alarm.

### 5.2 The producer protocol

```sql
begin;
  insert into artifact (artifact_id, ..., idempotency_key, ...)
  values (uuid_v5('...'::uuid, $key), ..., $key, ...)
  on conflict (workspace_id, idempotency_key) do nothing
  returning artifact_id;
  -- no row returned means another worker already produced it: read it and stop.

  -- side effects go in the SAME transaction, each with a deterministic emit_key
  insert into assertion (..., emit_key) values (..., $key || ':a:' || ordinal)
  on conflict (workspace_id, emit_key) do nothing;

  insert into pipeline_event (type, output_artifact_ids, ...)
  values ('artifact_written', ...);
commit;
```

Every emitted row carries `emit_key = idempotency_key || ':' || ordinal` under a unique constraint. A
worker that dies after writing half its assertions and is retried produces exactly the same
`emit_key`s, and the conflicts absorb the duplicates. Combined with the transaction, this yields
**exactly-once effects on top of at-least-once execution**, which is the only honest way to build it.

Job claiming uses `for update skip locked`:

```sql
update job set state='running', claimed_by=$1, claimed_at=now()
 where job_id = (select job_id from job
                  where state='queued' and run_after <= now()
                  order by priority, job_id
                  for update skip locked limit 1)
returning *;
```

### 5.3 Regeneration is additive

**DECISION (idem-2).** Never mutate an artifact in place. A new `stage_version` produces a **new**
artifact row; the old row gets `superseded_by` set and is retained, so old citations, old
`anchor_resolution` rows and old Assembly Replays remain intact.

```sql
create view artifact_current as
  select distinct on (workspace_id, source_blob_sha256, stage_key) *
    from artifact
   where superseded_by is null and purged_at is null
   order by workspace_id, source_blob_sha256, stage_key, stage_version desc;
```

**CORRECTED 2026-09-03.** `distinct on` treats NULLs as equal, so once `source_blob_sha256`
became nullable this view collapsed every scene artifact of one stage in one workspace into a
single row. Migration 0024 adds `scene_id` to the key, in the same position in both the
`distinct on` and the `order by`. The column list is unchanged.

### 5.4 This is a cost control, not only a correctness control

The correctness argument is the one above. The cost argument is separate and is the reason this is
built on day one rather than added when it hurts.

- **Re-ingesting the corpus is free unless something actually changed.** Every derivative is keyed by
  source hash plus pipeline version. Re-running the whole pipeline after a change to one stage
  regenerates that stage only. Without this key, "re-run everything" means paying for every vision call,
  every embedding and every GPU-second again, every time.
- **Two captures of identical bytes share one set of derivatives.** Duplicate photographs are normal in a
  personal library (exports, re-downloads, edited copies saved alongside originals). Deduplication at the
  blob level removes that cost automatically.
- **Retries are free.** At-least-once execution with exactly-once effects means a crashed worker's retry
  re-inserts nothing and re-bills nothing.
- **Cost is recorded per stage.** `pipeline_event.cost` carries `{input_tokens, output_tokens,
  gpu_seconds, usd_estimate}`, so spend is attributable to a stage and a model rather than appearing as
  one bill at the end of the month. The two named ways to burn money on this project are a forgotten GPU
  VM and a managed database, and neither is visible without per-stage accounting.

**DECISION (mig-4): the spine is frozen at v1 and extended additively only.** `blob_sha256`,
`track_key`, `t_start_ns`, `t_end_ns`, the half-open semantics and the nanosecond-to-tick rounding rule
may not change. (The tick-to-nanosecond rule was corrected once, on 2026-09-04, under the narrow
argument set out in section 1.4 and [adr/0015-timebase-rounding.md](adr/0015-timebase-rounding.md):
it had no callers, no non-image track existed, and no stored digest moved. That argument is spent.) If they ever must, it is a v2 span format written **alongside** v1, with v1 spans
migrated by a documented, reversible, verified transform, never dropped.

Five independent version fields, each stored on the row that uses it:

| Field | On | Meaning |
| --- | --- | --- |
| `span_format_version` | `evidence_span` | the frozen spine contract. A change here is a product-wide event |
| `stage_version` | `artifact`, `pipeline_event` | derivative semantics |
| `plan_version` | query plan | the restricted query language |
| `answer_version` | composed answer | the answer object schema |
| `vocab_version` | `predicate` | predicate vocabulary generation |

Readers must handle every version they can encounter. Writers only ever write the current version.

Schema migrations are **forward-only**, numbered, plain SQL, one file per migration, each in its own
transaction, tracked in a `schema_migrations` table carrying a SHA-256 checksum of the file. The
application verifies every applied checksum at boot and **refuses to start on drift**. No
down-migrations: a mistake is corrected by a new forward migration. Anything touching the spine uses
expand and contract (add nullable, dual-write, backfill in bounded batches via a job, switch reads, stop
writing the old column, drop in a **later** release).

---

## 6. Deletion, tombstones, and cascade

### 6.1 Two deletion classes

1. **Redaction:** the user removes an interval of a capture. For a photograph, the degenerate interval
   is the whole image.
2. **Hard delete:** an entire capture, an entity, or a whole workspace.

### 6.2 Tombstones are authoritative and monotonic

```sql
create type tombstone_scope as enum
  ('capture','interval','entity','assertion','workspace');

create table tombstone (
  tombstone_id       uuid primary key default uuidv7(),
  workspace_id       uuid not null,
  scope              tombstone_scope not null,
  capture_id         uuid,
  track_key          text,
  interval_ns        int8multirange,   -- for scope='interval'
  entity_id          uuid,
  assertion_id       uuid,
  blocklist_hash     boolean not null default false,  -- explicit opt-in, see 6.5
  requested_by       uuid not null,
  requested_at       timestamptz not null default now(),
  effective_at       timestamptz not null default now(),
  purge_completed_at timestamptz,
  reason             text
);
create index on tombstone (workspace_id, scope, capture_id);
create index on tombstone using gist (capture_id, interval_ns) where scope = 'interval';
```

**DECISION (del-1).** Tombstones are **never deleted and never expire**. Deletion is monotonic. "Undo
delete" is not offered; a short pre-tombstone grace period in the UI is offered instead.

### 6.3 The gate is a trigger, in the writing transaction

Application-level checks are not sufficient, because retries arrive from stale workers holding
pre-deletion state.

**DECISION (del-2), CORRECTED.** The function this document previously specified **cannot run.** It
was a single polymorphic trigger function reading `NEW.capture_id`, `NEW.entity_id`, `NEW.track_key`,
`NEW.t_start_ns` and `NEW.t_end_ns`, attached to four tables that do not have those columns:
`evidence_span` carries no `capture_id` and no `entity_id`, and `assertion` and `embedding` carry
none of the five. plpgsql resolves `NEW.<field>` when the trigger executes, so the first insert into
`evidence_span` raises `record "new" has no field "capture_id"` and every guarded write path fails.
That is not a guard that fails open; it is a guard that never runs at all, and the failure is loud
rather than silent only because nothing can be written while it is attached.

What was implemented instead: one shared predicate over the address, a small typed trigger per table
shape, and the workspace-context assertion of section 4.5 in front of every one of them.

```sql
-- Does a committed tombstone cover this address?
--
-- VOLATILE, not STABLE, and deliberately so. Under READ COMMITTED a stable function reuses the
-- statement snapshot, so a tombstone committing while this INSERT runs would not be seen. A
-- volatile function takes a fresh snapshot per call, which narrows the
-- time-of-check-to-time-of-use window to the smallest the isolation level allows. The cost is
-- that it cannot be inlined; at this write volume that is not a consideration.
create or replace function tombstone_blocks_span(
  p_workspace uuid, p_blob bytea, p_track text, p_start_ns bigint, p_end_ns bigint
) returns boolean language sql volatile as $fn$
  select exists (
    select 1
      from tombstone t
      left join capture c on c.capture_id = t.capture_id
     where t.workspace_id = p_workspace
       and t.effective_at <= now()
       and (
             t.scope = 'workspace'
          or (t.blocklist_hash and c.blob_sha256 = p_blob)
          or (t.scope = 'capture'
              and c.blob_sha256 = p_blob
              and not exists (select 1 from capture live
                               where live.workspace_id = p_workspace
                                 and live.blob_sha256  = p_blob
                                 and live.deleted_at is null))
          or (t.scope = 'interval'
              and c.blob_sha256 = p_blob
              and t.track_key   = p_track
              and t.interval_ns && int8multirange(int8range(p_start_ns, p_end_ns, '[)')))
       )
  );
$fn$;
```

Three sibling predicates take the same shape: `tombstone_blocks_any_span(workspace, span_ids)`
resolves an array of span ids through `evidence_span` and calls the function above,
`tombstone_blocks_capture(workspace, capture)` covers the capture and interval scopes by
`capture_id`, and `tombstone_blocks_entity(workspace, entity)` covers the entity scope. Five
triggers, each `before insert` and `for each row`, use them:

| Trigger on | What it refuses |
| --- | --- |
| `evidence_span` | the address itself, through `tombstone_blocks_span` |
| `occurrence` | its `capture_id`, and every span in `span_ids` |
| `assertion` | every span in `support_span_ids`, an entity subject named in `subject_ref`, and any workspace-scope tombstone |
| `embedding` | the referenced span or entity, or, for an occurrence reference, that occurrence's capture and spans, and any workspace-scope tombstone |
| `entity_link` | the entity. **Added beyond the four this document named:** without it an entity-scope tombstone has nowhere to bite, because no other guarded table carries `entity_id` in a column |

Three properties of the implemented guard, each of which was implicit before:

- **Context first.** Every trigger calls `assert_workspace_context(new.workspace_id)` before it
  trusts a lookup. Without that the guard reads RLS-protected tables, sees nothing, and permits the
  write. Section 4.5 has the argument in full.
- **The capture branch releases when the bytes are live again.** A capture tombstone stops matching
  once a non-deleted capture in the same workspace claims those bytes, which is what reconciles the
  guard with del-3 in section 6.5: a deliberate re-import creates a new live capture, and its
  derivatives proceed. An interval redaction is **not** released that way, because an interval
  tombstone is a statement about content rather than about one import of it, and deletion is
  monotonic. `blocklist_hash = true` also survives a re-import, which is the point of it.
- **`effective_at <= now()`** is in every branch, so a tombstone scheduled for later does not block
  writes before it takes effect.

Pinned by `tests/test_migration.py::test_the_tombstone_guard_fires_on_every_derived_write_path`,
`::test_every_guard_asserts_the_workspace_context_before_it_trusts_a_lookup` and
`::test_the_tombstone_guard_uses_a_fresh_snapshot`. Those are text-level checks over the migration
file. No server has executed it here, so what is verified is that the SQL says this, not that
PostgreSQL does it.

Because the trigger fires inside the writing transaction and reads the committed tombstone table, the
time-of-check-to-time-of-use race is closed: a worker that checked before the tombstone committed still
fails at insert. Workers treat `tombstoned` as a **terminal, non-retryable** error class and mark the job
cancelled. Note that the interval branch is exactly why section 1.5 insists images carry a real
interval: a NULL bound makes the `&&` test NULL, the enclosing `exists` is then false, and the guard
silently permits the write. An empty range `[0, 0)` fails the same way, because it overlaps nothing.
That is the whole argument for `[0, 1)`.

Supporting measures:

- On tombstone write, the same transaction sets `job.state = 'cancelled'` for every queued job whose
  input is covered.
- The object-store purge is idempotent and runs after commit, driven by a `purge_job` table, so a crashed
  purge resumes rather than being lost.
- `answer_cache` and `evidence_packet` rows carry a GIN-indexed `span_ids` array and are deleted on
  tombstone commit.

**ASSUMPTION.** The guard actually stops a stale worker. Settled by experiment **X-7**, the tombstone
race test: revoke consent while a job for that subject is mid-flight, force the retry policy to fire, and
assert that no derivative row is persisted and a metric is emitted (about 2 hours). This is described in
the experiment plan as the test most likely to find a real bug.

### 6.4 The cascade

| Deleted thing | Soft-marked | Physically purged | Kept |
| --- | --- | --- | --- |
| **Capture** | capture, occurrences, assertions, spans, embeddings, text chunks, derived artifacts, answer caches | original blob bytes, all derivative bytes, all embedding rows, all text-chunk bodies | `blob` stub (hash plus `purged_at`), `pipeline_event` ledger with payloads scrubbed to hashes, the tombstone |
| **Interval** | assertions and occurrences whose `presence` intersects the interval; artifacts overlapping it marked `needs_repair` | embeddings and text chunks derived from the interval; re-encoded clips of it | the rest of the capture; spans outside the interval |
| **Entity** | entity, links, proposals, assertions, entity-level aggregates | person and occurrence embeddings, person-dependent point maps, and every artifact for every reconstruction scene containing the confirmed occurrence; the display-name cache is cleared | source captures and original photograph bytes, `identity_rejection` rows, the dependency and withdrawal receipts |
| **Workspace** | everything | everything, including blobs | an audit stub |

**CORRECTED 2026-09-04. Entity withdrawal is now a production cascade. Interval withdrawal
remains partial.** Migration 0030 adds `person_derivative_dependency`. A confirmed identity link
records edges to the occurrence's point-map artifact, every reconstruction scene and job that
contains its capture whether registration succeeded or not, every retained scene artifact,
person and occurrence embeddings, dependent aggregate rows, and entity or scene assertions.
Triggers fill both directions: a late human confirmation backfills existing targets, and a late
artifact, membership, job, vector, aggregate, or assertion records its edge from existing
confirmed links. Model-only proposals create no destructive authority.

`IngestRepository.insert_tombstone` accepts `entity_id`. The tombstone transaction clears the
display-name cache, soft-deletes the entity, marks dependent aggregates stale, retracts entity
and scene-rung assertions, cancels queued or running reconstruction jobs, and enqueues all
person-dependent stored objects and vector rows. Geometry and world-package reads refuse the
dependency immediately, before the asynchronous purge catches up. The dedicated purge role may
DELETE from `embedding` and no other database table. Stored object bytes still use the
content-addressed privileged purger. `person_withdrawal_releases_artifact` refuses destruction
when any live artifact outside that exact entity dependency still holds the same bytes.

The original photograph is deliberately retained. An entity tombstone is not a media tombstone,
and `capture.deleted_at` remains null. This distinction is exercised in the delete-one-person
tests: the source object stays, unrelated geometry stays, but the linked point map, registered or
unregistered scene, every retained scene build, rung assertion, display identity, aggregate, and
vector leave their serving surfaces. `person_withdrawal_receipt` keeps a canonical, digest-bound,
machine-readable summary; the exact edges and purge jobs remain the detailed evidence.

*Interval scope soft-marks nothing and repairs nothing.* The same early return applies, so an
interval redaction leaves `capture.deleted_at` null and enqueues no purge job. The artifacts the
row above says are marked `needs_repair` are not marked: `mark_needs_repair` has exactly one
caller, `PhotoIngestPipeline.persist_artifact`, and it is the unreproducible-bytes case rather
than anything a tombstone reaches. The embeddings the row says are deleted are not deleted.

*A capture deletion now also reaches every scene that photograph was a member of, and the
reduction over a scene is the INVERSE of the one over a blob.* ADR-0009 D9: a pose receipt, a
splat and a placement record are facts about N photographs, and "a tombstone path that reaches a
scene artifact through any of its members" means deleting ONE of eight withdraws the receipt.
That is the opposite of the rule for a per-capture artifact, where a photograph imported twice is
one artifact and two captures and deleting one withdraws nothing. Migration 0024 carries both:
`tombstone_blocks_scene` answers "may this be served or written" and covers workspace, capture
and interval scope; the third clause of `purge_releases_bytes` answers "may these bytes be
destroyed" and asks `capture.deleted_at`, so it does not act on interval scope, for the reason
the row above already gives. `reconstruction_scene_member` is append-only, because a membership
that could be edited afterwards is a deletion that could be undone by an UPDATE, and del-1 says
deletion is monotonic. Pinned by `tests/test_scene_identity.py`, whose delete-one-of-three case
is D9's own no-ship rule.

The refusal half is deliberately narrower than this row and is not a gap.
`tombstone_blocks_derivative` has no interval branch, and migration 0011 says why: "a redaction
removes a moment and not a photograph", so a new derivative is written and then repaired rather
than refused. What closes the loop for a **still image** is that section 1.5 gives it the single
interval `[0, 1)`: there is no surviving moment to repair from, so the delivery route in
`exulanica/graph/geometry.py` asks `tombstone_blocks_capture`, which does cover interval scope, and
serves nothing derived from a redacted frame. That module says the same thing from its own side,
including the case that would make it the wrong predicate.
`tests/test_geometry_delivery.py` pins this paragraph.

Three consequences that must not be softened:

- **Entity deletion is not media deletion, and the UI must say so.** Deleting a person removes the name,
  the links and the person-level vectors. It does not remove them from the photographs, because that
  would mean deleting the user's own memories. Being vague about this in the UI would be a lie.
- **Aggregates must be recomputed on revocation, not row-deleted.** An exemplar set or centroid computed
  over N faces still encodes a removed face. This is a silent-retention bug and a genuine biometric
  retention issue. Settled by experiment **X-15**: delete one member of a multi-face cluster and verify
  the stored aggregate **changes** rather than persisting its pre-deletion value (about 1 hour).
- **Every generated summary must record the source-id set it was conditioned on**, so a generated title
  naming a person can be invalidated when that person is deleted. Without the recorded set, the name
  survives its own deletion in a caption.

Derivatives overlapping a redacted interval are marked `needs_repair` and regenerated from the surviving
intervals with a new `input_digest`, so the repaired artifact has a different identity key and cannot
collide with the tainted one. Embeddings derived from redacted content are **deleted, not hidden**: an
embedding of a redacted region still leaks it under inversion.

### 6.5 The re-upload trap

**DECISION (del-3).** A capture tombstone is keyed by `(workspace_id, capture_id)`, **never** by blob
hash. A hash-keyed tombstone permanently blocklists those exact bytes, so a user who deleted something
and later deliberately re-imported it would be silently blocked with no way to explain why. Re-uploading
the same bytes creates a **new** `capture_id` and proceeds normally. A user who genuinely wants "never
let this content back in" sets `blocklist_hash = true` explicitly, and only then does the guard also
match on `blob_sha256`. Two different intents, two different mechanisms.

**CORRECTED.** The schema in section 4.1 previously carried `unique (workspace_id, blob_sha256)` on
`capture`, which contradicts this decision outright: the re-import has nowhere to land, so the user
is silently blocked by a uniqueness error instead of by a blocklist. Two things were changed to make
the decision real. The constraint is now the partial unique index `where deleted_at is null`, so a
live duplicate still collapses to one capture while a re-import after a deletion gets a fresh
`capture_id`. And the guard's capture branch releases once a live capture claims those bytes again,
so the new capture's derivatives are not refused by the old capture's tombstone. `blocklist_hash`
keeps blocking in both cases, which is the whole difference between the two intents.

### 6.6 The honest limits

These are limits of the system, not of the implementation. They must appear in the product, not only
here.

| Limit | Why it exists | What is actually promised |
| --- | --- | --- |
| **Object versions persist** | Nebius Object Storage supports no WORM, no Object Lock and no Legal Hold, so append-only is a policy enforced by IAM. The same versioning that protects originals from accidental loss also preserves them against erasure | **Crypto-shredding is the primary erasure mechanism**: a per-capture key wrapped by a per-person key wrapped by a per-tenant KMS key. Destroying the key makes retained versions unreadable ciphertext. Say exactly that, not "the bytes are gone" |
| **Backups predate the deletion** | Any restore from a pre-deletion backup reintroduces deleted rows | Tombstone replay is a **mandatory, gated, tested** step in the restore runbook. A restored instance does not accept traffic until every tombstone with `effective_at` at or before the restore point has been replayed. Settled by experiment **X-12** (about 4 hours) |
| **Provider retention** | Inference requests leave the machine. Retention is the provider's policy, not ours | Zero-data-retention must be confirmed in writing for the specific model IDs in use, committed to the repository, and **asserted at service boot with a refusal to start otherwise**. This is recorded as assumption A-8 and is unvalidated until that confirmation exists |
| **Already-exported artifacts cannot be recalled** | A World Memory Package handed to a third party is a copy outside the system | Disclosed **at export time**, in the export dialog, not buried. Re-exporting after a deletion produces a new version with a different Merkle root, and the diff between two versions is the honest answer to "what changed" |
| **Vector index residency** | A row deleted from a table may persist inside an ANN index until compaction | Settled by experiment **X-11**: delete an embedding, force compaction or partition rebuild, open the raw index and assert the vector id is **physically absent**, not merely filtered from results (about 3 hours). Until that passes, no maximum-residency number may be published |

**DECISION.** The words "unlearning", "forgetting" and "the model has forgotten" are banned from all
Exulanica material. The truthful phrasing is: *removed from retrieval and from future training, with every
derived artifact recomputed from the remaining data.* Because there are no trained weights at MVP, that
recomputation is exact by construction, which is a **stronger** claim than the approximate-unlearning
literature can support: an audit of ten unlearning methods found that Fisher Forgetting, Hessian
Forgetting and Certified Hessian Forgetting all fail to achieve the true objective despite formal
certifications (<https://arxiv.org/html/2606.16110v1>, VERIFIED 2026-08-27).

**CORRECTED 2026-09-04, [adr/0017-exact-recomputation.md](adr/0017-exact-recomputation.md): "exact by
construction" was scoped too widely.** It is true of the stages that are pure functions of their
inputs. It is not true of a stage that calls a model. Sampled generation differs run to run by
design, and a neural forward pass differs across accelerators and library versions even at
temperature zero, so a re-run of a model stage produces a *different artifact*, not the same bytes.

Stages that are not exactly recomputable, and therefore excluded from that claim: `vision`,
`depth`, `segmentation`, `scene_splat_training`, `scene_splat_delivery`, and `generated_scene`.
`vision` and `depth` carry a `model_role`; all six have `stage_registry.deterministic=false`. The
Gaussian stages optimize scene-specific parameters and compress their result; their presence does
not establish reproducible GPU output. `generated_scene` is a world model's own sampled output,
which differs run to run by design; it carries no `model_role` because the generating model is
supplied per generation rather than routed through the reviewed model manifest, and its identity
travels in the generation receipt. `segmentation` runs local checkpoints whose forward pass differs
across accelerators and library versions; it carries no `model_role` because those checkpoints are
pinned by revision in the manifest's local section and their identity enters its input digest per
photograph, as the person-region stage does for its detector (added 2026-09-11, see
[scene-segments.md](scene-segments.md)).
`StageSpec` now refuses to construct a stage that names a model role and declares itself
deterministic, so the exclusion cannot be lost by editing a flag.

**UPDATED 2026-09-05.** The historical statement that there are no trained weights does not cover
the added Gaussian scene parameters. They are scene reconstruction artifacts, not biometric
templates. Withdrawal invalidates their scene and removes their published bytes and private
operational artifacts through the existing scene deletion machinery; no model-unlearning claim
is made. See [the training/rung decision](adr/gsplat-training-and-recorded-rung.md).

What is true of a model-produced artifact under deletion is narrower and is what the product says
instead: **it is invalidated and removed, not regenerated.** `derived_artifact.stale` is set through
`dep_index`, and no deletion path re-runs a model. Nothing about the account holder survives inside
a caption, because the caption is gone rather than rewritten.

A third case is neither: `scene_pose` is declared deterministic because it fixes COLMAP's
`random_seed`, which makes a differing pose worth an event. `exulanica/reconstruction/pycolmap_executor.py`
records that RANSAC threading still admits variation and that the residual has not been measured, so
the stage is **declared deterministic and not yet observed to reproduce**, and only the second of
those licenses an exact-recomputation claim.

**ASSUMPTION (A-24), NARROWED.** Deleting an exemplar and recomputing the **deterministic** closure
yields a bit-identical state. Settled by experiment **X-8**, the deletion closure test: delete one
exemplar, run the recompute path, build a fresh state from the remaining rows, and assert byte
equality of exemplars, negatives, cohort membership and index (about 1 day). Any nondeterminism
(ordering, float reduction order, coreset tie-breaking) must be eliminated, or the claim must be
weakened further. **This claim may not be made publicly until X-8 passes**, and it may never be made
about any of the excluded model/scene-training stages above.

Pinned by `tests/test_exact_recomputation.py`, which derives the excluded list from the registry
rather than trusting the sentence above.

---

## 7. The provenance ledger and Assembly Replay

Modelled on the PROV-O Entity / Activity / Agent triad but flattened into two append-only tables,
because what is needed is one queryable event stream for a replay UI, not an RDF graph.

**VERIFIED.** PROV-O is a W3C Recommendation dated 2013-04-30 with starting-point classes
`prov:Entity`, `prov:Activity`, `prov:Agent` and properties `wasGeneratedBy`, `used`, `wasDerivedFrom`,
`wasAttributedTo`, `wasAssociatedWith` and `wasInformedBy`. Source: <https://www.w3.org/TR/prov-o/>
(2026-08-27).

```sql
create type pipeline_event_type as enum (
  'run_started','stage_started','input_resolved','artifact_written','stage_succeeded',
  'stage_failed','retry_scheduled','nondeterminism_detected','assertion_emitted',
  'proposal_emitted','tombstone_applied','run_succeeded','run_failed','run_cancelled'
);

create table pipeline_run (
  run_id       uuid primary key default uuidv7(),
  workspace_id uuid not null,
  capture_id   uuid references capture(capture_id),
  trigger      text not null,            -- 'ingest'|'reprocess'|'repair'|'manual'
  started_at   timestamptz not null default now(),
  ended_at     timestamptz,
  status       text not null default 'running'
);

create table pipeline_event (
  event_id            uuid primary key default uuidv7(),  -- uuidv7 gives global time ordering
  run_id              uuid not null references pipeline_run(run_id),
  seq                 bigint not null,                    -- gapless per run
  parent_event_id     uuid references pipeline_event(event_id),
  type                pipeline_event_type not null,

  stage_key           text,      -- 'ingest','exif','ocr','caption','detect','embed','recon'
  stage_version       int,
  model_ref           jsonb,     -- {provider, model_id, revision, endpoint, dtype}
  params_digest       bytea,

  input_artifact_ids  uuid[] not null default '{}',   -- RECORDED, never implied by code shape
  output_artifact_ids uuid[] not null default '{}',
  input_blob_sha256   bytea,

  attempt             int not null default 1,
  max_attempts        int,
  error_class         text,
  error_message       text,

  started_at          timestamptz,
  ended_at            timestamptz,
  duration_ms         int,
  cost                jsonb,     -- {input_tokens, output_tokens, gpu_seconds, usd_estimate}
  host                text,
  occurred_at         timestamptz not null default now(),
  unique (run_id, seq)
);
create index on pipeline_event (run_id, seq);
create index on pipeline_event using gin (output_artifact_ids);
```

**DECISION (prov-1).** `input_artifact_ids` is **mandatory** on `stage_started`. The Assembly Replay must
reconstruct the DAG from the ledger alone, without reading source code. If the DAG is only implicit in
the code, the replay lies as soon as the code changes, and it lies most convincingly about old runs.

The Assembly Replay is then a straight query: `select * from pipeline_event where run_id = $1 order by
seq`, joined to `artifact` for clickable outputs, rendered as a swimlane per stage with retries visible
as repeated attempts. The chain is closed in both directions: every artifact in the replay opens, every
assertion traces to its spans, every span opens at the exact source moment.

**DECISION.** The ledger survives deletion, with payloads scrubbed to hashes (section 6.4). A ledger that
is purged along with its subject cannot answer "what happened to my data", which is the one question a
deletion needs the ledger to answer.

**ASSUMPTION (A-29).** The ingest pipeline can emit real per-stage counters over SSE. This is load-bearing
for the interaction design's "processing as spatial formation" beat, which degrades to a progress
indication without it. It is a 2-hour inspection of stage boundaries and should be done early.

---

## 8. The World Memory Package is a projection, not the store

### 8.1 The finding

**The research finding, preserved as stated: content addressing plus an append-only ledger plus a right
to erasure is an unsatisfiable triple.** Every candidate export format that gives strong versioning and
reproducibility gives it by making history immutable. If the package is the database, deletion becomes a
lie.

The legal backdrop, verified: GDPR does not itself define erasure, and erasure may be satisfied by
irreversible destruction of the link between the data and the data subject. Standard guidance for
immutable stores is to keep personal data off them entirely.
Source: <https://arxiv.org/pdf/2210.04541> (VERIFIED 2026-08-27).

### 8.2 The consequence: two zones

**DECISION (wmp-1).**

| | Zone 1: live store | Zone 2: World Memory Package |
| --- | --- | --- |
| What | PostgreSQL plus blob storage | A materialised RO-Crate produced by projecting zone 1 at an instant |
| Mutability | Mutable. Rows are deletable | Immutable once written, content addressed, signed |
| Raw media | Lives here, and only here | **Excluded by default**, described via fetch-style external references with digests, so a recipient can verify but not read |
| Embeddings and identity exemplars | Live here | **Excluded by default** |
| Append-only content | The pipeline ledger only, with payloads scrubbed to hashes on deletion | The whole package, by construction |
| Deletion | Real and complete | Not possible. A package already exported cannot be recalled |

*Rejected alternative:* make the content-addressed, append-only package **be** the live store, which is
the design that gives the strongest reproducibility and provenance story. Rejected because it makes
deletion impossible, and deletion is a hard requirement of this product, not a feature.

*Rejected alternative:* DVC or a Git-coupled pointer system. Rejected on the same axis: erasing an
exemplar from Git history is a history rewrite, and any clone retains it. That is exactly the wrong
property for personal biometric-adjacent data.

### 8.3 The format

**DECISION (wmp-2).** RO-Crate 1.2 as the package format, published under an Exulanica profile crate, with
a Croissant 1.0 plus RAI descriptor for the learning dataset **embedded in the same JSON-LD graph**,
BagIt-style fetch semantics for excluded raw media, and a signed Merkle-root manifest supplying the
versioning that RO-Crate does not provide.

**VERIFIED.** RO-Crate 1.2 requires exactly one `ro-crate-metadata.json` at the crate root, is JSON-LD
over schema.org, adds profile crates and detached crates, and is backwards compatible with 1.1. Croissant
is at version 1.0 (published 2024-03-01), also JSON-LD over schema.org, with a RAI extension providing
`rai:dataCollection`, `rai:dataAnnotationProtocol`, `rai:personalSensitiveInformation` and related
consent and provenance vocabulary. **Because both are JSON-LD over schema.org, a Croissant `sc:Dataset`
can be a node in the same graph as the RO-Crate root.** Sources:
<https://www.researchobject.org/ro-crate/specification/1.2/structure>,
<https://docs.mlcommons.org/croissant/docs/croissant-spec.html>,
<https://docs.mlcommons.org/croissant/docs/croissant-rai-spec.html> (2026-08-27).

**VERIFIED.** BagIt (RFC 8493) requires a payload manifest with a checksum per payload file, and
`fetch.txt` declares payload items held **outside** the bag, which maps precisely onto "raw private media
described but not packaged". Source: <https://www.rfc-editor.org/rfc/rfc8493.html> (2026-08-27).

*Rejected alternative:* OCI image spec 1.1 artifacts, which are genuinely attractive as a distribution
layer (`subject` plus the Referrers API is a clean way to attach an evaluation report to a package
version). Deferred post-MVP as a transport option, not the format: it needs a registry to be worth
anything, deletion in registries is tag-and-garbage-collect rather than erasure, and it imposes no
schema.

*Rejected alternatives, briefly:* Frictionless Data Package v2 (narrower than Croissant for ML and
narrower than RO-Crate for provenance), LakeFS (needs a running server and S3-compatible storage),
Delta Lake and Iceberg (need a query engine), and a hand-rolled content-addressed directory (what every
other option degenerates to, minus interoperability; its Merkle-root idea is adopted).

### 8.4 What must be said in the product

- Deletion in zone 1 is real and complete, subject to the limits in section 6.6.
- A package exported to a third party **cannot be recalled**. The export dialog says this before the
  export runs, not after.
- Re-exporting after a deletion produces a new version with a different Merkle root. **The diff between
  two package versions is the honest answer to "what changed".**

---

## 9. Where this document is not settled

Collected so nothing above has to be re-read to find the gaps.

### 9.1 What blocks a v1 freeze of the address format

These are the items inside the address. `span_digest` is a SHA-256 over the address tuple, so every
one of them is baked into every citation token, every permalink and every archived answer the moment
a span is written. **Adding a new field or a new enumerated value is additive. Changing the meaning
or the spelling of an existing one is not**: it is a v2 span format, written alongside v1, with a
documented and verified migration of every existing span. That is the whole reason this list is kept
separately from the general gaps below.

The corpus is small and the number of spans is currently near zero, which makes now the cheapest
moment these decisions will ever have. The window closes at first production ingest, and for the
timebase item specifically at first video ingest.

| Item | Status | Why it is inside the address | What settles it |
| --- | --- | --- | --- |
| EXIF Orientation has eight values, four of them mirrored; `media_track.rotation` allows only 0/90/180/270 | **CLOSED 2026-09-04** | `region.display` carries `rotation`, and the region is normalised against display space. A mirrored original puts every region on the wrong side of the image, permanently | Settled by ADR-0004 and [adr/0012-upright-display-space.md](adr/0012-upright-display-space.md): pixels are normalised at ingest, all eight values are admitted, `img` regions carry `display.rotation = 0`, and `media_track.rotation` means "still to apply" and is 0. Enforced by two check constraints in `0032_upright_display_space.sql`. No digest changed |
| Whether OCR text spans reuse `modality = 'transcript_text'` or take their own value | **CLOSED 2026-09-04** | `modality` is a digest input, and re-labelling spans already issued changes their digests | Neither. [adr/0016-ocr-is-a-region.md](adr/0016-ocr-is-a-region.md): OCR text is a `frame_region` span carrying an `ocr_text_is` assertion, which is what was already written. `transcript_text` is reserved for time-anchored transcripts and refused on the `img` track. The five modality values are unchanged |
| The tie direction of `round_half_down` | **CLOSED 2026-09-04** | It determines the quantisation of every region coordinate and every EXIF position | Ratified as ties toward zero by [adr/0015-timebase-rounding.md](adr/0015-timebase-rounding.md). It no longer takes part in the timebase at all |
| Tick to ns to tick is not the identity | **CLOSED 2026-09-04** | Both formulas produce values that go into the digest | Corrected, not carried: `ns_from_ticks` rounds up, the round trip is exact on every representable timebase, and it cost nothing because the conversion had no callers and no video or audio track had ever been written. ADR-0015, section 1.4 |
| The region encoding: parts per million on a `[0, 1_000_000]` integer grid | **CLOSED 2026-09-04** | `region` is a digest input, and a float has no canonical rendering that two implementations agree on. Changing the grid changes every region digest | Ratified as it stands by [adr/0013-region-encoding.md](adr/0013-region-encoding.md), and now enforced by `evidence_span_region_shape` in `0033_span_digest_input_shape.sql` rather than described in a comment. Nine malformed tuples are refused by `tests/test_span_digest_input_shape.py` |
| The digest encodings: lowercase hex for `blob_sha256`, absent keys rather than nulls, `prefix` and `suffix` excluded from `text_anchor` | **CLOSED 2026-09-04** | They are the difference between a digest that reproduces and one that does not | Ratified by [adr/0014-digest-encodings.md](adr/0014-digest-encodings.md) against a second implementation: `scripts/verify_canonical_conformance.mjs` reproduces the exact canonical bytes and digest of all seven vectors in `tests/vectors/span_digest_v1.json` outside Python. The algorithm is identified by `span_format_version`, which is itself inside the digest input |
| Whether the corpus contains motion photographs or bursts carrying a real embedded video track | **CLOSED 2026-09-04** | If one were ingested it would be stored as its first frame under a capture describing the whole file, and every span would address `img` on a blob whose other frames nothing can cite | Closed by refusing rather than by inspecting: `exulanica/ingest/decode.py` refuses any container holding more than one frame, at the header probe and at the decode, with a message naming the video path |

### 9.2 Everything else

| Item | Status | What settles it |
| --- | --- | --- |
| EXIF Orientation has 8 values including mirrored variants; `media_track.rotation` allows only 4 | **CLOSED 2026-09-04** | Pixels are normalised at ingest and the normalisation is recorded. ADR-0004, ADR-0012, section 9.1 |
| Whether OCR text spans reuse `modality = 'transcript_text'` or take their own modality value | **CLOSED 2026-09-04** | Neither: OCR text is a `frame_region` span with an `ocr_text_is` assertion. ADR-0016, section 9.1 |
| Whether the corpus contains motion photographs or bursts carrying a real embedded video track | **CLOSED 2026-09-04** | Closed by refusing a multi-frame container at ingest rather than by inspecting the corpus. Section 1.5 |
| The tie direction of `round_half_down` | **CLOSED 2026-09-04** | Ratified as ties toward zero, ADR-0015 and section 9.1 |
| Tick to ns to tick is not the identity under the frozen formulas | **CLOSED 2026-09-04** | Corrected inside its decision window; the round trip is now exact. ADR-0015 and section 9.1 |
| Whether migration `0001_spine.sql` applies at all | **VERIFIED 2026-09-04** | `tests/test_migration.py::test_the_migration_actually_applies` runs against PostgreSQL 18.6 with pgvector, nothing substituted. All thirty-four migrations apply, and 1445 of 1447 tests pass with a server configured |
| Whether exact search over `halfvec(4096)` stays fast enough as the library grows | **ASSUMPTION** | Measurement at corpus scale. The additive fallback is a truncated 1024-dimension recall column, section 4.4 |
| Browser seek accuracy against ffmpeg PTS | ASSUMPTION A-31 | Experiment X-3. Not live for a photograph corpus; becomes live when video arrives |
| Re-anchor rate across model versions | ASSUMPTION | Experiment X-19 |
| Structured-answer schema conformance | ASSUMPTION A-32 | Experiment X-4 |
| Cross-capture identity recall | ASSUMPTION A-18 | Experiment X-6. **No recall number may be published before it runs** |
| `identity_key` quantization stability | ASSUMPTION A-25 | Two detector runs at different versions, measure collision against miss rate |
| Calibration bin size of 30 | ASSUMPTION A-26 | Confidence-interval width on empirical p, once confirmation data exists |
| Tombstone guard stops a stale worker | ASSUMPTION | Experiment X-7 |
| Vector-index physical residency after delete | ASSUMPTION | Experiment X-11 |
| Restore with tombstone replay | ASSUMPTION | Experiment X-12 |
| Exact recomputation is bit-identical | ASSUMPTION A-24 | Experiment X-8. **The claim may not be made before it passes** |
| Provider zero-data-retention across all endpoints in use | ASSUMPTION A-8 | Written confirmation from the provider for the specific model IDs, committed to the repository, asserted at service boot |
| pgvector behaviour at production scale | ASSUMPTION A-27 / A-30 | Experiment X-18. Safe at demo scale regardless |
| Workspace is one user at MVP | ASSUMPTION A-30 | A product decision, not a technical one |
| When a biometric embedding may exist at all | **OPEN** | A risk-appetite decision, not a technical one. Three incompatible rules were proposed and the evidence does not choose between them. Tracked as open item P-1 in `product-specification.md` section 10. **Identity work must not begin before it is answered** |
| C2PA as a future device-signing option | not a dependency | The existence of the specification and the hard-binding concept are verified; exact clause numbering is unverified. Noted as future-compatible, never as an MVP dependency |
