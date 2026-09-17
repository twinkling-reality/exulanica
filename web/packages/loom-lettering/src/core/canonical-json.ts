/**
 * Canonical JSON, byte-identical to `exulanica.canonical.canonical_json` over what a catalog holds.
 *
 * Sorted keys, no insignificant whitespace, UTF-8, and no float anywhere. Reading is writing
 * backwards: a document is accepted only if re-serialising what `JSON.parse` produced gives the
 * exact input bytes. That one comparison refuses a repeated key (`JSON.parse` keeps the last),
 * `1.0` and `1e2` (they come back as `1` and `100`), unsorted keys, whitespace and a trailing
 * newline.
 *
 * Unlike `loom-tess`'s writer, this one WRITES booleans and nulls, because `canonical_json` writes
 * them: it refuses only floats. A catalog may not carry either, and the reader in `catalog.ts`
 * refuses them by name, so the two languages agree on which check fires.
 *
 * `JSON.stringify` escapes a string exactly as Python's `json.dumps(ensure_ascii=False)` does: the
 * quote, the backslash and the C0 controls, with the same short forms, and every other character
 * raw. Keys are sorted by code point, which for the ASCII keys a catalog uses is what Python's
 * `sort_keys` does.
 */
import { utf8Bytes, utf8Text } from './utf8.js';

export type CanonicalValue = number | string | boolean | null | readonly CanonicalValue[] | { readonly [key: string]: CanonicalValue };

export class CanonicalJsonError extends Error {}

function refuse(path: string, why: string): never {
  throw new CanonicalJsonError(`canonical JSON refuses ${path}: ${why}`);
}

/** A total order on strings by code point, which is Python's order for strings. */
export function compareCodePoints(a: string, b: string): number {
  const first = [...a];
  const second = [...b];
  for (let index = 0; index < Math.min(first.length, second.length); index += 1) {
    const one = first[index]!.codePointAt(0)!;
    const two = second[index]!.codePointAt(0)!;
    if (one !== two) return one < two ? -1 : 1;
  }
  return first.length - second.length;
}

function write(value: unknown, path: string): string {
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      refuse(path, `${String(value)} is not a safe integer; quantise to an integer unit first`);
    }
    // String(-0) is "0", which is what Python writes for the integer zero.
    return String(value);
  }
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (value === null) return 'null';
  if (Array.isArray(value)) {
    return `[${value.map((item: unknown, index) => write(item, `${path}[${index}]`)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const prototype: unknown = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      refuse(path, 'only plain objects have a canonical form');
    }
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort(compareCodePoints);
    const parts = keys.map((key) => {
      const item = record[key];
      if (item === undefined) refuse(`${path}.${key}`, 'undefined has no JSON form');
      return `${JSON.stringify(key)}:${write(item, `${path}.${key}`)}`;
    });
    return `{${parts.join(',')}}`;
  }
  return refuse(path, `a ${typeof value} has no canonical form here`);
}

/** The canonical serialisation of `value`. */
export function canonicalJson(value: CanonicalValue): string {
  return write(value, '$');
}

/** The canonical serialisation as UTF-8 bytes. */
export function canonicalBytes(value: CanonicalValue): Uint8Array {
  return utf8Bytes(canonicalJson(value), '$');
}

/** Parse bytes that must already be canonical JSON, or refuse. */
export function parseCanonical(bytes: Uint8Array, what: string): unknown {
  const text = utf8Text(bytes, what);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new CanonicalJsonError(`${what} is not JSON: ${String(error)}`);
  }
  if (write(parsed, what) !== text) {
    throw new CanonicalJsonError(
      `${what} is not canonical JSON: it must be exactly what exulanica.canonical.canonical_json `
        + 'writes (sorted keys, no whitespace, integers only, no repeated key)',
    );
  }
  return parsed;
}
