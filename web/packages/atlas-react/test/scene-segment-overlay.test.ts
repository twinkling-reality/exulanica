import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import {
  atlasVec3,
  islandId,
  localToAtlas,
  localVec3,
  makeIsland,
  placement,
  type Island,
} from '@exulanica/atlas-core';
import {
  AtlasBinding,
  SEGMENT_OVERLAY_SPLAT_MODIFIER,
  SegmentOverlayRuntime,
  segmentPaletteBytes,
  segmentPointGroups,
  segmentSlotsFor,
  type IslandVisual,
  type ProofLensColor,
  type SegmentOverlayEngine,
} from '../src/playcanvas/atlas-binding.js';
import { PROOF_LENS_SPLAT_MODIFIER } from '../src/playcanvas/scene-splats.js';

/**
 * The segment overlay, with the engine stood in for.
 *
 * What is under test is the one promise the overlay makes that a screenshot cannot check: that off
 * is exactly what was there before. So the gsplat component here records every call and holds its
 * parameters in a map, and the assertion that matters most is that a runtime which was never
 * applied, or was applied and then switched off, leaves that map and that modifier as it found them.
 *
 * The shader itself needs a GPU and was checked in the browser; the arithmetic it shares with the
 * proof lens is asserted on its source below, so the two cannot drift apart silently.
 */

const REGION_A = islandId('region-a');
const REGION_B = islandId('region-b');

const island = (id: typeof REGION_A, x = 0): Island => makeIsland({
  islandId: id,
  createdAt: 0,
  placement: placement(atlasVec3(x, 0, 0), Math.PI / 2, 2),
  rung: 3,
  scaleIsMetric: false,
  footprintRadiusLocal: 20,
  viewpointLocal: localVec3(0, 0, 0),
  anchors: [],
  layoutEntities: new Set(),
});

function fakeGsplat(initial: Record<string, unknown> = {}) {
  const parameters = new Map<string, unknown>(Object.entries(initial));
  const gsplat = {
    modifier: undefined as unknown,
    workBufferUpdate: pc.WORKBUFFER_UPDATE_AUTO as number,
    setWorkBufferModifier: vi.fn((value: unknown) => { gsplat.modifier = value; }),
    setParameter: vi.fn((name: string, data: unknown) => { parameters.set(name, data); }),
    getParameter: vi.fn((name: string) => parameters.get(name)),
    deleteParameter: vi.fn((name: string) => { parameters.delete(name); }),
  };
  return { gsplat, parameters };
}

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const SCALED = [2, 0, 0, 1, 0, 2, 0, 0, 0, 0, 2, -3, 0, 0, 0, 1];

function trainedVisual(region: Island, artifactId: string, pointCount: number, centres: Float32Array | null = null) {
  const held = fakeGsplat();
  return {
    held,
    visual: {
      island: region,
      entity: { gsplat: held.gsplat } as unknown as pc.Entity,
      asset: { resource: centres === null ? {} : { centers: centres } } as unknown as pc.Asset,
      geometry: {
        sceneId: `scene:${artifactId}`, islandId: region.islandId, artifactId, bytes: new ArrayBuffer(0),
        sceneFromAssetRowMajor: SCALED, bounds: { min: [0, 0, 0], max: [1, 1, 1] }, pointCount,
      },
    },
  };
}

function pointVisual(region: Island, artifactId: string, positions: Float32Array, sceneId = `scene:${artifactId}`): IslandVisual {
  return {
    island: region,
    entity: {} as pc.Entity,
    cloud: { pointCount: positions.length / 3 } as IslandVisual['cloud'],
    pointMap: {
      sceneId, artifactId, islandId: region.islandId,
      map: { position: positions } as IslandVisual['pointMap']['map'],
      sceneFromOpmRowMajor: IDENTITY, localUnitsToSceneUnits: 1,
    },
    uIsland: new Float32Array(4),
    uPoint: new Float32Array(4),
    uLens: new Float32Array(4),
  };
}

