import { describe, expect, it } from 'vitest';
import { DEFAULT_REPRESENTATION_INTENT, type RepresentationSubject } from '@exulanica/atlas-core';
import {
  RepresentationRuntime,
  type RepresentationDraw,
  type RepresentationPointAllocation,
} from '../src/playcanvas/representation-runtime.js';

const available = (id: string): RepresentationSubject => ({
  subjectId: id, subjectKind: 'geometry-group', sceneId: null, frameId: `frame:${id}`,
  origin: 'authored', sourceRefs: [`source:${id}`], availability: 'available', rendered: true,
  points: 'mesh-vertices', compatibleBlend: true, bounds: null, label: null,
  dataAvailable: false, unavailableReason: null,
});

class Allocation implements RepresentationPointAllocation {
  destroyed = 0;
  weights: number[] = [];
  constructor(readonly pointCount: number, readonly byteLength = pointCount * 24) {}
  setWeight(weight: number): void { this.weights.push(weight); }
  destroy(): void { this.destroyed += 1; }
}

class Draw implements RepresentationDraw {
  subject: RepresentationSubject;
  visible = true;
  rendered: number[] = [];
  limits: number[] = [];
  allocations: Allocation[] = [];
  restores = 0;
  constructor(id: string) { this.subject = available(id); }
  currentSubject(): RepresentationSubject { return this.subject; }
  parentVisible(): boolean { return this.visible; }
  setRenderedWeight(weight: number): void { this.rendered.push(weight); }
  createPoints(limit: number): RepresentationPointAllocation | null {
    this.limits.push(limit);
    const allocation = new Allocation(Math.min(4, limit));
    this.allocations.push(allocation);
    return allocation;
  }
  restore(): void { this.restores += 1; }
}

describe('bounded representation runtime', () => {
  it('blends, reverses without reallocating, then restores and disposes exactly once', () => {
    const runtime = new RepresentationRuntime(8, 4);
    const draw = new Draw('one');
    runtime.register(draw);
    expect(runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.25 })).toMatchObject({
      allocatedPoints: 4, allocatedBytes: 96,
      subjects: [{ resolved: { renderedWeight: 0.75, pointWeight: 0.25 } }],
    });
    runtime.setIntent(DEFAULT_REPRESENTATION_INTENT);
    runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    expect(draw.allocations).toHaveLength(1);
    expect(draw.allocations[0]!.weights).toEqual([0.25, 0, 1]);
    runtime.destroy();
    runtime.destroy();
    expect(draw.allocations[0]!.destroyed).toBe(1);
    expect(draw.restores).toBe(1);
    expect(runtime.report).toMatchObject({ allocatedPoints: 0, allocatedBytes: 0, subjects: [] });
  });

  it('counts every live allocation and frees budget across unregister and re-register', () => {
    const runtime = new RepresentationRuntime(6, 4);
    const one = new Draw('one');
    const two = new Draw('two');
    runtime.register(one); runtime.register(two);
    let report = runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    expect(one.limits).toEqual([4]);
    expect(two.limits).toEqual([2]);
    expect(report.allocatedPoints).toBe(6);
    runtime.unregister('one');
    const replacement = new Draw('one');
    runtime.register(replacement);
    report = runtime.update();
    expect(replacement.limits).toEqual([4]);
    expect(report.allocatedPoints).toBe(6);
    expect(one.allocations[0]!.destroyed).toBe(1);
  });

  it('lets withdrawal and existing parent visibility defeat requested point fallback', () => {
    const runtime = new RepresentationRuntime(8, 4);
    const draw = new Draw('one');
    runtime.register(draw);
    runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, data: true });
    draw.subject = { ...draw.subject, availability: 'withdrawn',
      unavailableReason: 'Current source permission was withdrawn.' };
    let report = runtime.update();
    expect(report.subjects[0]).toMatchObject({
      allocatedPoints: 0,
      resolved: { geometryVisible: false, renderedWeight: 0, pointWeight: 0, data: false },
    });
    expect(draw.allocations[0]!.destroyed).toBe(1);
    draw.subject = available('one'); draw.visible = false;
    report = runtime.update();
    expect(report.subjects[0]!.resolved.geometryVisible).toBe(false);
    expect(draw.allocations).toHaveLength(1);
    runtime.unregister('one');
    expect(draw.restores).toBe(1);
    expect(draw.rendered.at(-1)).toBe(0);
  });

  it('keeps borrowed native points outside allocation accounting', () => {
    const draw = new Draw('native') as Draw & {
      setExistingPointWeight(weight: number): void;
    };
    draw.subject = { ...draw.subject, rendered: false, points: 'retained-points',
      compatibleBlend: false, subjectKind: 'scene' };
    const nativeWeights: number[] = [];
    draw.setExistingPointWeight = weight => nativeWeights.push(weight);
    const runtime = new RepresentationRuntime(4, 4);
    runtime.register(draw);
    const report = runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    expect(report).toMatchObject({ allocatedPoints: 0, allocatedBytes: 0 });
    expect(nativeWeights).toEqual([1]);
    expect(draw.allocations).toHaveLength(0);
  });

  it('does not allocate an endpoint-only point form for an intermediate slider value', () => {
    const runtime = new RepresentationRuntime(4, 4);
    const draw = new Draw('endpoint');
    draw.subject = { ...draw.subject, compatibleBlend: false };
    runtime.register(draw);
    const report = runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.5 });
    expect(report).toMatchObject({ allocatedPoints: 0,
      subjects: [{ resolved: { renderedWeight: 1, pointWeight: 0 } }] });
    expect(draw.allocations).toHaveLength(0);
  });

  it('rejects allocations that exceed the granted point or byte allowance', () => {
    const runtime = new RepresentationRuntime(4, 4);
    const draw = new Draw('bad');
    draw.createPoints = limit => new Allocation(limit + 1);
    runtime.register(draw);
    expect(() => runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 })).toThrow();
  });

  it('refuses identity changes and use after destruction', () => {
    const runtime = new RepresentationRuntime(4, 4);
    const draw = new Draw('one');
    runtime.register(draw);
    draw.subject = available('two');
    expect(() => runtime.update()).toThrow('identity changed');
    draw.subject = available('one');
    runtime.destroy();
    expect(() => runtime.register(draw)).toThrow('destroyed');
  });
});
