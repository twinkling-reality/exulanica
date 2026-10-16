/**
 * The value readers every field of a style pack manifest goes through, and the refusal they raise.
 *
 * Each reader takes a JSON value and the path it was read at, and answers the value as read or
 * refuses it by name (`StylePackRefusal`): the reason, and the path of the first fault.
 * `style-pack.ts` reads a manifest with them and re-exports the public names. The backend's reader
 * holds the same rules in `exulanica/world/style_pack_reading.py`.
 *
 * Pure: no DOM, no Node, no renderer.
 */

export type Srgb8 = readonly [number, number, number];

export type StylePackRefusalReason = 'shape' | 'range' | 'reference' | 'duplicate' | 'licence';

export class StylePackRefusal extends Error {
  override readonly name = 'StylePackRefusal';
  constructor(readonly reason: StylePackRefusalReason, readonly path: string, detail: string) {
    super(`${path === '' ? 'manifest' : path}: ${detail}`);
  }
}

export type Json = unknown;
/**
 * A field a manifest may leave out. A field added within a profile is optional and its absence keeps
 * the meaning a manifest had before the field existed, so every manifest written under the profile
 * still reads. A manifest that leaves it out is returned without it, as given, so its bytes and
 * digest are its own; a reader of the result takes the absence as that earlier meaning.
 */
export interface Optional {
  readonly read: (value: Json, path: string) => unknown;
}
export const optional = (read: (value: Json, path: string) => unknown): Optional => ({ read });
export type Fields = Readonly<Record<string, ((value: Json, path: string) => unknown) | Optional>>;

export const fail = (reason: StylePackRefusalReason, path: string, detail: string): never => {
  throw new StylePackRefusal(reason, path, detail);
};
export const join = (path: string, key: string): string => (path === '' ? key : `${path}.${key}`);

export function object(value: Json, path: string, fields: Fields): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail('shape', path, 'must be an object');
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) if (!Object.hasOwn(fields, key)) fail('shape', path, `has an unknown key ${JSON.stringify(key)}`);
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(fields)) {
    if (!Object.hasOwn(record, key)) {
      if (typeof field !== 'function') continue;
      fail('shape', path, `is missing ${JSON.stringify(key)}`);
    }
    out[key] = (typeof field === 'function' ? field : field.read)(record[key], join(path, key));
  }
  return out;
}

export const integer = (min: number, max: number) => (value: Json, path: string): number => {
  if (typeof value !== 'number') return fail('shape', path, 'must be a whole number');
  // JSON.parse reads a whole number too long for a double as Infinity; the other reader holds it exactly and finds it out of range.
  if (!Number.isFinite(value)) return fail('range', path, `must be within ${min} to ${max}`);
  if (!Number.isInteger(value)) return fail('shape', path, 'must be a whole number');
  if (value < min || value > max) fail('range', path, `must be within ${min} to ${max}`);
  return value;
};
export const boolean = (value: Json, path: string): boolean => (typeof value === 'boolean' ? value : fail('shape', path, 'must be true or false'));
export const oneOf = <T extends string>(values: readonly T[]) => (value: Json, path: string): T =>
  (typeof value === 'string' && (values as readonly string[]).includes(value) ? (value as T) : fail('range', path, `must be one of ${values.join(', ')}`));
export const literal = (expected: string) => (value: Json, path: string): string => (value === expected ? expected : fail('shape', path, `must be ${JSON.stringify(expected)}`));
export const pattern = (re: RegExp, what: string) => (value: Json, path: string): string =>
  (typeof value === 'string' && re.test(value) ? value : fail('shape', path, `must be ${what}`));
/** A surrogate code unit outside a pair: JSON can escape one, but it is no character. */
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
/** The Unicode Bidi_Control characters: marks, embeddings, overrides and isolates. */
const BIDI_CONTROL = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/;
export const text = (max: number, allowEmpty = false) => (value: Json, path: string): string => {
  if (typeof value !== 'string') return fail('shape', path, 'must be text');
  // No leading or trailing space, and no control character: the same rule in every reader.
  if (value.startsWith(' ') || value.endsWith(' ') || (!allowEmpty && value.length === 0)) fail('shape', path, 'must be trimmed text, not empty');
  if (LONE_SURROGATE.test(value)) fail('shape', path, 'must hold no lone surrogate');
  if (value.length > max) fail('range', path, `must be at most ${max} characters`);
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f-\u009f]/.test(value)) fail('shape', path, 'must hold no control characters');
  if (BIDI_CONTROL.test(value)) fail('shape', path, 'must hold no bidirectional control characters');
  return value;
};
export const nullable = <T>(read: (value: Json, path: string) => T) => (value: Json, path: string): T | null => (value === null ? null : read(value, path));
export const srgb8 = (value: Json, path: string): Srgb8 => {
  if (!Array.isArray(value) || value.length !== 3) return fail('shape', path, 'must be three sRGB bytes');
  return value.map((channel, index) => integer(0, 255)(channel, `${path}[${index}]`)) as unknown as Srgb8;
};
export const list = <T>(read: (value: Json, path: string) => T, min: number, max: number) => (value: Json, path: string): T[] => {
  if (!Array.isArray(value)) return fail('shape', path, 'must be a list');
  if (value.length < min || value.length > max) fail('range', path, `must hold ${min} to ${max} items`);
  return value.map((item, index) => read(item, `${path}[${index}]`));
};
export const record = <T>(readKey: (key: string, path: string) => void, read: (value: Json, path: string) => T, max: number) => (value: Json, path: string): Record<string, T> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return fail('shape', path, 'must be an object');
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > max) fail('range', path, `must hold at most ${max} entries`);
  const out: Record<string, T> = {};
  for (const [key, item] of entries) {
    readKey(key, join(path, key));
    out[key] = read(item, join(path, key));
  }
  return out;
};

export const permille = (min: number, max: number) => integer(min, max);
