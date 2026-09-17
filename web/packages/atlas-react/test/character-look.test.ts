import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { CHARACTER_CATALOG, CHARACTER_CATALOG_JSON } from '../src/playcanvas/character/catalog-data.js';
import { catalogBase, catalogFamily } from '../src/playcanvas/character/catalog.js';
import { canonicalJson, sha256Hex } from '../src/playcanvas/character/digest.js';
import { INHABITANT_DRAW_DOMAIN, inhabitantLook } from '../src/playcanvas/character/inhabitant.js';
import {
  CHARACTER_LOOK_PROFILE,
  DrawStream,
  describeLook,
  describeLookBytes,
  drawLook,
  isqrt,
  lookSha256,
  validateLook,
  type CharacterLook,
} from '../src/playcanvas/character/look.js';

/** RFC 4122 name-based identifiers, as `uuid.uuid5` makes the society's inhabitants. */
function uuid5(namespace: string, name: string): string {
  const digest = createHash('sha1').update(Buffer.from(namespace.replace(/-/g, ''), 'hex')).update(name, 'utf8').digest();
  digest[6] = (digest[6]! & 0x0f) | 0x50;
  digest[8] = (digest[8]! & 0x3f) | 0x80;
  const x = digest.subarray(0, 16).toString('hex');
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}

// exulanica.world.society.SOCIETY_NAMESPACE, and a fixed society for the measured population.
const SOCIETY_NAMESPACE = '234a55f8-2680-4fd0-812d-bd67905fc930';
const SOCIETY = '6f1c1d9e-0b8a-5a35-9e53-8d2d5f0c7a11';
const inhabitant = (ordinal: number) => uuid5(SOCIETY_NAMESPACE, `${SOCIETY}:inhabitant:${ordinal}`);
const draw = (subject: string) => drawLook(CHARACTER_CATALOG, INHABITANT_DRAW_DOMAIN, subject);

