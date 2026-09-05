# ADR-0015: Ratify the tie direction, and correct the tick conversion inside its decision window

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build

## Context

Two timebase items sat in `docs/domain-and-evidence-model.md` section 9.1, both inside the address:

1. **The tie direction of `round_half_down` was OPEN.** The committed contract named the rule in the
   frozen tick-to-nanosecond formula and never defined it. Two readings are plausible, ties toward
   zero and ties toward negative infinity, and they differ only on exact negative halves. Negative
   `t_ns` is real: it occurs whenever a container's `start_pts` is later than track zero, which edit
   lists produce routinely. The implementation took ties toward zero and the document called that an
   interpretation rather than a decision.
2. **Tick to ns to tick was not the identity, pinned as a KNOWN DEFECT.** `ns_from_ticks` rounded to
   nearest while `ticks_from_ns` floors, so any tick whose nanosecond value rounded down landed back
   on the previous tick. At 48 kHz, tick 1 rendered as 20833 ns and 20833 ns floored straight back to
   tick 0. A citation stored in nanoseconds and converted back to a tick for a seek would open one
   sample early. The document said the decision window closes at first video ingest.

## Decision

### 1. `round_half_down` is ties toward zero. Ratified.

The standard reading of the name, the one `decimal.ROUND_HALF_DOWN` and Java's
`RoundingMode.HALF_DOWN` take. It is implemented in exact integer arithmetic and pinned by
`tests/test_blob_and_canonical.py::test_round_half_down_is_ties_toward_zero`, including the negative
exact halves that are the only place the two readings differ.

`round_half_down` remains the project's one rule for **quantising a measured value**: the region ppm
grid (ADR-0013) and the EXIF GPS and altitude conversions. It no longer takes part in the timebase.

### 2. `ns_from_ticks` rounds up. Corrected.

    ticks(t_ns) = floor( (t_ns * den) / (num * 1_000_000_000) )      unchanged
    t_ns(ticks) = ceil( ticks * num * 1_000_000_000 / den )          was round_half_down

Placing a tick on the nanosecond axis is not quantising a measurement, it is choosing a boundary, and
the requirement is that the choice is **invertible**. `ticks_from_ns` answers "which tick contains
this nanosecond", so only a boundary at or after the true instant lands back on the tick it came
from. Rounding to nearest reads as the more accurate choice and is the one that loses the sample.

Ceiling is toward **positive infinity**, not away from zero, because `ticks_from_ns` floors toward
negative infinity and the inverse has to round the same direction to compose. Away from zero would
be exact for positive times and lose a sample for negative ones, which is the harder failure to
notice because negative `t_ns` only appears when a container carries an edit list.

`ticks(t_ns(k)) == k` now holds for every `k` on every timebase whose tick is at least one
nanosecond, verified across 48 kHz, 44.1 kHz, 90 kHz, 1/15360, NTSC 1001/30000 and the canonical axis
itself, for negative ticks as well as positive.

**The correction is not a `span_format_version` event, and this is the load-bearing judgment.**
The document said it would be, because it would move `t_start_ns` and `t_end_ns` for spans derived
through the conversion. At the moment it was taken, the audit established that there were none:

- `ns_from_ticks` and `ticks_from_ns` had **no callers anywhere outside this package's own tests**;
- no `media_track` row with `kind` `video` or `audio` had ever been written, by any code path;
- every span in existence is a photograph carrying `[0, 1)` directly, and on the canonical
  `1/1_000_000_000` timebase ceiling and nearest agree on every value.

Not one stored digest moved. Writing a v2 span format alongside v1 would have produced two formats
that agree on every span that exists, which is worse than a corrected v1: it doubles the read paths
forever to record a difference nothing can observe. `span_format_version` therefore stays at 1, and
`tests/test_span_digest_conformance.py` pins the exact bytes of the corrected v1.

This is the last moment that argument is available. The window the document described closes at first
video ingest, and it is now closed by the correction rather than by the ingest.

### 3. A timebase finer than one nanosecond is refused

`TimeBase` refuses `den > num * 1_000_000_000`. Two ticks sharing one `t_ns` cannot both round trip,
so admitting one would mean storing boundaries that cannot be inverted. No container declares such a
timebase; the finest representable is `1/1_000_000_000`, which is the image timebase.

### 4. `ns_from_ticks` refuses a result outside int64

The canonical axis is signed int64 nanoseconds, which is 292 years. A PTS beyond that is a corrupt or
misread value, and the useful place to say so is the conversion, where the timebase is still in hand
to put in the message, rather than three layers later at the `bigint` column.

### 5. Boundary behaviour, restated and unchanged

Intervals are half-open `[start, end)`, matching Media Fragments URI 1.0. Abutting intervals do not
overlap. An empty interval is refused at construction, because an empty range overlaps nothing and
would make the tombstone interval guard fail open silently. `seconds_to_ns` and `ns_to_seconds` round
trip exactly over int64, and a sub-nanosecond seconds string is refused rather than rounded.

## Compatibility impact

None observable. No stored `t_start_ns`, `t_end_ns` or `span_digest` changes, for the reasons above.
The retained conformance vector for the audio case moved from ticks rendered under the old rule to
ticks rendered under the new one; it is a test fixture, and it is now derived through the conversion
rather than written as a literal, so a future change to the rule fails the pin instead of moving real
citation boundaries quietly.

## Failure behaviour

- A timebase with a sub-nanosecond tick, or a non-positive component, raises `InvalidAddressError` at
  construction naming the finest representable timebase.
- A tick whose nanosecond value leaves int64 raises `InvalidAddressError` naming the tick and the
  timebase.
- An empty or reversed interval raises `InvalidAddressError` and is refused by `span_non_empty` in
  the schema.

## What this touches

| Surface | Change |
| --- | --- |
| Evidence | `exulanica/canonical.py` gains `ceil_div`; `exulanica/evidence/timebase.py` uses it, bounds the result, and refuses a sub-nanosecond tick |
| Schema and migrations | None. No column, constraint or stored value changes |
| APIs, workers, exports, deletion, browser | None. The conversion had no callers outside tests |
| Tests | `tests/test_timebase.py` replaces the lossy-round-trip pin with an identity pin across six timebases; `tests/test_blob_and_canonical.py` pins both rounding rules; `tests/vectors/span_digest_v1.json` binds the audio vector to the conversion |

## Consequences

Two section 9.1 rows close: the tie direction, and the tick round trip. Video ingest no longer
carries a timebase precondition, and the "correct it or carry it" decision no longer has to be made
under time pressure at the moment a video first arrives.
