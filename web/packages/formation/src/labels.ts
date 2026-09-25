/**
 * The honest label for every formation state.
 *
 * interaction-model.md 8.1 and 8.3. Two rules shape every sentence below:
 *
 *   - The label names the real pipeline stage and the real unit of progress. No percentages, no
 *     estimated time remaining, no "almost done".
 *   - The label always states what is already usable, not only what is pending.
 *
 * And one rule shapes the file rather than the sentences: **the label set is byte-identical under
 * reduced motion** (8.3, and the table in section 9). Nothing here takes a motion preference,
 * which is the cheapest possible way to guarantee that no information lives only in an animation.
 */

import type { ReconstructionRung } from '@exulanica/atlas-core';
import { isOutcome, type FormationPhase } from './events.js';
import { elapsedMs, progressFraction, type FormationState } from './state.js';

export interface FormationLabel {
  /** The real pipeline stage, named. Shown as a small eyebrow above the sentence. */
  readonly stage: string;
  /** The one factual sentence. */
  readonly headline: string;
  /** Supporting facts. Always includes what is already usable, when anything is. */
  readonly detail: readonly string[];
  /**
   * Elapsed time, and only when there is no measurable progress (8.3: "if progress is not
   * measurable, the visual breathes rather than advances, and the label shows elapsed time").
   * Null the rest of the time, because elapsed time next to a real count is noise.
   */
  readonly elapsed: string | null;
  /** The pipeline's own message, kept in its own slot and never merged into `headline`. */
  readonly note: string | null;
}

/** The stage names, as the pipeline knows them. */
const STAGE_NAME: Readonly<Record<FormationPhase, string>> = Object.freeze({
  received: 'Upload received',
  media_extraction: 'Decode and metadata read',
  camera_recovery: 'Camera pose estimation',
  reconstruction: 'Dense reconstruction',
  entity_indexing: 'Entity detection and embedding',
  continuity_search: 'Cross-capture linking',
  review_required: 'Formed, awaiting your confirmation',
  ready: 'Ready',
  partial: 'Stopped, partial region kept',
  failed: 'Failed, photographs kept',
});

/**
 * Rung copy, written here because atlas-core deliberately carries only a `labelKey`
 * (product-specification.md P-2 records the exact wording as open).
 *
 * The fixed constraint from 5.2 is that no label may imply free movement in a region that does
 * not have it, and `test/formation-labels.test.ts` asserts exactly that against
 * `rungProperties(rung).impliesFreeMovement`.
 */
const RUNG_COPY: Readonly<Record<ReconstructionRung, string>> = Object.freeze({
  1: 'Full region. You can move freely inside it.',
  2: 'Corridor. You can travel the path the camera walked and look around from it.',
  3: 'Depth panels from single photographs. Real relief and a few degrees of parallax each, and every panel opens its source photograph.',
  4: 'Source first. The photographs are arranged by time and by what they share. No geometry was recovered.',
});

