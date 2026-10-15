// @vitest-environment happy-dom
/**
 * A texture a pack carries for its surfaces: fetched, held to its size, decoded and made into the set
 * the library's draw takes, then worn by a surface that names it, as a library set is.
 *
 * The pack is the shared case that carries one (`assets/style-packs/manifest-cases.v1.json`); its
 * pictures are stood in for by a decoder handed to the preparation, as the page hands it the browser's.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily, type StylePackFile, type StylePackManifest } from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing, siteMount } from '../src/playcanvas/generated-site/index.js';
import { packSiteDresser, packTextureSetId, preparePackTexture, type DecodePicture } from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const MANIFEST = CASES.cases.find((one) => one.name.startsWith('a pack carrying a texture its footway names'))!.manifest;
const pack = resolveStylePack([readStylePackManifest(MANIFEST, { families, textureSets: new Set(CASES.context.texture_sets) })]);
const PBR = { model: 'pbr', toon: null, ink: null } as const;

/** Bytes of a listed file's stated size: the fetcher hands the preparation what the manifest lists. */
const listedBytes = async (file: StylePackFile): Promise<Uint8Array> => new Uint8Array(file.bytes);
/** Two texels a side: the colour map warm, the normal map flat, each the size the case's maps share. */
const pictures = (sides: Record<string, number> = {}): DecodePicture => async (bytes) => {
  const side = sides[String(bytes.byteLength)] ?? 2;
  const flat = bytes.byteLength === 400_000;
  const rgba = new Uint8Array(side * side * 4);
  for (let i = 0; i < side * side; i += 1) rgba.set(flat ? [128, 128, 255, 255] : [200, 150, 100, 255], i * 4);
  return { width: side, height: side, rgba };
};

describe('a texture a pack carries', () => {
  it('is made into an opaque set of its colour, its normal and a fully rough, unoccluded, non-metal surface, repeating over its extent', async () => {
    const prepared = await preparePackTexture(pack, 'stone', listedBytes, pictures());
    expect(prepared.state).toBe('decoded');
    if (prepared.state !== 'decoded') return;
    const { set } = prepared;
    expect([set.entry.setId, set.materialClass, set.entry.width, set.entry.extentUMm, set.entry.extentVMm]).toEqual(['pack:stone', 'opaque', 2, 2000, 2000]);
    expect(set.channels.map((channel) => channel.map)).toEqual(['base_color', 'normal', 'orm']);
    expect([...set.maps.base_color!.slice(0, 3)]).toEqual([200, 150, 100]);
    expect([...set.maps.normal!.slice(0, 3)]).toEqual([128, 128, 255]);
    expect([...set.maps.orm!.slice(0, 3)]).toEqual([255, 255, 0]);
    expect(prepared.transferredBytes).toBe(1_000_000);
  });

  it('is refused by name when a picture is not its listed size, its maps are not one size, or the pack carries no texture of the name', async () => {
    const short = await preparePackTexture(pack, 'stone', async (file) => new Uint8Array(file.bytes - 1), pictures());
    expect(short).toMatchObject({ state: 'refused', setId: 'pack:stone' });
    expect(short.state === 'refused' && short.reason).toMatch(/599999 bytes; its manifest states 600000/);
    const uneven = await preparePackTexture(pack, 'stone', listedBytes, pictures({ 400000: 4 }));
    expect(uneven.state === 'refused' && uneven.reason).toMatch(/not one size/);
    const none = await preparePackTexture(pack, 'sand', listedBytes, pictures());
    expect(none).toEqual({ state: 'refused', setId: 'pack:sand', reason: 'The pack carries no texture sand' });
  });

  it('is worn by the surface that names it, as a library set is, and put back when the dressing goes', async () => {
    const prepared = await preparePackTexture(pack, 'stone', listedBytes, pictures());
    const drawing = parseStructuredSiteDrawing({
      profile: 'exulanica.site-drawing/v1', world_id: 'world-textured', receipt_sha256: 'a'.repeat(64),
      kind: { kind: 'fixture_path', version: 1, label: 'Path' },
      extent: { widthMm: 12_000, depthMm: 12_000, enclosure: 'open' },
      arrival: { positionMm: [6000, 2000, 0], facingMm: [0, 1] },
      slots: [{ identity: 'walk', part: 'walk', label: 'walk', lookRole: 'path.footway', positionMm: [6000, 6000, 0], yawQuarterTurns: 0, boxMm: [4000, 12_000, 0], front: '+y', fit: 'surface', primitive: 'plane' }],
      walk: { floorMm: [0, 0, 12_000, 12_000], blockersMm: [], keepOutMm: [] },
      seats: [],
    });
    const dresser = packSiteDresser({ pack, families, pieces: { pieces: new Map() }, shading: PBR, textures: new Map([[packTextureSetId('stone'), prepared]]) });
    const canvas = document.createElement('canvas');
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    const environmentRoot = new pc.Entity('environment');
    app.root.addChild(environmentRoot);
    let worn = '';
    let after = '';
    siteMount(drawing, {
      servedBytes: 1,
      dress: (host, drawn, dressing) => {
        const undress = dresser(host, drawn, dressing);
        const material = () => (drawn.root.findByName('walk:shape') as pc.Entity).render!.meshInstances[0]!.material.name;
        worn = material();
        return () => {
          undress();
          after = material();
        };
      },
    }).attach({ app, camera, environmentRoot }).dispose();
    expect(worn).toBe('generated-tile:pack:stone');
    expect(after).not.toBe('generated-tile:pack:stone');
  });
});
