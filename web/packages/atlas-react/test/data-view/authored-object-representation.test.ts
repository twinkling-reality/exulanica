// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { DEFAULT_REPRESENTATION_INTENT, type IslandId } from '@exulanica/atlas-core';
import { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { RepresentationRuntime } from '../../src/playcanvas/representation-runtime.js';
import {
  AUTHORED_OBJECT_MEDIA_TYPE,
  SceneObjectRuntime,
  type ObjectRepresentationRegistration,
  type PlacedAuthoredObject,
} from '../../src/playcanvas/scene-objects.js';
import {
  meshLocalExtent,
  representationWorldBounds,
} from '../../src/playcanvas/representation-binding.js';

const ISLAND = 'region-a' as IslandId;
const FIXTURES = resolve(process.cwd(), 'packages/graph-client/test/fixtures');

/** A permitted self-contained GLB with two static meshes under distinct transformed nodes. */
function staticMultiMeshFixture(): ArrayBuffer {
  const positions = [
    0, 0, 0, 1, 0, 0, 0, 1, 0,
    0, 0, 0, 0, 1, 0, 0, 0, 2,
  ];
  const binary = new ArrayBuffer(positions.length * 4);
  const binaryView = new DataView(binary);
  positions.forEach((value, index) => binaryView.setFloat32(index * 4, value, true));
  const gltf = {
    asset: { version: '2.0', generator: 'Exulanica bounded static multi-mesh test fixture' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [
      { name: 'assembly', translation: [0.5, 0.25, -0.75], children: [1, 2] },
      { name: 'left-static', mesh: 0, translation: [-1, 0, 0],
        rotation: [0, 0, 0.3826834323650898, 0.9238795325112867], scale: [2, 1, 0.5] },
      { name: 'right-static', mesh: 1, translation: [2, 1, 1],
        rotation: [0, 0.5, 0, 0.8660254037844386], scale: [0.5, 2, 1.5] },
    ],
    meshes: [
      { name: 'left-triangle', primitives: [{ attributes: { POSITION: 0 }, material: 0 }] },
      { name: 'right-triangle', primitives: [{ attributes: { POSITION: 1 }, material: 0 }] },
    ],
    materials: [{ pbrMetallicRoughness: {
      baseColorFactor: [0.55, 0.72, 0.92, 1], metallicFactor: 0, roughnessFactor: 0.8,
    } }],
    accessors: [
      { bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [1, 1, 0] },
      { bufferView: 1, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [0, 1, 2] },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: 36, target: 34962 },
      { buffer: 0, byteOffset: 36, byteLength: 36, target: 34962 },
    ],
    buffers: [{ byteLength: binary.byteLength }],
  };
  const jsonSource = new TextEncoder().encode(JSON.stringify(gltf));
  const jsonLength = Math.ceil(jsonSource.length / 4) * 4;
  const length = 12 + 8 + jsonLength + 8 + binary.byteLength;
  const bytes = new ArrayBuffer(length);
  const view = new DataView(bytes);
  view.setUint32(0, 0x46546c67, true); view.setUint32(4, 2, true); view.setUint32(8, length, true);
  view.setUint32(12, jsonLength, true); view.setUint32(16, 0x4e4f534a, true);
  const json = new Uint8Array(bytes, 20, jsonLength);
  json.fill(0x20); json.set(jsonSource);
  const binaryHeader = 20 + jsonLength;
  view.setUint32(binaryHeader, binary.byteLength, true);
  view.setUint32(binaryHeader + 4, 0x004e4942, true);
  new Uint8Array(bytes, binaryHeader + 8).set(new Uint8Array(binary));
  return bytes;
}

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.AnimComponentSystem];
  options.resourceHandlers = [pc.TextureHandler, pc.ContainerHandler];
  app.init(options);
  const atlas = Object.create(AtlasBinding.prototype) as AtlasBinding;
  Object.assign(atlas as unknown as Record<string, unknown>, {
    app, device,
    representationController: new RepresentationRuntime(256, 64),
    representationDefaults: new Map(),
    representationOverrides: new Map(),
    representationFrames: new Map(),
    representationSelectionObservers: new Set(),
    ownedDistrict: null,
    onRepresentationChange: null,
    dirty: false,
  });
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const register = (object: PlacedAuthoredObject, entity: pc.Entity): ObjectRepresentationRegistration =>
    (atlas as unknown as {
      registerAuthoredObjectRepresentation(
        held: PlacedAuthoredObject,
        node: pc.Entity,
      ): ObjectRepresentationRegistration;
    }).registerAuthoredObjectRepresentation(object, entity);
  const runtime = new SceneObjectRuntime(app, new Map([[ISLAND, region]]), {
    registerRepresentation: register,
    invalidate: () => atlas.invalidate(),
  });
  return { app, atlas, runtime, region };
}