describe('deterministic inhabitant looks', () => {
  it('reproduces the shared draw vectors the backend also reads', async () => {
    expect(uuid5('6ba7b810-9dad-11d1-80b4-00c04fd430c8', 'python.org')).toBe('886313e1-3b8a-5372-9b90-0c9aee199e5d');
    const subjects = [...[0, 1, 2, 3, 4, 5, 6, 7].map(inhabitant), '0', 'a "quoted" \\ subject'];
    const vectors = {
      profile: 'exulanica.character-draw-conformance/v1',
      catalog: {
        catalogId: CHARACTER_CATALOG.catalogId,
        revision: CHARACTER_CATALOG.revision,
        canonicalSha256: sha256Hex(new TextEncoder().encode(CHARACTER_CATALOG_JSON)),
      },
      domain: INHABITANT_DRAW_DOMAIN,
      vectors: subjects.map((subject) => {
        const stream = new DrawStream(INHABITANT_DRAW_DOMAIN, subject);
        const look = draw(subject);
        return {
          subject,
          seed: canonicalJson({ domain: INHABITANT_DRAW_DOMAIN, profile: 'exulanica.character-draw/v1', subject }),
          streamPrefix: Array.from({ length: 12 }, () => stream.next()),
          look,
          lookSha256: lookSha256(look),
        };
      }),
    };
    await expect(`${JSON.stringify(vectors, null, 2)}\n`).toMatchFileSnapshot('../../../../tests/vectors/character_draw_v1.json');
  });

  it('gives an identity the same look and the same renderable bytes every time', () => {
    const id = inhabitant(42);
    const first = draw(id);
    expect(draw(id)).toEqual(first);
    for (const detail of ['near', 'far'] as const) {
      expect(describeLookBytes(CHARACTER_CATALOG, draw(id), detail)).toBe(describeLookBytes(CHARACTER_CATALOG, first, detail));
    }
    expect(describeLookBytes(CHARACTER_CATALOG, first, 'near')).not.toBe(describeLookBytes(CHARACTER_CATALOG, first, 'far'));
    expect(sha256Hex(new TextEncoder().encode(describeLookBytes(CHARACTER_CATALOG, first, 'near'))))
      .toBe('f3a9c05d6d8bee003821d46c02a093bb6b24d26735c43a84b37f371fe9e7bb54');
  });

  it('ignores society, branch and every other field of the identity', () => {
    const id = inhabitant(7);
    const look = inhabitantLook({ societyId: SOCIETY, branchId: 'main', inhabitantId: id });
    expect(inhabitantLook({ societyId: 'another-society', branchId: 'counterfactual-3', inhabitantId: id })).toEqual(look);
    expect(look).toEqual(draw(id));
  });

  it('spreads a thousand inhabitants across every body, garment, hairstyle, skin and height', () => {
    const population = 1000;
    const family = catalogFamily(CHARACTER_CATALOG, 'makehuman-people/v1');
    const profile = CHARACTER_CATALOG.population.find((p) => p.domain === INHABITANT_DRAW_DOMAIN)!;
    const looks = Array.from({ length: population }, (_, i) => draw(inhabitant(i)));
    expect(new Set(looks.map(lookSha256)).size).toBe(population);

    const bases = new Map<string, CharacterLook[]>();
    for (const look of looks) bases.set(look.baseId, [...(bases.get(look.baseId) ?? []), look]);
    const totalBaseWeight = Object.values(profile.bases).reduce((a, b) => a + b, 0);
    for (const [baseId, weight] of Object.entries(profile.bases)) {
      const members = bases.get(baseId) ?? [];
      within(members.length, (population * weight) / totalBaseWeight, `${baseId} bodies`);
      const base = catalogBase(family, baseId);
      for (const slot of family.slots) {
        const weights = slot.kind === 'colour' ? profile.colours[slot.slot]! : profile.choices[baseId]![slot.slot]!;
        const total = Object.values(weights).reduce((a, b) => a + b, 0);
        for (const [choice, w] of Object.entries(weights)) {
          const seen = members.filter((look) => {
            if (slot.kind === 'part') return (look.parts[slot.slot] ?? 'none') === choice;
            if (slot.kind === 'material') return look.materials[slot.slot] === choice;
            return look.colours[slot.slot] === choice;
          }).length;
          // Every catalog choice appears, in proportion to its declared weight.
          expect(seen, `${baseId} ${slot.slot} ${choice}`).toBeGreaterThan(0);
          within(seen, (members.length * w) / total, `${baseId} ${slot.slot} ${choice}`);
        }
      }
      const heights = members.map((look) => look.parameters['heightMillimetres']!);
      const mean = heights.reduce((a, b) => a + b, 0) / heights.length;
      const deviation = Math.sqrt(heights.reduce((a, b) => a + (b - mean) ** 2, 0) / heights.length);
      const range = profile.parameters[baseId]!['heightMillimetres']!;
      expect(Math.min(...heights)).toBeGreaterThanOrEqual(base.heightMillimetres.min);
      expect(Math.max(...heights)).toBeLessThanOrEqual(base.heightMillimetres.max);
      expect(Math.max(...heights) - Math.min(...heights), `${baseId} height span`).toBeGreaterThan(200);
      expect(deviation, `${baseId} height deviation`).toBeGreaterThan(40);
      within(mean, (range.min + range.mode + range.max) / 3, `${baseId} mean height`, 25);
    }
  });
});

/** Observed within five standard errors of a binomial expectation (a fixed population, so exact). */
function within(observed: number, expected: number, what: string, tolerance = 5 * Math.sqrt(expected) + 3): void {
  expect(Math.abs(observed - expected), `${what}: ${observed} against ${expected.toFixed(1)}`).toBeLessThanOrEqual(tolerance);
}

describe('exact integer draws', () => {
  it('computes integer square roots exactly at the edges', () => {
    for (const n of [0, 1, 2, 3, 4, 15, 16, 17, 2 ** 52 - 1, Number.MAX_SAFE_INTEGER]) {
      const r = isqrt(n);
      expect(BigInt(r) * BigInt(r) <= BigInt(n) && (BigInt(r) + 1n) * (BigInt(r) + 1n) > BigInt(n), `isqrt ${n}`).toBe(true);
    }
    expect(() => isqrt(-1)).toThrow(RangeError);
    expect(() => isqrt(0.5)).toThrow(RangeError);
  });

  it('keeps triangular draws inside the range and weighted draws independent of key order', () => {
    const stream = new DrawStream('test/v1', 'subject');
    for (let i = 0; i < 2000; i++) {
      const value = stream.triangular({ min: -500, mode: 0, max: 800 });
      expect(value >= -500 && value <= 800 && Number.isInteger(value)).toBe(true);
    }
    const a = new DrawStream('test/v1', 'order');
    const b = new DrawStream('test/v1', 'order');
    for (let i = 0; i < 50; i++) expect(a.weighted({ x: 1, y: 5, z: 2 })).toBe(b.weighted({ z: 2, x: 1, y: 5 }));
    expect(new DrawStream('test/v1', 'point').triangular({ min: 3, mode: 3, max: 3 })).toBe(3);
    expect(() => new DrawStream('test/v1', 'wide').triangular({ min: 0, mode: 1, max: 0x200000 })).toThrow(RangeError);
    expect(() => new DrawStream('test/v1', 'wide').below(0)).toThrow(RangeError);
  });
});

