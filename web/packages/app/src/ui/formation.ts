/**
 * The forming panel: what is happening to an upload, in words that are true.
 *
 * interaction-model.md 8.1: "Every visual formation state is paired with a factual label naming
 * the real pipeline stage and the real unit of progress. There is no synthetic progress bar and
 * no invented percentage."
 *
 * **This file renders a label and does not compose one.** `formationLabel` in
 * `@exulanica/formation` already decides the stage name, the one factual sentence, the supporting
 * facts, whether elapsed time belongs on screen at all, and what to say when contact was lost.
 * Working those out again from the raw state would be two places for the same rules to drift
 * and one of them untested. Everything below writes out what the label carries, in the order it
 * carries it.
 *
 * **There is no bar and no percentage.** The label's supporting facts already print the pair the
 * pipeline counted. Turning that into a percentage would be turning a count into a fraction of a
 * total that is often unknown, which is the exact invention section 8.1 rules out.
 */

import type { FormationState } from '@exulanica/formation';
import { formationLabel } from '@exulanica/formation';
import { el, replace } from './dom.js';

export interface FormationPanel {
  readonly root: HTMLElement;
  render(state: FormationState | null, batchLabel: string | null): void;
}

export function buildFormation(): FormationPanel {
  const root = el('section', { class: 'forming', 'aria-label': 'Forming', hidden: '' });

  return {
    root,
    render(state, batchLabel) {
      if (state === null || state.phase === 'ready') {
        root.hidden = true;
        replace(root, []);
        return;
      }
      root.hidden = false;

      const label = formationLabel(state);
      const children: HTMLElement[] = [
        el('p', { class: 'forming-stage', text: label.stage }),
        el('h2', { class: 'forming-head', text: batchLabel ?? 'Forming' }),
        // aria-live, because this sentence changes as the pipeline moves and a screen reader user
        // is otherwise told nothing at all: the world it describes is a canvas.
        el('p', { class: 'forming-headline', 'aria-live': 'polite', text: label.headline }),
      ];

      if (label.detail.length > 0) {
        children.push(
          el('ul', { class: 'forming-detail' }, label.detail.map((line) => el('li', { text: line }))),
        );
      }
      if (label.elapsed !== null) {
        // Present only when there is nothing measurable to report. Elapsed time next to a real
        // count is noise, and the label is what decides which of the two this is.
        children.push(el('p', { class: 'forming-elapsed', text: label.elapsed }));
      }
      if (label.note !== null) {
        // The pipeline's own message, in a slot marked as coming from the pipeline. Never merged
        // into the headline, which has to stay derivable from numbers alone.
        children.push(el('p', { class: 'forming-note', text: label.note }));
      }
      replace(root, children);
    },
  };
}