function fakeEngine() {
  const textures: { kind: string; width: number; height: number; bytes: Uint8Array; writes: Uint8Array[]; destroyed: boolean }[] = [];
  const overlays: { order: Uint32Array; groups: readonly { slot: number; base: number; count: number }[]; lens: Map<number, ProofLensColor>; destroyed: boolean }[] = [];
  const engine: SegmentOverlayEngine = {
    maxTextureSize: 4096,
    texture(kind, width, height, bytes) {
      const texture = { kind, width, height, bytes: bytes.slice(), writes: [] as Uint8Array[], destroyed: false };
      textures.push(texture);
      return {
        texture,
        write: (next) => { texture.writes.push(next.slice()); },
        destroy: () => { texture.destroyed = true; },
      };
    },
    pointGroups(_visual, order, groups) {
      const overlay = { order: order.slice(), groups, lens: new Map<number, ProofLensColor>(), destroyed: false };
      overlays.push(overlay);
      return {
        setLens: (slot, color) => { overlay.lens.set(slot, color); },
        destroy: () => { overlay.destroyed = true; },
      };
    },
  };
  return { engine, textures, overlays };
}

function host(lensPrepared = false) {
  return { lensPrepared: vi.fn(() => lensPrepared), settle: vi.fn(), invalidate: vi.fn() };
}

const RED: ProofLensColor = [1, 0, 0, 0.8];
const BLUE: ProofLensColor = [0, 0, 1, 0.8];
const tint = (slot: number, artifactId: string, indices: number[]) => ({ slot, artifactId, indices: Uint32Array.from(indices) });

