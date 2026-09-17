import {
  DATA_VIEW_STYLE,
  DEFAULT_REPRESENTATION_INTENT,
  REPRESENTATION_POINT_BUDGET,
  REPRESENTATION_POINTS_PER_SUBJECT,
  isDataViewKindKey,
  representationIntent,
  resolveRepresentation,
  type DataViewHex,
  type DataViewStyle,
  type RepresentationIntent,
  type RepresentationResolution,
  type RepresentationSubject,
} from '@exulanica/atlas-core';

/** How one subject's points look this frame. Plain data: the draw turns it into uniforms. */
export interface RepresentationPointLook {
  /** The palette colour for the subject's colour key, from the style descriptor. */
  readonly colour: DataViewHex;
  /** `dashes` only under the labelled visualization treatment. */
  readonly treatment: 'points' | 'dashes';
  /** Display gain relative to the style's intensity: the panel selection's emphasis. */
  readonly gain: number;
}
export interface RepresentationPointAllocation {
  readonly pointCount: number;
  readonly byteLength: number;
  setWeight(weight: number): void;
  setLook?(look: RepresentationPointLook): void;
  destroy(): void;
}
/** Borrowed draws retain their authoritative transform, picking subject and parent gates. */
export interface RepresentationDraw {
  currentSubject(): RepresentationSubject;
  parentVisible(): boolean;
  setRenderedWeight(weight: number): void;
  /**
   * How many points this draw would show at the style's density: surface area times density for
   * a sampled surface, the retained count for a retained buffer. The budget scales every demand
   * by one factor, so density stays even across subjects instead of following registration order.
   */
  pointDemand?(): number;
  createPoints(limit: number): RepresentationPointAllocation | null;
  /** Borrowed native point draw: no additional allocation or ownership transfer. */
  setExistingPointWeight?(weight: number): void;
  /** Mark borrowed appearance as changed before the next weight application. */
  refresh?(): void;
  restore(): void;
}
export interface RepresentationEntryReport {
  readonly subject: RepresentationSubject;
  readonly resolved: RepresentationResolution;
  readonly allocatedPoints: number;
  /** The share of the budget this subject would receive, or 0 when it holds no point form. */
  readonly plannedPoints: number;
}
export interface RepresentationReport {
  readonly intent: RepresentationIntent;
  readonly subjects: readonly RepresentationEntryReport[];
  readonly allocatedPoints: number;
  readonly allocatedBytes: number;
  readonly pointBudget: number;
  readonly perSubjectLimit: number;
  /** Subjects whose points were requested and are still being prepared, a bounded amount per update. */
  readonly pendingSubjects: number;
  /** The subject the panel selected, highlighted in the view. Presentation only. */
  readonly selection: string | null;
  readonly style: { readonly id: string; readonly version: number };
}
interface Held { draw: RepresentationDraw; points: RepresentationPointAllocation | null; look: string }

/**
 * Points prepared per update. The first slide away from the rendered end samples and uploads
 * every subject's points; spreading that over a few frames keeps the slider responsive.
 */
export const REPRESENTATION_POINTS_PER_UPDATE = 262_144;

export interface RepresentationRuntimeOptions {
  readonly style?: DataViewStyle;
  readonly pointsPerUpdate?: number;
}

/** One bounded presentation registry. No fetch, renderer replacement, world state or clock access. */
export class RepresentationRuntime {
  readonly #held = new Map<string, Held>();
  readonly #pointBudget: number;
  readonly #perSubject: number;
  readonly #perUpdate: number;
  readonly #style: DataViewStyle;
  #intent = DEFAULT_REPRESENTATION_INTENT;
  #selection: string | null = null;
  #plan: Map<string, number> | null = null;
  #destroyed = false;
  #points = 0;
  #bytes = 0;
  #report: RepresentationReport;

