import type { DataViewStyle, RepresentationSubject } from '@exulanica/atlas-core';
import type { RepresentationEntryReport, RepresentationReport } from '../representation-runtime.js';

/**
 * What the data view overlay may draw this frame, decided without a renderer.
 *
 * Every mark here comes from a record the view already holds, and every refusal is stated:
 * a box only from the subject's own bounds, an id tag only from its own id, a label tag only from
 * its own label, a link only where two subjects share a real record relation (the same
 * reconstruction scene). A tag is placed at a corner of the subject's own box, so a subject
 * without bounds has nowhere honest to put one and gets none.
 */

export type WorldPoint = readonly [number, number, number];
export type WorldCorners = readonly WorldPoint[];

export interface OverlayBox {
  readonly subjectId: string;
  readonly corners: WorldCorners;
  readonly selected: boolean;
}
export interface OverlayTag {
  readonly subjectId: string;
  readonly corners: WorldCorners;
  /** The subject's kind as it states it, then its id and label where each is shown. */
  readonly lines: readonly string[];
  readonly colourKey: string;
  readonly selected: boolean;
}
export interface OverlayLink {
  readonly from: string;
  readonly to: string;
  readonly start: WorldPoint;
  readonly end: WorldPoint;
  /** The relation the link stands for, in plain words. */
  readonly relation: string;
}
export interface OverlayRefusal {
  readonly subjectId: string;
  readonly overlay: 'box' | 'id' | 'label' | 'link';
  readonly reason: string;
}
export interface DataViewOverlayPlan {
  readonly boxes: readonly OverlayBox[];
  readonly tags: readonly OverlayTag[];
  readonly links: readonly OverlayLink[];
  readonly refusals: readonly OverlayRefusal[];
  /** How far the background behind every surface is taken to the style's dark ground, 0 to 1. */
  readonly groundWeight: number;
}

/** The kind word a tag leads with: what the subject says it is, and a group says it is a group. */
export function overlayKindWord(subject: RepresentationSubject): string {
  if (subject.record !== undefined) return subject.record.kind;
  return subject.subjectKind === 'geometry-group' ? 'Group, not an object' : subject.subjectKind;
}

function centre(corners: WorldCorners): WorldPoint {
  let x = 0; let y = 0; let z = 0;
  for (const [cx, cy, cz] of corners) { x += cx; y += cy; z += cz; }
  return [x / corners.length, y / corners.length, z / corners.length];
}

