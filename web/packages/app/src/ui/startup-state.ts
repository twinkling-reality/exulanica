import { ApiError } from '@exulanica/graph-client';
import { el } from './dom.js';
import { buildThinkingStatus } from './thinking-status.js';

/**
 * What somebody sees before their world is on the screen, and what they see when it will not come.
 *
 * ONE SENTENCE AND ONE ACTION. A refusal used to stack a wordmark, a headline and a reason that
 * repeated the headline, so the same thing was said three times before anything useful appeared.
 * The sentence says what happened; a second line appears only when it carries something the first
 * one does not, which is the engineering message behind an unrecognised failure.
 *
 * The action wears the sign-in control's pill, because a refusal arriving in the browser's default
 * typeface with a default button reads as different software than the one that just asked to sign
 * somebody in.
 *
 * The words name the product, never the runtime. `frontier-roadmap.md` states it: public surfaces
 * say Exulanica, and Atlas is an internal name for the world runtime that must not appear as if
 * it were a second product.
 */
export function buildStartupState(error?: unknown): HTMLElement {
  if (error === undefined) return buildThinkingStatus('Opening your world');

  const unreachable = (error instanceof ApiError && error.status >= 500)
    || (error instanceof TypeError && /fetch|network|load failed/i.test(error.message))
    || (error instanceof DOMException && ['NetworkError', 'TimeoutError'].includes(error.name));
  const signedOut = error instanceof ApiError && error.isUnauthenticated;
  const statement = signedOut
    ? 'You are not signed in to this world.'
    : unreachable
      ? 'Exulanica is not answering right now.'
      : 'Your world could not be loaded.';
  // Reloading a signed-out session lands on the sign-in screen, so the label says what happens.
  const action = el('button', {
    type: 'button',
    class: 'gate-action',
    text: signedOut ? 'Sign in' : 'Try again',
  });
  action.addEventListener('click', () => window.location.reload());
  // Only what the statement does not already carry: the message behind an unrecognised failure.
  const detail = !signedOut && !unreachable && error instanceof Error && error.message !== ''
    ? [el('p', { class: 'gate-note', text: error.message })]
    : [];
  const panel = el('section', { class: 'gate', role: 'alert' }, [
    el('h1', { text: statement }),
    ...detail,
    action,
  ]);
  return panel;
}
