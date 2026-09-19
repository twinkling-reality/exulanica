import { describe, expect, it } from 'vitest';
import type { ManifestEntryRead } from '../src/manifest-reader.js';
import { MANIFEST_FILE } from '../src/publish.js';
import { publishedLook, publishedSets } from '../src/inspect/published-look.js';
import { readPublished } from './support.js';

/**
 * Pictures of the published sets, from the committed bytes.
 *
 * What this holds is that every published set can be pictured and that the picture set follows the
 * set's CLASS: the maps it stores, and the one channel its class leaves over. The lighting is a
 * person's tool and not a contract, so nothing here asserts a pixel; the dimensions, the names and
 * the coverage of every published pair are what a person relies on when they open the directory.
 */
const manifest = publishedSets(readPublished(MANIFEST_FILE));

/**
 * The channel each kind of container leaves over, by container profile and material class. This is
 * a table of expectations, so it is a gate that enumerates: the test below therefore asserts that
 * every pair the manifest actually publishes appears here, and a pair that does not fails by name
 * rather than going unpictured and unnoticed.
 */
const EXTRA_CHANNEL: Record<string, string | null> = {
  'exulanica.texture-set/v1 opaque': 'height',
  'exulanica.texture-set/v2 opaque': null,
  'exulanica.texture-set/v2 cutout': 'coverage',
  'exulanica.texture-set/v2 decal': 'coverage',
  'exulanica.texture-set/v2 glazing': 'transmission',
};

const pairOf = (entry: { containerProfile: string; materialClass: string }): string =>
  `${entry.containerProfile} ${entry.materialClass}`;

describe('pictures of a published set', () => {
  /**
   * The CALL of `checkTextureSet`, not the check.
   *
   * `checkTextureSet` has its own cases in texture-set-cases.test.ts and had no caller in any
   * product path: the look command read `blobs/<content_sha256>.ltex`, using the pinned digest as
   * a file name and never as a digest. Measured 2026-09-19 by putting the road-paint container
   * under the kerb's name: the command drew six pictures at 256 by 64, printed
   * `cc0.kerb-stone opaque 1024x256` beside them, and exited 0.
   *
   * A published directory cannot produce this pairing, which is why the input is built here by
   * handing one set's committed bytes to another set's entry. Two real sets, so nothing about the
   * bytes is synthetic; only their pairing is.
   */
  it('refuses a container that is not the one its entry pins', () => {
    const [first, second] = [...manifest.values()];
    const bytes = readPublished(`blobs/${second!.contentSha256}.ltex`);
    // The control: those same bytes under their OWN entry are drawn without complaint, so the
    // refusal below is about the pairing and not about the bytes or about this fixture.
    expect(() => publishedLook(bytes, second!, 1)).not.toThrow();
    expect(second!.contentSha256).not.toBe(first!.contentSha256);
    expect(() => publishedLook(bytes, first!, 1)).toThrow();
  });

  it('cover every profile and class pair the manifest publishes', () => {
    const published = new Set([...manifest.values()].map(pairOf));
    expect([...published].filter((pair) => !(pair in EXTRA_CHANNEL)).sort()).toEqual([]);
  });

  /**
   * One set per pair, not all seventeen: what varies between sets of the same pair is the pixels,
   * which this does not assert, and picturing every set cost twenty seconds of the suite to repeat
   * the same five checks. The test above is what holds every published set to a pair that is
   * pictured here, so a new pair cannot hide behind a representative.
   */
  const representatives = new Map<string, { setId: string; entry: ManifestEntryRead }>();
  for (const [setId, entry] of [...manifest].sort(([left], [right]) => (left < right ? -1 : 1))) {
    if (!representatives.has(pairOf(entry))) representatives.set(pairOf(entry), { setId, entry });
  }

  for (const [pair, { setId, entry }] of representatives) {
    it(`${pair} is pictured as its class stores it, from ${setId}`, () => {
      const container = readPublished(`blobs/${entry.contentSha256}.ltex`);
      const pictures = publishedLook(container, entry, 2);
      const extra = EXTRA_CHANNEL[pairOf(entry)];
      const expected = [
        'base-colour-1to1',
        'lit-from-front-2x2',
        'lit-from-side-2x2',
        'normal-1to1',
        'orm-1to1',
        ...(extra === null || extra === undefined ? [] : [`${extra}-1to1`]),
      ].sort();
      expect([...pictures.keys()].sort()).toEqual(expected);
      for (const [name, image] of pictures) {
        const tiles = name.endsWith('-2x2') ? 2 : 1;
        expect({ name, width: image.width, height: image.height }).toEqual({
          name,
          width: entry.width * tiles,
          height: entry.height * tiles,
        });
        expect(image.rgb.length).toBe(image.width * image.height * 3);
      }
    });
  }
});
