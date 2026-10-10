/**
 * The kit places pack as the page resolves it: a pack drawn on the cozy town, whose ready-made
 * pieces stand in the slots that name their leaves and in no others.
 *
 * Read from the committed manifests with the browser's reader. A contained piece is scaled whole to
 * touch its slot's box, so the case states the size a person would see: the rowing boat fills a
 * boat's box by its width. The pack names no well: a well keeps the box the cozy town draws.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readStylePackManifest, readStylePiece, resolveLookRole, resolveStylePack, swatchKeyOf, type LookFamily } from '@exulanica/atlas-core';

// Relative to web/, where the suite runs.
const PACKS = '../assets/style-packs/packs';
const KIT = 'exulanica.kit-places';
const catalog = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(catalog.entries.map((e) => [e.key, { fit: e.fit, dressing: e.dressing, fillMinimumPermille: e.fill_minimum_permille, fillMaximumPermille: e.fill_maximum_permille }]));
const textureSets = new Set<string>((JSON.parse(readFileSync('../assets/textures/manifest.json', 'utf8')) as { sets: { set_id: string }[] }).sets.map((s) => s.set_id));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const manifestOf = (packId: string) => readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${packId}/manifest.json`, 'utf8')), { families, textureSets });

const kit = manifestOf(KIT);
const base = manifestOf(kit.base!.pack_id);
const pack = resolveStylePack([kit, base]);
const slot = (lookRole: string, boxMm: readonly [number, number, number]) => resolveLookRole(
  pack, { identity: `test:${lookRole}`, lookRole, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm }, families, 'module',
);
/** The size a piece is drawn at in a box, millimetres: width, depth, height. */
const drawn = (lookRole: string, boxMm: readonly [number, number, number]): number[] => {
  const dressing = slot(lookRole, boxMm);
  if (dressing?.kind !== 'module') throw new Error(`${lookRole} is not dressed by a piece`);
  const [w, d, h] = pack.modules[dressing.role]!.variants[dressing.variant]!.size_mm;
  // Scales are on glTF axes: x width, y height, z depth.
  return [w * dressing.scale[0], d * dressing.scale[2], h * dressing.scale[1]].map(Math.round);
};

describe('the kit places pack', () => {
  it('is drawn on the committed cozy town and states only its own pieces and swatches', () => {
    expect(kit.base).toEqual({ pack_id: base.pack_id, version: base.version, manifest_sha256: kit.base!.manifest_sha256 });
    expect(base.pack_id).toBe('exulanica.cozy-town');
    expect([kit.light, kit.shading, kit.edge]).toEqual([null, null, null]);
    expect(Object.keys(kit.surfaces)).toEqual([]);
    expect(Object.keys(kit.modules).sort()).toEqual(['vehicle.fishing_boat']);
    // Everything else a world wears is its base's, piece for piece.
    for (const role of Object.keys(base.modules)) expect(pack.modules[role]!.stated).toBe(1);
    expect(pack.light).toEqual(base.light);
  });

  it('colours each of its pieces in swatches of its own, which the page finds by the piece\'s colour', () => {
    const own = new Set(kit.palette.swatches.map((swatch) => swatch.key));
    for (const [role, module] of Object.entries(kit.modules)) {
      for (const variant of module.variants) {
        const bytes = new Uint8Array(readFileSync(`${PACKS}/${KIT}/${variant.file}`));
        for (const group of readStylePiece(bytes, TABLE).groups) {
          const key = swatchKeyOf(pack, pack.modules[role]!, group.srgb8);
          expect(key === null ? false : own.has(key), `${variant.file} ${group.srgb8.join(',')}`).toBe(true);
        }
      }
    }
  });

  it('stands a rowing boat in a boat\'s box, scaled whole until its beam touches', () => {
    // The two boxes a drafted fishing village gives its boats: moored, and pulled up on the beach.
    expect(drawn('vehicle.fishing_boat', [2000, 5000, 2000])).toEqual([2000, 3994, 896]);
    expect(drawn('vehicle.fishing_boat', [1500, 4000, 1500])).toEqual([1500, 2996, 672]);
  });

  it('stands no piece in for a leaf it does not name, and keeps the cozy town\'s pieces for its own leaves', () => {
    // A well among them: no kit read for the pack holds a low well head, so a well keeps its box.
    for (const leaf of ['fixture.well', 'fixture.bed', 'fixture.counter', 'fixture.default', 'prop.default', 'vehicle.ferry']) {
      expect(slot(leaf, [2000, 2000, 2000]), leaf).toBeNull();
    }
    const sedan = slot('vehicle.sedan', [1800, 4600, 1440]);
    expect(sedan?.kind === 'module' ? pack.modules[sedan.role]!.stated : -1).toBe(1);
  });
});
