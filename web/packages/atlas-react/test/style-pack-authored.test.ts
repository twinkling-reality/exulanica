// @vitest-environment happy-dom
/**
 * The authored style packs, read the way the page reads them: each manifest by the browser's reader
 * against this tree's catalogs, each piece by its digest and the palette piece reader, its one
 * preview picture by its digest, each frame that stretches resolved into the smallest and largest
 * openings the city grammar cuts, each light preset's sky as the renderer lights a surface with it,
 * and every earlier version the host still serves.
 */
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readStylePackManifest, readStylePiece, resolveLookRole, resolveStylePack, type LookFamily } from '@exulanica/atlas-core';
import { renderSkyRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

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

  it('carry pieces whose bytes are their digests and whose colours are their palettes\', and one preview picture', () => {
    for (const folder of folders) {
      const manifest = readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets });
      const colours = new Set(manifest.palette.swatches.map((s) => s.srgb8.join(',')));
      const pictures: string[] = [];
      for (const file of manifest.files) {
        const bytes = new Uint8Array(readFileSync(`${PACKS}/${folder}/${file.path}`));
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(file.sha256);
        if (file.media_type !== 'model/gltf-binary') {
          pictures.push(file.path);
          continue;
        }
        for (const group of readStylePiece(bytes, TABLE).groups) expect(colours.has(group.srgb8.join(','))).toBe(true);
      }
      expect(pictures).toEqual([manifest.preview]);
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

  it('light a surface in shade at most twice as blue as red, so a shaded street never reads navy', () => {
    for (const folder of folders) {
      const pack = resolveStylePack([readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets })]);
      for (const [name, preset] of Object.entries(pack.light.presets)) {
        const look = renderLookOfPreset(preset, pack.shading, pack.edge);
        // The sky's light on an upward-facing surface the sun does not reach: its radiance as the
        // renderer lights with it, weighted by the cosine over the upper hemisphere.
        let red = 0;
        let blue = 0;
        for (let i = 0; i < 64; i += 1) {
          const theta = ((i + 0.5) / 64) * (Math.PI / 2);
          for (let j = 0; j < 256; j += 1) {
            const phi = ((j + 0.5) / 256) * 2 * Math.PI;
            const radiance = renderSkyRadiance(look, [Math.sin(theta) * Math.cos(phi), Math.cos(theta), Math.sin(theta) * Math.sin(phi)], true);
            red += radiance[0] * Math.cos(theta) * Math.sin(theta);
            blue += radiance[2] * Math.cos(theta) * Math.sin(theta);
          }
        }
        expect(blue / red, `${folder} ${name}`).toBeLessThanOrEqual(2);
      }
    }
  });

  it('keep every earlier version readable by the page, each the manifest its ledger entry records', () => {
    const ledger = JSON.parse(readFileSync('../assets/style-packs/published.v1.json', 'utf8')) as {
      versions: { pack_id: string; version: number; manifest_sha256: string }[];
    };
    expect(ledger.versions.length).toBeGreaterThan(0);
    for (const entry of ledger.versions) {
      const folder = `../assets/style-packs/published/${entry.pack_id}/${entry.version}`;
      const file = readFileSync(`${folder}/manifest.json`);
      expect(createHash('sha256').update(file.subarray(0, file.length - 1)).digest('hex')).toBe(entry.manifest_sha256);
      const manifest = readStylePackManifest(JSON.parse(file.toString('utf8')), { families, textureSets });
      expect([manifest.pack_id, manifest.version]).toEqual([entry.pack_id, entry.version]);
      const colours = new Set(manifest.palette.swatches.map((s) => s.srgb8.join(',')));
      for (const listed of manifest.files) {
        const bytes = new Uint8Array(readFileSync(`${folder}/${listed.path}`));
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(listed.sha256);
        if (listed.media_type !== 'model/gltf-binary') continue;
        for (const group of readStylePiece(bytes, TABLE).groups) expect(colours.has(group.srgb8.join(','))).toBe(true);
      }
    }
  });
});
