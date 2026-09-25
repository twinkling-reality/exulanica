import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CHARACTER_CATALOG, CHARACTER_CATALOG_JSON } from '../src/playcanvas/character/catalog-data.js';
import { validateCharacterCatalog, type CharacterCatalog } from '../src/playcanvas/character/catalog.js';
import { canonicalJson } from '../src/playcanvas/character/digest.js';
import { designedLook, validateDesignedLooks, type DesignedLooks } from '../src/playcanvas/character/look.js';
import { DESIGNED_LOOKS, DESIGNED_LOOKS_JSON } from '../src/playcanvas/character/looks-data.js';

const committed = readFileSync(new URL('../../../../assets/characters/catalog.json', import.meta.url), 'utf8');
const committedLooks = readFileSync(new URL('../../../../assets/characters/looks.json', import.meta.url), 'utf8');
// A fresh, freely editable copy for each refusal; the refusals reach into arbitrary depth.
const copy = (): any => JSON.parse(CHARACTER_CATALOG_JSON);

describe('committed character catalog', () => {
  it('is the same document as assets/characters/catalog.json', () => {
    // Sorted keys, no whitespace, integers and ASCII only: the generator's compact form exactly.
    expect(canonicalJson(JSON.parse(committed))).toBe(CHARACTER_CATALOG_JSON);
    expect(committed.endsWith('\n')).toBe(true);
  });

  it('validates, and names every family, base, material and population it offers', () => {
    expect(validateCharacterCatalog(copy() as CharacterCatalog)).toBeTruthy();
    const family = CHARACTER_CATALOG.families[0]!;
    expect(family.familyId).toBe('makehuman-people/v1');
    expect(family.bases.map((b) => b.baseId)).toEqual(['feminine', 'masculine']);
    expect(CHARACTER_CATALOG.population.map((p) => p.domain)).toEqual(['street-population/v1']);
    for (const base of family.bases) {
      expect(base.parts.filter((p) => p.slot === 'outfit').length).toBe(8);
      expect(base.materials['skin']!.length).toBe(6);
    }
  });

  it('keeps every asset key unique and every file one container', () => {
    const assets = CHARACTER_CATALOG.families.flatMap((family) => [
      ...family.bases.map((b) => b.asset),
      ...family.bases.flatMap((b) => b.parts.flatMap((p) => (p.asset ? [p.asset] : []))),
      ...family.materials.map((m) => m.asset),
    ]);
    expect(new Set(assets.map((a) => a.assetKey)).size).toBe(assets.length);
    // Each repository file names exactly one container.
    const byFile = new Map<string, string>();
    for (const asset of assets) {
      expect(byFile.get(asset.file) ?? asset.contentSha256).toBe(asset.contentSha256);
      byFile.set(asset.file, asset.contentSha256);
    }
  });
});

