import { ApiError } from '@exulanica/graph-client';
import { el } from './dom.js';

export function buildStartupState(error?: unknown): HTMLElement {
  const failed = error !== undefined;
  const panel = el('section', { class: 'gate', role: failed ? 'alert' : 'status' });
  panel.append(el('h1', { text: failed ? 'Atlas could not open' : 'Opening Atlas' }));
  const reason = error instanceof ApiError && error.isUnauthenticated
    ? 'This session is not authorized. Use an access token configured for this instance.'
    : error instanceof Error ? error.message
      : failed ? 'The library could not load. Please retry.'
        : 'Loading the library, its source photographs, and verified reconstructions…';
  panel.append(el('p', { class: failed ? 'gate-failure' : 'gate-note', text: reason }));
  if (failed) {
    const retry = el('button', { type: 'button', text: 'Retry opening Atlas' });
    retry.addEventListener('click', () => window.location.reload());
    panel.append(retry);
  }
  return panel;
}
