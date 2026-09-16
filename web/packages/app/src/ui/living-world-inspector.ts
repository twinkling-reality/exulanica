import { el } from './dom.js';

export interface InspectionNote {
  readonly subject: string;
  readonly title: string;
  readonly description: string;
  readonly activity: string;
  readonly details: readonly (readonly [string, string])[];
}

/** A plain-language foreground with a keyboard-accessible provenance disclosure. */
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
  const details = el('details', {}, [
    el('summary', { text: 'Origin and details' }),
    fields,
  ]);
  root.append(title, description, activity, details);
  return {
    root,
    show(note: InspectionNote) {
      root.querySelectorAll('button').forEach((button) => button.remove());
      root.hidden = false;
      root.dataset['subjectId'] = note.subject;
      title.textContent = note.title;
      description.textContent = note.description;
      activity.textContent = note.activity;
      fields.replaceChildren(
        ...[['Subject', note.subject], ...note.details].flatMap(
          ([label, value]) => [
            el('dt', { text: label! }),
            el('dd', { text: value! }),
          ],
        ),
      );
    },
    clear() {
      root.hidden = true;
      fields.replaceChildren();
      delete root.dataset['subjectId'];
    },
  };
}
