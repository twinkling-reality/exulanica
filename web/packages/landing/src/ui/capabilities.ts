/** Two supported paths through a world: make it, then run and compare it. */

import { el } from './dom.js';

export function buildCapabilities(): HTMLElement {
  return el('section', {
    id: 'capabilities',
    class: 'pane pane-information pane-capabilities',
    tabindex: '-1',
    'aria-labelledby': 'capabilities-title',
  }, [
    el('article', { class: 'reading-space' }, [
      el('h1', { id: 'capabilities-title', class: 'sr-only', text: 'Capabilities' }),
      el('section', { class: 'capability-section', 'aria-labelledby': 'capability-world' }, [
        el('h2', { id: 'capability-world', class: 'capability-heading', text: 'Build a world' }),
        el('p', {
          class: 'reading-copy',
          text: 'Start with a saved place or a town recipe. Add supported objects, shape its appearance, and inspect what exists and where it came from.',
        }),
      ]),
      el('section', { class: 'capability-section', 'aria-labelledby': 'capability-agents' }, [
        el('h2', { id: 'capability-agents', class: 'capability-heading', text: 'Run and compare models' }),
        el('p', {
          class: 'reading-copy',
          text: 'Choose an available open model for a person or group. Exulanica validates and records its decisions. Paired runs begin from the same saved version, so you can inspect what each model did differently.',
        }),
      ]),
    ]),
  ]);
}
