/** Atlas orientation and omission disclosures. */

import type {
  OccurrenceKind,
  ReconstructionRungRef,
  RenderingSubstrate,
  TrainingQualityRecord,
} from '@exulanica/graph-client';
import { personPresenceSentence } from '@exulanica/graph-client';
import { rungSentence } from '@exulanica/formation';
import { el } from './dom.js';

// Imported below the local import rather than beside the other package imports, because the
// person-consent branch adds its own import directly above `rungSentence` and adjacent inserts
// conflict over nothing.
import {
  PROOF_TIERS,
  PROOF_TIER_LABELS,
  PROOF_TIER_SENTENCES,
  proofLensSwatch,
  proofTierOf,
  type PresentationTheme,
  type ProofTier,
} from '@exulanica/presentation';

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
  readonly admittedSourceCount?: number;
  readonly onInspectAdmittedSources?: () => void;
  readonly sourceRegions?: readonly { readonly regionId: string; readonly captureCount: number }[];
  /** Explicit reconstruction-review presentation; counts are the exact inspector inventories. */
  readonly reconstructionFocus?: {
    readonly collections: readonly { readonly sceneId: string; readonly sourceCount: number }[];
  };
  /**
   * The proof lens switch and the legend that makes its colours checkable.
   *
   * Declared LAST in this interface, and rendered last in `buildStatus`, deliberately. The
   * person-consent branch inserts its per-member consent line beside the registration paragraph
   * in the middle of the reconstruction block; a new field and a new section at the two ends stay
   * textually clear of it, so the two branches merge without an argument about an ordering neither
   * of them has an opinion about.
   */
  readonly proofLens?: ProofLensControl;
}

/** The lens switch as the status panel sees it: a current state and somewhere to send a change. */
export interface ProofLensControl {
  readonly enabled: boolean;
  readonly theme: PresentationTheme;
  readonly onToggle: (enabled: boolean) => void;
}

export interface ReconstructionRungDisclosure {
  readonly sceneId: string;
  readonly recordedRung: ReconstructionRungRef | null;
  readonly displayedRung: ReconstructionRungRef;
  readonly registeredMemberCount: number;
  readonly memberCount: number;
  readonly renderingSubstrate: RenderingSubstrate;
  readonly reasons: readonly string[];
  /** How many people in this scene are not being drawn, and across how many photographs. */
  readonly hiddenPersonCount?: number;
  readonly maskedMemberCount?: number;
  /** Photographs nobody has screened for people, which are withheld rather than shown. */
  readonly unscreenedMemberCount?: number;
  /** The trainer's measured held-out appearance and accounting, shown beside a trained substrate. */
  readonly trainingQuality?: TrainingQualityRecord;
  /**
   * Whether this scene is the one its region draws.
   *
   * A scene whose region displays a more complete reconstruction of the same photographs is still
   * listed, and the proof lens must say it is showing nothing rather than colour it as though it
   * were showing reconstruction.
   */
  readonly drawn?: boolean;
  /** Whether a model-generated surface is among what this scene draws. */
  readonly showingGenerated?: boolean;
}

/**
 * What the proof lens says about one scene, as text.
 *
 * The lens colours the world; this is the same fact in the panel where every other honesty claim
 * in this product already lives, and it is what a screen reader and a screenshot both get. The
 * label and the sentence come from `@exulanica/presentation` verbatim rather than being reworded
 * here, so the colour and the words cannot drift apart.
 */
