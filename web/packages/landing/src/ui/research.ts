/** The rules that make model behavior in a world inspectable. */

import { el } from './dom.js';

export function buildResearch(): HTMLElement {
  return el('section', {
    id: 'research',
    class: 'pane pane-information pane-research',
    tabindex: '-1',
    'aria-labelledby': 'research-title',
  }, [
    el('article', { class: 'reading-space' }, [
      el('h1', { id: 'research-title', class: 'sr-only', text: 'Research' }),
      el('section', { class: 'capability-section', 'aria-labelledby': 'research-decisions' }, [
        el('h2', { id: 'research-decisions', class: 'capability-heading', text: 'Models make decisions, the engine checks them' }),
        el('p', { class: 'reading-copy', text: 'A model can propose what a person does. The world validates that action before it happens and records the decision for inspection.' }),
      ]),
      el('section', { class: 'capability-section', 'aria-labelledby': 'research-comparison' }, [
        el('h2', { id: 'research-comparison', class: 'capability-heading', text: 'A fair comparison starts from one world' }),
        el('p', { class: 'reading-copy', text: 'Two model runs use the same saved starting version. Recorded decisions replay without another model call, so the difference has a trace.' }),
      ]),
      el('section', { class: 'capability-section', 'aria-labelledby': 'research-question' }, [
        el('h2', { id: 'research-question', class: 'capability-heading', text: 'The question we are testing' }),
        el('p', { class: 'reading-copy', text: 'Whether people prefer discovering open models through a world rather than a list or leaderboard stays an open question.' }),
      ]),
    ]),
  ]);
}
