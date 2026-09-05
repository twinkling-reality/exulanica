-- 0033_span_digest_input_shape.sql
-- Freeze the shape of the span digest input, which 0001 described in comments and enforced
-- nowhere. ADR-0013 (region encoding) and ADR-0014 (digest encodings and algorithm
-- identification) record why each of these is inside the address rather than beside it.
--
-- The failure this prevents is not a crash. It is a row that stores 0.312 where the writer meant
-- 312000, or a `text_anchor` carrying the `prefix`/`suffix` keys 0001's comment mentions and the
-- implementation never wrote. Either one produces a `span_digest` that a second implementation
-- reading the same address computes differently, and the citation token verified against it then
-- fails for a reason nothing in the row explains.
--
-- Every constraint below describes what `exulanica.evidence` already writes. No existing row can
-- violate one, and no digest changes.

begin;

select pg_advisory_xact_lock(119622309);

comment on column evidence_span.span_digest is
  'SHA-256 over the RFC 8785 subset canonical JSON of the address tuple, as produced by '
  'exulanica.canonical.canonical_json: sorted keys, no insignificant whitespace, UTF-8 with '
  'non-ASCII emitted literally, no floats anywhere, optional members absent rather than null. '
  'The algorithm and the canonicalisation are bound to span_format_version: v1 means exactly '
  'this pair, and changing either is a v2 span format written alongside v1, never a rewrite.';

comment on column evidence_span.region is
  'The frozen region digest tuple: {kind:''rect'', rect:{x,y,w,h}, display:{w,h,rotation,'
  'sar_num,sar_den}}. Every value is a non-negative integer; rect coordinates are parts per '
  'million of the normalised unit square, 0..1000000, in upright display space (ADR-0012). '
  'kind is a discriminator so a polygon kind can be added later without changing the digest of '
  'any rectangle already issued.';

comment on column evidence_span.text_anchor is
  'The frozen text anchor digest tuple: {artifact_id, char_start, char_end} plus optional '
  '`exact`. The `prefix` and `suffix` keys named in 0001''s comment were never written and are '
  'excluded permanently: quote context is a highlight aid, and putting it inside the address '
  'would make a citation depend on text either side of the thing it cites.';

-- The region tuple. `jsonb - text[]` removes the named keys, so comparing the remainder to an
-- empty object is an exact "no key outside this set" test that a CHECK constraint can hold.
alter table evidence_span
  add constraint evidence_span_region_shape check (
    region is null or (
      region ->> 'kind' = 'rect'
      -- Present AND nothing else. `?&` catches a missing member, which the key-removal test
      -- below cannot: removing keys from a NULL sub-object yields NULL, and a CHECK passes on
      -- NULL. A region that lost its display space would otherwise slip through, and the
      -- display space is exactly what the coordinates are normalised against.
      and region ?& array['kind', 'rect', 'display']
      and region -> 'rect' ?& array['x', 'y', 'w', 'h']
      and region -> 'display' ?& array['w', 'h', 'rotation', 'sar_num', 'sar_den']
      and region - array['kind', 'rect', 'display'] = '{}'::jsonb
      -- Parenthesised because subtraction binds tighter than `->`: without them PostgreSQL
      -- reads `'rect' - array[...]` and tries to parse the key as jsonb.
      and (region -> 'rect') - array['x', 'y', 'w', 'h'] = '{}'::jsonb
      and (region -> 'display') - array['w', 'h', 'rotation', 'sar_num', 'sar_den']
            = '{}'::jsonb
      -- Integers, spelled as integers. A regex over the rendered text refuses 0.312, 3.12e5 and
      -- -1 in one check, which a numeric range test would not: jsonb_typeof calls a float a
      -- number too, and a float has no canonical rendering two implementations agree on.
      and region -> 'rect' ->> 'x' ~ '^(0|[1-9][0-9]*)$'
      and region -> 'rect' ->> 'y' ~ '^(0|[1-9][0-9]*)$'
      and region -> 'rect' ->> 'w' ~ '^(0|[1-9][0-9]*)$'
      and region -> 'rect' ->> 'h' ~ '^(0|[1-9][0-9]*)$'
      and region -> 'display' ->> 'w' ~ '^[1-9][0-9]*$'
      and region -> 'display' ->> 'h' ~ '^[1-9][0-9]*$'
      and region -> 'display' ->> 'sar_num' ~ '^[1-9][0-9]*$'
      and region -> 'display' ->> 'sar_den' ~ '^[1-9][0-9]*$'
      and (region -> 'display' ->> 'rotation') in ('0', '90', '180', '270')
      -- Non-empty and inside the unit square, for the same reason an empty interval is refused:
      -- a zero-area region overlaps nothing, so every overlap guard would pass it.
      and (region -> 'rect' ->> 'w')::bigint >= 1
      and (region -> 'rect' ->> 'h')::bigint >= 1
      and (region -> 'rect' ->> 'x')::bigint + (region -> 'rect' ->> 'w')::bigint <= 1000000
      and (region -> 'rect' ->> 'y')::bigint + (region -> 'rect' ->> 'h')::bigint <= 1000000
    )
  );

alter table evidence_span
  add constraint evidence_span_text_anchor_shape check (
    text_anchor is null or (
      text_anchor ?& array['artifact_id', 'char_start', 'char_end']
      and text_anchor - array['artifact_id', 'char_start', 'char_end', 'exact'] = '{}'::jsonb
      and text_anchor ->> 'char_start' ~ '^(0|[1-9][0-9]*)$'
      and text_anchor ->> 'char_end' ~ '^[1-9][0-9]*$'
      and (text_anchor ->> 'char_end')::bigint > (text_anchor ->> 'char_start')::bigint
    )
  );

commit;
