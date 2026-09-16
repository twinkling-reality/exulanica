/**
 * Canonical JSON, byte-identical to `exulanica.canonical.canonical_json`.
 *
 * The container header and the manifest are digest inputs, and the Python backend re-serialises
 * both to check them. That only works if the two languages agree on every byte, so this writer
 * accepts exactly the subset where agreement is certain and refuses everything else:
 *
 *   - Numbers must be safe integers. A float is refused outright, as `canonical.py` refuses it,
 *     because IEEE-754 has no decimal rendering every JSON writer agrees on. This is not a style
 *     rule; the Python side raises.
 *   - Strings must be printable ASCII. Python's `json.dumps(ensure_ascii=False)` and ECMAScript's
 *     `JSON.stringify` agree on the escapes for `"` and `\`, and printable ASCII needs no others,
 *     so nothing depends on how either handles control characters, astral code points or lone
 *     surrogates.
 *   - Object keys are sorted. With ASCII keys, JavaScript's code-unit order and Python's
 *     code-point order are the same order.
 *   - No insignificant whitespace, and no trailing newline: the output IS the canonical bytes.
 */

type Json = null | boolean | number | string | readonly Json[] | { readonly [key: string]: Json };

const PRINTABLE_ASCII = /^[\x20-\x7e]*$/;

function refuse(path: string, why: string): never {
  throw new TypeError(`canonical JSON refuses ${path}: ${why}`);
}

function writeString(value: string, path: string): string {
  if (!PRINTABLE_ASCII.test(value)) refuse(path, 'strings are printable ASCII only');
  return `"${value.replace(/[\\"]/g, (character) => `\\${character}`)}"`;
}

function write(value: unknown, path: string): string {
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      refuse(path, `${value} is not a safe integer; quantise to an integer unit first`);
    }
    // String(-0) is "0", which is also what Python writes for the integer zero.
    return String(value);
  }
  if (typeof value === 'string') return writeString(value, path);
  if (Array.isArray(value)) {
    return `[${value.map((item, index) => write(item, `${path}[${index}]`)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      refuse(path, 'only plain objects are serialisable');
    }
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    const parts = keys.map((key) => {
      const item = record[key];
      if (item === undefined) refuse(`${path}.${key}`, 'undefined has no JSON form');
      return `${writeString(key, `${path} key`)}:${write(item, `${path}.${key}`)}`;
    });
    return `{${parts.join(',')}}`;
  }
  return refuse(path, `a ${typeof value} has no canonical form`);
}

/** The canonical serialisation of `value`, as a string of printable ASCII. */
export function canonicalJson(value: Json | object): string {
  return write(value, '$');
}

/** The canonical serialisation as UTF-8 bytes, which for printable ASCII is one byte a character. */
export function canonicalBytes(value: Json | object): Uint8Array {
  return new TextEncoder().encode(canonicalJson(value));
}
