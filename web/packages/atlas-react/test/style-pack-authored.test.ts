// @vitest-environment happy-dom
/**
 * The authored style packs, read the way the page reads them: each manifest by the browser's reader
 * against this tree's catalogs, each piece by its digest and the palette piece reader, and each
 * frame that stretches resolved into the smallest and largest openings the city grammar cuts.
 */
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readStylePackManifest, readStylePiece, resolveLookRole, resolveStylePack, type LookFamily } from '@exulanica/atlas-core';

// Relative to web/, where the suite runs.
const PACKS = '../assets/style-packs/packs';
const catalog = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(catalog.entries.map((e) => [e.key, { fit: e.fit, dressing: e.dressing, fillMinimumPermille: e.fill_minimum_permille, fillMaximumPermille: e.fill_maximum_permille }]));
const textureSets = new Set<string>((JSON.parse(readFileSync('../assets/textures/manifest.json', 'utf8')) as { sets: { set_id: string }[] }).sets.map((s) => s.set_id));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const folders = readdirSync(PACKS).sort();

describe('the authored packs', () => {
  it('are three, each read by the browser\'s reader against this tree\'s catalogs', () => {
    expect(folders).toEqual(['exulanica.cozy-town', 'exulanica.finished-town', 'exulanica.toon-town']);
    for (const folder of folders) {
      const manifest = readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets });
      expect(manifest.pack_id).toBe(folder);
    }
  });

  it('carry only pieces whose bytes are their digests and whose colours are their palettes\'', () => {
    for (const folder of folders) {
      const manifest = readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets });
      const colours = new Set(manifest.palette.swatches.map((s) => s.srgb8.join(',')));
      for (const file of manifest.files) {
        const bytes = new Uint8Array(readFileSync(`${PACKS}/${folder}/${file.path}`));
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(file.sha256);
        for (const group of readStylePiece(bytes, TABLE).groups) expect(colours.has(group.srgb8.join(','))).toBe(true);
      }
    }
  });

  it('dress every window from the smallest opening the grammar cuts to the largest', () => {
    // The city grammar's opening bounds (exulanica/grammar/grammars/city/facade.py, OPENING_SHAPE).
    const holes: (readonly [number, number, number])[] = [[300, 120, 500], [4000, 250, 5000], [758, 121, 982], [1844, 243, 2933]];
    for (const folder of folders) {
      const pack = resolveStylePack([readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets })]);
      for (const leaf of ['plain', 'lintel', 'hood', 'arch']) {
        for (const boxMm of holes) {
          const dressing = resolveLookRole(pack, { identity: `${folder}:${leaf}`, lookRole: `window.${leaf}`, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm }, families, 'module');
          expect(dressing, `${folder} window.${leaf} ${boxMm.join('x')}`).toMatchObject({ kind: 'module' });
        }
      }
    }
  });
});
