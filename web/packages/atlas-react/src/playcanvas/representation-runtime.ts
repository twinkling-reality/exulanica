import {
  DEFAULT_REPRESENTATION_INTENT, representationIntent, resolveRepresentation,
  type RepresentationIntent, type RepresentationResolution, type RepresentationSubject,
} from '@exulanica/atlas-core';

export interface RepresentationPointAllocation {
  readonly pointCount: number;
  readonly byteLength: number;
  setWeight(weight: number): void;
  destroy(): void;
}
/** Borrowed draws retain their authoritative transform, picking subject and parent gates. */
export interface RepresentationDraw {
  currentSubject(): RepresentationSubject;
  parentVisible(): boolean;
  setRenderedWeight(weight: number): void;
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
}
export interface RepresentationReport {
  readonly intent: RepresentationIntent;
  readonly subjects: readonly RepresentationEntryReport[];
  readonly allocatedPoints: number;
  readonly allocatedBytes: number;
  readonly pointBudget: number;
}
interface Held { draw: RepresentationDraw; points: RepresentationPointAllocation | null }

/** One bounded presentation registry. No fetch, renderer replacement, world state or clock access. */
export class RepresentationRuntime {
  readonly #held = new Map<string, Held>();
  readonly #pointBudget: number;
  readonly #perSubject: number;
  #intent = DEFAULT_REPRESENTATION_INTENT;
  #destroyed = false;
  #points = 0;
  #bytes = 0;
  #report: RepresentationReport;

  constructor(pointBudget = 65_536, perSubject = 4_096) {
    if (!Number.isSafeInteger(pointBudget) || pointBudget < 1 || pointBudget > 65_536
      || !Number.isSafeInteger(perSubject) || perSubject < 1 || perSubject > pointBudget) {
      throw new TypeError('Invalid representation allocation budget');
    }
    this.#pointBudget = pointBudget; this.#perSubject = perSubject;
    this.#report = this.#snapshot([]);
  }
  get report(): RepresentationReport { return this.#report; }
  get intent(): RepresentationIntent { return this.#intent; }

  register(draw: RepresentationDraw): void {
    if (this.#destroyed) throw new Error('Representation runtime is destroyed');
    const subject = draw.currentSubject();
    resolveRepresentation(this.#intent, subject);
    if (!this.#held.has(subject.subjectId) && this.#held.size >= 256) {
      throw new RangeError('Representation registry is limited to 256 borrowed draws');
    }
    this.unregister(subject.subjectId);
    this.#held.set(subject.subjectId, { draw, points: null });
  }
  unregister(subjectId: string): void {
    const held = this.#held.get(subjectId);
    if (!held) return;
    this.#release(held);
    held.draw.restore();
    this.#held.delete(subjectId);
  }
  setIntent(intent: RepresentationIntent): RepresentationReport {
    if (this.#destroyed) throw new Error('Representation runtime is destroyed');
    this.#intent = representationIntent(intent);
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
    for (const [subjectId, held] of this.#held) {
      let subject = held.draw.currentSubject();
      if (subject.subjectId !== subjectId) throw new TypeError('Borrowed subject identity changed');
      const visible = held.draw.parentVisible();
      if (subject.availability !== 'available') this.#release(held);
      const requested = resolveRepresentation(this.#intent, subject, visible);
      if (requested.pointWeight > 0
        && subject.points !== null && held.points === null && held.draw.setExistingPointWeight === undefined) {
        const limit = Math.min(this.#perSubject, this.#pointBudget - this.#points);
        const points = limit > 0 ? held.draw.createPoints(limit) : null;
        if (points !== null) {
          if (!Number.isSafeInteger(points.pointCount) || points.pointCount < 1 || points.pointCount > limit
            || !Number.isSafeInteger(points.byteLength) || points.byteLength < 0
            || points.byteLength > points.pointCount * 64) {
            points.destroy();
            throw new RangeError('Point adapter exceeded its allocation allowance');
          }
          held.points = points;
          this.#points += points.pointCount; this.#bytes += points.byteLength;
        }
        if (held.points === null) subject = { ...subject, points: null, compatibleBlend: false,
          unavailableReason: limit === 0 ? 'Point display budget is exhausted.' : 'This draw has no compatible retained point buffer.' };
      }
      const resolved = resolveRepresentation(this.#intent, subject, visible);
      held.draw.setRenderedWeight(resolved.renderedWeight);
      held.draw.setExistingPointWeight?.(resolved.pointWeight);
      held.points?.setWeight(resolved.pointWeight);
      entries.push(Object.freeze({ subject, resolved, allocatedPoints: held.points?.pointCount ?? 0 }));
    }
    this.#report = this.#snapshot(entries);
    return this.#report;
  }
  /** Returns all borrowed states before their owning renderer destroys them. Idempotent. */
  destroy(): void {
    if (this.#destroyed) return;
    for (const id of [...this.#held.keys()]) this.unregister(id);
    this.#destroyed = true;
    this.#report = this.#snapshot([]);
  }
  #release(held: Held): void {
    if (held.points === null) return;
    this.#points -= held.points.pointCount; this.#bytes -= held.points.byteLength;
    held.points.destroy(); held.points = null;
  }
  #snapshot(subjects: readonly RepresentationEntryReport[]): RepresentationReport {
    return Object.freeze({ intent: this.#intent, subjects: Object.freeze(subjects),
      allocatedPoints: this.#points, allocatedBytes: this.#bytes, pointBudget: this.#pointBudget });
  }
}
