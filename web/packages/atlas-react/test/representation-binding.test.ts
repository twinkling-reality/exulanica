import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  representationParentVisible,
  representationWorldBounds,
  sampledMeshPositions,
  sampledMeshSurfacePositions,
  staticMeshRepresentation,
} from '../src/playcanvas/representation-binding.js';
import { AtlasBinding } from '../src/playcanvas/atlas-binding.js';
import { RepresentationRuntime } from '../src/playcanvas/representation-runtime.js';
import type { RepresentationSubject } from '@exulanica/atlas-core';

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
    expect(original.opacity).toBe(0.8);
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

    const sources = ['current:one'];
    binding.setRepresentationSubjects([{ ...subject, sourceRefs: sources, label: 'Current' }]);
    sources[0] = 'mutated:later';
    const accepted = overrides.get(subject.subjectId)!;
    expect(accepted.sourceRefs).toEqual(['current:one']);
    expect(accepted.label).toBe('Current');
  });
});