export function planDataViewOverlay(
  report: RepresentationReport,
  worldBounds: (subject: RepresentationSubject) => WorldCorners | null,
  style: DataViewStyle,
): DataViewOverlayPlan {
  const boxes: OverlayBox[] = [];
  const tags: OverlayTag[] = [];
  const links: OverlayLink[] = [];
  const refusals: OverlayRefusal[] = [];
  const cornersOf = new Map<string, WorldCorners>();
  const { intent } = report;
  const anyOverlay = intent.boxes || intent.ids || intent.labels;
  let pointsShown = false;
  for (const entry of report.subjects) {
    const { subject, resolved } = entry;
    if (resolved.pointWeight > 0 && entry.allocatedPoints > 0) pointsShown = true;
    if (!anyOverlay || subject.availability !== 'available') continue;
    const wantsTag = resolved.ids || resolved.labels;
    if (!resolved.boxes && !wantsTag) {
      if (subject.bounds === null && resolved.geometryVisible) {
        if (intent.boxes) refusals.push({ subjectId: subject.subjectId, overlay: 'box', reason: 'No bounds of its own.' });
        if (intent.ids) refusals.push({ subjectId: subject.subjectId, overlay: 'id', reason: 'No bounds of its own to place the tag at.' });
        if (intent.labels) refusals.push({ subjectId: subject.subjectId, overlay: 'label', reason: 'No bounds of its own to place the tag at.' });
      } else if (intent.labels && subject.label === null && resolved.geometryVisible) {
        refusals.push({ subjectId: subject.subjectId, overlay: 'label', reason: 'No label of its own.' });
      }
      continue;
    }
    const corners = worldBounds(subject);
    if (corners === null || corners.length !== 8 || !corners.every(point => point.every(Number.isFinite))) {
      for (const overlay of ['box', 'id', 'label'] as const) {
        if ((overlay === 'box' && resolved.boxes) || (overlay === 'id' && resolved.ids)
          || (overlay === 'label' && resolved.labels)) {
          refusals.push({ subjectId: subject.subjectId, overlay, reason: 'Its bounds have no frame in this view.' });
        }
      }
      continue;
    }
    cornersOf.set(subject.subjectId, corners);
    const selected = report.selection === subject.subjectId;
    if (resolved.boxes) boxes.push({ subjectId: subject.subjectId, corners, selected });
    if (intent.labels && !resolved.labels) {
      refusals.push({ subjectId: subject.subjectId, overlay: 'label', reason: 'No label of its own.' });
    }
    if (wantsTag) {
      const lines = [overlayKindWord(subject)];
      if (resolved.ids && subject.subjectId.length > 0) lines.push(subject.subjectId);
      if (resolved.labels && subject.label !== null && subject.label.length > 0) lines.push(subject.label);
      if (lines.length > 1) {
        tags.push({ subjectId: subject.subjectId, corners, lines, colourKey: resolved.colourKey, selected });
      }
    }
  }
  const selected = report.subjects.find(entry => entry.subject.subjectId === report.selection);
  if (selected !== undefined && intent.boxes && cornersOf.has(selected.subject.subjectId)) {
    links.push(...relatedLinks(selected, report.subjects, cornersOf, style.links.maxCount));
    if (selected.subject.sceneId === null) {
      refusals.push({ subjectId: selected.subject.subjectId, overlay: 'link', reason: 'It states no scene, so no related subject is linked.' });
    }
  }
  return Object.freeze({
    boxes: Object.freeze(boxes),
    tags: Object.freeze(tags),
    links: Object.freeze(links),
    refusals: Object.freeze(refusals),
    groundWeight: pointsShown ? Math.min(1, intent.pointMix * style.ground.rise) * style.ground.strength : 0,
  });
}

/** Links only to subjects that name the same reconstruction scene, the one relation every scene subject states. */
function relatedLinks(
  selected: RepresentationEntryReport,
  entries: readonly RepresentationEntryReport[],
  cornersOf: ReadonlyMap<string, WorldCorners>,
  maxCount: number,
): OverlayLink[] {
  const sceneId = selected.subject.sceneId;
  const start = cornersOf.get(selected.subject.subjectId);
  if (sceneId === null || start === undefined) return [];
  const from = centre(start);
  const links: OverlayLink[] = [];
  for (const entry of entries) {
    if (links.length >= maxCount) break;
    if (entry.subject.subjectId === selected.subject.subjectId || entry.subject.sceneId !== sceneId) continue;
    const corners = cornersOf.get(entry.subject.subjectId);
    if (corners === undefined || !entry.resolved.boxes) continue;
    links.push({
      from: selected.subject.subjectId,
      to: entry.subject.subjectId,
      start: from,
      end: centre(corners),
      relation: `Both belong to scene ${sceneId}`,
    });
  }
  return links;
}

/** The twelve edges of a box whose corners are ordered x, then y, then z, each min before max. */
export const BOX_EDGES: readonly (readonly [number, number])[] = (() => {
  const edges: [number, number][] = [];
  for (let corner = 0; corner < 8; corner += 1) {
    for (const bit of [4, 2, 1]) if ((corner & bit) === 0) edges.push([corner, corner | bit]);
  }
  return edges;
})();

/** The four top corners of that ordering, where a tag may stand. */
export const TOP_CORNERS: readonly number[] = [2, 3, 6, 7];
