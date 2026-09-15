/**
 * The research position, stated as refusals and measurements rather than ambitions.
 *
 * Purpose is the surface written in the "is being built" tense and Capabilities is present tense
 * about the product. Neither can carry this, because what is interesting here is not a capability
 * at all: it is what the project has decided not to do, and what it measured that made it decide.
 * Every paragraph below is a recorded decision or a recorded number, so this page stays true as
 * the product moves. Nothing here describes work that is planned, and nothing here turns an open
 * question into a delivered claim; the third section names the open question directly.
 *
 * Sources, in order: adr/0008-generated-geometry.md, adr/0009-the-ladder-above-rung-3.md with
 * capabilities/scene-reconstruction.md, and reconstruction-findings.md section 4 with the
 * epistemic-status convention in docs/README.md.
 *
 * The page names no document and carries no link, because the reading surfaces are unadorned
 * prose by rule: informational-pages.test.ts refuses `hr`, `strong`, `em` and `a` on all three.
 * Documentation and GitHub already sit in the Resources disclosure the visitor arrived through.
 */

import { el } from './dom.js';

export function buildResearch(): HTMLElement {
  return el(
    'section',
    {
      id: 'research',
      class: 'pane pane-information pane-research',
      tabindex: '-1',
      'aria-labelledby': 'research-title',
    },
    [
      el('article', { class: 'reading-space' }, [
        el('h1', { id: 'research-title', class: 'sr-only', text: 'Research' }),
        el('section', { class: 'capability-section', 'aria-labelledby': 'research-refusal' }, [
          el('h2', {
            id: 'research-refusal',
            class: 'capability-heading',
            text: 'What was recorded and what was generated stay apart',
          }),
          el('p', {
            class: 'reading-copy',
            text: 'A generative model can fill in what a camera never saw. Exulanica does not let it. Invented geometry cannot be a floor you walk on, a distance you measure, or a shape on the map.',
          }),
        ]),
        el('section', { class: 'capability-section', 'aria-labelledby': 'research-ladder' }, [
          el('h2', {
            id: 'research-ladder',
            class: 'capability-heading',
            text: 'A place is admitted at the rung its evidence supports',
          }),
          el('p', {
            class: 'reading-copy',
            text: 'Reconstruction is a ladder, not one result. One photograph yields a partial surface, not a place you can walk around. Overlapping photographs recover where the camera stood, and each scene is published at the rung its evidence supports.',
          }),
        ]),
        el('section', { class: 'capability-section', 'aria-labelledby': 'research-agreement' }, [
          el('h2', {
            id: 'research-agreement',
            class: 'capability-heading',
            text: 'Agreement is not evidence',
          }),
          el('p', {
            class: 'reading-copy',
            text: 'Estimating one scene\'s scale across eight views gave numbers agreeing within three percent while sitting nine to eighteen percent from the truth. Whether an ordinary photo library holds enough overlapping views stays an open question.',
          }),
        ]),
      ]),
    ],
  );
}
