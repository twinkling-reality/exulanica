import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { DEFAULT_REPRESENTATION_INTENT, type RepresentationSubject } from '@exulanica/atlas-core';
import { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import {
  RepresentationRuntime,
  type RepresentationDraw,
  type RepresentationPointAllocation,
} from '../../src/playcanvas/representation-runtime.js';

const record = (id: string, changes: Partial<RepresentationSubject> = {}): RepresentationSubject => ({
  subjectId: id, subjectKind: 'object', sceneId: null, frameId: 'tile:0:0:render-metres', origin: 'generated',
  sourceRefs: ['a'.repeat(64)], availability: 'available', rendered: true, points: 'mesh-surface-samples',
  compatibleBlend: true,
  bounds: { frameId: 'tile:0:0:render-metres', units: 'metres', origin: 'generated', basis: 'generated-extent',
    min: [0, 0, 0], max: [2, 3, 4] },
  label: null, dataAvailable: true, unavailableReason: null, ...changes,
});

class OwnDraw implements RepresentationDraw {
  rendered: number[] = [];
  restores = 0;
  allocations: { weights: number[]; destroyed: number }[] = [];
  constructor(readonly subject: RepresentationSubject) {}
  currentSubject(): RepresentationSubject { return this.subject; }
  parentVisible(): boolean { return true; }
  setRenderedWeight(weight: number): void { this.rendered.push(weight); }
  pointDemand(): number { return 8; }
  createPoints(limit: number): RepresentationPointAllocation {
    const allocation = { weights: [] as number[], destroyed: 0 };
    this.allocations.push(allocation);
    return { pointCount: limit, byteLength: limit * 40,
      setWeight: weight => { allocation.weights.push(weight); },
      destroy: () => { allocation.destroyed += 1; } };
  }
  restore(): void { this.restores += 1; }
}

function binding(): AtlasBinding {
  const value = Object.create(AtlasBinding.prototype) as AtlasBinding;
  Object.assign(value as unknown as Record<string, unknown>, {
    representationController: new RepresentationRuntime(64, 16),
    representationDefaults: new Map(),
    representationOverrides: new Map(),
    representationFrames: new Map(),
    ownedDistrict: null,
    onRepresentationChange: null,
    device: {},
    dirty: false,
  });
  return value;
}

describe('external representation subjects', () => {
  it('registers a caller\'s own draw under the same rules, and places its box through the node', () => {
    const atlas = binding();
    const node = new pc.GraphNode('tile');
    node.setLocalPosition(10, 0, 0);
    const draw = new OwnDraw(record('generated:one'));
    const release = atlas.registerRepresentationSubjects(node, [{ subject: draw.subject, draw }]);
    let report = atlas.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.5, boxes: true });
    expect(report.subjects).toHaveLength(1);
    expect(report.subjects[0]).toMatchObject({ allocatedPoints: 8, resolved: { boxes: true, pointWeight: 0.5 } });
    expect(atlas.representationBounds(draw.subject)).toContainEqual([12, 3, 4]);
    // Rights arrive through the ordinary update path and win.
    report = atlas.setRepresentationSubjects([{ ...draw.subject, availability: 'withdrawn' }]);
    expect(report.subjects[0]).toMatchObject({ allocatedPoints: 0, resolved: { boxes: false, geometryVisible: false } });
    expect(draw.allocations[0]!.destroyed).toBe(1);
    expect(atlas.representationBounds(draw.subject)).toBeNull();
    release();
    release();
    expect(draw.restores).toBe(1);
    expect(atlas.representationReport.subjects).toHaveLength(0);
    expect(() => atlas.setRepresentationSubjects([draw.subject])).toThrow('Unknown representation subject');
  });

  it('refuses a boxless subject a box, and refuses the whole set when one entry is wrong', () => {
    const atlas = binding();
    const node = new pc.GraphNode('tile');
    const boxless = new OwnDraw(record('generated:boxless', { bounds: null }));
    atlas.registerRepresentationSubjects(node, [{ subject: boxless.subject, draw: boxless }]);
    const report = atlas.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, boxes: true, ids: true });
    expect(report.subjects[0]!.resolved).toMatchObject({ boxes: false, ids: false });

    const good = new OwnDraw(record('generated:good'));
    for (const entries of [
      [{ subject: good.subject, draw: good }, { subject: boxless.subject, draw: boxless }],
      [{ subject: good.subject, draw: good }, { subject: record('generated:bad', { sourceRefs: [''] }), draw: good }],
      [{ subject: good.subject }],
      [{ subject: good.subject, draw: good, instance: {} as pc.MeshInstance }],
      [{ subject: good.subject, draw: good }, { subject: good.subject, draw: good }],
      [{ subject: good.subject, draw: good },
        { subject: record('generated:mesh'), instance: { material: {} } as unknown as pc.MeshInstance }],
    ]) {
      expect(() => atlas.registerRepresentationSubjects(node, entries)).toThrow();
      expect(atlas.representationReport.subjects.map(entry => entry.subject.subjectId)).toEqual(['generated:boxless']);
    }
    expect(good.restores).toBe(1);
  });

  it('unregisters by itself when the node it was registered against is destroyed', () => {
    const atlas = binding();
    const parent = new pc.GraphNode('world');
    const node = new pc.GraphNode('tile');
    parent.addChild(node);
    const draw = new OwnDraw(record('generated:one'));
    atlas.registerRepresentationSubjects(node, [{ subject: draw.subject, draw }]);
    node.destroy();
    expect(draw.restores).toBe(1);
    expect(atlas.representationReport.subjects).toHaveLength(0);
  });
});
