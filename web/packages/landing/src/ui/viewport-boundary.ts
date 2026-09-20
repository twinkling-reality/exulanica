/**
 * The viewport boundary: the one screen that says this product is desktop only.
 *
 * This is not a soft preference dressed up as a requirement. The Atlas is navigated with
 * mouse-look, mouse-look is built on the Pointer Lock API, and interaction-model.md 2.1 records
 * the verified platform fact that pointer lock is unsupported on iOS Safari and Android Chrome:
 * "a hard platform limit with no workaround, not a scoping choice, and it is not solvable by
 * effort." product-specification.md 7 defers mobile Atlas traversal for exactly that reason.
 *
 * So the boundary states the real cause rather than "unsupported browser". A visitor who is told
 * why can decide what to do about it; a visitor who is told their device is wrong cannot.
 *
 * The predicate is separated from the DOM so it can be tested without a browser, which is the
 * only way the thresholds stay honest as the layout changes.
 */

import { el } from './dom.js';

/** Below this the title screen cannot hold its composition and the Atlas has no input model. */
export const MIN_WIDTH = 1024;
export const MIN_HEIGHT = 620;

export interface ViewportFacts {
  readonly width: number;
  readonly height: number;
  /**
   * True when the primary input is coarse, which is the platform's own statement that this is a
   * touch device. Checked in addition to size because a tablet in landscape can clear both
   * thresholds and still have no pointer to lock.
   */
  readonly coarsePointer: boolean;
}

export type BoundaryReason = 'narrow' | 'short' | 'touch';

/**
 * Why this viewport cannot run the product, or `null` if it can.
 *
 * Order matters: touch is reported ahead of size, because a phone held in landscape is blocked by
 * its input model rather than by its dimensions, and saying "make the window wider" to someone who
 * cannot would be useless advice.
 */
export function boundaryReason(v: ViewportFacts): BoundaryReason | null {
  if (v.coarsePointer) return 'touch';
  if (v.width < MIN_WIDTH) return 'narrow';
  if (v.height < MIN_HEIGHT) return 'short';
  return null;
}

export function readViewport(): ViewportFacts {
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    coarsePointer: window.matchMedia('(pointer: coarse)').matches,
  };
}

const BODY: Readonly<Record<BoundaryReason, string>> = Object.freeze({
  touch:
    'The Atlas is navigated by mouse-look, which is built on the Pointer Lock API. That API is not implemented by iOS Safari or Android Chrome, so there is no way to offer this on a touch device yet. It is a platform limitation rather than something left undone.',
  narrow: `The title screen and the Atlas both need a window at least ${MIN_WIDTH} pixels wide. Widen this one and it will pick up from here.`,
  short: `The title screen and the Atlas both need a window at least ${MIN_HEIGHT} pixels tall. Make this one taller and it will pick up from here.`,
});

/**
 * The boundary screen.
 *
 * Built once and shown or hidden, rather than constructed on each resize: dragging a window edge
 * fires continuously, and a version that rebuilt would rebuild dozens of times per second.
 */
export function buildViewportBoundary(): {
  readonly root: HTMLElement;
  apply(reason: BoundaryReason | null): void;
} {
  const root = el('div', { id: 'boundary', class: 'boundary', hidden: '' });
  const body = el('p', { class: 'boundary-body' });

  root.append(
    el('p', { class: 'boundary-eyebrow', text: 'Exulanica' }),
    el('h1', { class: 'boundary-head', text: 'Desktop only.' }),
    body,
  );

  return {
    root,
    apply(reason) {
      root.hidden = reason === null;
      // The document is locked while the boundary stands, so a visitor cannot scroll the title
      // screen around underneath it and find the controls it just said were unavailable.
      document.documentElement.dataset['blocked'] = reason === null ? 'false' : 'true';
      if (reason !== null) body.textContent = BODY[reason];
    },
  };
}