describe('the segment overlay is exactly nothing when it is off', () => {
  it('touches nothing at all when it was never applied', () => {
    const { visual, held } = trainedVisual(island(REGION_A), 'splats-a', 8);
    const points = pointVisual(island(REGION_A), 'points-a', new Float32Array(9));
    const engine = vi.fn(() => fakeEngine().engine);
    const calls = host();
    const runtime = new SegmentOverlayRuntime([points], [visual], engine, calls);

    expect(runtime.apply(null)).toEqual({ islandId: null, assets: [], refused: [] });
    runtime.setPalette(new Map([[1, RED]]));

    expect(engine).not.toHaveBeenCalled();
    expect(held.gsplat.setWorkBufferModifier).not.toHaveBeenCalled();
    expect(held.gsplat.setParameter).not.toHaveBeenCalled();
    expect(held.gsplat.deleteParameter).not.toHaveBeenCalled();
    expect(held.gsplat.workBufferUpdate).toBe(pc.WORKBUFFER_UPDATE_AUTO);
    expect(calls.settle).not.toHaveBeenCalled();
    expect(calls.invalidate).not.toHaveBeenCalled();
    expect(runtime.report).toBeNull();
  });

  it('installs one modifier and two textures on the region drawn, and nothing on another', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 2000);
    const b = trainedVisual(island(REGION_B, 50), 'splats-b', 2000);
    const { engine, textures } = fakeEngine();
    const calls = host();
    const runtime = new SegmentOverlayRuntime([], [a.visual, b.visual], () => engine, calls);

    const report = runtime.apply({
      islandId: REGION_A,
      tints: [tint(1, 'splats-a', [1, 3, 1500])],
      palette: new Map([[1, RED]]),
    });

    expect(a.held.gsplat.modifier).toBe(SEGMENT_OVERLAY_SPLAT_MODIFIER);
    expect(a.held.parameters.get('uSegmentSlots')).toBe(textures[0]);
    expect(a.held.parameters.get('uSegmentPalette')).toBe(textures[1]);
    // The lens was never switched on, so off has to be a value rather than whatever the device
    // scope last held for that name.
    expect(a.held.parameters.get('uProofLens')).toEqual([0, 0, 0, 0]);
    expect(a.held.gsplat.workBufferUpdate).toBe(pc.WORKBUFFER_UPDATE_ALWAYS);
    expect(calls.settle).toHaveBeenCalledOnce();

    const slots = textures[0]!;
    expect([slots.kind, slots.width, slots.height]).toEqual(['slots', 1024, 2]);
    expect([...slots.bytes].flatMap((slot, index) => (slot === 0 ? [] : [[index, slot]]))).toEqual([[1, 1], [3, 1], [1500, 1]]);
    const palette = textures[1]!;
    expect([palette.kind, palette.width, palette.height]).toEqual(['palette', 256, 1]);
    expect([...palette.bytes.slice(0, 8)]).toEqual([0, 0, 0, 0, 255, 0, 0, 204]);

    expect(b.held.gsplat.setWorkBufferModifier).not.toHaveBeenCalled();
    expect(b.held.gsplat.setParameter).not.toHaveBeenCalled();
    expect(report.assets.map((asset) => [asset.artifactId, asset.kind, [...asset.indices], [...asset.slots]]))
      .toEqual([['splats-a', 'gaussians', [1, 3, 1500], [1, 1, 1]]]);
    expect(runtime.covers(a.visual.entity)).toBe(true);
    expect(runtime.covers(b.visual.entity)).toBe(false);
  });

  it('puts back no modifier and no parameter when switched off, if the lens never ran', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 16);
    const { engine, textures } = fakeEngine();
    const calls = host(false);
    const runtime = new SegmentOverlayRuntime([], [a.visual], () => engine, calls);
    runtime.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [0, 5])], palette: new Map([[1, RED]]) });

    expect(runtime.apply(null).assets).toEqual([]);

    expect(a.held.gsplat.setWorkBufferModifier).toHaveBeenLastCalledWith(null);
    expect([...a.held.parameters.keys()]).toEqual([]);
    expect(textures.every((texture) => texture.destroyed)).toBe(true);
    expect(runtime.covers(a.visual.entity)).toBe(false);
    expect(runtime.report).toBeNull();
    // Refilled once more without the tint, inside the settle window, then left for the lens's own
    // settle to return to AUTO.
    expect(a.held.gsplat.workBufferUpdate).toBe(pc.WORKBUFFER_UPDATE_ALWAYS);
    expect(calls.settle).toHaveBeenCalledTimes(2);
  });

  it('puts back the lens modifier and keeps the lens value when the lens was there first', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 16);
    a.held.parameters.set('uProofLens', [0.2, 0.3, 0.4, 0.5]);
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([], [a.visual], () => engine, host(true));

    runtime.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [2])], palette: new Map([[1, RED]]) });
    expect(a.held.parameters.get('uProofLens')).toEqual([0.2, 0.3, 0.4, 0.5]);
    runtime.apply(null);

    expect(a.held.gsplat.modifier).toBe(PROOF_LENS_SPLAT_MODIFIER);
    expect([...a.held.parameters]).toEqual([['uProofLens', [0.2, 0.3, 0.4, 0.5]]]);
  });

  it('moves with the visitor: the region left is put back as it was', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 16);
    const b = trainedVisual(island(REGION_B, 50), 'splats-b', 16);
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([], [a.visual, b.visual], () => engine, host());
    runtime.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [1])], palette: new Map([[1, RED]]) });
    runtime.apply({ islandId: REGION_B, tints: [tint(1, 'splats-b', [2])], palette: new Map([[1, BLUE]]) });

    expect(a.held.gsplat.modifier).toBeNull();
    expect([...a.held.parameters.keys()]).toEqual([]);
    expect(b.held.gsplat.modifier).toBe(SEGMENT_OVERLAY_SPLAT_MODIFIER);
    expect(runtime.report?.islandId).toBe(REGION_B);
  });

  it('draws a point map as one indexed draw per slot over its own samples, and one draw again when off', () => {
    const region = island(REGION_A);
    const points = pointVisual(region, 'points-a', new Float32Array(18));
    const { engine, overlays } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([points], [], () => engine, host());

    runtime.apply({
      islandId: REGION_A,
      tints: [tint(1, 'points-a', [0, 2]), tint(2, 'points-a', [5])],
      palette: new Map([[1, RED], [2, BLUE]]),
    });
    const overlay = overlays[0]!;
    expect([...overlay.order]).toEqual([1, 3, 4, 0, 2, 5]);
    expect(overlay.groups).toEqual([{ slot: 0, base: 0, count: 3 }, { slot: 1, base: 3, count: 2 }, { slot: 2, base: 5, count: 1 }]);
    expect([...overlay.lens]).toEqual([[1, RED], [2, BLUE]]);

    runtime.setPalette(new Map([[1, BLUE], [2, RED]]));
    expect([...overlay.lens]).toEqual([[1, BLUE], [2, RED]]);

    runtime.apply(null);
    expect(overlay.destroyed).toBe(true);
  });
});

