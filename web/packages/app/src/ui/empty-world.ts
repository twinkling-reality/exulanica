/** The authenticated state in which the graph has no live region to render. */

import type { GraphSnapshot } from '@exulanica/graph-client';
import { el } from './dom.js';

/**
 * Return the complete empty-world surface, or null when there is a region to draw.
 *
 * The layout solver deliberately accepts one to five islands. Keeping this decision at the
 * application boundary preserves that invariant and prevents a deletion from being represented
 * by an invented region.
 *
 * ONE SENTENCE, ON THE SAME SURFACE AS EVERY OTHER FULL-PAGE STATE. It carried a wordmark and a
 * paragraph about where photographs are held, which explained storage policy to somebody who may
 * have uploaded nothing, directly above the photo panel that `main.ts` mounts underneath it. What
 * that paragraph was protecting, that nothing implies the originals were destroyed, is protected
 * better by saying nothing about it at all.
 *
 * It also had a surface of its own: a gradient where the others are flat, its own padding, and a
 * heading capped at 18 characters so it wrapped where theirs do not. It now carries `gate`, so the
 * sign-in screen, a refusal and this share one look and cannot drift apart again.
 *
 * WHAT IT SAYS IS WHAT IS TRUE OF IT. `main.ts` sends every startup case with no open world to the
 * saved world surface before it mounts, so this is reached only under `?preview=1` and when a
 * world that was already mounted empties during a session. "There are no memories here yet"
 * described neither of those, and neither did a paragraph about where photographs are held.
 */
export function buildEmptyWorld(snapshot: GraphSnapshot): HTMLElement | null {
  if (snapshot.islands.length !== 0) return null;

  return el('section', {
    class: 'gate atlas-empty',
    role: 'status',
    'aria-labelledby': 'atlas-empty-title',
    'data-empty-world': true,
  }, [
    el('h1', { id: 'atlas-empty-title', text: 'Your world did not open' }),
  ]);
}
