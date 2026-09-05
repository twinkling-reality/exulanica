/** Atlas orientation and omission disclosures. */

import type {
  OccurrenceKind,
  ReconstructionRungRef,
  RenderingSubstrate,
  TrainingQualityRecord,
} from '@exulanica/graph-client';
import { rungSentence } from '@exulanica/formation';
import { el } from './dom.js';

/** Fixed by interaction-model.md 6.2 and shown with Atlas Map, where layout can be misread. */
export const MAP_ORIENTATION_CAPTION =
  'Positions show how these memories relate, not where they happened.';

export interface StatusInput {
  readonly omittedRegionCount: number;
  readonly undrawable: ReadonlyMap<OccurrenceKind, number>;
  /**
   * Everything the world could not load, one line each, in the order it was discovered.
   *
   * Renamed from `sourceMediaNotices` when reconstruction geometry gained a production loader and
   * a second kind of notice arrived. The name says what the field is rather than where the first
   * caller's strings came from, so the next kind does not need a third field or a misleading
   * second use of this one.
   */
  readonly notices?: readonly string[];
  readonly reconstructionScenes?: readonly ReconstructionRungDisclosure[];
  readonly onInspectScene?: (sceneId: string) => void;
  readonly onInspectSources?: (sceneId: string) => void;
  /** Live photograph groups before a reconstruction job has created a scene receipt. */
  readonly sourceRegions?: readonly { readonly regionId: string; readonly captureCount: number }[];
  /** Explicit reconstruction-review presentation; counts are the exact inspector inventories. */
  readonly reconstructionFocus?: {
    readonly collections: readonly { readonly sceneId: string; readonly sourceCount: number }[];
  };
}

export interface ReconstructionRungDisclosure {
  readonly sceneId: string;
  readonly recordedRung: ReconstructionRungRef | null;
  readonly displayedRung: ReconstructionRungRef;
  readonly registeredMemberCount: number;
  readonly memberCount: number;
  readonly renderingSubstrate: RenderingSubstrate;
  readonly reasons: readonly string[];
  /** The trainer's measured held-out appearance and accounting, shown beside a trained substrate. */
  readonly trainingQuality?: TrainingQualityRecord;
}

/** Measured numbers stay numbers: fixed decimals, units named, no adjectives. */
export function trainingQualitySentences(quality: TrainingQualityRecord): readonly [string, string] {
  const minutes = quality.durationSeconds / 60;
  return [
    `Held-out appearance over ${counted(quality.heldoutViews, 'photograph', 'photographs')}: `
      + `PSNR ${quality.psnr.toFixed(2)} dB, SSIM ${quality.ssim.toFixed(3)}, LPIPS ${quality.lpips.toFixed(3)}; `
      + `coverage ${quality.coverageFraction.toFixed(3)}, floater proxy ${quality.floatersFraction.toFixed(3)}. `
      + 'Pose conditioning used every photograph; scores describe appearance only.',
    `Trained ${quality.iterationsCompleted.toLocaleString('en-US')} iterations in ${minutes.toFixed(1)} min `
      + `on ${quality.gpu} for $${quality.usdCost.toFixed(2)} at the declared rate.`,
  ];
}

