import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  MAX_RETAINED_POINTS,
  meshLocalExtent,
  meshSurfaceArea,
  representationParentVisible,
  representationWorldBounds,
  sampledMeshPositions,
  sampledMeshSurfacePositions,
  staticMeshRepresentation,
} from '../src/playcanvas/representation-binding.js';
import { AtlasBinding } from '../src/playcanvas/atlas-binding.js';
import { RepresentationRuntime } from '../src/playcanvas/representation-runtime.js';
import { DATA_VIEW_STYLE, REPRESENTATION_POINTS_PER_SUBJECT, type RepresentationSubject } from '@exulanica/atlas-core';

const subject: RepresentationSubject = {
  subjectId: 'authored:batch', subjectKind: 'geometry-group', sceneId: null,
  frameId: 'district:render-metres', origin: 'authored', sourceRefs: ['recipe:one'],
  availability: 'available', rendered: true, points: 'mesh-vertices',
  compatibleBlend: true, bounds: null, label: null, dataAvailable: false,
  unavailableReason: null,
};

describe('PlayCanvas representation binding', () => {
  it('inherits existing ancestor visibility without changing the hierarchy', () => {
    const root = { enabled: true, parent: null } as unknown as pc.GraphNode;
    const child = { enabled: true, parent: root } as unknown as pc.GraphNode;
    expect(representationParentVisible(child)).toBe(true);
    (root as unknown as { enabled: boolean }).enabled = false;
    expect(representationParentVisible(child)).toBe(false);
    expect(child.parent).toBe(root);
  });

  it('samples exact finite mesh vertices in the borrowed frame', () => {
    const positions = [0, 1, 2, 10, 11, 12, 20, 21, 22, 30, 31, 32];
    expect([...sampledMeshPositions(positions, 2)!]).toEqual([0, 1, 2, 20, 21, 22]);
    expect(sampledMeshPositions([0, Number.NaN, 2], 1)).toBeNull();
    expect(sampledMeshPositions([0, 1], 1)).toBeNull();
  });

  it('fills sparse triangle surfaces with bounded deterministic presentation samples', () => {
    const positions = [0, 0, 0, 2, 0, 0, 0, 2, 0];
    const first = sampledMeshSurfacePositions(positions, [0, 1, 2], 64)!;
    expect(first).toEqual(sampledMeshSurfacePositions(positions, [0, 1, 2], 64));
    expect(first).toHaveLength(192);
    for (let offset = 0; offset < first.length; offset += 3) {
      expect(first[offset]).toBeGreaterThanOrEqual(0);
      expect(first[offset + 1]).toBeGreaterThanOrEqual(0);
      expect(first[offset]! + first[offset + 1]!).toBeLessThanOrEqual(2.000001);
      expect(first[offset + 2]).toBe(0);
    }
    expect(sampledMeshSurfacePositions(positions, [0, 1, 9], 4)).toBeNull();
    expect(sampledMeshSurfacePositions(positions, [], REPRESENTATION_POINTS_PER_SUBJECT))
      .toHaveLength(REPRESENTATION_POINTS_PER_SUBJECT * 3);
    expect(sampledMeshSurfacePositions(positions, [], REPRESENTATION_POINTS_PER_SUBJECT + 1)).toBeNull();
    expect(sampledMeshSurfacePositions([0, 0, 0, 1, 0, 0, 2, 0, 0], [], 4)).toBeNull();
  });

  it('measures the surface a sampled draw would cover, and the mesh\'s own extent', () => {
    expect(meshSurfaceArea([0, 0, 0, 2, 0, 0, 0, 2, 0, 2, 2, 0], [0, 1, 2, 1, 3, 2])).toBeCloseTo(4);
    expect(meshSurfaceArea([0, 0, 0, 2, 0, 0, 0, 2, 0], [])).toBeCloseTo(2);
    expect(meshSurfaceArea([0, 0, 0, 2, 0, 0, 0, 2, 0], [0, 1, 7])).toBeNaN();
    const aabb = new pc.BoundingBox(new pc.Vec3(1, 2, 3), new pc.Vec3(4, 5, 6));
    expect(meshLocalExtent({ aabb } as pc.Mesh)).toEqual({ min: [-3, -3, -3], max: [5, 7, 9] });
    const broken = new pc.BoundingBox(new pc.Vec3(Number.NaN, 0, 0), new pc.Vec3(1, 1, 1));
    expect(meshLocalExtent({ aabb: broken } as pc.Mesh)).toBeNull();
  });

  it('bounds retained address sampling by the retained buffer, not by triangle sampling', () => {
    expect(sampledMeshPositions({ length: (MAX_RETAINED_POINTS + 1) * 3 } as ArrayLike<number>, 1)).toBeNull();
    const large = new Float32Array(300_000 * 3).map((_, index) => index % 7);
    expect(sampledMeshPositions(large, 4)).toHaveLength(12);
  });

  it('projects explicit-frame bounds through the existing node transform', () => {
    const matrix = new pc.Mat4().setTranslate(10, 20, 30);
    const node = { getWorldTransform: () => matrix } as unknown as pc.GraphNode;
    expect(representationWorldBounds({
      frameId: 'district:render-metres', units: 'metres', origin: 'external',
      basis: 'source-bounds', min: [1, 2, 3], max: [4, 5, 6],
    }, node)).toContainEqual([11, 22, 33]);
    expect(() => representationWorldBounds({
      frameId: 'source-mm', units: 'millimetres', origin: 'external',
      basis: 'source-bounds', min: [0, 0, 0], max: [1, 1, 1],
    }, node)).toThrow('units');
  });

  it('clones a standard material for blending and restores every borrowed state', () => {
    const original = new pc.StandardMaterial();
    original.opacity = 0.8;
    original.blendType = pc.BLEND_NONE;
    original.depthWrite = true;
    const node = { enabled: true, parent: null } as unknown as pc.GraphNode;
    const instance = {
      material: original, skinInstance: null, morphInstance: null, visible: true, node,
      mesh: { vertexBuffer: { numVertices: 3 }, primitive: [{ type: pc.PRIMITIVE_TRIANGLES }],
        getPositions: () => undefined, getIndices: () => undefined },
    } as unknown as pc.MeshInstance;
    const draw = staticMeshRepresentation({} as pc.GraphicsDevice, instance, () => subject);
    expect(draw).not.toBeNull();
    draw!.setRenderedWeight(0.5);
    expect(instance.material).not.toBe(original);
    expect((instance.material as pc.StandardMaterial).opacity).toBeCloseTo(0.4);
    // A dissolve, not a blend: the surface stays opaque and depth-writing while it loses pixels.
    expect((instance.material as pc.StandardMaterial).opacityDither).toBe(pc.DITHER_IGNNOISE);
    expect((instance.material as pc.StandardMaterial).blendType).toBe(pc.BLEND_NONE);
    expect((instance.material as pc.StandardMaterial).depthWrite).toBe(true);
    expect(original.opacity).toBe(0.8);
    expect(original.opacityDither).toBe(pc.DITHER_NONE);
    expect(original.blendType).toBe(pc.BLEND_NONE);
    expect(original.depthWrite).toBe(true);
    const clone = instance.material as pc.StandardMaterial;
    let copies = 0;
    const copy = clone.copy.bind(clone);
    clone.copy = value => { copies += 1; return copy(value); };
    draw!.setRenderedWeight(0.5);
    expect(copies).toBe(0);
    draw!.refresh?.();
    draw!.setRenderedWeight(0.5);
    expect(copies).toBe(1);
    draw!.setRenderedWeight(0);
    expect(instance.visible).toBe(true);
    expect((instance.material as pc.StandardMaterial).opacity).toBe(0);
    draw!.restore();
    expect(instance.material).toBe(original);
    expect(instance.visible).toBe(true);
  });

  it('asks for points in proportion to the surface it samples', () => {
    const node = { enabled: true, parent: null } as unknown as pc.GraphNode;
    const positions = [0, 0, 0, 4, 0, 0, 0, 5, 0];
    const instance = {
      material: new pc.StandardMaterial(), skinInstance: null, morphInstance: null, visible: true, node,
      mesh: { vertexBuffer: { numVertices: 3 }, primitive: [{ type: pc.PRIMITIVE_TRIANGLES }],
        getPositions: (out: number[]) => { out.push(...positions); }, getIndices: () => undefined },
    } as unknown as pc.MeshInstance;
    const draw = staticMeshRepresentation({} as pc.GraphicsDevice, instance, () => subject)!;
    expect(draw.pointDemand!()).toBeCloseTo(10 * DATA_VIEW_STYLE.points.densityPerSquareMetre);
  });

  it('refuses skinned, morphing, non-standard and oversized draws', () => {
    const node = { enabled: true, parent: null } as unknown as pc.GraphNode;
    const base = {
      material: new pc.StandardMaterial(), skinInstance: null, morphInstance: null,
      visible: true, node,
      mesh: { vertexBuffer: { numVertices: 3 }, primitive: [{ type: pc.PRIMITIVE_TRIANGLES }],
        getPositions: () => undefined, getIndices: () => undefined },
    };
    for (const changes of [
      { skinInstance: {} }, { morphInstance: {} }, { material: {} },
      { mesh: { vertexBuffer: { numVertices: 250_001 }, primitive: [{ type: pc.PRIMITIVE_TRIANGLES }],
        getPositions: () => undefined, getIndices: () => undefined } },
    ]) expect(staticMeshRepresentation({} as pc.GraphicsDevice,
      { ...base, ...changes } as unknown as pc.MeshInstance, () => subject)).toBeNull();
  });

  it('validates current subject records atomically before changing rights or metadata', () => {
    const second: RepresentationSubject = {
      ...subject, subjectId: 'authored:second', label: 'Second', sourceRefs: ['recipe:two'],
    };
    const overrides = new Map<string, RepresentationSubject>();
    const binding = Object.create(AtlasBinding.prototype) as AtlasBinding;
    Object.assign(binding as unknown as Record<string, unknown>, {
      representationController: new RepresentationRuntime(),
      representationDefaults: new Map([
        [subject.subjectId, subject],
        [second.subjectId, second],
      ]),
      representationOverrides: overrides,
      onRepresentationChange: null,
    });
    expect(() => binding.setRepresentationSubjects([
      { ...subject, label: 'Accepted only if the batch is valid' },
      { ...second, sourceRefs: [''] },
    ])).toThrow('Unsupported representation subject');
    expect(overrides.size).toBe(0);
    expect(() => binding.setRepresentationSubjects([{ ...subject, blend: 'overlay' }])).toThrow('changed blend');
    const record = { kind: 'city.massing' as const, version: 1, identity: '5f0c7a2e-1b3d-4c5e-8f60-718293a4b5c6', key: 'parcel_ordinal.3' };
    const generated: RepresentationSubject = {
      ...subject, subjectId: 'generated:record', origin: 'generated', subjectKind: 'object', record,
    };
    (binding as unknown as { representationDefaults: Map<string, RepresentationSubject> })
      .representationDefaults.set(generated.subjectId, generated);
    expect(() => binding.setRepresentationSubjects([{ ...generated, record: { ...record, key: 'parcel_ordinal.4' } }]))
      .toThrow('changed record');
    expect(overrides.size).toBe(0);

    const sources = ['current:one'];
    binding.setRepresentationSubjects([{ ...subject, sourceRefs: sources, label: 'Current' }]);
    sources[0] = 'mutated:later';
    const accepted = overrides.get(subject.subjectId)!;
    expect(accepted.sourceRefs).toEqual(['current:one']);
    expect(accepted.label).toBe('Current');
  });
});
