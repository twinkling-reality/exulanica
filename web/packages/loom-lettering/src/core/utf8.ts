/**
 * UTF-8 to a string and back, with no host codec.
 *
 * Core compiles against ES2022 alone, so `TextDecoder` and `TextEncoder` are compile errors here.
 * A catalog is canonical JSON, which is mostly ASCII, but a defective one can carry any character
 * a JSON string may hold: a catalog whose glyph list names an accented letter is one of the shared
 * cases. So the codec is written out, and it refuses what `json.loads` would refuse: an
 * over-long form, a surrogate, a truncated sequence or a code point above U+10FFFF. A refusal is
 * the point; those bytes are not something Python and this reader could agree on.
 */

export class Utf8Error extends Error {}

function refuse(where: string, at: number): never {
  throw new Utf8Error(`${where} is not UTF-8: byte ${at}`);
}

/** The text of `bytes`, or a refusal. */
export function utf8Text(bytes: Uint8Array, where: string): string {
  let text = '';
  let index = 0;
  while (index < bytes.length) {
    const first = bytes[index]!;
    let code: number;
    let length: number;
    if (first < 0x80) {
      code = first;
      length = 1;
    } else if (first >= 0xc2 && first <= 0xdf) {
      code = first & 0x1f;
      length = 2;
    } else if (first >= 0xe0 && first <= 0xef) {
      code = first & 0x0f;
      length = 3;
    } else if (first >= 0xf0 && first <= 0xf4) {
      code = first & 0x07;
      length = 4;
    } else {
      refuse(where, index);
    }
    if (index + length > bytes.length) refuse(where, index);
    for (let step = 1; step < length; step += 1) {
      const next = bytes[index + step]!;
      if ((next & 0xc0) !== 0x80) refuse(where, index + step);
      code = (code << 6) | (next & 0x3f);
    }
    if (length === 3 && (code < 0x800 || (code >= 0xd800 && code <= 0xdfff))) refuse(where, index);
    if (length === 4 && (code < 0x10000 || code > 0x10ffff)) refuse(where, index);
    text += String.fromCodePoint(code);
    index += length;
  }
  return text;
}

/** The UTF-8 bytes of `text`. A lone surrogate is refused: it has no encoding. */
export function utf8Bytes(text: string, where: string): Uint8Array {
  const out: number[] = [];
  for (let index = 0; index < text.length; index += 1) {
    const code = text.codePointAt(index)!;
    if (code >= 0xd800 && code <= 0xdfff) refuse(where, index);
    if (code < 0x80) {
      out.push(code);
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
      index += 1;
    }
  }
  return new Uint8Array(out);
}
