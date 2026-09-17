/**
 * Canonical JSON, byte-identical to `exulanica.canonical.canonical_json` over the subset this
 * package reads and writes, and the strict reader that goes with it.
 *
 * `canonical.py` says the only place its form could diverge from ECMAScript is string escaping,
 * and only while every value is an integer or a string. This writer holds the subset to exactly
 * that, and narrower:
 *
 *   - numbers are safe integers; a float is refused, as `canonical.py` refuses it;
 *   - strings are printable ASCII, where `json.dumps(ensure_ascii=False)` and `JSON.stringify`
 *     agree on every byte (only the quote and the backslash are escaped);
 *   - `null` and booleans are refused: a value a record does not have is a field it does not
 *     carry, which is `exulanica.grammar.records`' rule;
 *   - object keys are sorted, and with ASCII keys code-unit order is code-point order.
 *
 * `loom-texture` has a writer with the same intent. It is not imported: the dependency-cruiser
 * fence lets this package's core reach nothing in the workspace, and an offline baker must never
 * be reachable from a browser build.
 *
 * READING IS WRITING BACKWARDS. `parseCanonical` accepts a document only if re-serialising what
 * `JSON.parse` produced gives back the exact input. That one comparison refuses a repeated key
 * (`JSON.parse` keeps the last), `1.0` and `1e2` (they re-serialise as `1` and `100`), unsorted
 * keys, insignificant whitespace, a trailing newline, and every value outside the subset. The
 * Python side writes these documents with `canonical_json`, so a document that is not already
 * canonical was not written by it.
 */
import { asciiBytes, asciiText } from './ascii.js';

export type CanonicalValue =
  | number
  | string
  | readonly CanonicalValue[]
  | { readonly [key: string]: CanonicalValue };

export class CanonicalJsonError extends Error {}

function refuse(path: string, why: string): never {
  throw new CanonicalJsonError(`canonical JSON refuses ${path}: ${why}`);
}

function writeString(value: string, path: string): string {
  // asciiBytes refuses anything outside printable ASCII, which is the whole escaping argument.
  asciiBytes(value, path);
  return `"${value.replace(/[\\"]/g, (character) => `\\${character}`)}"`;
}

function write(value: unknown, path: string): string {
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      refuse(path, `${String(value)} is not a safe integer; quantise to an integer unit first`);
    }
    // String(-0) is "0", which is what Python writes for the integer zero.
    return String(value);
  }
  if (typeof value === 'string') return writeString(value, path);
  if (Array.isArray(value)) {
    return `[${value.map((item: unknown, index) => write(item, `${path}[${index}]`)).join(',')}]`;
  }
  if (typeof value === 'object' && value !== null) {
    const prototype: unknown = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      refuse(path, 'only plain objects have a canonical form');
    }
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort(compareCodeUnits);
    const parts = keys.map((key) => {
      const item = record[key];
      if (item === undefined) refuse(`${path}.${key}`, 'undefined has no JSON form');
      return `${writeString(key, `${path} key`)}:${write(item, `${path}.${key}`)}`;
    });
    return `{${parts.join(',')}}`;
  }
  return refuse(path, `a ${value === null ? 'null' : typeof value} has no canonical form here`);
}

/** Total order on strings by UTF-16 code unit, which for ASCII is Python's order. */
export function compareCodeUnits(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/** The canonical serialisation of `value`. */
export function canonicalJson(value: CanonicalValue): string {
  return write(value, '$');
}

/** The canonical serialisation as bytes: printable ASCII, one byte a character. */
export function canonicalBytes(value: CanonicalValue): Uint8Array {
  return asciiBytes(canonicalJson(value), '$');
}

/** Parse bytes that must already be canonical JSON, or refuse. */
export function parseCanonical(bytes: Uint8Array, what: string): unknown {
  const text = asciiText(bytes, what);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new CanonicalJsonError(`${what} is not JSON: ${String(error)}`);
  }
  const rewritten = write(parsed, what);
  if (rewritten !== text) {
    throw new CanonicalJsonError(
      `${what} is not canonical JSON: it must be exactly what exulanica.canonical.canonical_json `
        + 'writes (sorted keys, no whitespace, integers only, no repeated key, no null)',
    );
  }
  return parsed;
}
