/** Two clear outcomes: an explorable world and context for personal agents. */

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
        el('h2', { id: 'capability-world', class: 'capability-heading', text: 'Explore your memories in a connected world' }),
        el('p', {
          class: 'reading-copy',
          text: 'Exulanica brings your personal media into an interactive world. It connects memories of the same people, places, and events, and reconstructs places in 3D where your images support it. Your companion helps you find memories and understand their connections.',
        }),
      ]),
      el('section', { class: 'capability-section', 'aria-labelledby': 'capability-agents' }, [
        el('h2', { id: 'capability-agents', class: 'capability-heading', text: 'Power your personal agents with context from your life' }),
        el('p', {
          class: 'reading-copy',
          text: 'Export a World Memory Package that organizes your memories, relationships, and the context you add into a format software can read. It provides the foundation for personal agents to use that history when helping you, with references to the original sources.',
        }),
      ]),
    ]),
  ]);
}
