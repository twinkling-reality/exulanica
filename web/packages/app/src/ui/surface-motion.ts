import { navigationMotion, NAVIGATION_MOTION } from '@exulanica/presentation/navigation-motion';
import { replace } from './dom.js';

const running = new WeakMap<HTMLElement, Animation>();

/** Personal comfort settings take precedence over the operating system. */
export function surfaceMotionReduced(): boolean {
  const preference = document.documentElement.dataset['motion'];
  return preference === 'reduced' || (preference !== 'full' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

/** Only the latest animation may complete a surface change. Focus is managed by its owner. */
export async function animateSurface(surface: HTMLElement, phase: 'enter' | 'leave'): Promise<boolean> {
  surface.style.setProperty('--view-input-duration', `${NAVIGATION_MOTION.inputShape}ms`);
  surface.style.setProperty('--view-easing', NAVIGATION_MOTION.easing);
  surface.style.setProperty('--view-leave-duration', `${NAVIGATION_MOTION.leave}ms`);
  running.get(surface)?.cancel();
  running.delete(surface);
  const options = navigationMotion(surfaceMotionReduced(), phase === 'enter' ? 'page' : 'leave');
  if (options.duration === 0 || typeof surface.animate !== 'function') return true;
  const animation = surface.animate(
    phase === 'enter' ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 1 }, { opacity: 0 }],
    { ...options, fill: 'both' },
  );
  running.set(surface, animation);
  try {
    await animation.finished;
    if (running.get(surface) !== animation) return false;
    running.delete(surface);
    animation.cancel();
    return true;
  } catch {
    if (running.get(surface) === animation) running.delete(surface);
    return false;
  }
}

/** Navigation swaps content immediately; incoming content fades without delaying focus or reads. */
export function replaceSurface(surface: HTMLElement, children: readonly (Node | string)[]): void {
  replace(surface, children);
  void animateSurface(surface, 'enter');
}