describe('look validation and description', () => {
  const look = (): CharacterLook => JSON.parse(JSON.stringify(draw(inhabitant(3)))) as CharacterLook;
  const refuses = (edit: (value: { -readonly [K in keyof CharacterLook]: any }) => void, message: RegExp) => {
    const value = look();
    edit(value);
    expect(() => validateLook(CHARACTER_CATALOG, value)).toThrow(message);
  };

  it('refuses a look that is not exactly a recipe over its catalog', () => {
    refuses((v) => { v.profile = 'exulanica.character-look/v2'; }, /unsupported profile/);
    refuses((v) => { v.familyId = 'someone-else/v1'; }, /Unknown character family/);
    refuses((v) => { v.parts = { ...v.parts, hat: null }; }, /parts must be exactly/);
    refuses((v) => { v.parts = { ...v.parts, outfit: null }; }, /outfit is required/);
    refuses((v) => {
      const other = v.baseId === 'feminine' ? 'masculine' : 'feminine';
      v.parts = { ...v.parts, outfit: CHARACTER_CATALOG.families[0]!.bases.find((b) => b.baseId === other)!.parts.find((p) => p.slot === 'outfit')!.partId };
    }, /is not a outfit on/);
    refuses((v) => { v.materials = { ...v.materials, skin: 'skin/unknown' }; }, /is not a skin on/);
    refuses((v) => { v.colours = { hairColour: 'green' }; }, /is not a hairColour/);
    refuses((v) => { v.parameters = { ...v.parameters, heightMillimetres: 2500 }; }, /outside/);
    refuses((v) => { v.parameters = { ...v.parameters, fullness: 12.5 }; }, /outside/);
  });

  it('describes a near person with every container and a far person with none', () => {
    const value = look();
    expect(value.profile).toBe(CHARACTER_LOOK_PROFILE);
    const near = describeLook(CHARACTER_CATALOG, value, 'near');
    const far = describeLook(CHARACTER_CATALOG, value, 'far');
    const base = catalogBase(CHARACTER_CATALOG.families[0]!, value.baseId);
    expect(near.base).toEqual(base.asset);
    expect(far.base).toBeNull();
    expect(far.parts.every((part) => part.asset === null)).toBe(true);
    expect(near.parts.filter((part) => part.asset).map((part) => part.slot).sort()).toEqual(
      ['hair', 'outfit', 'shoes'].filter((slot) => value.parts[slot] !== null),
    );
    expect(near.parts.map((part) => part.slot)).toEqual([...near.parts.map((part) => part.slot)].sort());
    const bits = near.parts.map((part) => base.parts.find((p) => p.partId === part.partId)!.hideBit).filter((bit) => bit !== undefined);
    expect(near.hideMask).toBe(bits.reduce((mask, bit) => mask | (1 << bit!), 0));
    expect(bits.length).toBe(2);
    expect(near.scaleMicro).toBe(Math.round((value.parameters['heightMillimetres']! * 1_000_000) / base.restHeightMillimetres));
    const fullness = value.parameters['fullness']!;
    expect(near.morphWeightsMilli).toEqual({
      'fullness-up': Math.max(0, fullness),
      'fullness-down': Math.max(0, -fullness),
      'muscle-up': Math.max(0, value.parameters['muscle']!),
      'muscle-down': Math.max(0, -value.parameters['muscle']!),
    });
    for (const colour of Object.values(near.farColours)) if (colour !== null) expect(colour).toMatch(/^#[0-9a-f]{6}$/);
    expect(near.farColours).toEqual(far.farColours);
    expect(near.lookSha256).toBe(lookSha256(value));
  });
});
