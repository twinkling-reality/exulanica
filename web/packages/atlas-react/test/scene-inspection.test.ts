// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { Mat4 } from 'playcanvas';
import { atlasVec3, islandId, localVec3, makeIsland, placement } from '@exulanica/atlas-core';
import { AtlasBinding, sceneInspectionViews, validateRecoveredSceneCamera,
  type RecoveredSceneCamera, type PlacedScenePointMap, type PointMap } from '../src/playcanvas/index.js';

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
const recovered = (x: number, ordinal = 0): RecoveredSceneCamera => ({
  sceneId: 'scene', islandId: island.islandId, captureId: `capture:${x}`, ordinal,
  poseReceiptSha256: 'a'.repeat(64), projection: 'pinhole',
  sceneFromCameraRowMajor: [1, 0, 0, x, 0, 1, 0, 3, 0, 0, 1, 4, 0, 0, 0, 1],
  calibration: { model: 'PINHOLE', width: 800, height: 600, fx: 800, fy: 600, cx: 300, cy: 280,
    parameters: [800, 600, 300, 280] },
});

describe('bounded reconstruction inspection', () => {
  it('uses accepted cameras without any OPM and preserves exact capture, receipt, calibration, and order', () => {
    const views = sceneInspectionViews(island, [], [recovered(5, 1), recovered(2)]);
    expect(views.map((view) => view.id)).toEqual(['scene:camera:capture:2',
      'scene:midpoint:capture:2:capture:5', 'scene:camera:capture:5']);
    expect(views[0]!.position).toEqual([22, 11, 24]);
    expect(views[0]!.captureIds).toEqual(['capture:2']);
    expect(views[0]!.poseReceiptSha256).toBe('a'.repeat(64));
    expect(views[0]!.artifactIds).toEqual([]);
    expect(views[0]!.fovYDeg).toBeCloseTo(2 * Math.atan(0.5) * 180 / Math.PI);
    expect(views[0]!.calibration).toEqual(recovered(2).calibration);
    expect(views[1]!.projection).toBe('interpolated');
    expect(views[1]!.calibration).toBeNull();
    const withMap = sceneInspectionViews(island, [{ ...map(90), captureId: 'capture:2' }], [recovered(2)]);
    expect(withMap[0]!.position).toEqual(views[0]!.position);
    expect(withMap[0]!.fovYDeg).not.toBe(55);
    expect(() => validateRecoveredSceneCamera({ ...recovered(2),
      sceneFromCameraRowMajor: map(2).sceneFromOpmRowMajor })).toThrow(/declared uniform scale/);
  });

  it('opens a loaded trained scene without maps and restores the prior projection after calibrated inspection', () => {
    const originalProjection = vi.fn();
    const camera = { fov: 73, aspectRatio: 4 / 3, nearClip: 0.1, farClip: 1000,
      calculateProjection: originalProjection };
    const binding = Object.create(AtlasBinding.prototype) as AtlasBinding;
    Object.assign(binding, {
      islands: [], trainedScenes: [{ island, geometry: { sceneId: 'scene' }, entity: {} }],
      recoveredCameras: [recovered(2)], camera: { camera },
      controls: { state: { x: 1, y: 2, z: 3, yaw: 0, pitch: 0 }, setEnabled: vi.fn() },
      device: { canvas: document.createElement('canvas') }, inspection: null, mapState: null,
      navigationTransition: null, applicationControlsEnabled: true,
      sourceFirst: { setResidency: vi.fn() }, residencyAllocated: new Map(),
    });
    expect(binding.inspectionViews('unloaded')).toEqual([]);
    const views = binding.inspectionViews('scene');
    expect(views).toHaveLength(1);
    expect(binding.inspectSceneView('scene', views[0]!.id)).toBe(true);
    const matrix = new Mat4();
    binding.camera.camera!.calculateProjection(matrix, 0);
    // Independently project a known camera-space ray using retained fx/fy/cx/cy.
    const d = matrix.data;
    const ndcX = (d[0]! * 0.2 + d[8]! * -2) / 2;
    const ndcY = (d[5]! * 0.1 + d[9]! * -2) / 2;
    expect(ndcX).toBeCloseTo(2 * (800 * 0.2 / 2 + 300) / 800 - 1);
    expect(ndcY).toBeCloseTo(1 - 2 * (280 - 600 * 0.1 / 2) / 600);
    binding.endSceneInspection();
    expect(camera.calculateProjection).toBe(originalProjection);
    expect(camera.fov).toBe(73);
  });
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