describe('catalog validation refuses', () => {
  const refuses = (mutate: (catalog: any) => void, message: RegExp) => {
    const catalog = copy();
    mutate(catalog);
    expect(() => validateCharacterCatalog(catalog as CharacterCatalog)).toThrow(message);
  };

  it('an unknown profile or revision', () => {
    refuses((c) => { c.profile = 'exulanica.character-catalog/v2'; }, /unsupported profile/);
    refuses((c) => { c.revision = 0; }, /positive integer/);
  });

  it('a malformed or oversized container reference', () => {
    refuses((c) => { c.families[0].bases[0].asset.contentSha256 = 'ABC'; }, /digest is malformed/);
    refuses((c) => { c.families[0].bases[0].asset.file = '../escape.glb'; }, /file path is malformed/);
    refuses((c) => { c.families[0].materials[0].asset.byteSize = 64 * 1024 * 1024; }, /byte size/);
    refuses((c) => { c.families[0].materials[0].asset.mediaType = 'model/gltf+json'; }, /only GLB/);
  });

  it('a posture a base lacks, an activity drawn in no posture, or a malformed joint', () => {
    refuses((c) => { c.families[0].bases[0].postures = {}; }, /postures must be exactly/);
    refuses((c) => { c.families[0].activityPostures.rest = 'kneeling'; }, /unknown posture kneeling/);
    refuses((c) => { c.families[0].seatPostures.rest = 'kneeling'; }, /unknown posture kneeling/);
    refuses((c) => { c.families[0].bases[0].postures.perched.seatMillimetres = 0.5; }, /seat height is malformed/);
    refuses((c) => { c.families[0].bases[1].postures.seated.jointsMillimetres.leftKnee = [0, 1.5, 2]; }, /joint leftKnee is malformed/);
    refuses((c) => { c.families[0].bases[0].farForm.hipWidthMillimetres = 0; }, /far form widths/);
  });

  it('a slot or parameter the studio cannot place', () => {
    refuses((c) => { c.families[0].slots[0].section = 'hat'; }, /studio section is unknown/);
    refuses((c) => { c.families[0].parameters[0].step = 0; }, /studio step/);
  });

  it('a duplicated asset key across entries', () => {
    refuses((c) => { c.families[0].materials[1].asset.assetKey = c.families[0].materials[0].asset.assetKey; }, /asset keys/);
  });

  it('a part naming an unknown material, slot or morph target', () => {
    refuses((c) => { c.families[0].bases[0].parts[0].material = 'skin/unknown'; }, /unknown material/);
    refuses((c) => { c.families[0].bases[0].parts[0].slot = 'hat'; }, /unknown part slot/);
    refuses((c) => { c.families[0].bases[0].parts.find((p: { morphTargets: string[] }) => p.morphTargets.length === 0).morphTargets = ['smile']; }, /unknown morph target/);
  });

  it('two parts claiming the same body surface bit', () => {
    refuses((c) => {
      const parts = c.families[0].bases[0].parts.filter((p: { hideBit?: number }) => p.hideBit !== undefined);
      parts[1].hideBit = parts[0].hideBit;
    }, /hide bits/);
  });

  it('a height default outside its range', () => {
    refuses((c) => { c.families[0].bases[0].heightMillimetres.default = 2400; }, /height default/);
  });

  it('a population weight for a part the base does not have', () => {
    refuses((c) => {
      const outfits = c.population[0].choices.feminine.outfit;
      outfits['masculine/outfit/male_worksuit01'] = 3;
    }, /not a outfit choice on feminine/);
  });

  it('a population draw that could leave a required slot empty', () => {
    refuses((c) => { c.population[0].choices.feminine.outfit = { none: 1 }; }, /not a outfit choice/);
  });

  it('a zero or fractional weight', () => {
    refuses((c) => { c.population[0].bases.feminine = 0; }, /bad base weight/);
    refuses((c) => { c.population[0].colours.hairColour.black = 1.5; }, /bad hairColour colour weight/);
  });

  it('a height distribution beyond the base', () => {
    refuses((c) => { c.population[0].parameters.feminine.heightMillimetres.max = 1990; }, /outside its range/);
  });
});

describe('designed looks', () => {
  const looks = (): any => JSON.parse(DESIGNED_LOOKS_JSON);
  const refuses = (mutate: (value: any) => void, message: RegExp) => {
    const value = looks();
    mutate(value);
    expect(() => validateDesignedLooks(CHARACTER_CATALOG, value as DesignedLooks)).toThrow(message);
  };

  it('are the same document as assets/characters/looks.json', () => {
    expect(canonicalJson(JSON.parse(committedLooks))).toBe(DESIGNED_LOOKS_JSON);
  });

  it('give every body a default over itself and the player a designed default', () => {
    for (const base of CHARACTER_CATALOG.families[0]!.bases) {
      expect(designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.bases[base.baseId]!).baseId).toBe(base.baseId);
    }
    expect(designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.player).profile).toBe('exulanica.character-look/v1');
    expect(new Set(DESIGNED_LOOKS.looks.map((entry) => entry.look.parts['outfit'])).size).toBe(DESIGNED_LOOKS.looks.length);
  });

  it('refuse a look outside the catalog, a missing body default and a default over the wrong body', () => {
    refuses((v) => { v.looks[0].look.parts.outfit = 'feminine/outfit/cape'; }, /is not a outfit/);
    refuses((v) => { v.looks.push({ ...v.looks[0] }); }, /designed twice/);
    refuses((v) => { v.looks[0].note = 'extra'; }, /must be exactly/);
    refuses((v) => { delete v.defaults.bases.masculine; }, /designed base defaults/);
    refuses((v) => { v.defaults.player = 'nobody'; }, /not a designed look/);
    refuses((v) => { v.defaults.bases.feminine = v.defaults.bases.masculine; }, /over another base/);
    refuses((v) => { v.catalogId = 'another-catalog'; }, /another catalog/);
  });
});
