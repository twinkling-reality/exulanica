import { el } from './dom.js';

export interface InspectionNote {
  readonly subject: string;
  readonly showSubject?: boolean;
  readonly title: string;
  readonly description: string;
  readonly activity: string;
  readonly details: readonly (readonly [string, string])[];
}

/**
 * A plain-language foreground with a keyboard-accessible provenance disclosure.
 *
 * Controls for the subject being shown go in its own action slot through `addAction`, and every
 * `show` or `clear` empties that slot, so a control never outlives the subject it acts on.
 *
 * Under another surface's view of the same subject (the thing card), `setUnderView(true)` leaves
 * only the subject's controls and the record, which then reads "How we know": the view says the rest.
 */
export function createLivingWorldInspector() {
  const root = el('section', {
    class: 'living-world-inspector',
    hidden: true,
    'aria-label': 'Selected world subject',
  });
  const title = el('h3');
  const description = el('p');
  const activity = el('p', {
    class: 'living-world-activity',
    'aria-live': 'polite',
  });
  const fields = el('dl');
  const summary = el('summary', { text: 'Origin and details' });
  const details = el('details', {}, [summary, fields]);
  let shown: InspectionNote | null = null;
  const actions = el('div', { class: 'living-world-actions' });
  root.append(title, description, activity, details, actions);
  return {
    root,
    addAction(node: HTMLElement) {
      actions.append(node);
    },
    /** What `show` was last given, or null while nothing is shown. */
    note(): InspectionNote | null {
      return shown;
    },
    setUnderView(under: boolean) {
      root.toggleAttribute('data-under-view', under);
      summary.textContent = under ? 'How we know' : 'Origin and details';
    },
    show(note: InspectionNote) {
      shown = note;
      actions.replaceChildren();
      root.hidden = false;
      root.dataset['subjectId'] = note.subject;
      title.textContent = note.title;
      description.textContent = note.description;
      activity.textContent = note.activity;
      fields.replaceChildren(
        ...[...(note.showSubject === false ? [] : [['Subject', note.subject]]), ...note.details].flatMap(
          ([label, value]) => [
            el('dt', { text: label! }),
            el('dd', { text: value! }),
          ],
        ),
      );
    },
    clear() {
      shown = null;
      root.hidden = true;
      fields.replaceChildren();
      actions.replaceChildren();
      delete root.dataset['subjectId'];
    },
  };
}