describe('what the overlay refuses, and why it says so', () => {
  it('refuses a tint whose indices could not have been computed against these bytes', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 10);
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([], [a.visual], () => engine, host());
    const report = runtime.apply({
      islandId: REGION_A,
      tints: [tint(1, 'splats-a', [4, 2]), tint(2, 'splats-a', [9, 10]), tint(3, 'splats-a', [7])],
      palette: new Map([[3, RED]]),
    });
    expect(report.refused.map((item) => item.reason)).toEqual([
      "Slot 1 names samples out of order or beyond this asset's 10.",
      "Slot 2 names samples out of order or beyond this asset's 10.",
    ]);
    expect([...report.assets[0]!.indices]).toEqual([7]);
  });

  it('does not tint point maps a region draws as trained geometry, or assets it does not draw at all', () => {
    const region = island(REGION_A);
    const trained = trainedVisual(region, 'splats-a', 4);
    const hidden = pointVisual(region, 'points-a', new Float32Array(12), trained.visual.geometry.sceneId);
    const { engine, overlays } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([hidden], [trained.visual], () => engine, host());
    const report = runtime.apply({
      islandId: REGION_A,
      tints: [tint(1, 'points-a', [0]), tint(2, 'elsewhere', [0])],
      palette: new Map(),
    });
    expect(overlays).toEqual([]);
    expect(trained.held.gsplat.setWorkBufferModifier).not.toHaveBeenCalled();
    expect(report.refused).toEqual([
      { artifactId: 'points-a', reason: 'Not drawn: this region draws its trained geometry instead of its point maps.' },
      { artifactId: 'elsewhere', reason: 'Not drawn in this region, so there is nothing of it to tint.' },
    ]);
  });
});

describe('where the tinted samples are, for a click', () => {
  it('reports atlas positions through the scene transform and the region placement', () => {
    const region = island(REGION_A, 10);
    const centres = Float32Array.from([0, 0, 0, 1, 2, 3, -1, 0.5, 4]);
    const trained = trainedVisual(region, 'splats-a', 3, centres);
    const points = pointVisual(island(REGION_B, -20), 'points-b', Float32Array.from([1, 0, 0, 0, 1, 0]));
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([points], [trained.visual], () => engine, host());

    const [asset] = runtime.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [1, 2])], palette: new Map() }).assets;
    const expected = [[1, 2, 3], [-1, 0.5, 4]].map(([x, y, z]) =>
      localToAtlas(region.placement, localVec3(2 * x! + 1, 2 * y!, 2 * z! - 3)));
    expect([...asset!.positions!].map((value) => Number(value.toFixed(4))))
      .toEqual(expected.flatMap((p) => [p.x, p.y, p.z]).map((value) => Number(value.toFixed(4))));

    const [pointAsset] = runtime.apply({ islandId: REGION_B, tints: [tint(1, 'points-b', [1])], palette: new Map() }).assets;
    const point = localToAtlas(points.island.placement, localVec3(0, 1, 0));
    expect([...pointAsset!.positions!].map((value) => Number(value.toFixed(4))))
      .toEqual([point.x, point.y, point.z].map((value) => Number(value.toFixed(4))));
  });

  it('says it holds no positions for a trained scene whose centres stayed on the GPU', () => {
    const trained = trainedVisual(island(REGION_A), 'splats-a', 3, null);
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([], [trained.visual], () => engine, host());
    const [asset] = runtime.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [0])], palette: new Map() }).assets;
    expect(asset!.positions).toBeNull();
  });
});

