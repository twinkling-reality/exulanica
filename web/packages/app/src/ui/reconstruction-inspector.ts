import type { SourceMediaDescriptor } from '@exulanica/atlas-react/playcanvas';
import { el, replace } from './dom.js';

export interface ReconstructionInspectionOption {
  readonly id: string;
  readonly kind: 'source-camera' | 'between-cameras' | 'source-only';
  readonly label: string;
  readonly projection?: 'pinhole' | 'pinhole-approximation' | 'opm-estimate' | 'interpolated';
  readonly source: SourceMediaDescriptor | null;
  /**
   * Which photograph this view stands on, when it stands on one.
   *
   * Carried because the person review below is about a photograph and not about a scene, and the
   * caller already resolves the member to build `source`. Null for a midpoint between cameras,
   * where there is no single photograph a review could be of.
   */
  readonly captureId?: string | null;
}

/** One photograph that recorded the selected point, as the panel needs to show it. */
export interface ObservingPhotograph {
  readonly captureId: string;
  /** From the capture's own evidence handle, or null when this session holds no authorized one. */
  readonly title: string | null;
  readonly label: string;
  /** An authorized object URL for the original, when the session already has one. */
  readonly url: string | null;
  readonly alt: string;
  readonly available: boolean;
  /** Where in that photograph the point was recorded, in its own pixels. */
  readonly x: number;
  readonly y: number;
  readonly consentSentence: string;
}

/**
 * What the evidence panel is currently able to say, and every one of these is a real answer.
 *
 * `miss` in particular. A click that resolves to nothing means no photograph's recorded
 * observations reach that part of the view, which is the honest state for a plain surface the
 * reconstruction matched few features on, and it has to be shown rather than swallowed: a panel
 * that quietly kept the previous answer would be attributing one surface's photographs to another.
 */
export type ObservationEvidenceState =
  /** This view has no calibrated recovered camera, so a click has nothing exact to invert. */
  | { readonly kind: 'unsupported'; readonly reason: string }
  | { readonly kind: 'loading' }
  /** A click is with the server. Whatever the panel said about the previous click is gone. */
  | { readonly kind: 'resolving' }
  | { readonly kind: 'failed'; readonly reason: string }
  | { readonly kind: 'ready'; readonly pointCount: number; readonly retainedPerImage: number }
  | { readonly kind: 'miss'; readonly toleranceSourcePx: number; readonly canvasPx: number }
  | {
      readonly kind: 'hit';
      /** `observationSentence` from atlas-core, verbatim. */
      readonly sentence: string;
      readonly pointId: number;
      readonly pixelDistance: number;
      /**
       * COLMAP's mean reprojection error for this POINT over its whole track.
       *
       * One number per point, not per observation. `points3D.txt` field 7 is the point's mean
       * residual, and the pose stage copies it onto every row of the track, so listing it beside
       * each photograph would show the same value N times and invite a reader to compare
       * photographs by a number that does not vary between them.
       */
      readonly meanReprojectionErrorPx: number;
      readonly projection: 'pinhole' | 'pinhole-approximation';
      readonly photographs: readonly ObservingPhotograph[];
    };

