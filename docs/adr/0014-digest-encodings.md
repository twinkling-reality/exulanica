# ADR-0014: Ratify the v1 digest encodings, and say how the algorithm is identified

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build

## Context

`docs/domain-and-evidence-model.md` section 9.1 listed the digest encodings as a **DECISION taken in
the implementation, needs ratification**, naming three: lowercase hex for `blob_sha256`, absent keys
rather than nulls, and `prefix`/`suffix` excluded from `text_anchor`. It said what would settle them:
"ratify against a second implementation, ideally one not written in Python, since the point of a
canonical form is cross-implementation agreement".

That criterion had never been exercised. The whole canonical form existed only in
`exulanica/canonical.py`, and no artifact stated what the correct bytes were, so a second reader had
nothing to disagree with.

A fourth question was implicit and unrecorded: **the span digest does not name its own algorithm.**
`span_digest` is 32 opaque bytes. Adding a `hash_algorithm` field to the digest input would change
every digest already issued, so it is not available as a fix.

## Decision

### 1. The algorithm is identified by `span_format_version`, not by a field

**`span_format_version = 1` binds exactly one pair: SHA-256 over the RFC 8785 subset canonical JSON
produced by `exulanica.canonical.canonical_json`.** The version integer is already inside the digest
input, so it is covered by the digest, and a v2 that used a different hash or a different
canonicalisation would be a different, declared format written alongside v1. Nothing has to change,
and nothing is left implicit.

Everywhere the digest leaves the address, the algorithm **is** named, and that stays true:
`ni:///sha-256;…` (RFC 6920) in the permalink, `content_sha256` and `record_sha256` in wire and record
fields, `blob_sha256` in the schema. The one place a bare digest travels, it travels with its version.

### 2. Lowercase hex inside a digest input; base64url only in a rendering

`blob_sha256` enters the span tuple as 64 lowercase hex characters, which is what the database prints
and what the browser's `requiredDigest` already refuses to accept in any other form. The unpadded
base64url of RFC 6920 appears in `to_uri()` and in `blob.ni_uri`, which are renderings, never inputs.

### 3. Absent, never null

An optional member is omitted from the digest input. It is never present with a null. `{"a":1}` and
`{"a":1,"b":null}` are different byte strings, so a writer that emitted nulls for absent optionals
would produce a different digest for the same address, silently, because both documents are valid
JSON. Pinned by `test_no_digest_input_carries_a_null`.

This rule is scoped to the **span** digest input. Other canonical records in the system, such as the
privacy authorization record, do carry explicit nulls for fields that are meaningfully "not set"
(`valid_until`, `synthetic_manifest_sha256`). That is consistent, not an exception: those fields are
always present and sometimes null, which is a stable shape. The rule that matters, and the one that
was never written down, is that **no field may be sometimes absent and sometimes null.**

### 4. `prefix` and `suffix` stay out of `text_anchor`

The `text_anchor` digest input is `{artifact_id, char_start, char_end}` plus `exact` when present.
The `prefix` and `suffix` keys named in migration 0001's column comment were never written by any
version of this code and are excluded permanently. Quote context is a highlight aid; putting it
inside the address would make a citation depend on the text either side of the thing it cites, so a
re-generated transcript that changed a neighbouring word would invalidate a citation to an unchanged
one. Enforced by `evidence_span_text_anchor_shape`.

### 5. Ratification against a second implementation

`tests/vectors/span_digest_v1.json` retains, for seven addresses, the digest input, **the exact
canonical JSON bytes**, their UTF-8 length, and the digest. The bytes are the part that matters: an
implementation that agrees on the digest but not on the bytes agrees by luck.

`scripts/verify_canonical_conformance.mjs` is an independent reader. It shares no code with the
backend: a different JSON parser, a serialiser written from the specification rather than ported, and
Node's SHA-256. **Verified 2026-09-04: all seven vectors agree on the canonical bytes and on the
digest, under Node v24.15.0.** A negative control was run: perturbing one ppm coordinate in the
retained file by 1 makes the reader exit non-zero and print both byte strings.

The vectors cover the cases where two JSON writers are most likely to differ: a negative
`t_start_ns`; non-ASCII text, which JCS emits literally and many writers escape as `\uXXXX`; a quote,
a backslash and a tab, which pin the short escapes; and an absent optional beside a present one.

**What this does not establish.** Node's `JSON.stringify` and Python's `json` are two implementations,
not two independent specifications, and both are ECMAScript-descended in their string escaping. The
ratification is therefore strong for encoding and ordering and weaker for exotic escaping. A third
reader in a language with a different string model would strengthen it further and is not built,
because no consumer needs one yet.

## Compatibility impact

None. No digest changes; every rule describes what is already written. The two check constraints
describe rows the implementation already produces.

## Failure behaviour

- A float anywhere in a digest input raises `CanonicalisationError` naming the path, before any hash
  is taken.
- A malformed `text_anchor` is refused by `TextAnchor.__post_init__` and by
  `evidence_span_text_anchor_shape` (SQLSTATE 23514).
- A span read back that does not rebuild to its stored digest raises `IntegrityError` in
  `address_from_span_row`, naming both digests, rather than being served.
- A drift between this build and the retained vectors fails
  `tests/test_span_digest_conformance.py::test_the_retained_vectors_match_what_this_build_computes`.

## What this touches

| Surface | Change |
| --- | --- |
| Schema | `0033_span_digest_input_shape.sql`: `evidence_span_text_anchor_shape`, plus comments on `span_digest`, `region` and `text_anchor` stating the frozen contract |
| Migrations | Forward only |
| Evidence | No behaviour change |
| Tests and tooling | `tests/vectors/span_digest_v1.json`, `tests/test_span_digest_conformance.py`, `scripts/verify_canonical_conformance.mjs` |
| APIs, workers, exports, deletion, browser | No change |

## Consequences

The section 9.1 row "the digest encodings ... needs ratification" is **closed**. The retained vector
file is the artifact any future implementation is ratified against, and it is the thing to hand a
port rather than a paragraph of prose.