describe('the numbers the overlay hands the renderer', () => {
  it('gives a sample to the first tint that names it', () => {
    const { slots, refused } = segmentSlotsFor(6, [tint(2, 'a', [1, 2]), tint(3, 'a', [2, 3])]);
    expect([...slots]).toEqual([0, 2, 2, 3, 0, 0]);
    expect(refused).toEqual([]);
    expect(segmentSlotsFor(2, [tint(0, 'a', [0])]).refused).toEqual(['Slot 0 is outside 1 to 255.']);
  });

  it('leaves slot 0 all zero, which is what makes a sample in no segment an exact identity', () => {
    const bytes = segmentPaletteBytes(new Map([[255, [0.5, 1, 0, 0.25] as ProofLensColor]]));
    expect(bytes.length).toBe(1024);
    expect([...bytes.slice(0, 4)]).toEqual([0, 0, 0, 0]);
    expect([...bytes.slice(1020)]).toEqual([128, 255, 0, 64]);
    expect(() => segmentPaletteBytes(new Map([[0, RED]]))).toThrow(RangeError);
    expect(() => segmentPaletteBytes(new Map([[256, RED]]))).toThrow(RangeError);
  });

  it('groups a point order untinted first, preserving each sample index', () => {
    const { order, groups } = segmentPointGroups(Uint8Array.from([3, 0, 3, 1, 0]));
    expect([...order]).toEqual([1, 4, 3, 0, 2]);
    expect(groups).toEqual([{ slot: 0, base: 0, count: 2 }, { slot: 1, base: 2, count: 1 }, { slot: 3, base: 3, count: 2 }]);
  });

  it('keeps the lens arithmetic, reads the splat by its own index, and defines every hook', () => {
    for (const source of [SEGMENT_OVERLAY_SPLAT_MODIFIER.glsl, SEGMENT_OVERLAY_SPLAT_MODIFIER.wgsl]) {
      expect(source).toContain('uProofLens');
      expect(source).toContain('0.2126, 0.7152, 0.0722');
      expect(source).toContain('0.004');
      expect(source).toContain('splat.index');
      expect(source).toContain('modifySplatCenter');
      expect(source).toContain('modifySplatRotationScale');
      expect(source).toContain('modifySplatColor');
    }
    expect(SEGMENT_OVERLAY_SPLAT_MODIFIER.glsl).toContain('uniform sampler2D uSegmentSlots;');
    expect(SEGMENT_OVERLAY_SPLAT_MODIFIER.wgsl).toContain('var uSegmentSlots : texture_2d<f32>;');
  });
});

describe('the proof lens and the overlay share one modifier slot without taking it from each other', () => {
  function bindingWith(visual: ReturnType<typeof trainedVisual>['visual']) {
    const prepared = new Set<pc.Entity>();
    const binding = Object.create(AtlasBinding.prototype) as AtlasBinding;
    const { engine } = fakeEngine();
    const runtime = new SegmentOverlayRuntime([], [visual], () => engine, {
      lensPrepared: (entity) => prepared.has(entity), settle: () => undefined, invalidate: () => undefined,
    });
    Object.assign(binding, {
      islands: [], trainedScenes: [visual], proofLensSplatsPrepared: prepared,
      proofLensSettleUntil: -1, elapsed: 0, dirty: false, segmentOverlay: runtime,
    });
    return binding;
  }

  it('installs the lens as before when no overlay is on', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 4);
    bindingWith(a.visual).setProofLens(new Map([[REGION_A, [0, 1, 0, 0.5] as ProofLensColor]]));
    expect(a.held.gsplat.setWorkBufferModifier.mock.calls).toEqual([[PROOF_LENS_SPLAT_MODIFIER]]);
  });

  it('keeps the segment modifier when the lens arrives second, and hands the lens its own when the overlay leaves', () => {
    const a = trainedVisual(island(REGION_A), 'splats-a', 4);
    const binding = bindingWith(a.visual);
    binding.segmentOverlay.apply({ islandId: REGION_A, tints: [tint(1, 'splats-a', [1])], palette: new Map([[1, RED]]) });
    binding.setProofLens(new Map([[REGION_A, [0, 1, 0, 0.5] as ProofLensColor]]));

    expect(a.held.gsplat.modifier).toBe(SEGMENT_OVERLAY_SPLAT_MODIFIER);
    expect(a.held.parameters.get('uProofLens')).toEqual([0, 1, 0, 0.5]);

    binding.segmentOverlay.apply(null);
    expect(a.held.gsplat.modifier).toBe(PROOF_LENS_SPLAT_MODIFIER);
    expect(a.held.parameters.get('uProofLens')).toEqual([0, 1, 0, 0.5]);
    expect(a.held.parameters.has('uSegmentSlots')).toBe(false);
  });
});
