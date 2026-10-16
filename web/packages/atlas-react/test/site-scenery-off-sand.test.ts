// @vitest-environment happy-dom
/**
 * A site on land by the sea keeps its scenery off the sand: where the land wears its surfaces, a
 * piece stands where the land is drawn above the sand and not where it is drawn in the sand by the
 * sea, as land cover reads the land (`landBandAt`). With no surfaces handed over, or on land with no
 * sea, every dry piece stands as before.
 *
 * The site is the fixture's yard (`fixtures/site-land.v5.json`) under a lawn, on land rebuilt here
 * over four chunks: it rises 40 per mille to the north of the yard's south edge and falls 200 per
 * mille to the south of it, to a flat shore 1 m over the sea, which lies to the south. The drawing
 * names these chunks' and this backdrop's digests in place of the fixture's.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { canonicalJson, readLandSurfaces, readSiteScenery, readSurfaceMaterials, sceneryBeyond, type SceneryPiece } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { parseStructuredSiteDrawing, readSiteLand, siteMount, type SiteDresser, type StructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';
import type { TileLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const SCENERY = readSiteScenery(readFileSync('../assets/catalogs/world-kinds/site-scenery.v1.json', 'utf8'));
const SURFACES = readLandSurfaces(readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8'));
const COZY = JSON.parse(readFileSync('../assets/style-packs/packs/exulanica.cozy-town/manifest.json', 'utf8')) as {
  light: { default_preset: string; presets: Record<string, never> }; shading: never; edge: never;
};
/** A look that draws a ground beyond the place, which scenery stands on. */
const edgedLook = (): TileLook => renderLookOfPreset(COZY.light.presets[COZY.light.default_preset]!, COZY.shading, COZY.edge);
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const digestOf = (document: unknown): string => sha256(new TextEncoder().encode(canonicalJson(document)));

/** The land at a lattice point, millimetres above the sea: rising north of the yard's edge, falling south of it to the shore. */
const lattice = (north: number): number => (north >= 0 ? 6000 + (40 * north) / 1000 : Math.max(1000, 6000 + north / 5));
function chunkDocument(chunkX: number, chunkY: number): Record<string, unknown> {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(lattice(chunkY * 128_000 + j * 1000));
  return { profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height };
}
const PLACES = [[-1, -1], [0, -1], [-1, 0], [0, 0]] as const;
const AXIS = [-400_000, -128_000, 0, 128_000, 400_000];
const BACKDROP = {
  profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, -128_000, 128_000, 128_000], x_mm: AXIS, y_mm: AXIS,
  height_mm: AXIS.flatMap((y) => AXIS.map(() => lattice(y))),
  water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
};

/** The fixture's yard under a lawn, on this land; with `sea` false, its land states no sea. */
function yardDocument(sea = true): Record<string, unknown> {
  const document = structuredClone(FIXTURE) as { slots: { identity: string; lookRole: string }[]; land: { chunks: unknown; backdrop_sha256: string; water: { kind: string }[] } };
  document.slots.find((slot) => slot.identity === 'yard:ground')!.lookRole = 'ground.grass';
  document.land.chunks = PLACES.map(([x, y]) => ({ chunk: [x, y], sha256: digestOf(chunkDocument(x, y)) }));
  document.land.backdrop_sha256 = digestOf(BACKDROP);
  if (!sea) document.land.water = document.land.water.filter((body) => body.kind !== 'sea');
  return document as unknown as Record<string, unknown>;
}

function nullApp(): { app: pc.AppBase; camera: pc.Entity; environmentRoot: pc.Entity } {
  const canvas = document.createElement('canvas');
  canvas.width = 0;
  canvas.height = 0;
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
  return { app, camera, environmentRoot };
}

/** The scenery pieces a site is drawn with, as its dresser is handed them, with the land's surfaces or none. */
function drawnPieces(drawing: StructuredSiteDrawing, withSurfaces: boolean): readonly SceneryPiece[] {
  const land = readSiteLand(drawing, new Map(PLACES.map(([x, y]) => [`${x},${y}`, chunkDocument(x, y)])), BACKDROP, sha256);
  let handed: readonly SceneryPiece[] = [];
  const dress: SiteDresser = (_host, _drawn, _drawing, scenery) => {
    handed = scenery?.pieces ?? [];
    return () => undefined;
  };
  const { app, camera, environmentRoot } = nullApp();
  const attachment = siteMount(drawing, {
    servedBytes: 1, land, look: edgedLook(), materials: MATERIALS, scenery: SCENERY, dress, ...(withSurfaces ? { landSurfaces: SURFACES } : {}),
  }).attach({ app, camera, environmentRoot });
  attachment.dispose();
  return handed;
}

describe("a site's scenery by the sea", () => {
  const drawing = parseStructuredSiteDrawing(yardDocument());
  const stated = sceneryBeyond(drawing.worldId, drawing.extent, SCENERY.byMaterial.get('grass')!);
  // The sand band, read from the catalog: whole at or under its third height, gone by its fourth,
  // each moved at most the noise's jitter either way.
  const sand = SURFACES.bands.find((band) => band.needsSea)!;
  const onSand = (piece: SceneryPiece): boolean => lattice(Math.max(-128_000, Math.min(128_000, piece.yMm))) <= sand.heightMm![2] * (1 - SURFACES.noise.jitter);
  const aboveSand = (piece: SceneryPiece): boolean => lattice(Math.max(-128_000, Math.min(128_000, piece.yMm))) >= sand.heightMm![3] * (1 + SURFACES.noise.jitter);
  const ids = (pieces: readonly SceneryPiece[]): string[] => pieces.map((piece) => piece.identity);

  it('states trees both on the shore and on the land above it', () => {
    expect(stated.filter(onSand).length).toBeGreaterThan(0);
    expect(stated.filter(aboveSand).length).toBeGreaterThan(0);
  });

  it('draws no tree on the sand and every tree above it', () => {
    const drawn = drawnPieces(drawing, true);
    expect(drawn.filter(onSand)).toEqual([]);
    expect(ids(drawn.filter(aboveSand))).toEqual(ids(stated.filter(aboveSand)));
  });

  it('draws every tree, the shore\'s too, with no surfaces handed over', () => {
    expect(ids(drawnPieces(drawing, false))).toEqual(ids(stated));
  });

  it('draws every tree, the shore\'s too, on land with no sea', () => {
    expect(ids(drawnPieces(parseStructuredSiteDrawing(yardDocument(false)), true))).toEqual(ids(stated));
  });
});
