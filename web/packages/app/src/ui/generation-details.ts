/** A town generator's saved receipt. Current specifications never rewrite its values or labels. */
import type { GeneratedGround } from '../world-entry-api.js';
import { el } from './dom.js';
import './generation-details.css';

export function buildGenerationDetails(options: {
  readonly entry: { readonly title: string; readonly generatedGround?: Pick<GeneratedGround, 'recipeLabel' | 'specification' | 'values'> | null };
  readonly createFrom?: () => void;
}): { readonly root: HTMLDialogElement; show(): void } {
  const receipt = options.entry.generatedGround;
  const rows = el('dl', { class: 'generation-details-values' });
  for (const [key, value] of Object.entries(receipt?.values ?? {})) {
    rows.append(el('div', { 'data-saved-key': key }, [el('dt', { text: key }), el('dd', { text: String(value) })]));
  }
  const close = el('button', { type: 'button', text: 'Close' });
  const root = el('dialog', { class: 'generation-details', 'aria-labelledby': 'generation-details-title' }, [
    el('h2', { id: 'generation-details-title', text: 'Town generation details' }),
    el('p', { text: options.entry.title }),
    el('p', { text: 'These are the recorded inputs that made this world. Viewing them does not change it.' }),
    el('dl', { class: 'generation-details-values' }, [
      el('div', {}, [el('dt', { text: 'Recipe' }), el('dd', { text: receipt?.recipeLabel ?? 'Not recorded' })]),
      el('div', {}, [el('dt', { text: 'Recorded schema' }), el('dd', { text: receipt?.specification ?? 'Not recorded' })]),
    ]),
    ...(receipt?.values == null ? [el('p', { text: 'This receipt did not record individual input values.' })] : [
      el('p', { text: 'Saved keys and values are shown exactly as recorded. Historical field labels and units are not supplied by this read.' }), rows,
    ]),
    el('footer', { class: 'generation-details-actions' }, [close]),
  ]);
  let previous: HTMLElement | null = null;
  const dismiss = (): void => {
    root.close(); root.remove();
    if (previous?.isConnected) previous.focus({ preventScroll: true });
  };
  close.addEventListener('click', dismiss);
  root.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
  if (receipt?.values != null && options.createFrom !== undefined) {
    const createFrom = options.createFrom;
    const create = el('button', { type: 'button', text: 'Create another from these inputs' });
    create.addEventListener('click', () => { dismiss(); createFrom(); });
    root.querySelector('footer')!.prepend(create);
  }
  return { root, show() {
    previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.append(root); root.showModal(); close.focus();
  } };
}
