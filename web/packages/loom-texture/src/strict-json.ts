/**
 * Strict JSON: how this package and `exulanica.materials` read a document from bytes.
 *
 * `JSON.parse` and Python's `json.loads` agree on valid JSON but not on what a number is:
 * JavaScript reads `1.0` and `2.4e1` as the integers 1 and 24, and Python reads them as floats. A
 * recipe is integers, so a document may write a number only as an integer literal inside the safe
 * range. Both readers also refuse a repeated key (`JSON.parse` would keep the last one), a document
 * nested deeper than `MAXIMUM_DEPTH` (Python's parser recurses), and bytes that are not UTF-8 or
 * that begin with a byte-order mark.
 *
 * Every refusal is one of five fixed problems, chosen by a fixed precedence rather than by where a
 * parser happened to notice it: nesting first (measured by the same bracket scan in both
 * languages, so it holds even for text that is not JSON), then syntax, then a number with a
 * fraction or exponent, then an integer outside the safe range, then a repeated key. The two
 * languages therefore refuse the same bytes for the same stated reason, which the `documents`
 * cases in `test/recipe-cases.json` hold them to.
 */
export const MAXIMUM_DEPTH = 64;

export const STRICT_JSON_PROBLEMS = {
  depth: `a document nests more than ${MAXIMUM_DEPTH} deep`,
  syntax: 'a document is not JSON',
  number: 'a number is written with a fraction or an exponent',
  range: 'an integer is outside the safe range',
  duplicate: 'an object repeats a key',
} as const;

export class StrictJsonError extends Error {}

const SAFE_DIGITS = '9007199254740991';

/** The deepest bracket nesting outside strings. Defined on any text, JSON or not. */
export function nesting(text: string): number {
  let depth = 0;
  let deepest = 0;
  let inString = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (inString) {
      if (character === '\\') index += 1;
      else if (character === '"') inString = false;
    } else if (character === '"') {
      inString = true;
    } else if (character === '[' || character === '{') {
      depth += 1;
      if (depth > deepest) deepest = depth;
    } else if (character === ']' || character === '}') {
      depth -= 1;
    }
  }
  return deepest;
}

/** Whether an unsigned run of digits, as JSON writes an integer, exceeds 2^53 - 1. */
function outOfRange(digits: string): boolean {
  return digits.length > SAFE_DIGITS.length
    || (digits.length === SAFE_DIGITS.length && digits > SAFE_DIGITS);
}

interface Container {
  readonly keys: Set<string> | null;
  expectKey: boolean;
}

/** Number and key problems in text already known to be valid JSON. */
function scan(text: string): { number: boolean; range: boolean; duplicate: boolean } {
  const found = { number: false, range: false, duplicate: false };
  const stack: Container[] = [];
  let index = 0;
  while (index < text.length) {
    const character = text[index]!;
    if (character === '"') {
      let end = index + 1;
      while (text[end] !== '"') end += text[end] === '\\' ? 2 : 1;
      const top = stack[stack.length - 1];
      if (top !== undefined && top.keys !== null && top.expectKey) {
        const key = JSON.parse(text.slice(index, end + 1)) as string;
        if (top.keys.has(key)) found.duplicate = true;
        top.keys.add(key);
        top.expectKey = false;
      }
      index = end + 1;
    } else if (character === '{') {
      stack.push({ keys: new Set(), expectKey: true });
      index += 1;
    } else if (character === '[') {
      stack.push({ keys: null, expectKey: false });
      index += 1;
    } else if (character === '}' || character === ']') {
      stack.pop();
      index += 1;
    } else if (character === ',') {
      const top = stack[stack.length - 1];
      if (top !== undefined && top.keys !== null) top.expectKey = true;
      index += 1;
    } else if (character === '-' || (character >= '0' && character <= '9')) {
      let end = index + 1;
      while (end < text.length && /[0-9.eE+-]/.test(text[end]!)) end += 1;
      const literal = text.slice(index, end);
      if (/[.eE]/.test(literal)) found.number = true;
      else if (outOfRange(literal.startsWith('-') ? literal.slice(1) : literal)) found.range = true;
      index = end;
    } else {
      index += 1;
    }
  }
  return found;
}

/** Parse `text`, or throw a `StrictJsonError` naming the one problem the precedence picks. */
export function parseStrictJson(text: string): unknown {
  if (nesting(text) > MAXIMUM_DEPTH) throw new StrictJsonError(STRICT_JSON_PROBLEMS.depth);
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new StrictJsonError(STRICT_JSON_PROBLEMS.syntax);
  }
  const found = scan(text);
  if (found.number) throw new StrictJsonError(STRICT_JSON_PROBLEMS.number);
  if (found.range) throw new StrictJsonError(STRICT_JSON_PROBLEMS.range);
  if (found.duplicate) throw new StrictJsonError(STRICT_JSON_PROBLEMS.duplicate);
  return value;
}

/** Parse UTF-8 bytes. A byte-order mark is kept, so it is refused as the syntax it is not. */
export function parseStrictJsonBytes(bytes: Uint8Array): unknown {
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new StrictJsonError(STRICT_JSON_PROBLEMS.syntax);
  }
  return parseStrictJson(text);
}