function reviewed(key: string, objectId: string, behaviour: PlacedAuthoredObject['behaviour'] = null) {
  const buffer = readFileSync(resolve(FIXTURES, `${key}.glb`));
  const bytes = Uint8Array.from(buffer).buffer;
  const object: PlacedAuthoredObject = {
    objectId,
    islandId: ISLAND,
    asset: {
      assetKey: key,
      mediaType: AUTHORED_OBJECT_MEDIA_TYPE,
      contentSha256: createHash('sha256').update(buffer).digest('hex'),
      byteSize: buffer.byteLength,
    },
    transform: { xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 0, scaleMilli: 1000 },
    behaviour,
  };
  return { bytes, object };
}

function reviewedFixture(
  bytes: ArrayBuffer,
  objectId: string,
  behaviour: PlacedAuthoredObject['behaviour'] = null,
) {
  const object: PlacedAuthoredObject = {
    objectId,
    islandId: ISLAND,
    asset: {
      assetKey: 'cc0.fixture-static-multi',
      mediaType: AUTHORED_OBJECT_MEDIA_TYPE,
      contentSha256: createHash('sha256').update(new Uint8Array(bytes)).digest('hex'),
      byteSize: bytes.byteLength,
    },
    transform: { xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 0, scaleMilli: 1000 },
    behaviour,
  };
  return { bytes, object };
}

const matrices = (node: pc.GraphNode): number[] => [...node.getWorldTransform().data];

function worldExtent(instances: readonly pc.MeshInstance[]) {
  const points: (readonly [number, number, number])[] = [];
  const local = new pc.Vec3();
  const world = new pc.Vec3();
  for (const instance of instances) {
    const extent = meshLocalExtent(instance.mesh)!;
    for (const x of [extent.min[0], extent.max[0]]) for (const y of [extent.min[1], extent.max[1]]) {
      for (const z of [extent.min[2], extent.max[2]]) {
        instance.node.getWorldTransform().transformPoint(local.set(x, y, z), world);
        points.push([world.x, world.y, world.z]);
      }
    }
  }
  return {
    min: [0, 1, 2].map(axis => Math.min(...points.map(point => point[axis]!))),
    max: [0, 1, 2].map(axis => Math.max(...points.map(point => point[axis]!))),
  };
}

