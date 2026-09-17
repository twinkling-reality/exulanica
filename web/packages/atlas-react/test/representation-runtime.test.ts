import { describe, expect, it } from 'vitest';
import {
  DATA_VIEW_STYLE,
  DATA_VIEW_STYLE_V1,
  dataViewStyle,
  DEFAULT_REPRESENTATION_INTENT,
  REPRESENTATION_POINT_BUDGET,
  REPRESENTATION_POINTS_PER_SUBJECT,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import {
  RepresentationRuntime,
  type RepresentationDraw,
  type RepresentationPointAllocation,
  type RepresentationPointLook,
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
  looks: RepresentationPointLook[] = [];
  constructor(readonly pointCount: number, readonly byteLength = pointCount * 24) {}
  setWeight(weight: number): void { this.weights.push(weight); }
  setLook(look: RepresentationPointLook): void { this.looks.push(look); }
  destroy(): void { this.destroyed += 1; }
}

class Draw implements RepresentationDraw {
  subject: RepresentationSubject;
  visible = true;
  rendered: number[] = [];
  limits: number[] = [];
  allocations: Allocation[] = [];
  restores = 0;
  demand: number | undefined;
  constructor(id: string, demand?: number) { this.subject = available(id); this.demand = demand; }
  pointDemand(): number { return this.demand ?? 4; }
  currentSubject(): RepresentationSubject { return this.subject; }
  parentVisible(): boolean { return this.visible; }
  setRenderedWeight(weight: number): void { this.rendered.push(weight); }
  createPoints(limit: number): RepresentationPointAllocation | null {
    this.limits.push(limit);
    const allocation = new Allocation(limit);
    this.allocations.push(allocation);
    return allocation;
  }
  restore(): void { this.restores += 1; }
}

describe('bounded representation runtime', () => {
  it('refuses a contract v2 subject under a version 1 style, or a kind the style declares no colour for', () => {
    const v2 = (kind: `city.${string}`, key = ''): Draw => {
      const draw = new Draw(`generated:${kind}:5488228a-3210-54a7-9517-968a75f4624b`);
      draw.subject = { ...draw.subject, origin: 'generated', subjectKind: 'object',
        record: { kind, version: 2, identity: '5488228a-3210-54a7-9517-968a75f4624b', key } };
      return draw;
    };
    const old = new RepresentationRuntime(8, 4, { style: dataViewStyle(JSON.parse(JSON.stringify(DATA_VIEW_STYLE_V1))) });
    expect(() => old.register(v2('city.street'))).toThrow('needs data view style version 2 or later');
    expect(() => old.register(v2('city.massing'))).toThrow('needs data view style version 2 or later');
    old.register(v2('city.massing', 'parcel_ordinal.3'));
    expect(old.report.subjects).toHaveLength(0);
    const current = new RepresentationRuntime(8, 4);
    current.register(v2('city.street'));
    expect(() => current.register(v2('city.bus_shelter'))).toThrow('declares no colour for city.bus_shelter');
    const report = current.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, colour: 'kind' });
    expect(report.subjects.map(entry => entry.subject.record?.kind)).toEqual(['city.street']);
  });

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
    // Both want 4 of a budget of 6: one factor scales both, so the second is not starved.
    expect(one.limits).toEqual([3]);
    expect(two.limits).toEqual([3]);
    expect(report.allocatedPoints).toBe(6);
    expect(report.subjects.map(entry => entry.plannedPoints)).toEqual([3, 3]);
    runtime.unregister('one');
    const replacement = new Draw('one');
    runtime.register(replacement);
    report = runtime.update();
    expect(replacement.limits).toEqual([3]);
    expect(report.allocatedPoints).toBe(6);
    expect(one.allocations[0]!.destroyed).toBe(1);
  });

  it('scales every demand by one factor and never beyond a subject\'s cap', () => {
    const runtime = new RepresentationRuntime(100, 60);
    const draws = [new Draw('large', 300), new Draw('small', 100), new Draw('empty', 0)];
    for (const draw of draws) runtime.register(draw);
    const report = runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    expect(draws.map(draw => draw.limits)).toEqual([[60], [25], []]);
    expect(report.allocatedPoints).toBe(85);
    expect(report.subjects[2]).toMatchObject({ allocatedPoints: 0, plannedPoints: 0,
      subject: { points: null, unavailableReason: 'This draw has nothing to sample.' },
      resolved: { renderedWeight: 1, pointWeight: 0 } });
  });

  it('prepares a bounded number of points per update and keeps the surface until they arrive', () => {
    const runtime = new RepresentationRuntime(40, 20, { pointsPerUpdate: 25 });
    const draws = [new Draw('a', 20), new Draw('b', 20), new Draw('c', 20)];
    for (const draw of draws) runtime.register(draw);
    let report = runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.5 });
    expect(report.pendingSubjects).toBe(2);
    expect(draws.map(draw => draw.limits.length)).toEqual([1, 0, 0]);
    expect(report.subjects[1]).toMatchObject({
      subject: { unavailableReason: 'Points for this subject are still being prepared.' },
      resolved: { renderedWeight: 1, pointWeight: 0 },
    });
    report = runtime.update();
    report = runtime.update();
    expect(report.pendingSubjects).toBe(0);
    expect(report.allocatedPoints).toBe(39);
    expect(report.subjects.map(entry => entry.resolved.pointWeight)).toEqual([0.5, 0.5, 0.5]);
  });

  it('tells each allocation its palette colour, treatment and selection emphasis', () => {
    const runtime = new RepresentationRuntime(8, 4);
    const one = new Draw('one');
    const two = new Draw('two');
    two.subject = { ...two.subject, origin: 'inferred', subjectKind: 'scene', sceneId: 'scene:1' };
    runtime.register(one); runtime.register(two);
    runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 });
    const palette = DATA_VIEW_STYLE.palette;
    expect(one.allocations[0]!.looks.at(-1)).toEqual({ colour: palette.origin.authored, treatment: 'points', gain: 1 });
    expect(two.allocations[0]!.looks.at(-1)).toEqual({ colour: palette.origin.inferred, treatment: 'points', gain: 1 });
    runtime.setIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, colour: 'kind', binary: 'visualization' });
    expect(one.allocations[0]!.looks.at(-1)).toEqual({ colour: palette.kind['geometry-group'], treatment: 'dashes', gain: 1 });
    expect(two.allocations[0]!.looks.at(-1)!.colour).toBe(palette.kind.scene);
    const looks = one.allocations[0]!.looks.length;
    runtime.update();
    expect(one.allocations[0]!.looks).toHaveLength(looks);
    const report = runtime.setSelection('two');
    expect(report.selection).toBe('two');
    expect(two.allocations[0]!.looks.at(-1)!.gain).toBe(DATA_VIEW_STYLE.points.selectedGain);
    expect(one.allocations[0]!.looks.at(-1)!.gain).toBe(DATA_VIEW_STYLE.points.unselectedGain);
    expect(() => runtime.setSelection('missing')).toThrow('Unknown representation subject');
    runtime.unregister('two');
    expect(runtime.update().selection).toBeNull();
    expect(runtime.report.style).toEqual({ id: 'exulanica.data-view', version: DATA_VIEW_STYLE.version });
  });

  it('holds its budgets to the measured limits', () => {
    expect(new RepresentationRuntime().report).toMatchObject({
      pointBudget: REPRESENTATION_POINT_BUDGET, perSubjectLimit: REPRESENTATION_POINTS_PER_SUBJECT,
    });
    expect(() => new RepresentationRuntime(REPRESENTATION_POINT_BUDGET + 1)).toThrow('budget');
    expect(() => new RepresentationRuntime(REPRESENTATION_POINT_BUDGET, REPRESENTATION_POINTS_PER_SUBJECT + 1))
      .toThrow('budget');
    expect(() => new RepresentationRuntime(8, 9)).toThrow('budget');
    expect(() => new RepresentationRuntime(0)).toThrow('budget');
    expect(() => new RepresentationRuntime(8, 4, { pointsPerUpdate: 0 })).toThrow('allowance');
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