  constructor(
    pointBudget = REPRESENTATION_POINT_BUDGET,
    perSubject = REPRESENTATION_POINTS_PER_SUBJECT,
    options: RepresentationRuntimeOptions = {},
  ) {
    if (!Number.isSafeInteger(pointBudget) || pointBudget < 1 || pointBudget > REPRESENTATION_POINT_BUDGET
      || !Number.isSafeInteger(perSubject) || perSubject < 1 || perSubject > pointBudget
      || perSubject > REPRESENTATION_POINTS_PER_SUBJECT) {
      throw new TypeError('Invalid representation allocation budget');
    }
    const perUpdate = options.pointsPerUpdate ?? REPRESENTATION_POINTS_PER_UPDATE;
    if (!Number.isSafeInteger(perUpdate) || perUpdate < 1 || perUpdate > REPRESENTATION_POINT_BUDGET) {
      throw new TypeError('Invalid representation preparation allowance');
    }
    this.#pointBudget = pointBudget; this.#perSubject = perSubject; this.#perUpdate = perUpdate;
    this.#style = options.style ?? DATA_VIEW_STYLE;
    this.#report = this.#snapshot([], 0);
  }
  get report(): RepresentationReport { return this.#report; }
  get intent(): RepresentationIntent { return this.#intent; }
  get style(): DataViewStyle { return this.#style; }

  register(draw: RepresentationDraw): void {
    if (this.#destroyed) throw new Error('Representation runtime is destroyed');
    const subject = draw.currentSubject();
    resolveRepresentation(this.#intent, subject);
    if (!this.#held.has(subject.subjectId) && this.#held.size >= 256) {
      throw new RangeError('Representation registry is limited to 256 borrowed draws');
    }
    this.unregister(subject.subjectId);
    this.#held.set(subject.subjectId, { draw, points: null, look: '' });
    this.#plan = null;
  }
  unregister(subjectId: string): void {
    const held = this.#held.get(subjectId);
    if (!held) return;
    this.#release(held);
    held.draw.restore();
    this.#held.delete(subjectId);
    this.#plan = null;
    if (this.#selection === subjectId) this.#selection = null;
  }
  setIntent(intent: RepresentationIntent): RepresentationReport {
    if (this.#destroyed) throw new Error('Representation runtime is destroyed');
    this.#intent = representationIntent(intent);
    return this.update();
  }
  /** Highlight one registered subject, or none. Changes no world selection and no camera. */
  setSelection(subjectId: string | null): RepresentationReport {
    if (this.#destroyed) return this.#report;
    if (subjectId !== null && !this.#held.has(subjectId)) throw new TypeError(`Unknown representation subject ${subjectId}`);
    this.#selection = subjectId;
    return this.update();
  }
  refresh(): RepresentationReport {
    if (this.#destroyed) return this.#report;
    for (const held of this.#held.values()) held.draw.refresh?.();
    return this.update();
  }
  /** Re-evaluate rights and existing parent visibility before each frame's draws. */
  update(): RepresentationReport {
    if (this.#destroyed) return this.#report;
    const entries: RepresentationEntryReport[] = [];
    const plan = this.#planned();
    let allowance = this.#perUpdate;
    let pending = 0;
    for (const [subjectId, held] of this.#held) {
      let subject = held.draw.currentSubject();
      if (subject.subjectId !== subjectId) throw new TypeError('Borrowed subject identity changed');
      const visible = held.draw.parentVisible();
      if (subject.availability !== 'available') this.#release(held);
      const requested = resolveRepresentation(this.#intent, subject, visible);
      const planned = plan.get(subjectId) ?? 0;
      if (requested.pointWeight > 0
        && subject.points !== null && held.points === null && held.draw.setExistingPointWeight === undefined) {
        const limit = Math.min(planned, this.#perSubject, this.#pointBudget - this.#points);
        let reason: string | null = null;
        if (planned < 1) reason = 'This draw has nothing to sample.';
        else if (limit < 1) reason = 'Point display budget is exhausted.';
        else if (limit > allowance && allowance < this.#perUpdate) {
          reason = 'Points for this subject are still being prepared.';
          pending += 1;
        } else {
          const points = held.draw.createPoints(limit);
          allowance -= limit;
          if (points !== null) {
            if (!Number.isSafeInteger(points.pointCount) || points.pointCount < 1 || points.pointCount > limit
              || !Number.isSafeInteger(points.byteLength) || points.byteLength < 0
              || points.byteLength > points.pointCount * 64) {
              points.destroy();
              throw new RangeError('Point adapter exceeded its allocation allowance');
            }
            held.points = points;
            held.look = '';
            this.#points += points.pointCount; this.#bytes += points.byteLength;
          } else reason = 'This draw has no compatible retained point buffer.';
        }
        if (held.points === null) {
          subject = { ...subject, points: null, compatibleBlend: false, unavailableReason: reason };
          delete (subject as { blend?: unknown }).blend;
        }
      }
      const resolved = resolveRepresentation(this.#intent, subject, visible);
      held.draw.setRenderedWeight(resolved.renderedWeight);
      held.draw.setExistingPointWeight?.(resolved.pointWeight);
      if (held.points !== null) {
        const look = this.#look(resolved);
        const signature = `${look.colour}|${look.treatment}|${look.gain}`;
        if (signature !== held.look) { held.points.setLook?.(look); held.look = signature; }
        held.points.setWeight(resolved.pointWeight);
      }
      entries.push(Object.freeze({
        subject, resolved, allocatedPoints: held.points?.pointCount ?? 0, plannedPoints: planned,
      }));
    }
    this.#report = this.#snapshot(entries, pending);
    return this.#report;
  }
  /** Returns all borrowed states before their owning renderer destroys them. Idempotent. */
  destroy(): void {
    if (this.#destroyed) return;
    for (const id of [...this.#held.keys()]) this.unregister(id);
    this.#destroyed = true;
    this.#report = this.#snapshot([], 0);
  }
  #look(resolved: RepresentationResolution): RepresentationPointLook {
    const key = resolved.colourKey;
    const palette = this.#style.palette;
    const colour = this.#intent.colour === 'origin'
      ? palette.origin[key as keyof typeof palette.origin]
      : isDataViewKindKey(key) ? palette.kind[key] : undefined;
    if (colour === undefined) throw new TypeError(`The data view style has no colour for ${key}`);
    const gain = this.#selection === null ? 1
      : this.#selection === resolved.subjectId ? this.#style.points.selectedGain : this.#style.points.unselectedGain;
    return { colour, treatment: resolved.binary ? 'dashes' : 'points', gain };
  }
  /** One factor for every subject that holds points, so a denser request never starves a later one. */
  #planned(): Map<string, number> {
    if (this.#plan !== null) return this.#plan;
    const demands = new Map<string, number>();
    let total = 0;
    for (const [subjectId, held] of this.#held) {
      const subject = held.draw.currentSubject();
      if (subject.points === null || held.draw.setExistingPointWeight !== undefined) continue;
      const raw = held.draw.pointDemand?.() ?? this.#perSubject;
      const demand = Number.isFinite(raw) && raw > 0 ? raw : 0;
      demands.set(subjectId, demand);
      total += demand;
    }
    const scale = total > this.#pointBudget ? this.#pointBudget / total : 1;
    const plan = new Map<string, number>();
    for (const [subjectId, demand] of demands) {
      plan.set(subjectId, demand > 0 ? Math.max(1, Math.min(this.#perSubject, Math.floor(demand * scale))) : 0);
    }
    this.#plan = plan;
    return plan;
  }
  #release(held: Held): void {
    if (held.points === null) return;
    this.#points -= held.points.pointCount; this.#bytes -= held.points.byteLength;
    held.points.destroy(); held.points = null; held.look = '';
  }
  #snapshot(subjects: readonly RepresentationEntryReport[], pendingSubjects: number): RepresentationReport {
    return Object.freeze({
      intent: this.#intent, subjects: Object.freeze(subjects),
      allocatedPoints: this.#points, allocatedBytes: this.#bytes, pointBudget: this.#pointBudget,
      perSubjectLimit: this.#perSubject, pendingSubjects, selection: this.#selection,
      style: Object.freeze({ id: this.#style.id, version: this.#style.version }),
    });
  }
}
