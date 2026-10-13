/** One production creation flow: offer, setup, start, progress, saved result, open. */
import type { SavedWorldEntry } from '../world-entry-api.js';
import { ApiError } from '@exulanica/graph-client';
import type { WorldDraftOffer, WorldMakingDraft, WorldMakingMemory, WorldMakingStart } from '../world-making-api.js';
import { buildWorldSentence } from '../ui/world-sentence.js';
import { say } from '../ui/copy.js';
import { el, commandAction } from '../ui/dom.js';
import { animateSurface } from '../ui/surface-motion.js';
import '../ui/world-creation.css';

/** The offer is a fixed route, so a router's untyped 404 is a deployment mismatch. */
export function creationOfferFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'http_404') return say('worldSentence.offer.missing');
    if (error.isUnauthenticated) return say('worldSentence.offer.session');
    if (error.status === 403) return say('worldSentence.offer.permission');
    return say('worldSentence.offer.server');
  }
  if (error instanceof SyntaxError || (error instanceof TypeError && error.message.startsWith('The server returned an invalid'))) {
    return say('worldSentence.offer.unreadable');
  }
  return say('worldSentence.offer.connection');
}

export function buildWorldCreation(options: {
  readonly readOffer: () => Promise<WorldDraftOffer>;
  readonly start: (description: string, submission?: WorldMakingStart) => Promise<WorldMakingDraft>;
  readonly memory?: WorldMakingMemory;
  readonly read: (draftId: string) => Promise<WorldMakingDraft>;
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly onClose: () => void;
  readonly setupURL?: string;
  /** Page-session memory, owned by the composition root; never sent until creation starts. */
  readonly descriptionMemory?: { value: string };
}) {
  const root = el('dialog', { class: 'world-creation entry-surface', 'aria-label': 'Create a world' });
  let prior: HTMLElement | null = null;
  let closing = false;
  let generation = 0;
  let description = options.descriptionMemory?.value ?? '';
  const retainDescription = (): void => {
    const field = root.querySelector<HTMLTextAreaElement>('textarea');
    if (field !== null) description = field.value;
    if (options.descriptionMemory !== undefined) options.descriptionMemory.value = description;
  };
  root.addEventListener('input', retainDescription);
  const remove = (): void => { generation += 1; root.close(); root.remove(); };
  const close = (): void => {
    if (closing) return;
    retainDescription();
    closing = true;
    root.inert = true;
    void animateSurface(root, 'leave').then(() => {
      remove(); options.onClose();
      if (prior?.isConnected) prior.focus({ preventScroll: true });
    });
  };
  let returnAction: () => void = close;
  let connectionAction: (() => void) | null = null;
  root.addEventListener('cancel', event => { event.preventDefault(); returnAction(); });
  root.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.key !== 'Enter' || event.isComposing || connectionAction === null) return;
    if (event.target instanceof HTMLAnchorElement || event.target instanceof HTMLButtonElement) return;
    event.preventDefault(); connectionAction();
  });
  const back = (callback: () => void, words = 'Return') => {
    const control = el('button', { type: 'button', class: 'entry-command' }, commandAction('Esc', words));
    control.addEventListener('click', callback);
    return control;
  };
  const configure = (): void => {
    retainDescription();
    returnAction = () => { void load(); };
    connectionAction = () => { void load(); };
    generation += 1;
    const recheck = el('button', { type: 'button', class: 'entry-command' }, commandAction('↵', 'Recheck connection'));
    recheck.addEventListener('click', () => { void load(); });
    root.replaceChildren(el('section', { class: 'world-creation-task' }, [
      el('div', { class: 'world-creation-content world-creation-setup' }, [
        el('h1', { text: 'AI connection' }),
        el('label', { for: 'world-setup-description', text: 'Describe your world' }),
        el('textarea', { id: 'world-setup-description', class: 'world-sentence-input', rows: '2', readonly: true, 'aria-label': 'Your world description' }, [document.createTextNode(description)]),
        el('section', { class: 'world-creation-connection', 'aria-label': 'AI connection' }, [
          el('p', { text: 'AI is disabled on this installation.' }),
          ...(options.setupURL === undefined ? [] : [el('a', { href: options.setupURL, target: '_blank', rel: 'noopener', text: 'Installation instructions' })]),
          el('details', {}, [el('summary', { text: 'Configuration steps' }), el('ol', {}, [
            el('li', { text: 'Configure NEBIUS_API_KEY on the server.' }),
            el('li', { text: 'Allow the provider in EXULANICA_EGRESS_ALLOWLIST.' }),
            el('li', { text: 'Set EXULANICA_SPENDING and the server’s model budget.' }),
            el('li', { text: 'Restart the server with models enabled.' }),
          ])]),
        ]),
      ]),
      el('footer', { class: 'world-creation-commands' }, [back(() => { void load(); }), recheck]),
    ]));
    recheck.focus();
  };
  const load = async (): Promise<void> => {
    retainDescription();
    returnAction = close;
    connectionAction = null;
    const version = ++generation;
    root.replaceChildren(el('p', { class: 'world-creation-loading', role: 'status', text: 'Checking creation…' }));
    try {
      const offer = await options.readOffer();
      if (!root.isConnected || generation !== version || closing) return;
      const panel = buildWorldSentence({
        offer, readOffer: options.readOffer, start: options.start,
        ...(options.memory === undefined ? {} : { memory: options.memory }),
        read: options.read, open: options.open,
        workshop: { onReturn: close, configure },
      });
      root.replaceChildren(panel.root);
      const field = panel.root.querySelector<HTMLTextAreaElement>('textarea');
      if (field !== null && offer.runningDraftId === null && options.memory?.pending == null) field.value = description;
      field?.dispatchEvent(new Event('input'));
      panel.focus();
    } catch (error: unknown) {
      if (!root.isConnected || generation !== version || closing) return;
      const retry = el('button', { type: 'button', class: 'entry-command' }, commandAction('', 'Try again'));
      retry.addEventListener('click', () => { void load(); });
      const field = el('textarea', { id: 'world-creation-description', class: 'world-sentence-input', rows: '3', 'aria-label': 'Describe your world' });
      field.value = description;
      root.replaceChildren(el('section', { class: 'world-creation-task' }, [
        el('div', { class: 'world-creation-content' }, [
          el('h1', { text: 'Create a world' }),
          el('label', { for: field.id, text: 'Describe your world' }), field,
          el('p', { role: 'status', text: creationOfferFailure(error) }),
          ...(error instanceof ApiError ? [el('details', {}, [el('summary', { text: 'Technical details' }), el('p', { text: `Creation offer: HTTP ${error.status}, ${error.code}.` })])] : []),
        ]),
        el('footer', { class: 'world-creation-commands' }, [back(close), retry]),
      ]));
      retry.focus();
    }
  };
  return { root, get isConnected() { return root.isConnected; }, remove, show() {
    prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.append(root); root.showModal();
    void animateSurface(root, 'enter'); void load();
  } };
}