export function rungSentence(rung: ReconstructionRung): string {
  return RUNG_COPY[rung];
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${plural(s, 'second', 'seconds')} elapsed`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem === 0 ? `${plural(m, 'minute', 'minutes')} elapsed` : `${m} min ${rem} s elapsed`;
  const h = Math.floor(m / 60);
  return `${h} h ${m % 60} min elapsed`;
}

function usableLine(state: FormationState): string | null {
  const n = state.outcome?.photographsAvailable ?? state.photographs;
  if (n === null || n === undefined) return null;
  return `${plural(n, 'photograph is', 'photographs are')} available to open now.`;
}

function stageHeadline(state: FormationState): string {
  const c = state.counters;
  switch (state.phase) {
    // What the queue knows at this stage is that the upload arrived and no stage has reported on it
    // since. That is all it says: whether the photographs were handled elsewhere, or will be, is
    // not something this stream can see, and a sentence claiming either contradicted the line
    // saying they can be opened.
    case 'received':
      return state.photographs === null
        ? 'Photographs received. No count reported yet.'
        : `Received ${plural(state.photographs, 'photograph', 'photographs')}. No processing stage has reported yet.`;

    case 'media_extraction':
      if (!c) return 'Reading images. No count reported yet.';
      return c.total === null
        ? `Reading images: ${c.done} read so far. Total not yet known.`
        : `Reading images: ${c.done} of ${c.total}.`;

    case 'camera_recovery':
      if (!c) return 'Estimating camera positions. No count reported yet.';
      return c.total === null
        ? `Estimating camera positions: ${c.done} registered so far.`
        : `Estimating camera positions: ${c.done} of ${c.total} registered.`;

    // 8.2 for dense reconstruction: "Shown only when a real fraction exists." When it does not,
    // the sentence says so instead of inventing one.
    case 'reconstruction':
      if (!c || c.total === null) return 'Reconstructing surfaces. No measurable progress to report.';
      return `Reconstructing surfaces: ${c.done} of ${c.total} clusters converged.`;

    case 'entity_indexing': {
      const d = state.detections;
      if (!d) return 'Looking for people, objects and places. Nothing found yet.';
      return `Found ${plural(d.people, 'person', 'people')}, ${plural(d.objects, 'object', 'objects')}, ${plural(d.places, 'place', 'places')}.`;
    }

    case 'continuity_search':
      if (!c) return 'Comparing with existing regions. No count reported yet.';
      if (c.total === 0) return 'No existing regions to compare with. This is the first one.';
      return c.total === null
        ? `Comparing with existing regions: ${c.done} compared so far.`
        : `Comparing with ${plural(c.total, 'existing region', 'existing regions')}. ${c.done} compared.`;

    default:
      return outcomeHeadline(state);
  }
}

function outcomeHeadline(state: FormationState): string {
  const o = state.outcome;
  switch (state.phase) {
    case 'review_required':
      if (!o) return 'This region is formed and is waiting on your confirmation.';
      return `This region is formed. ${plural(o.openQuestions, 'thing needs', 'things need')} your confirmation before it can support an answer.`;

    // No congratulation, no completion metric, and 0 is a normal number here rather than a
    // finish line (product-specification.md section 7, "any completion metric" is excluded).
    case 'ready':
      if (!o) return 'This region is ready.';
      return o.openQuestions === 0
        ? 'This region is ready. Nothing is waiting on you.'
        : `This region is ready. ${plural(o.openQuestions, 'thing', 'things')} I am unsure about.`;

    case 'partial': {
      const stopped = o?.stoppedAt ? STAGE_NAME[o.stoppedAt].toLowerCase() : 'an earlier stage';
      return `Formation stopped at ${stopped}. The partial region is kept and is enterable.`;
    }

    case 'failed': {
      const at = o?.stoppedAt ? STAGE_NAME[o.stoppedAt].toLowerCase() : 'an earlier stage';
      const count = state.counters?.done;
      const where = count === undefined ? `${at} failed` : `${at} failed after ${plural(count, 'image', 'images')}`;
      const why =
        o?.reason === 'insufficient_registration'
          ? ' Too few images registered into a single model.'
          : o?.reason === 'cancelled'
            ? ' The job was stopped.'
            : '';
      return `${where}.${why} The photographs are available.`;
    }

    default:
      return 'Forming.';
  }
}

export function formationLabel(state: FormationState): FormationLabel {
  const detail: string[] = [];

  // Stream loss is stated first, because every number below it is now stale and the user has to
  // know that before they read them (8.4).
  if (state.stream === 'lost') {
    detail.push('Contact with the pipeline was lost. The counts below are the last ones received.');
  } else if (state.stream === 'connecting') {
    detail.push('Connecting to the pipeline.');
  }

  const rung = state.outcome?.rung;
  if (rung !== undefined) detail.push(rungSentence(rung));

  const usable = usableLine(state);
  if (usable !== null) detail.push(usable);

  if (state.phase === 'failed' || state.phase === 'partial') {
    // Restated at the moment the user is most likely to doubt it.
    detail.push('Nothing was deleted. The originals are retained.');
  }

  if (isOutcome(state.phase) && state.detections) {
    const d = state.detections;
    detail.push(`${d.people + d.objects + d.places} detections are indexed and searchable.`);
  }

  const ms = elapsedMs(state);
  const measurable = progressFraction(state) !== null;
  const elapsed = !measurable && ms !== null && !isOutcome(state.phase) ? formatElapsed(ms) : null;

  return {
    stage: STAGE_NAME[state.phase],
    headline: stageHeadline(state),
    detail,
    elapsed,
    note: state.note,
  };
}

/**
 * The label as one line, in reading order: stage, headline, detail, then the pipeline's note.
 * Elapsed time is left out, as a one-line status has no second slot to hold it.
 */
export function formationLabelLine(label: FormationLabel): string {
  return [label.stage, label.headline, ...label.detail, label.note].filter(Boolean).join(' ');
}

export { STAGE_NAME };
