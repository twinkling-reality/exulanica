import * as pc from 'playcanvas';
import { describe, expect, it, vi } from 'vitest';
import { StaticMeshPicker } from '../src/playcanvas/mesh-picking.js';

function triangle() {
  const node = new pc.GraphNode(); (node as unknown as { _enabledInHierarchy: boolean })._enabledInHierarchy = true; node.setLocalPosition(0, 0, 3);
  const mesh = {
    primitive: [{ type: pc.PRIMITIVE_TRIANGLES, base: 0, count: 3, indexed: true }],
    getPositions: (out: number[]) => out.push(-1, -1, 0, 1, -1, 0, 0, 1, 0),
    getIndices: (out: number[]) => out.push(0, 1, 2),
  };
  const instance = { mesh, node, visible: true, aabb: new pc.BoundingBox(new pc.Vec3(0, 0, 3), new pc.Vec3(1, 1, 0.001)) } as unknown as pc.MeshInstance;
  return { node, instance };
}

describe('picking actual static renderer triangles', () => {
  it('prepares hidden geometry before interaction and retains live visibility and frames', () => {
    const { instance, node } = triangle(); const picker = new StaticMeshPicker();
    const readPositions = vi.spyOn(instance.mesh, 'getPositions');
    instance.visible = false;
    picker.prepare(instance);
    expect(readPositions).toHaveBeenCalledTimes(1);
    expect(picker.pick(instance, [0,0,0], [0,0,1], 10)).toBeNull();
    instance.visible = true;
    node.setLocalPosition(0,0,6); instance.aabb.center.set(0,0,6);
    expect(picker.pick(instance, [0,0,0], [0,0,1], 10)).toBe(6);
    expect(readPositions).toHaveBeenCalledTimes(1);
    instance.morphInstance = {} as pc.MorphInstance;
    expect(picker.pick(instance, [0,0,0], [0,0,1], 10)).toBeNull();
  });
  it('rejects empty space inside bounds and obeys the nearer occluder', () => {
    const { instance } = triangle(); const picker = new StaticMeshPicker();
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 4)).toBe(3);
    expect(picker.pick(instance, [0.9, 0.9, 0], [0, 0, 1], 4)).toBeNull();
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 2)).toBeNull();
  });
  it('uses the live nested frame, including scale, after geometry was cached', () => {
    const { instance, node } = triangle(); const picker = new StaticMeshPicker();
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 10)).toBe(3);
    const parent = new pc.GraphNode(); (parent as unknown as { _enabledInHierarchy: boolean })._enabledInHierarchy = true; parent.setLocalPosition(0, 0, 2); parent.setLocalScale(2, 1, 2); parent.addChild(node);
    instance.aabb.center.set(0, 0, 8); instance.aabb.halfExtents.set(2, 1, 0.001);
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 10)).toBe(8);
    parent.enabled = false;
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 10)).toBeNull();
  });
  it('does not select hidden or animated meshes using stale static triangles', () => {
    const { instance } = triangle(); const picker = new StaticMeshPicker(); instance.visible = false;
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 10)).toBeNull();
    instance.visible = true; instance.skinInstance = {} as pc.SkinInstance;
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 10)).toBeNull();
  });
  it('keeps world distance under rotated, mirrored and nonuniform nested frames', () => {
    const { instance, node } = triangle(); const picker = new StaticMeshPicker();
    node.setLocalEulerAngles(0, 37, 0);
    node.setLocalScale(-2, 3, 0.5);
    const frame = node.getWorldTransform();
    const centre = frame.transformPoint(new pc.Vec3(0, 0, 0));
    const direction = frame.transformVector(new pc.Vec3(0, 0, 1)).normalize();
    const origin = centre.clone().sub(direction.clone().mulScalar(7));
    instance.aabb.center.copy(centre); instance.aabb.halfExtents.set(10, 10, 10);
    const ray: readonly [number, number, number] = [direction.x, direction.y, direction.z];
    const start: readonly [number, number, number] = [origin.x, origin.y, origin.z];
    expect(picker.pick(instance, start, ray, 8)).toBeCloseTo(7, 6);
    expect(picker.pick(instance, start, ray, 6)).toBeNull();
  });
  it('retains visible triangles when a singular frame flattens only their normal axis', () => {
    const { instance, node } = triangle(); const picker = new StaticMeshPicker();
    node.setLocalScale(1, 1, 0);
    expect(picker.pick(instance, [0, 0, 0], [0, 0, 1], 4)).toBe(3);
  });
  it('respects live indexed primitive ranges when the shared mesh was cached', () => {
    const { instance } = triangle(); const picker = new StaticMeshPicker();
    const mesh = instance.mesh as unknown as {
      primitive: { base: number; count: number }[];
      getPositions(out: number[]): unknown;
      getIndices(out: number[]): unknown;
    };
    mesh.getPositions = out => out.push(-1,-1,0, 1,-1,0, 0,1,0, -1,-1,2, 1,-1,2, 0,1,2);
    mesh.getIndices = out => out.push(0,1,2, 3,4,5);
    instance.aabb.center.set(0,0,4); instance.aabb.halfExtents.set(1,1,1);
    expect(picker.pick(instance, [0,0,0], [0,0,1], 8)).toBe(3);
    mesh.primitive[0]!.base = 3;
    expect(picker.pick(instance, [0,0,0], [0,0,1], 8)).toBe(5);
  });
  it('picks nonindexed triangles from the declared offset only', () => {
    const { instance } = triangle(); const picker = new StaticMeshPicker();
    const mesh = instance.mesh as unknown as {
      primitive: { base: number; count: number; indexed: boolean }[];
      getPositions(out: number[]): unknown;
    };
    mesh.getPositions = out => out.push(-1,-1,-2, 1,-1,-2, 0,1,-2, -1,-1,0, 1,-1,0, 0,1,0);
    Object.assign(mesh.primitive[0]!, { base: 3, indexed: false });
    expect(picker.pick(instance, [0,0,0], [0,0,1], 4)).toBe(3);
  });

});
