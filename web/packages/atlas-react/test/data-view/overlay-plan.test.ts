import { describe, expect, it } from 'vitest';
import {
  DATA_VIEW_STYLE,
  DEFAULT_REPRESENTATION_INTENT,
  resolveRepresentation,
  type RepresentationIntent,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { BOX_EDGES, TOP_CORNERS, overlayKindWord, planDataViewOverlay } from '../../src/playcanvas/data-view/overlay-plan.js';
import type { RepresentationReport } from '../../src/playcanvas/representation-runtime.js';

const bounds = (frameId: string) => ({
  frameId, units: 'metres' as const, origin: 'inferred' as const, basis: 'source-bounds' as const,
  min: [0, 0, 0] as const, max: [1, 2, 3] as const,
});
const scene = (id: string, changes: Partial<RepresentationSubject> = {}): RepresentationSubject => ({
  subjectId: id, subjectKind: 'scene', sceneId: 'scene:1', frameId: `frame:${id}`, origin: 'inferred',
  sourceRefs: [id], availability: 'available', rendered: true, points: 'retained-points',
  compatibleBlend: true, blend: 'overlay', bounds: bounds(`frame:${id}`), label: `Label ${id}`,
  dataAvailable: true, unavailableReason: null, ...changes,
});
const corners = (offset: number) => {
  const out: [number, number, number][] = [];
  for (const x of [offset, offset + 1]) for (const y of [0, 2]) for (const z of [0, 3]) out.push([x, y, z]);
  return out;
};

function report(
  subjects: readonly RepresentationSubject[], intent: Partial<RepresentationIntent>,
  options: { selection?: string | null; allocated?: number; visible?: boolean } = {},
): RepresentationReport {
  const full = { ...DEFAULT_REPRESENTATION_INTENT, ...intent };
  return {
    intent: full,
    subjects: subjects.map(subject => ({
      subject,
      resolved: resolveRepresentation(full, subject, options.visible ?? true),
      allocatedPoints: options.allocated ?? 10,
      plannedPoints: 10,
    })),
    allocatedPoints: 0, allocatedBytes: 0, pointBudget: 100, perSubjectLimit: 10, pendingSubjects: 0,
    selection: options.selection ?? null, style: { id: DATA_VIEW_STYLE.id, version: DATA_VIEW_STYLE.version },
  };
}

const worldBounds = (subject: RepresentationSubject) =>
  subject.bounds === null ? null : corners(Number(subject.subjectId.replace(/\D/g, '') || 0));

describe('data view overlay plan', () => {
  it('draws boxes from own bounds and tags from own id and label, led by the subject\'s kind', () => {
    const plan = planDataViewOverlay(
      report([scene('a1')], { boxes: true, ids: true, labels: true, pointMix: 1 }), worldBounds, DATA_VIEW_STYLE);
    expect(plan.boxes).toEqual([{ subjectId: 'a1', corners: corners(1), selected: false }]);
    expect(plan.tags).toEqual([{ subjectId: 'a1', corners: corners(1), lines: ['scene', 'a1', 'Label a1'],
      colourKey: 'inferred', selected: false }]);
    expect(plan.refusals).toEqual([]);
  });

  it('refuses every overlay for a subject without bounds, and says why', () => {
    const plan = planDataViewOverlay(
      report([scene('a1', { bounds: null })], { boxes: true, ids: true, labels: true }), worldBounds, DATA_VIEW_STYLE);
    expect(plan.boxes).toEqual([]);
    expect(plan.tags).toEqual([]);
    expect(plan.refusals.map(item => item.overlay)).toEqual(['box', 'id', 'label']);
    expect(plan.refusals[0]!.reason).toBe('No bounds of its own.');
  });

  it('refuses a label tag without its own label, and keeps the id tag', () => {
    const plan = planDataViewOverlay(
      report([scene('a1', { label: null })], { ids: true, labels: true }), worldBounds, DATA_VIEW_STYLE);
    expect(plan.tags[0]!.lines).toEqual(['scene', 'a1']);
    expect(plan.refusals).toEqual([{ subjectId: 'a1', overlay: 'label', reason: 'No label of its own.' }]);
    const labelOnly = planDataViewOverlay(
      report([scene('a1', { label: null })], { labels: true }), worldBounds, DATA_VIEW_STYLE);
    expect(labelOnly.tags).toEqual([]);
    expect(labelOnly.refusals.map(item => item.overlay)).toEqual(['label']);
  });

  it('refuses a mark whose bounds have no frame in the view', () => {
    const plan = planDataViewOverlay(
      report([scene('a1')], { boxes: true, ids: true }), () => null, DATA_VIEW_STYLE);
    expect(plan.boxes).toEqual([]);
    expect(plan.tags).toEqual([]);
    expect(plan.refusals.map(item => [item.overlay, item.reason])).toEqual([
      ['box', 'Its bounds have no frame in this view.'], ['id', 'Its bounds have no frame in this view.'],
    ]);
    const broken = planDataViewOverlay(report([scene('a1')], { boxes: true }),
      () => [[0, 0, Number.NaN], ...corners(0).slice(1)], DATA_VIEW_STYLE);
    expect(broken.boxes).toEqual([]);
  });

  it('draws nothing for a withdrawn or hidden subject, whatever the slider and overlays say', () => {
    const everything = { boxes: true, ids: true, labels: true, pointMix: 1, binary: 'visualization' as const };
    for (const plan of [
      planDataViewOverlay(report([scene('a1', { availability: 'withdrawn' })], everything), worldBounds, DATA_VIEW_STYLE),
      planDataViewOverlay(report([scene('a1', { availability: 'unavailable' })], everything, { selection: 'a1' }), worldBounds, DATA_VIEW_STYLE),
      planDataViewOverlay(report([scene('a1')], everything, { visible: false }), worldBounds, DATA_VIEW_STYLE),
    ]) {
      expect([plan.boxes, plan.tags, plan.links, plan.refusals]).toEqual([[], [], [], []]);
    }
  });

  it('never presents an aggregate batch as an object', () => {
    const group = scene('g1', { subjectKind: 'geometry-group', sceneId: null, origin: 'generated',
      bounds: { ...bounds('frame:g1'), origin: 'generated', basis: 'generated-extent' }, blend: 'crossfade' });
    expect(overlayKindWord(group)).toBe('Group, not an object');
    const plan = planDataViewOverlay(report([group], { ids: true }), worldBounds, DATA_VIEW_STYLE);
    expect(plan.tags[0]!.lines[0]).toBe('Group, not an object');
    const record = { ...group, subjectKind: 'object' as const,
      record: { kind: 'city.facade' as const, version: 1, identity: '5f0c7a2e-1b3d-4c5e-8f60-718293a4b5c6', key: 'edge_ordinal.0' } };
    expect(overlayKindWord(record)).toBe('city.facade');
  });

  it('links a selected subject only to subjects of the same scene', () => {
    const subjects = [scene('a1'), scene('a2'), scene('a3', { sceneId: 'scene:2' }), scene('a4', { bounds: null })];
    const plan = planDataViewOverlay(report(subjects, { boxes: true }, { selection: 'a1' }), worldBounds, DATA_VIEW_STYLE);
    expect(plan.links.map(link => [link.from, link.to, link.relation])).toEqual([['a1', 'a2', 'Both belong to scene scene:1']]);
    expect(plan.links[0]!.start).toEqual([1.5, 1, 1.5]);
    expect(plan.boxes.find(box => box.subjectId === 'a1')!.selected).toBe(true);
    const lonely = planDataViewOverlay(
      report([scene('a1', { sceneId: null }), scene('a2', { sceneId: null })], { boxes: true }, { selection: 'a1' }),
      worldBounds, DATA_VIEW_STYLE);
    expect(lonely.links).toEqual([]);
    expect(lonely.refusals).toEqual([{ subjectId: 'a1', overlay: 'link',
      reason: 'It states no scene, so no related subject is linked.' }]);
    const off = planDataViewOverlay(report(subjects, { ids: true }, { selection: 'a1' }), worldBounds, DATA_VIEW_STYLE);
    expect(off.links).toEqual([]);
  });

  it('darkens the ground only while points are actually drawn', () => {
    const style = DATA_VIEW_STYLE;
    expect(planDataViewOverlay(report([scene('a1')], { pointMix: 0 }), worldBounds, style).groundWeight).toBe(0);
    expect(planDataViewOverlay(report([scene('a1')], { pointMix: 0.2 }), worldBounds, style).groundWeight)
      .toBeCloseTo(Math.min(1, 0.2 * style.ground.rise) * style.ground.strength);
    expect(planDataViewOverlay(report([scene('a1')], { pointMix: 1 }), worldBounds, style).groundWeight)
      .toBeCloseTo(style.ground.strength);
    expect(planDataViewOverlay(report([scene('a1')], { pointMix: 1 }, { allocated: 0 }), worldBounds, style).groundWeight).toBe(0);
    expect(planDataViewOverlay(report([scene('a1', { availability: 'withdrawn' })], { pointMix: 1 }), worldBounds, style)
      .groundWeight).toBe(0);
  });

  it('knows the twelve edges and four top corners of the corner order it is given', () => {
    expect(BOX_EDGES).toHaveLength(12);
    for (const [a, b] of BOX_EDGES) expect([1, 2, 4]).toContain(a ^ b);
    const box = corners(0);
    expect(TOP_CORNERS.map(index => box[index]![1])).toEqual([2, 2, 2, 2]);
  });
});