function counted(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function buildStatus(input: StatusInput): HTMLElement {
  const bar = el('footer', { class: 'status' });
  const sourceOnly = input.reconstructionFocus !== undefined
    && !(input.reconstructionScenes ?? []).some((scene) => scene.renderingSubstrate !== 'source_photographs');
  if (sourceOnly) {
    const collections = input.reconstructionFocus!.collections.filter((collection) => collection.sourceCount > 0);
    const notice = el('section', { class: 'reconstruction-availability', 'aria-label': 'Reconstruction availability' });
    notice.append(
      el('p', { class: 'reconstruction-availability-kicker', text: 'Source collection' }),
      el('h2', { text: 'No 3D reconstruction is loaded' }),
      el('p', { text: collections.length > 0
        ? 'The landscape is authored. Use the source inspector to view the original photographs.'
        : 'The landscape is authored. No source photographs are available in this session.' }),
    );
    for (const [index, collection] of collections.entries()) {
      const row = el('div', { class: 'reconstruction-availability-collection' });
      row.append(el('p', { text: counted(collection.sourceCount, 'original photograph', 'original photographs') }));
      if (input.onInspectSources !== undefined) {
        const inspect = el('button', { type: 'button', text: collections.length === 1
          ? 'Inspect source photographs' : `Inspect collection ${index + 1}` });
        inspect.addEventListener('click', () => input.onInspectSources?.(collection.sceneId));
        row.append(inspect);
      }
      notice.append(row);
    }
    bar.append(notice);
  }

  const undrawableCount = [...input.undrawable.values()].reduce(
    (total, count) => total + count,
    0,
  );
  const missing: string[] = [];

  if (input.omittedRegionCount > 0) {
    missing.push(counted(input.omittedRegionCount, 'region', 'regions'));
  }
  if (undrawableCount > 0) {
    missing.push(counted(undrawableCount, 'detection', 'detections'));
  }

  if (missing.length > 0) {
    bar.append(
      el('p', {
        class: 'status-warning',
        text: `${missing.join(' and ')} not shown in the Atlas.`,
      }),
    );
  }

  for (const notice of input.notices ?? []) {
    bar.append(el('p', { class: 'status-warning source-status', text: notice }));
  }

  for (const scene of input.reconstructionScenes ?? []) {
    const details = el('details', { class: 'reconstruction-rung' });
    details.dataset.sceneId = scene.sceneId;
    const recorded = scene.recordedRung === null ? 'unreadable' : String(scene.recordedRung);
    const substrate = scene.renderingSubstrate === 'posed_point_maps'
      ? 'posed point maps'
      : scene.renderingSubstrate === 'gaussian_splats' ? 'trained Gaussian reconstruction' : 'source photographs';
    details.append(
      el('summary', {
        text: `Recorded rung ${recorded}; showing rung ${scene.displayedRung} from ${substrate}.`,
      }),
      el('p', {
        class: 'reconstruction-rung-copy',
        text: rungSentence(scene.displayedRung),
      }),
      el('p', {
        class: 'reconstruction-rung-registration',
        text: `${scene.registeredMemberCount} of ${scene.memberCount} photographs registered.`,
      }),
    );
    if (scene.reasons.length > 0) {
      const reasons = el('ul', { class: 'reconstruction-rung-reasons' });
      for (const reason of scene.reasons) reasons.append(el('li', { text: reason }));
      details.append(reasons);
    }
    if (scene.trainingQuality !== undefined && scene.renderingSubstrate === 'gaussian_splats') {
      for (const sentence of trainingQualitySentences(scene.trainingQuality)) {
        details.append(el('p', { class: 'reconstruction-rung-quality', text: sentence }));
      }
    }
    if (scene.renderingSubstrate !== 'source_photographs' && input.onInspectScene !== undefined) {
      const inspect = el('button', { type: 'button', text: 'Inspect reconstruction' });
      inspect.addEventListener('click', () => input.onInspectScene?.(scene.sceneId));
      details.append(inspect);
    }
    if (input.onInspectSources !== undefined) {
      const sources = el('button', { type: 'button', text: 'Inspect source photographs' });
      sources.addEventListener('click', () => input.onInspectSources?.(scene.sceneId));
      details.append(sources);
    }
    bar.append(details);
  }

  for (const region of input.sourceRegions ?? []) {
    const details = el('details', { class: 'reconstruction-rung' });
    details.dataset.regionId = region.regionId;
    details.append(el('summary', {
      text: `${counted(region.captureCount, 'grouped photograph', 'grouped photographs')} · reconstruction unavailable`,
    }));
    if (input.onInspectSources !== undefined) {
      const sources = el('button', { type: 'button', text: 'Inspect source photographs' });
      sources.addEventListener('click', () => input.onInspectSources?.(region.regionId));
      details.append(sources);
    }
    bar.append(details);
  }

  return bar;
}
