/**
 * Independent verification of the v1 span-digest conformance vectors.
 *
 * `docs/domain-and-evidence-model.md` section 9.1 says the digest encodings are "a DECISION taken
 * in the implementation, needs ratification", and that ratifying them means agreement with a
 * second implementation, ideally one not written in Python. This is that second reader. It shares
 * no code with the backend: a different JSON parser, a different serialiser, a different SHA-256.
 *
 * It checks three things per vector, and the middle one is the one that matters:
 *
 *   1. re-serialising `digest_input` under the canonical rules reproduces `canonical_json`
 *      **byte for byte**, so agreement is not luck;
 *   2. the UTF-8 encoding of those bytes hashes to `span_digest_sha256`;
 *   3. no float and no null reached the digest input, which is what makes (1) possible at all.
 *
 * Run:  node scripts/verify_canonical_conformance.mjs
 * Exits non-zero and names the first disagreement.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const VECTORS = join(HERE, '..', 'tests', 'vectors', 'span_digest_v1.json');

/**
 * The canonical form, written from the specification rather than ported from the Python.
 *
 * RFC 8785 subset: object keys sorted by their UTF-16 code units, no insignificant whitespace,
 * non-ASCII emitted literally as UTF-8, and no floats anywhere. `JSON.stringify` already emits
 * the short escapes JCS requires and already emits non-ASCII literally, so the only work here is
 * key order and the refusal.
 */
function canonicalise(value, path = '$') {
  if (value === null) throw new Error(`null at ${path}: absent keys, never nulls`);
  if (typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isInteger(value)) throw new Error(`float at ${path}: ${value}`);
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, i) => canonicalise(item, `${path}[${i}]`)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value).sort();
    const parts = keys.map(
      (key) => `${JSON.stringify(key)}:${canonicalise(value[key], `${path}.${key}`)}`,
    );
    return `{${parts.join(',')}}`;
  }
  throw new Error(`unsupported ${typeof value} at ${path}`);
}

const document = JSON.parse(readFileSync(VECTORS, 'utf8'));
if (document.profile !== 'exulanica.span-digest-conformance/v1') {
  throw new Error(`unexpected profile ${document.profile}`);
}
if (document.hash_algorithm !== 'sha-256' || document.canonicalisation !== 'rfc8785-subset') {
  throw new Error('the vector file no longer declares the algorithm this reader implements');
}

let checked = 0;
for (const vector of document.vectors) {
  const encoded = canonicalise(vector.digest_input);
  if (encoded !== vector.canonical_json) {
    console.error(`${vector.name}: canonical bytes disagree`);
    console.error(`  retained: ${vector.canonical_json}`);
    console.error(`  computed: ${encoded}`);
    process.exit(1);
  }
  const bytes = Buffer.from(encoded, 'utf8');
  if (bytes.length !== vector.canonical_json_byte_length) {
    console.error(
      `${vector.name}: ${bytes.length} UTF-8 bytes, retained ${vector.canonical_json_byte_length}`,
    );
    process.exit(1);
  }
  const digest = createHash('sha256').update(bytes).digest('hex');
  if (digest !== vector.span_digest_sha256) {
    console.error(`${vector.name}: digest ${digest}, retained ${vector.span_digest_sha256}`);
    process.exit(1);
  }
  checked += 1;
}

console.log(
  `span-digest conformance: ${checked} vectors agree on canonical bytes and SHA-256, ` +
    `verified by ${process.release?.name ?? 'node'} ${process.version}`,
);
