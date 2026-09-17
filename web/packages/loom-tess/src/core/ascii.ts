/**
 * Printable ASCII to bytes and back, with no TextEncoder.
 *
 * Core compiles against ES2022 alone, and `TextEncoder` and `TextDecoder` are host APIs (lib.dom
 * and @types/node), so they are compile errors here. Every string this package digests or writes
 * is canonical JSON held to printable ASCII, so one character is one byte and the codec is a loop
 * that refuses everything else. A refusal is the point: a byte outside the range is a document
 * `canonical.py` and `JSON.stringify` might not agree on.
 */

/** The space character, the first printable ASCII code. */
export const ASCII_SPACE = 0x20;
/** The tilde, the last printable ASCII code. */
const ASCII_TILDE = 0x7e;

export class AsciiError extends Error {}

export function asciiBytes(text: string, where: string): Uint8Array {
  const bytes = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < ASCII_SPACE) throw new AsciiError(`${where}: character ${index} is not printable ASCII`);
    if (code > ASCII_TILDE) throw new AsciiError(`${where}: character ${index} is not printable ASCII`);
    bytes[index] = code;
  }
  return bytes;
}

export function asciiText(bytes: Uint8Array, where: string): string {
  let text = '';
  for (let index = 0; index < bytes.length; index += 1) {
    const code = bytes[index]!;
    if (code < ASCII_SPACE) throw new AsciiError(`${where}: byte ${index} is not printable ASCII`);
    if (code > ASCII_TILDE) throw new AsciiError(`${where}: byte ${index} is not printable ASCII`);
    text += String.fromCharCode(code);
  }
  return text;
}
