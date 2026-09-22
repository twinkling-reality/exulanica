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

/**
 * What a person is told about a world that did not open, or null when nothing can be added.
 *
 * NOT THE ENGINEERING MESSAGE. The failure arrives here wrapped: "The saved appearance version
 * could not be opened: Failed to fetch" names two things a person has no model of, and a line
 * that only repeats the heading in longer words says the same thing twice. So the wrapper is
 * unwound to what actually happened, and a failure this does not recognise adds no line at all,
 * leaving the heading and the one action to say everything that is known.
 */
export function worldOpeningReason(error: unknown): string | null {
  for (let cause: unknown = error, depth = 0; depth < 8; depth += 1) {
    if (cause instanceof ApiError) {
      if (cause.isUnauthenticated) return 'This session is no longer signed in.';
      if (cause.status >= 500) return 'The server did not answer.';
      return null;
    }
    if (cause instanceof TypeError && /fetch|network|load failed/iu.test(cause.message)) {
      return 'The server did not answer.';
    }
    if (cause instanceof DOMException && ['NetworkError', 'TimeoutError'].includes(cause.name)) {
      return 'The server did not answer.';
    }
    if (!(cause instanceof Error) || cause.cause === undefined) return null;
    cause = cause.cause;
  }
  return null;
}

/**
 * One world that did not open, said the way every other refusal is said.
 *
 * A LIST OF ONE IS NOT A CHOICE. This used to be the saved-world chooser: a person whose only
 * world failed to open was shown "Choose a saved world" above a list containing their one world,
 * with nothing saying anything had gone wrong, and pressing it failed again for a reason they
 * were reading for the first time. Nothing in the product can give a workspace a second world,
 * so that heading described a situation that does not exist and hid the one that did.
 *
 * It wears the plain `gate`, which is the centred surface the sign-in screen and every refusal
 * already use, rather than the reading column the list needs. One sentence, at most one line
 * under it, and at most one action: a world that cannot be opened at all is given no button,
 * because a button that cannot work is worse than no button.
 */
export function buildWorldOpeningFailure(deps: {
  readonly reason: string | null;
  readonly retry: (() => Promise<void>) | null;
}): HTMLElement {
  const status = el('p', { class: 'gate-note', role: 'status' });
  status.hidden = deps.reason === null;
  if (deps.reason !== null) status.textContent = deps.reason;
  const panel = el('section', { class: 'gate world-opening-failure', role: 'alert' }, [
    el('h1', { text: 'Your world did not open' }),
    status,
  ]);
  if (deps.retry === null) return panel;
  const action = el('button', { type: 'button', class: 'gate-action', text: 'Try again' });
  action.addEventListener('click', () => {
    action.disabled = true;
    status.hidden = false;
    status.textContent = 'Opening your world…';
    void deps.retry!().catch((error: unknown) => {
      action.disabled = false;
      const again = worldOpeningReason(error);
      status.hidden = again === null;
      if (again !== null) status.textContent = again;
    });
  });
  panel.append(action);
  return panel;
}