describe('authored-object representation', () => {
  it('registers every reviewed marker as one authored subject with generated surface samples', async () => {
    const { app, atlas, runtime } = setup();
    for (const [index, key] of [
      'cc0.marker-cube', 'cc0.marker-pillar', 'cc0.marker-plate',
    ].entries()) {
      const { bytes, object } = reviewed(key, `object:marker-${index}`);
      expect(await runtime.place(object, bytes)).toMatchObject({ notices: [] });
    }
    const report = atlas.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    expect(report.subjects).toHaveLength(3);
    for (const entry of report.subjects) {
      expect(entry).toMatchObject({
        subject: {
          subjectKind: 'object', origin: 'authored', points: 'mesh-surface-samples',
          compatibleBlend: true, bounds: { basis: 'authored-bounds', units: 'scene-units' },
        },
        resolved: { pointLabel: 'Generated surface samples', renderedWeight: 0, pointWeight: 1 },
      });
      expect(entry.subject.sourceRefs).toHaveLength(1);
      expect(entry.allocatedPoints).toBeGreaterThan(0);
    }
    runtime.destroy();
    app.destroy();
  });

  it('keeps the surface and points in one frame through pose, motion and region transforms', async () => {
    const { app, atlas, runtime, region } = setup();
    const { bytes, object } = reviewed('cc0.marker-cube', 'object:moving', {
      behaviourKey: 'motion.bounded-path', behaviourVersion: 1,
      parameters: { axis: 'y', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000 },
    });
    await runtime.place(object, bytes);
    const entity = region.findByName('authored-object:object:moving') as pc.Entity;
    const instance = (entity.findComponents('render')[0] as pc.RenderComponent).meshInstances[0]!;
    const originalMaterial = instance.material;
    atlas.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, boxes: true });
    const points = instance.node.findByName('data-view-points:object:moving') as pc.Entity;
    expect(points.parent).toBe(instance.node);
    expect(matrices(points)).toEqual(matrices(instance.node));
    expect(instance.material).not.toBe(originalMaterial);

    region.setLocalPosition(10, 3, -7);
    region.setLocalEulerAngles(0, 30, 0);
    runtime.setTransform('object:moving', {
      xMm: -2000, yMm: 500, zMm: 4000, yawMicroradians: 1_570_796, scaleMilli: 1750,
    });
    atlas.representation.update();
    expect(instance.node.findByName('data-view-points:object:moving')).toBe(points);
    expect(matrices(points)).toEqual(matrices(instance.node));

    expect(runtime.control('object:moving', 'trigger')).toEqual({ ok: true });
    expect(runtime.animating).toBe(true);
    runtime.update(2);
    expect(matrices(points)).toEqual(matrices(instance.node));
    runtime.control('object:moving', 'stop');
    expect(runtime.animating).toBe(false);

    atlas.setRepresentationIntent({ ...atlas.representationReport.intent, pointMix: 0 });
    expect(instance.material).toBe(originalMaterial);

    const observed = vi.fn();
    atlas.observeRepresentationSelection(observed);
    atlas.setRepresentationSelection('object:moving');
    runtime.remove('object:moving');
    expect(points.parent).toBeNull();
    expect(atlas.representationReport.subjects).toHaveLength(0);
    expect(atlas.representationReport.selection).toBeNull();
    expect(observed).toHaveBeenLastCalledWith(null, 'unregistered');
    app.destroy();
  });

  it('keeps a transformed static multi-mesh fixture one bounded authored subject', async () => {
    const { app, atlas, runtime, region } = setup();
    const fixture = staticMultiMeshFixture();
    const { bytes, object } = reviewedFixture(fixture, 'object:multi-static', {
      behaviourKey: 'motion.bounded-path', behaviourVersion: 1,
      parameters: { axis: 'x', easing: 'linear', travel_mm: 750, period_milliseconds: 3000 },
    });
    expect(await runtime.place(object, bytes)).toMatchObject({ notices: [] });
    const entity = region.findByName('authored-object:object:multi-static') as pc.Entity;
    const instances = (entity.findComponents('render') as pc.RenderComponent[])
      .flatMap(render => render.meshInstances);
    expect(instances).toHaveLength(2);

    const report = atlas.setRepresentationIntent({
      ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, boxes: true,
    });
    expect(report.subjects).toHaveLength(1);
    const entry = report.subjects[0]!;
    expect(entry).toMatchObject({
      subject: {
        subjectId: 'object:multi-static', subjectKind: 'object', origin: 'authored',
        sourceRefs: [object.asset.contentSha256], points: 'mesh-surface-samples',
        compatibleBlend: true, bounds: { basis: 'authored-bounds', units: 'scene-units' },
        unavailableReason: expect.stringContaining('not observed measurements, semantic parts or segmentation'),
      },
      resolved: { pointLabel: 'Generated surface samples', renderedWeight: 0, pointWeight: 1 },
      plannedPoints: 48,
      allocatedPoints: 48,
    });
    expect(report).toMatchObject({
      allocatedPoints: 48,
      pointBudget: 256,
      perSubjectLimit: 64,
    });
    const points = instances.map(instance =>
      instance.node.findByName('data-view-points:object:multi-static') as pc.Entity);
    expect(points.every(Boolean)).toBe(true);
    for (let index = 0; index < instances.length; index += 1) {
      expect(points[index]!.parent).toBe(instances[index]!.node);
      expect(matrices(points[index]!)).toEqual(matrices(instances[index]!.node));
    }

    const assertBoundsAgree = (exact: boolean) => {
      const bounds = atlas.representationReport.subjects[0]!.subject.bounds!;
      const reported = representationWorldBounds(bounds, entity);
      const actual = worldExtent(instances);
      for (const axis of [0, 1, 2]) {
        const reportedMin = Math.min(...reported.map(point => point[axis]!));
        const reportedMax = Math.max(...reported.map(point => point[axis]!));
        if (exact) {
          expect(reportedMin).toBeCloseTo(actual.min[axis]!, 5);
          expect(reportedMax).toBeCloseTo(actual.max[axis]!, 5);
        } else {
          // A rotated object-root AABB is conservative in world space, but never excludes a mesh.
          expect(reportedMin).toBeLessThanOrEqual(actual.min[axis]! + 1e-5);
          expect(reportedMax).toBeGreaterThanOrEqual(actual.max[axis]! - 1e-5);
        }
      }
    };
    assertBoundsAgree(true);

    region.setLocalPosition(8, -2, 11);
    region.setLocalEulerAngles(0, -35, 0);
    runtime.setTransform('object:multi-static', {
      xMm: -2800, yMm: 625, zMm: 3600, yawMicroradians: 785_398, scaleMilli: 1600,
    });
    expect(runtime.control('object:multi-static', 'trigger')).toEqual({ ok: true });
    runtime.update(1.25);
    atlas.representation.update();
    for (let index = 0; index < instances.length; index += 1) {
      expect(matrices(points[index]!)).toEqual(matrices(instances[index]!.node));
    }
    assertBoundsAgree(false);

    const observed = vi.fn();
    atlas.observeRepresentationSelection(observed);
    atlas.setRepresentationSelection('object:multi-static');
    runtime.remove('object:multi-static');
    expect(points.every(point => point.parent === null)).toBe(true);
    expect(atlas.representationReport.subjects).toHaveLength(0);
    expect(atlas.representationReport.selection).toBeNull();
    expect(observed).toHaveBeenLastCalledWith(null, 'unregistered');
    app.destroy();
  });

  it('hides both forms with residency and refuses an animated mesh without hiding it', async () => {
    const { app, atlas, runtime, region } = setup();
    const { bytes, object } = reviewed('cc0.marker-pillar', 'object:pillar');
    await runtime.place(object, bytes);
    atlas.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.5 });
    runtime.setResidency(new Map([[ISLAND, 'stub']]), false);
    const hidden = atlas.setRepresentationIntent({ ...atlas.representationReport.intent });
    expect(hidden.subjects[0]!.resolved.geometryVisible).toBe(false);
    runtime.setResidency(new Map([[ISLAND, 'full']]), false);

    const multi = new pc.Entity('multi');
    let animatedInstance: pc.MeshInstance | null = null;
    for (let index = 0; index < 2; index += 1) {
      const node = new pc.Entity(`mesh-${index}`);
      const mesh = new pc.Mesh(app.graphicsDevice);
      mesh.setPositions([0, 0, 0, 1, 0, 0, 0, 1, 0]);
      mesh.setIndices([0, 1, 2]);
      mesh.update(pc.PRIMITIVE_TRIANGLES);
      const material = new pc.StandardMaterial();
      const instance = new pc.MeshInstance(mesh, material, node);
      if (index === 1) Object.defineProperty(instance, 'morphInstance', {
        value: { destroy: vi.fn() }, configurable: true,
      });
      if (index === 1) animatedInstance = instance;
      node.addComponent('render', { meshInstances: [instance] });
      multi.addChild(node);
    }
    region.addChild(multi);
    const refused = (atlas as unknown as {
      registerAuthoredObjectRepresentation(
        held: PlacedAuthoredObject,
        node: pc.Entity,
      ): ObjectRepresentationRegistration;
    }).registerAuthoredObjectRepresentation({ ...object, objectId: 'object:multi' }, multi);
    expect(refused).toMatchObject({ ok: false, reason: expect.stringContaining('skinned or morphing') });
    expect(multi.enabled).toBe(true);
    expect(atlas.representationReport.subjects.map(entry => entry.subject.subjectId))
      .toEqual(['object:pillar']);
    runtime.destroy();
    if (animatedInstance !== null) Reflect.deleteProperty(animatedInstance, 'morphInstance');
    multi.destroy();
    app.destroy();
  });
});