/** A bounded camera register beside the live world. Source media keeps its existing authorization. */
export function buildReconstructionInspector(options: {
  readonly onView: (sceneId: string, viewId: string) => boolean;
  readonly onReturn: () => void;
  /**
   * Called after a view is installed, so the caller can say what a click here could resolve.
   *
   * Separate from `onView`, which runs before the selection moves and answers whether the renderer
   * accepted the view at all. Evidence depends on which view is now showing, so it needs the one
   * that runs after.
   */
  readonly onViewShown?: (sceneId: string, view: ReconstructionInspectionOption) => void;
  /**
   * Resolve the middle of the view, for anyone not using a pointer.
   *
   * The world canvas is `aria-hidden="true"` by deliberate decision, so a gesture that exists only
   * as a click on it exists only for sighted mouse users. This aside is the accessible surface, so
   * the same question is askable from a real button inside it. It resolves the centre of the view
   * rather than a chosen coordinate because the centre is the one point a keyboard user can aim at
   * without a cursor: the view itself is what they move, with Previous and Next.
   */
  readonly onResolveCentre?: () => void;
}) {
  const root = el('aside', {
    class: 'reconstruction-inspector', hidden: true,
    'aria-label': 'Reconstruction inspection',
  });
  const title = el('h2', { text: 'Reconstruction views' });
  const disclosure = el('p', {
    text: 'Camera inspection · fitted relative scale · physical scale unverified. These views do not establish a walkable surface.',
  });
  const select = el('select', { 'aria-label': 'Inspection viewpoint' });
  const previous = el('button', { type: 'button', text: 'Previous view' });
  const next = el('button', { type: 'button', text: 'Next view' });
  const back = el('button', { type: 'button', text: 'Return to Atlas' });
  const state = el('p', { role: 'status', 'aria-live': 'polite' });
  const source = el('details', { class: 'reconstruction-inspector-source' });
  const sourceBody = el('div');
  source.append(el('summary', { text: 'Inspect original source' }), sourceBody);
  // Click-to-evidence lives here, under the camera register and above nothing.
  //
  // It is in the inspector rather than in traverse because traverse holds Pointer Lock, which
  // freezes the cursor coordinates a pick needs (`atlas-react/src/playcanvas/controls.ts`), and
  // because the focus solver must never take a screen-space input. The inspector has already
  // exited the lock and already stands on a calibrated recovered camera, so a click here has real
  // coordinates and an exact projection to invert.
  const evidence = el('section', {
    class: 'reconstruction-evidence', 'aria-label': 'Observed by',
  });
  // The person review sits below the evidence panel, in the inspector, for the same reason
  // click-to-evidence does: this is the one surface that already stands on a single named
  // photograph, and a review is about a photograph. It is a slot rather than a renderer because
  // `ui/person-review.ts` owns what a review looks like and owns the argument that it must never
  // draw the pixels; duplicating any of that here would be a second place for it to be wrong.
  const review = el('section', {
    class: 'reconstruction-review', 'aria-label': 'People in this photograph',
  });
  const evidenceState = el('p', { class: 'reconstruction-evidence-state', role: 'status', 'aria-live': 'polite' });
  const evidenceDetail = el('p', { class: 'reconstruction-evidence-detail' });
  const evidenceList = el('ol', { class: 'reconstruction-evidence-list' });
  evidence.append(el('h3', { text: 'Observed by' }));
  if (options.onResolveCentre !== undefined) {
    const resolve = el('button', {
      type: 'button', class: 'reconstruction-evidence-resolve',
      text: 'Resolve the centre of this view',
    });
    resolve.addEventListener('click', () => options.onResolveCentre?.());
    evidence.append(
      el('p', {
        class: 'reconstruction-evidence-how',
        text: 'Click anywhere in the view to resolve that surface to the photographs that '
          + 'observed it, or use the button for the centre of the view.',
      }),
      resolve,
    );
  }
  evidence.append(evidenceState, evidenceDetail, evidenceList);
  root.append(el('header', { class: 'reconstruction-inspector-header' }, [title, back]),
    disclosure, select, el('nav', {}, [previous, next]), state, source, evidence, review);
  let sceneId = '';
  let views: readonly ReconstructionInspectionOption[] = [];
  let restoreFocus: HTMLElement | null = null;

  function showView(index: number): void {
    const view = views[index];
    if (view === undefined) return;
    if (view.kind !== 'source-only' && !options.onView(sceneId, view.id)) {
      state.textContent = 'This view is unavailable. Return to Atlas to use its source photographs.';
      source.hidden = true;
      return;
    }
    select.selectedIndex = index;
    root.dataset.viewId = view.id;
    previous.disabled = index === 0;
    next.disabled = index === views.length - 1;
    state.textContent = view.kind === 'source-only'
      ? 'Original photograph. Reconstructed camera inspection is unavailable for this scene.'
      : view.kind === 'source-camera'
      ? (view.projection === 'pinhole-approximation'
        ? 'Recovered camera with calibrated focal lengths and principal point. Lens distortion is approximated by a pinhole projection.'
        : view.projection === 'pinhole' ? 'Recovered camera with its calibrated pinhole projection.'
          : 'Recovered source camera using the point-map field-of-view estimate.')
      : 'Midpoint between consecutive recovered cameras. This is an unobserved viewpoint, not measured geometry or a validated route.';
    source.hidden = false;
    source.open = view.kind === 'source-only';
    if (view.source?.available && view.source.url !== null) {
      replace(sourceBody, [el('img', { src: view.source.url, alt: view.source.alt }),
        el('p', { text: sourceCaption(view.source.title, view.label), title: view.source.title })]);
    } else {
      replace(sourceBody, [el('p', {
        text: view.kind === 'between-cameras'
          ? 'No photograph was taken at this midpoint. Choose either adjacent source camera to inspect its original.'
          : 'The authorized original source is unavailable in this session.',
      })]);
    }
    options.onViewShown?.(sceneId, view);
  }
  function showEvidence(next: ObservationEvidenceState): void {
    evidence.dataset.evidence = next.kind;
    switch (next.kind) {
      case 'unsupported':
        evidenceState.textContent = next.reason;
        evidenceDetail.textContent = '';
        replace(evidenceList, []);
        return;
      case 'loading':
        evidenceState.textContent = 'Reading the recorded observations for this scene.';
        evidenceDetail.textContent = '';
        replace(evidenceList, []);
        return;
      case 'resolving':
        evidenceState.textContent = 'Finding the recorded point nearest that click.';
        evidenceDetail.textContent = '';
        replace(evidenceList, []);
        return;
      case 'failed':
        evidenceState.textContent = next.reason;
        evidenceDetail.textContent = '';
        replace(evidenceList, []);
        return;
      case 'ready':
        evidenceState.textContent =
          `Click the view to see which photographs observed a point. `
          + `${next.pointCount.toLocaleString('en-US')} recorded points are held for this scene, `
          + `at most ${next.retainedPerImage.toLocaleString('en-US')} per photograph.`;
        evidenceDetail.textContent = '';
        replace(evidenceList, []);
        return;
      case 'miss':
        // A NULL PICK IS AN ANSWER. Sparse points are sparse: a plain surface the reconstruction
        // matched few features on genuinely has no recorded observation near the cursor, and
        // reporting the nearest point from somewhere else in the frame would attribute one
        // surface's photographs to another.
        evidenceState.textContent = 'No recorded observation is within reach of that click.';
        evidenceDetail.textContent =
          `Nothing COLMAP recorded lies within ${next.canvasPx} screen pixels `
          + `(${Math.round(next.toleranceSourcePx)} pixels of the original photograph) of where you `
          + 'clicked. The sparse points are the recorded evidence; the surface drawn between them '
          + 'is not itself observed.';
        replace(evidenceList, []);
        return;
      case 'hit': {
        // `observationSentence` verbatim, from atlas-core. It is the one sentence that has to say
        // both numbers when a point's track is longer than the sample retained here, and rewording
        // it in the panel is how those two would come apart.
        evidenceState.textContent = next.sentence;
        evidenceDetail.textContent =
          `Recorded sparse point ${String(next.pointId)}, `
          + `${next.pixelDistance.toFixed(0)} source pixels from the cursor, `
          + `mean reprojection error ${next.meanReprojectionErrorPx.toFixed(2)} px over its whole track. `
          + 'This is the nearest point COLMAP actually recorded, not the surface under the pointer, '
          + 'and the photographs below are the ones that observed it'
          + (next.projection === 'pinhole-approximation'
            ? '. The original lens had a distortion model this projection approximates as a pinhole.'
            : '.');
        replace(evidenceList, next.photographs.map((photograph) => {
          const item = el('li', { class: 'reconstruction-evidence-photograph' });
          item.dataset.captureId = photograph.captureId;
          if (photograph.available && photograph.url !== null) {
            item.append(el('img', { src: photograph.url, alt: photograph.alt }));
          }
          item.append(
            el('p', {
              class: 'reconstruction-evidence-title',
              text: sourceCaption(photograph.title ?? photograph.label, photograph.label),
              title: photograph.title ?? photograph.label,
            }),
            el('p', {
              class: 'reconstruction-evidence-where',
              text: `Recorded at ${photograph.x.toFixed(0)}, ${photograph.y.toFixed(0)} in this photograph.`,
            }),
            el('p', { class: 'reconstruction-evidence-consent', text: photograph.consentSentence }),
          );
          if (!photograph.available) {
            item.append(el('p', {
              class: 'reconstruction-evidence-unavailable',
              text: 'The authorized original is not loaded in this session.',
            }));
          }
          return item;
        }));
        return;
      }
    }
  }

  const hide = (): void => {
    root.hidden = true;
    source.open = false;
    replace(sourceBody, []);
    replace(review, []);
    // A closed inspector holds no answer. Leaving the last pick on screen would let a later
    // session read it as being about whatever is open then.
    showEvidence({ kind: 'unsupported', reason: 'Open a reconstruction view to resolve a surface to its photographs.' });
    if (restoreFocus?.isConnected) restoreFocus.focus();
    restoreFocus = null;
  };
  const close = (): void => { options.onReturn(); hide(); };
  back.addEventListener('click', close);
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    close();
  });
  select.addEventListener('change', () => showView(select.selectedIndex));
  previous.addEventListener('click', () => showView(select.selectedIndex - 1));
  next.addEventListener('click', () => showView(select.selectedIndex + 1));
  /**
   * Put a review panel under the evidence, or clear it.
   *
   * Null clears, and every path that changes which photograph is showing must call it with null
   * before it has an answer for the new one. A stale panel here would attribute one photograph's
   * people to another, which is the same failure `showEvidence` guards against and is worse: the
   * buttons in it write receipts.
   */
  function showReview(panel: HTMLElement | null): void {
    replace(review, panel === null ? [] : [panel]);
  }

  return {
    root, hide, showEvidence, showReview,
    /** The view a click would be inverted through, so the caller can refuse an uncalibrated one. */
    get selected(): ReconstructionInspectionOption | null {
      return root.hidden ? null : (views[select.selectedIndex] ?? null);
    },
    open(id: string, choices: readonly ReconstructionInspectionOption[]): boolean {
      if (choices.length === 0) return false;
      if (root.hidden) restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      sceneId = id;
      views = choices;
      const sourceOnly = choices[0]!.kind === 'source-only';
      title.textContent = sourceOnly ? 'Source photographs' : 'Reconstruction views';
      disclosure.textContent = sourceOnly
        ? 'Authorized original evidence. No reconstructed surface or measured route is implied.'
        : 'Camera inspection · fitted relative scale · physical scale unverified. These views do not establish a walkable surface.';
      select.setAttribute('aria-label', sourceOnly ? 'Source photograph' : 'Inspection viewpoint');
      root.dataset.sceneId = id;
      replace(select, choices.map((view) => el('option', { value: view.id, text: view.label })));
      root.hidden = false;
      showView(0);
      select.focus();
      return true;
    },
  };
}

/** Generated source identifiers remain metadata, while the reading label stays short. */
export function sourceCaption(title: string, fallback: string): string {
  return /^(?:(?:source|capture)[\s:_-]*)?[0-9a-f]{8}[-\s][0-9a-f]{4}[-\s][0-9a-f]{4}[-\s][0-9a-f]{4}[-\s][0-9a-f]{12}$/iu.test(title)
    ? fallback : title;
}
