# ADR-0013: Ratify the parts-per-million integer grid as the canonical region encoding

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build

## Context

`docs/domain-and-evidence-model.md` section 9.1 listed the region encoding as a **DECISION taken in
the implementation, needs ratification**: the committed schema said a region is "normalised to
`[0,1]` in display space" and never said how the number is encoded. `region` is inside `span_digest`,
so the gap is load bearing. `0.312` written by Python and `0.312` written by another JSON writer can
hash differently while denoting the same box, and the resulting citation token verifies against
nothing.

`exulanica/evidence/region.py` chose integers in parts per million of the unit square. The choice has
been in place since the module was written and was never ratified, and the schema enforced none of
it: migration 0001 declared `region jsonb` and described the tuple in a comment.

## Decision

**Ratified as it stands.** A region is
`{kind: 'rect', rect: {x, y, w, h}, display: {w, h, rotation, sar_num, sar_den}}`, integers
throughout, with `rect` coordinates in parts per million of the normalised unit square, `0` to
`1_000_000`, measured in upright display space (ADR-0012).

The invariants, now enforced by `evidence_span_region_shape` in migration
`0033_span_digest_input_shape.sql` as well as by the dataclasses:

- every value is a non-negative integer, spelled as an integer. A regex over the rendered text
  refuses `0.312`, `3.12e5` and `-1` in one check, which a numeric range test would not: `jsonb_typeof`
  calls a float a number too;
- `w >= 1` and `h >= 1`. A zero-area region overlaps nothing, so every overlap guard would pass it,
  which is the same reason an empty interval is refused;
- `x + w <= 1_000_000` and `y + h <= 1_000_000`;
- `display.rotation` is one of `0`, `90`, `180`, `270`, and is `0` on the `img` track (ADR-0012);
- no key outside the named set, and no member missing.

**Why one ppm and not something else.** One ppm of a 6000 pixel wide photograph is 0.006 px, three
orders of magnitude below any detector's own precision, so the grid loses nothing real. It divides
evenly into the Media Fragments percentage rendering: one ppm is exactly 0.0001 percent, so
`Rect.as_percent_string` is lossless at four decimal places and parses back to the same integers.
A power-of-two grid (say 2^20) would have been marginally finer and would have made every rendered
percentage a repeating decimal, which is a worse trade for a value that appears in permalinks.

**Why `kind` is present even though only one value exists.** It is a discriminator. Adding a polygon
kind later is then additive and changes the digest of no rectangle already issued. Removing `kind`
now and adding it later would change every one of them.

## Compatibility impact

None. Every constraint describes what `exulanica.evidence.region` already writes; no existing row can
violate one, and no digest changes. Quantisation from a float goes through `Fraction` and then
`round_half_down` (ADR-0015), so it is exact rather than platform dependent.

Changing the grid later is a `span_format_version` event, not a patch: it changes every region digest
and therefore every citation token, permalink and archived answer containing one.

## Failure behaviour

A malformed region is refused twice and never stored: `InvalidAddressError` from `Rect` or
`DisplayGeometry` with a sentence naming the rule, and SQLSTATE 23514 from
`evidence_span_region_shape` on a route that does not go through those classes.

## What this touches

| Surface | Change |
| --- | --- |
| Schema | `0033_span_digest_input_shape.sql`: `evidence_span_region_shape`, plus a column comment stating the frozen tuple |
| Migrations | Forward only |
| Evidence | No behaviour change. `exulanica/evidence/region.py` already produced this shape |
| APIs | No change. `graph-client` already carries ppm integers over the wire |
| Browser | No change. `web/packages/graph-client/src/read-model.ts` models `EvidenceRegion` as `xPpm`/`yPpm`/`wPpm`/`hPpm` |
| Workers, exports, deletion | No change |

## Tests

- `tests/test_span_digest_input_shape.py` writes nine malformed region tuples through raw SQL and
  requires the database to refuse each, and writes the two shapes the pipeline really produces and
  requires it to accept them.
- `tests/vectors/span_digest_v1.json` pins the canonical bytes of a real region tuple, and
  `scripts/verify_canonical_conformance.mjs` reproduces them outside Python (ADR-0014).
