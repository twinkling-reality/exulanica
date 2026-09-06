/**
 * A quiet, single-paragraph purpose surface.
 *
 * It carries the position as well as the reason, because the position is the future tense one.
 * frontier-roadmap.md records that the four things which would make Exulanica the layer a
 * generative model reads from "are tracked as work, not claimed", and the World Read API only
 * started today. Capabilities is present tense by its own rule, so it cannot hold this. Purpose
 * already says "is being built", and that is the only register in which this is honest.
 */

import { el } from './dom.js';

export function buildPurpose(): HTMLElement {
  return el('section', {
    id: 'purpose',
    class: 'pane pane-information pane-purpose',
    tabindex: '-1',
    'aria-labelledby': 'purpose-title',
  }, [
    el('article', { class: 'reading-space' }, [
      el('h1', { id: 'purpose-title', class: 'sr-only', text: 'Purpose' }),
      el('p', {
        class: 'reading-copy',
        text: 'We record more of our lives than ever, yet much of what makes those moments ours remains scattered: the people who connect them, the places we return to, and how we change over time. Exulanica is being built to bring those fragments into a connected personal world, shaped by the media you keep and the context only you can give. A world you can revisit, add to, and carry forward, preserving the relationships that give individual moments meaning. A world of that kind is what today\'s generative world models do not have. They imagine a convincing place for a session, forget it, and cannot tell you which part of it was ever real. Exulanica is being built to be the record underneath them, one persistent world made from real captures where what was recorded and what was generated stay labelled apart.',
      }),
    ]),
  ]);
}
