import {
  DATA_VIEW_STYLE,
  DEFAULT_REPRESENTATION_INTENT,
  REPRESENTATION_POINT_BUDGET,
  REPRESENTATION_POINTS_PER_SUBJECT,
  dataViewKindColour,
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
/** A spatial record the data view may inspect without taking ownership of its aggregate draw. */
export interface RepresentationMetadata {
  currentSubject(): RepresentationSubject;
  parentVisible(): boolean;
  /** Mark caller-owned metadata as changed before the next resolution. */
  refresh?(): void;
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
type Held =
  | { kind: 'draw'; source: RepresentationDraw; points: RepresentationPointAllocation | null; look: string }
  | { kind: 'metadata'; source: RepresentationMetadata; points: null; look: '' };

/**
 * Points prepared per update. The first slide away from the rendered end samples and uploads
 * every subject's points; spreading that over a few frames keeps the slider responsive.
 */
export const REPRESENTATION_POINTS_PER_UPDATE = 262_144;
/** Borrowed GPU draws stay tightly bounded; metadata has no point or renderer allocation. */
export const REPRESENTATION_DRAW_LIMIT = 256;
export const REPRESENTATION_METADATA_LIMIT = 4_096;

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
  #draws = 0;
  #metadata = 0;
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

  /**
   * Refuses a subject this runtime's style cannot colour honestly: a contract v2 generated record
   * (its reference carries no ordinal key) needs style version 2 or later, and a declared colour for
   * its own kind. Nothing is guessed for a kind the style does not name.
   */
  assertStyleAccepts(subject: RepresentationSubject): void {
    const record = subject.record;
    if (record === undefined || record.key !== '') return;
    if (this.#style.version < 2) {
      throw new TypeError(`${subject.subjectId} is a contract v2 subject and needs data view style version 2 or later`);
    }
    if (dataViewKindColour(this.#style, record.kind) === undefined) {
      throw new TypeError(`Data view style version ${this.#style.version} declares no colour for ${record.kind}`);
    }
  }

  register(draw: RepresentationDraw): void {
    const subject = this.#accepted(draw);
    if (this.#held.get(subject.subjectId)?.kind !== 'draw' && this.#draws >= REPRESENTATION_DRAW_LIMIT) {
      throw new RangeError('Representation registry is limited to 256 borrowed draws');
    }
    this.unregister(subject.subjectId);
    this.#held.set(subject.subjectId, { kind: 'draw', source: draw, points: null, look: '' });
    this.#draws += 1;
    this.#plan = null;
  }
  /** Register an inspectable bounded record without borrowing, hiding or sampling its draw. */
  registerMetadata(metadata: RepresentationMetadata): void {
    const subject = this.#accepted(metadata);
    if (!subject.rendered || subject.points !== null || subject.compatibleBlend || subject.bounds === null) {
      throw new TypeError('Representation metadata requires rendered bounds and no isolated point form');
    }
    if (this.#held.get(subject.subjectId)?.kind !== 'metadata'
      && this.#metadata >= REPRESENTATION_METADATA_LIMIT) {
      throw new RangeError(`Representation registry is limited to ${REPRESENTATION_METADATA_LIMIT} metadata records`);
    }
    this.unregister(subject.subjectId);
    this.#held.set(subject.subjectId, { kind: 'metadata', source: metadata, points: null, look: '' });
    this.#metadata += 1;
    this.#plan = null;
  }
  unregister(subjectId: string): void {
    const held = this.#held.get(subjectId);
    if (!held) return;
    this.#release(held);
    if (held.kind === 'draw') { held.source.restore(); this.#draws -= 1; }
    else this.#metadata -= 1;
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
    if (subjectId !== null && this.#held.get(subjectId)!.source.currentSubject().availability !== 'available') {
      throw new TypeError(`Unavailable representation subject ${subjectId}`);
    }
    this.#selection = subjectId;
    return this.update();
  }
  refresh(): RepresentationReport {
    if (this.#destroyed) return this.#report;
    for (const held of this.#held.values()) held.source.refresh?.();
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
      let subject = held.source.currentSubject();
      if (subject.subjectId !== subjectId) throw new TypeError('Representation subject identity changed');
      const visible = held.source.parentVisible();
      if (subject.availability !== 'available') {
        this.#release(held);
        if (this.#selection === subjectId) this.#selection = null;
      }
      const requested = resolveRepresentation(this.#intent, subject, visible);
      const planned = plan.get(subjectId) ?? 0;
      if (held.kind === 'draw' && requested.pointWeight > 0
        && subject.points !== null && held.points === null && held.source.setExistingPointWeight === undefined) {
        const limit = Math.min(planned, this.#perSubject, this.#pointBudget - this.#points);
        let reason: string | null = null;
        if (planned < 1) reason = 'This draw has nothing to sample.';
        else if (limit < 1) reason = 'Point display budget is exhausted.';
        else if (limit > allowance && allowance < this.#perUpdate) {
          reason = 'Points for this subject are still being prepared.';
          pending += 1;
        } else {
          const points = held.source.createPoints(limit);
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
      if (held.kind === 'draw') {
        held.source.setRenderedWeight(resolved.renderedWeight);
        held.source.setExistingPointWeight?.(resolved.pointWeight);
      }
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
      : dataViewKindColour(this.#style, key);
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
      if (held.kind === 'metadata') continue;
      const subject = held.source.currentSubject();
      if (subject.points === null || held.source.setExistingPointWeight !== undefined) continue;
      const raw = held.source.pointDemand?.() ?? this.#perSubject;
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
  #accepted(source: RepresentationDraw | RepresentationMetadata): RepresentationSubject {
    if (this.#destroyed) throw new Error('Representation runtime is destroyed');
    const subject = source.currentSubject();
    resolveRepresentation(this.#intent, subject);
    this.assertStyleAccepts(subject);
    return subject;
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
