/** The authenticated state in which the graph has no live region to render. */

import type { GraphSnapshot } from '@exulanica/graph-client';
import { el } from './dom.js';

/**
 * Return the complete empty-world surface, or null when the Atlas has a drawable region.
 *
 * The layout solver deliberately accepts one to five islands. Keeping this decision at the
 * application boundary preserves that invariant and prevents a deletion from being represented
 * by an invented region. Source retention is a separate policy, so the copy does not imply that
 * original files were destroyed when the live graph became empty.
 */
export function buildEmptyWorld(snapshot: GraphSnapshot): HTMLElement | null {
  if (snapshot.islands.length !== 0) return null;

  return el('section', {
    class: 'atlas-empty',
    role: 'status',
    'aria-labelledby': 'atlas-empty-title',
    'data-empty-world': true,
  }, [
    el('p', { class: 'atlas-empty-kicker', text: 'Atlas' }),
    el('h1', { id: 'atlas-empty-title', text: 'No live memories are available' }),
    el('p', {
      class: 'atlas-empty-note',
      text:
        'This view contains no live regions or occurrences. Source files retained by policy ' +
        'remain outside the Atlas until they support a live memory.',
    }),
  ]);
}
