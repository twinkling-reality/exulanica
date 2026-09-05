// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { atlasVec3, islandId, localVec3, makeIsland, placement } from '@exulanica/atlas-core';
import { AtlasBinding, sceneInspectionViews, type PlacedScenePointMap, type PointMap } from '../src/playcanvas/index.js';

const island = makeIsland({
  islandId: islandId('island'), createdAt: 0,
  placement: placement(atlasVec3(10, 2, 30), Math.PI / 2, 3),
  rung: 3, scaleIsMetric: false, footprintRadiusLocal: 20,
  viewpointLocal: localVec3(0, 0, 0), anchors: [], layoutEntities: new Set(),
});
const map = (x: number): PlacedScenePointMap => ({
  sceneId: 'scene', artifactId: `artifact:${x}`, islandId: island.islandId,
  map: { header: { viewpoint: { position: [0, 0, 0], fovYDeg: 55, aspect: 1.5 } } } as unknown as PointMap,
  sceneFromOpmRowMajor: [2, 0, 0, x, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1],
  localUnitsToSceneUnits: 2,
});

describe('bounded reconstruction inspection', () => {
  it('preserves the source projection and transforms fitted camera axes exactly once', () => {
    const views = sceneInspectionViews(island, [map(1), map(5)]);
    expect(views.map((view) => view.kind)).toEqual(['source-camera', 'between-cameras', 'source-camera']);
    expect(views[0]!.position[0]).toBeCloseTo(10);
    expect(views[0]!.position[1]).toBe(2);
    expect(views[0]!.position[2]).toBeCloseTo(27);
    expect(views[0]!.forward[0]).toBeCloseTo(-1);
    expect(views[0]!.forward[2]).toBeCloseTo(0);
    expect(views[0]!.up).toEqual([0, 1, 0]);
    expect(views[0]!.fovYDeg).toBe(55);
    expect(views[0]!.sourceAspect).toBe(1.5);
    expect(views[1]!.position[2]).toBeCloseTo(21);
    expect(views[1]!.artifactIds).toEqual(['artifact:1', 'artifact:5']);
    expect(sceneInspectionViews(island, [map(1), map(5)])).toEqual(views);
  });

  it('never joins different scenes or invents a midpoint for opposing cameras', () => {
    const second = { ...map(5), sceneId: 'other' };
    expect(sceneInspectionViews(island, [map(1), second])).toHaveLength(2);
    const opposite = { ...map(5), sceneFromOpmRowMajor: [-2, 0, 0, 5, 0, 2, 0, 0, 0, 0, -2, 0, 0, 0, 0, 1] };
    expect(sceneInspectionViews(island, [map(1), opposite])).toHaveLength(2);
    expect(sceneInspectionViews(island, [{ ...map(1), islandId: islandId('other') }])).toEqual([]);
  });

  it('keeps inspection out of walking and restores the exact original pose and field of view', () => {
    const start = { x: 1.2345, y: 2.3456, z: -9.123, yaw: 0.63, pitch: -0.21 };
    const views = sceneInspectionViews(island, [map(1), map(5)]);
    const enabled = vi.fn();
    const binding = Object.create(AtlasBinding.prototype) as AtlasBinding;
    Object.assign(binding, {
      controls: { state: { ...start }, setEnabled: enabled },
      camera: { camera: { fov: 73 } }, device: { canvas: document.createElement('canvas') },
      inspection: null, mapState: null, navigationTransition: null, applicationControlsEnabled: true,
      sourceFirst: { setResidency: vi.fn() }, islands: [], residencyAllocated: new Map(),
      trainedScenes: [],
      inspectionViews: () => views,
    });
    expect(binding.inspectSceneView('scene', views[0]!.id)).toBe(true);
    binding.setControlsEnabled(true);
    expect(enabled).toHaveBeenLastCalledWith(false);
    expect(binding.camera.camera!.fov).toBe(55);
    expect(binding.inspectSceneView('scene', views[2]!.id)).toBe(true);
    expect(binding.inspectionView?.id).toBe(views[2]!.id);
    expect(binding.inspectSceneView('scene', 'unavailable')).toBe(false);
    expect(binding.inspectionView?.id).toBe(views[2]!.id);
    binding.endSceneInspection();
    expect(binding.controls.state).toEqual(start);
    expect(binding.camera.camera!.fov).toBe(73);
    expect(enabled).toHaveBeenLastCalledWith(true);
    expect(binding.inspectionView).toBeNull();
  });
});
