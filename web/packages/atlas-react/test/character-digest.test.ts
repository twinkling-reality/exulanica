import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { canonicalJson, canonicalSha256, sha256Hex } from '../src/playcanvas/character/digest.js';

const bytes = (text: string) => new TextEncoder().encode(text);

describe('synchronous SHA-256', () => {
  it('reproduces the standard vectors', () => {
    expect(sha256Hex(bytes(''))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex(bytes('abc'))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(sha256Hex(bytes('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')))
      .toBe('248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1');
    expect(sha256Hex(new Uint8Array(1_000_000).fill(0x61)))
      .toBe('cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0');
  });

  it('agrees with the platform across every padding boundary', () => {
    for (let length = 0; length <= 260; length++) {
      const data = Uint8Array.from({ length }, (_, i) => (i * 131 + length * 7) & 0xff);
      expect(sha256Hex(data), `length ${length}`).toBe(createHash('sha256').update(data).digest('hex'));
    }
  });

  it('hashes only the viewed bytes of a subarray', () => {
    const backing = Uint8Array.from({ length: 64 }, (_, i) => i);
    const view = backing.subarray(9, 41);
    expect(sha256Hex(view)).toBe(createHash('sha256').update(view).digest('hex'));
  });
});

describe('canonical JSON', () => {
  it('sorts keys at every depth and writes no whitespace', () => {
    expect(canonicalJson({ b: 1, a: [true, null, { d: 'x', c: -2 }] })).toBe('{"a":[true,null,{"c":-2,"d":"x"}],"b":1}');
    expect(canonicalJson({ B: 1, a: 2, _: 3 })).toBe('{"B":1,"_":3,"a":2}');
  });

  it('escapes quotes and backslashes the way the backend does', () => {
    expect(canonicalJson({ path: 'a"b\\c/d' })).toBe('{"path":"a\\"b\\\\c/d"}');
  });

  it('matches the backend bytes and digest of the same value', () => {
    // exulanica.canonical.canonical_json and sha256_of_canonical of this value, run in Python.
    const value = { path: 'a"b\\c/d', parts: { hair: null }, parameters: { heightMillimetres: 1700 }, familyId: 'makehuman-people/v1' };
    expect(canonicalJson(value)).toBe('{"familyId":"makehuman-people/v1","parameters":{"heightMillimetres":1700},"parts":{"hair":null},"path":"a\\"b\\\\c/d"}');
    expect(canonicalSha256(value)).toBe('8278ea489a4b711943cffed5613074ba9a6946c393948056b0f42735efb3ceb1');
  });

  it('refuses anything that could serialise two ways', () => {
    expect(() => canonicalJson({ scale: 1.5 })).toThrow(/not a safe integer/);
    expect(() => canonicalJson({ big: 2 ** 53 })).toThrow(/not a safe integer/);
    expect(() => canonicalJson({ nan: Number.NaN })).toThrow(/not a safe integer/);
    expect(() => canonicalJson({ label: 'café' })).toThrow(/printable ASCII/);
    expect(() => canonicalJson({ label: 'line\nbreak' })).toThrow(/printable ASCII/);
    expect(() => canonicalJson({ missing: undefined })).toThrow(/undefined/);
    expect(() => canonicalJson({ when: new Date(0) })).toThrow(/plain objects/);
    expect(() => canonicalJson(Symbol('x'))).toThrow(/no canonical form/);
  });
});
