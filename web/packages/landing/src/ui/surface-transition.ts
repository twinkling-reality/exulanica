import type { Surface } from './chrome.js';

type Panes = Readonly<Record<Surface, HTMLElement>>;
const REST = 'translate3d(0, 0, 0) scale(1)';
type InformationSurface = Exclude<Surface, 'title'>;
type Rectangle = Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>;

/** Place a point above the selected end of the wordmark at the viewport centre. */
export function titleCamera(
  destination: InformationSurface,
  wordmark: Rectangle,
  pane: Rectangle,
  viewport: { width: number; height: number },
): { transform: string; x: number; y: number; scale: number; target: { x: number; y: number } } {
  const scale = 2.5;
  const target = {
    x: wordmark.left + wordmark.width * (destination === 'purpose' ? 0.82 : 0.18),
    y: wordmark.top - wordmark.height * 0.65,
  };
  const origin = { x: pane.left + pane.width / 2, y: pane.top + pane.height / 2 };
  const x = viewport.width / 2 - origin.x - scale * (target.x - origin.x);
  const y = viewport.height / 2 - origin.y - scale * (target.y - origin.y);
  return { transform: `translate3d(${x}px, ${y}px, 0) scale(${scale})`, x, y, scale, target };
}

const informationDistance = (destination: InformationSurface): string =>
  `translate3d(${destination === 'purpose' ? 6 : -6}vw, -3vh, 0) scale(0.97)`;

/** Move through the title plane while leaving the shared navigation outside the camera. */
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
    // This synchronous measurement runs after cancellation, so no scaled coordinates leak into
    // the next camera. Temporarily exposing a hidden title also supports a direct information URL.
    title.hidden = false;
    const wordmark = title.querySelector<HTMLElement>('#title-wordmark');
    const result = wordmark === null ? REST : titleCamera(
      destination,
      wordmark.getBoundingClientRect(),
      title.getBoundingClientRect(),
      { width: window.innerWidth, height: window.innerHeight },
    ).transform;
    title.hidden = wasHidden;
    return result;
  };
  const cameraFor = (destination: Surface): string => {
    if (destination === 'title') return REST;
    return cameras[destination] ??= measureCamera(destination);
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
      const toInformation = previous === 'title';
      const toTitle = next === 'title';
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
      const destination = next === 'title' ? previous : next;
      const camera = (landscape !== undefined || (previous !== null && !reduced && (toInformation || toTitle)))
        && destination !== null && destination !== 'title'
        ? cameraFor(destination) : REST;
      current = next;
      if (landscape) placeLandscape(next === 'title' ? REST : camera);
      settle();
      if (outgoing === null || typeof incoming.animate !== 'function') return;

      outgoing.hidden = false;
      // The outgoing surface stays visible only as scenery, never as a second active document.
      outgoing.inert = true;
      outgoing.setAttribute('aria-hidden', 'true');
      const duration = reduced ? 140 : toInformation || toTitle ? 600 : 360;
      const options: KeyframeAnimationOptions = {
        duration,
        easing: 'cubic-bezier(0.25, 0.55, 0.35, 1)',
        fill: 'both',
      };
      const information = destination as InformationSurface;
      const lateral = next === 'capabilities' ? -3 : 3;
      const outgoingEnd = toInformation ? camera : toTitle
        ? informationDistance(information) : `translate3d(${-lateral}vw, 0, 0) scale(1)`;
      const incomingFrom = toInformation ? informationDistance(information) : toTitle
        ? landscapeStart ?? camera : `translate3d(${lateral}vw, 0, 0) scale(1)`;
      const outFrames: Keyframe[] = reduced
        ? [{ opacity: outgoingStart?.opacity ?? 1 }, { opacity: 0 }]
        : [
            { ...(outgoingStart ?? { transform: REST, opacity: 1 }), transformOrigin: '50% 50%' },
            { transform: outgoingEnd, opacity: 0, transformOrigin: '50% 50%' },
          ];
      const inFrames: Keyframe[] = reduced
        ? [{ opacity: incomingStart?.opacity ?? 0 }, { opacity: 1 }]
        : [
            { ...(incomingStart ?? { transform: incomingFrom, opacity: 0 }), transformOrigin: '50% 50%' },
            { transform: REST, opacity: 1, transformOrigin: '50% 50%' },
          ];
      const token = generation;
      for (const pane of [outgoing, incoming]) {
        layerHints.set(pane, pane.style.willChange);
        pane.style.willChange = reduced ? 'opacity' : 'transform, opacity';
      }
      animations = [
        outgoing.animate(outFrames, options),
        incoming.animate(inFrames, {
          ...options,
          duration: reduced || !toInformation ? duration : 520,
          delay: 0,
        }),
      ];
      if (landscape && !reduced && typeof landscape.animate === 'function') {
        layerHints.set(landscape, landscape.style.willChange);
        landscape.style.willChange = 'transform';
        animations.push(landscape.animate([
          { transform: landscapeStart ?? REST },
          { transform: landscapeTarget },
        ], options));
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