export function proofTierDisclosure(scene: ReconstructionRungDisclosure): {
  readonly tier: ProofTier;
  readonly label: string;
  readonly sentence: string;
} {
  const tier = proofTierOf({
    substrate: scene.renderingSubstrate,
    drawn: scene.drawn ?? true,
    showingGenerated: scene.showingGenerated ?? false,
  });
  return { tier, label: PROOF_TIER_LABELS[tier], sentence: PROOF_TIER_SENTENCES[tier] };
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
  if ((input.admittedSourceCount ?? 0) > 0) {
    const sources = el('section', { 'aria-label': 'Admitted photographs' });
    sources.append(el('p', { text: counted(input.admittedSourceCount!, 'admitted photograph', 'admitted photographs') }));
    if (input.onInspectAdmittedSources !== undefined) {
      const inspect = el('button', { type: 'button', text: 'Inspect admitted photographs' });
      inspect.addEventListener('click', input.onInspectAdmittedSources);
      sources.append(inspect);
    }
    bar.append(sources);
  }
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
        : (input.admittedSourceCount ?? 0) > 0
          ? 'Admitted photographs are available in the source inspector.'
          : 'No source photographs are available in this session.' }),
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
      : scene.renderingSubstrate === 'unposed_point_maps'
        ? 'each photograph\u2019s own depth, in an unmeasured arrangement'
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
    // Appended here rather than through `notices`, which carries `status-warning source-status`
    // and would frame somebody's consent decision as a load failure. A hidden person is not an
    // error; a photograph nobody has screened is, and the sentence says which is which.
    const presence = personPresenceSentence({
      hiddenPersonCount: scene.hiddenPersonCount ?? 0,
      maskedMemberCount: scene.maskedMemberCount ?? 0,
      unscreenedMemberCount: scene.unscreenedMemberCount ?? 0,
    });
    if (presence !== null) {
      details.append(el('p', { class: 'reconstruction-person-presence', text: presence }));
    }
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
    // Last of the sentences and before the buttons, so it reads as the summary of everything above
    // it. Also deliberately far from the registration paragraph, which is where the person-consent
    // branch appends its own line.
    const proof = proofTierDisclosure(scene);
    const proofLine = el('p', {
      class: 'reconstruction-proof-tier',
      text: `${proof.label}. ${proof.sentence}`,
    });
    proofLine.dataset.proofTier = proof.tier;
    details.append(proofLine);
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

  // THE PROOF LENS SWITCH AND ITS LEGEND, at the very end of the panel.
  //
  // Placed here rather than beside the per-scene proof-tier line for two reasons. It belongs to
  // the whole view rather than to one scene, and the `person-consent-masking` branch appends its
  // per-member consent line inside the reconstruction block above; keeping this section clear of
  // that block is what makes the two branches merge textually instead of semantically.
  //
  // The legend is not decoration. A colour nobody can name is a claim nobody can check, so every
  // tier appears here with its swatch, its label and its sentence whether or not any region is
  // currently at that tier. Reading the three strings straight from `@exulanica/presentation` is
  // what keeps the words and the colour from drifting: they are the same table the shader's
  // uniform was resolved from.
  if (input.proofLens !== undefined) {
    const lens = input.proofLens;
    const section = el('section', { class: 'proof-lens', 'aria-label': 'Proof lens' });
    const toggle = el('button', {
      type: 'button',
      class: 'proof-lens-toggle',
      text: lens.enabled ? 'Proof lens on' : 'Proof lens off',
    });
    toggle.setAttribute('aria-pressed', lens.enabled ? 'true' : 'false');
    let on = lens.enabled;
    toggle.addEventListener('click', () => {
      on = !on;
      // The button restates ITSELF and calls out. It deliberately does not ask the panel to
      // re-render: the lens changes how the world is coloured and nothing else, and a status
      // panel that rebuilt on every toggle would make that harder to believe, not easier.
      toggle.textContent = on ? 'Proof lens on' : 'Proof lens off';
      toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
      section.dataset.proofLens = on ? 'on' : 'off';
      lens.onToggle(on);
    });
    section.dataset.proofLens = lens.enabled ? 'on' : 'off';
    section.append(
      el('h2', { text: 'Proof lens' }),
      el('p', {
        class: 'proof-lens-copy',
        text: 'Colour every region by what produced the surface you are looking at. It changes '
          + 'nothing about the scene, its rung or its receipts.',
      }),
      toggle,
    );
    const legend = el('ul', { class: 'proof-lens-legend' });
    for (const tier of PROOF_TIERS) {
      const item = el('li');
      item.dataset.proofTier = tier;
      const swatch = el('span', { class: 'proof-lens-swatch', 'aria-hidden': 'true' });
      // The exact row the renderer is given, so the key and the picture cannot disagree.
      swatch.style.backgroundColor = proofLensSwatch(lens.theme, tier);
      item.append(swatch, el('span', {
        class: 'proof-lens-legend-text',
        text: `${PROOF_TIER_LABELS[tier]}. ${PROOF_TIER_SENTENCES[tier]}`,
      }));
      legend.append(item);
    }
    section.append(legend);
    // WHAT THE LENS DOES NOT REPAINT, said out loud rather than left as a silent gap.
    //
    // A region showing an original photograph is showing evidence, and tinting evidence would
    // alter the thing being offered as evidence. So the lens colours derived geometry and leaves a
    // photograph alone; `photographed` stays in the legend because a visitor still has to be able
    // to read what the absence of a tint means.
    section.append(el('p', {
      class: 'proof-lens-limit',
      text: 'The lens colours derived geometry. A region showing an original photograph is left '
        + 'exactly as it was recorded, because tinting evidence would alter it.',
    }));
    bar.append(section);
  }

  return bar;
}
