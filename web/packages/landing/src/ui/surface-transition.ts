import type { Surface } from '../router.js';

type Panes = Readonly<Record<Surface, HTMLElement>>;
const REST = 'translate3d(0, 0, 0) scale(1)';
type InformationSurface = 'purpose' | 'capabilities' | 'research' | 'waitlist' | 'developers';
type Rectangle = Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>;

/**
 * Where above the wordmark each surface sits, and how far in the camera pushes to get there.
 *
 * `along` is a fraction of the wordmark's width, so the reading pages take its two ends and the
 * two later surfaces take its centre at different depths. A table rather than a chain of
 * conditionals because four destinations was the point where the chain stopped being readable;
 * the three original values are unchanged.
 */
const CAMERA: Readonly<Record<InformationSurface, { along: number; scale: number }>> = Object.freeze({
  purpose: { along: 0.82, scale: 2.5 },
  capabilities: { along: 0.18, scale: 2.5 },
  research: { along: 0.5, scale: 3.4 },
  waitlist: { along: 0.5, scale: 2.0 },
  developers: { along: 0.5, scale: 2.8 },
});

/** Place a point above the selected end of the wordmark at the viewport centre. */
export function titleCamera(
  destination: InformationSurface,
  wordmark: Rectangle,
  pane: Rectangle,
  viewport: { width: number; height: number },
): { transform: string; x: number; y: number; scale: number; target: { x: number; y: number } } {
  const { along, scale } = CAMERA[destination];
  const target = {
    x: wordmark.left + wordmark.width * along,
    y: wordmark.top - wordmark.height * 0.65,
  };
  const origin = { x: pane.left + pane.width / 2, y: pane.top + pane.height / 2 };
  const x = viewport.width / 2 - origin.x - scale * (target.x - origin.x);
  const y = viewport.height / 2 - origin.y - scale * (target.y - origin.y);
  return { transform: `translate3d(${x}px, ${y}px, 0) scale(${scale})`, x, y, scale, target };
}

/** Text crossfades in place; only the decorative landscape follows the camera. */
export function createSurfaceTransition(
  panes: Panes,
  reducedMotion: () => boolean,
  landscape?: HTMLElement,
): {
  show(next: Surface): void;
  finish(): void;
  refresh(): void;
} {
  let current: Surface | null = null;
  let animations: Animation[] = [];
  let generation = 0;
  const layerHints = new Map<HTMLElement, string>();
  let cameras: Partial<Record<InformationSurface, string>> = {};
  let landscapeTarget = REST;

  const settle = (): void => {
    for (const [key, pane] of Object.entries(panes)) {
      pane.hidden = key !== current;
      pane.inert = key !== current;
      pane.setAttribute('aria-hidden', String(key !== current));
    }
  };
  const cancel = (): void => {
    generation += 1;
    if (landscape) landscape.style.transform = landscapeTarget;
    animations.forEach((animation) => animation.cancel());
    animations = [];
    for (const [pane, original] of layerHints) pane.style.willChange = original;
    layerHints.clear();
  };
  const measureCamera = (destination: InformationSurface): string => {
    const title = panes.title;
    const wasHidden = title.hidden;
    // Expose the title before reading its scroll offset. Hidden scrollports need not report it.
    title.hidden = false;
    const scrollTop = title.scrollTop;
    title.scrollTop = 0;
    try {
      const wordmark = title.querySelector<HTMLElement>('#title-wordmark');
      return wordmark === null ? REST : titleCamera(
        destination,
        wordmark.getBoundingClientRect(),
        title.getBoundingClientRect(),
        { width: window.innerWidth, height: window.innerHeight },
      ).transform;
    } finally {
      // The camera uses the resting composition without discarding the visitor's reading position.
      title.scrollTop = scrollTop;
      title.hidden = wasHidden;
    }
  };
  const cameraFor = (destination: Surface): string => {
    if (!(destination in CAMERA)) return REST;
    const information = destination as InformationSurface;
    return cameras[information] ??= measureCamera(information);
  };
  const placeLandscape = (transform: string): void => {
    landscapeTarget = transform;
    if (!landscape) return;
    landscape.style.transformOrigin = '50% 50%';
    landscape.style.transform = transform;
  };

  return {
    finish() {
      cancel();
      settle();
    },
    refresh() {
      cancel();
      cameras = {};
      if (current !== null && landscape) placeLandscape(cameraFor(current));
      settle();
    },
    show(next) {
      if (next === current) return;
      const previous = current;
      const reduced = reducedMotion();
      const outgoing = previous === null ? null : panes[previous];
      const incoming = panes[next];
      // Read the painted positions before cancelling, so a quick reversal starts where it is.
      const painted = (pane: HTMLElement): Keyframe => {
        const style = getComputedStyle(pane);
        return { transform: style.transform || REST, opacity: style.opacity || '1' };
      };
      const outgoingStart = outgoing && animations.length > 0
        ? painted(outgoing) : { transform: REST, opacity: 1 };
      const incomingStart = !incoming.hidden && animations.length > 0 ? painted(incoming) : null;
      const landscapeStart = landscape
        ? animations.length > 0 ? painted(landscape).transform : landscapeTarget
        : undefined;
      cancel();
      // Returning to the title must not replay its first-paint typography entrance.
      if (previous !== null || next !== 'title') panes.title.dataset['entered'] = 'true';
      current = next;
      if (landscape) placeLandscape(cameraFor(next));
      settle();
      if (outgoing === null || typeof incoming.animate !== 'function') return;

      outgoing.hidden = false;
      outgoing.inert = true;
      outgoing.setAttribute('aria-hidden', 'true');
      const options: KeyframeAnimationOptions = {
        duration: reduced ? 100 : 180,
        easing: 'cubic-bezier(.22,1,.36,1)',
        fill: 'both',
      };
      const outFrames: Keyframe[] = [{ opacity: outgoingStart?.opacity ?? 1 }, { opacity: 0 }];
      const inFrames: Keyframe[] = [{ opacity: incomingStart?.opacity ?? 0 }, { opacity: 1 }];
      const token = generation;
      for (const pane of [outgoing, incoming]) {
        layerHints.set(pane, pane.style.willChange);
        pane.style.willChange = 'opacity';
      }
      animations = [
        outgoing.animate(outFrames, options),
        incoming.animate(inFrames, options),
      ];
      if (landscape && !reduced && typeof landscape.animate === 'function') {
        layerHints.set(landscape, landscape.style.willChange);
        landscape.style.willChange = 'transform';
        animations.push(landscape.animate([
          { transform: landscapeStart ?? REST },
          { transform: landscapeTarget },
        ], { ...options, duration: 420, easing: 'cubic-bezier(0.25, 0.55, 0.35, 1)' }));
      }
      void Promise.all(animations.map((animation) => animation.finished)).then(() => {
        if (generation !== token) return;
        settle();
        cancel();
      }, () => {
        // Cancellation belongs to a later navigation; its generation owns cleanup.
      });
    },
  };
}
