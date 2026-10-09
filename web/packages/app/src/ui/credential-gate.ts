import { ApiError } from '@exulanica/graph-client';
import { problemSentence } from './words/problems.js';
import type { BrowserAccountState, SignInModes } from '../account-session.js';
import { el } from './dom.js';

/** Why a guest was not let in, in words, by the guest route's codes. */
export function guestRefusalWords(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Exulanica could not be reached. Check the connection and try again.';
  switch (error.code) {
    case 'guest_entry_code_wrong': return 'That code does not open this server. Check it and try again.';
    case 'guest_entries_exhausted': {
      const seconds = error.extensions['retry_after_seconds'];
      return `This server has let in all the guests it can today. Try again ${typeof seconds === 'number' ? laterWords(seconds) : 'tomorrow'}.`;
    }
    case 'guest_entry_off': return 'This server does not let guests in.';
    case 'guest_entry_unavailable': return 'This server could not let a guest in just now. Try again in a moment.';
    case 'origin_not_permitted': return 'This page is not served by this server, so it cannot let you in. Open the server’s own address.';
    default: return problemSentence(error, {}, { happened: 'You could not be let in.', next: 'Try again in a moment.' });
  }
}

/** When to try again, in words, from a count of seconds. */
function laterWords(seconds: number): string {
  if (seconds < 90) return 'in a minute';
  if (seconds < 3600) return `in about ${Math.round(seconds / 60)} minutes`;
  const hours = Math.round(seconds / 3600);
  return hours === 1 ? 'in about an hour' : `in about ${hours} hours`;
}

/**
 * The gate a person meets before a world: an entry code where this server lets guests in, Google
 * sign-in where it has accounts, and the developer-token entry.
 *
 * WHAT IS OFFERED IS WHAT THE SERVER STATES. A signed-out answer may state its sign-in modes
 * (`sign_in`: Google on or off, a guest entry asking a code, taking none, or off); where it does,
 * the gate offers exactly those. Where it states none, the rule below holds.
 *
 * GOOGLE IS OFFERED ONLY WHERE THE SERVER SAID ACCOUNTS ARE CONFIGURED. `GET /auth/session`
 * answers 401 for a signed-out browser on a server with accounts, and 503 where it has none; a
 * failed read is treated as the latter. Without accounts the sign-in route answers 503 too, so a
 * button there is a dead end, and a button that cannot work is worse than no button.
 */
export function buildCredentialGate(deps: {
  readonly accounts: Exclude<BrowserAccountState['kind'], 'authenticated'>;
  /** The sign-in modes the server stated, or null where it stated none. */
  readonly modes?: SignInModes | null;
  readonly signIn: () => void;
  readonly enter: (token: string) => Promise<void>;
  /** Enter as a guest, with the code where one is asked; resolves once the session is set. */
  readonly enterAsGuest?: (code: string | null) => Promise<void>;
}): HTMLFormElement {
  const modes = deps.modes ?? null;
  const configured = modes === null ? deps.accounts === 'signed-out' : modes.google;
  const guestMode = modes === null || deps.enterAsGuest === undefined ? 'off' : modes.guest;
  const form = el('form', { class: 'gate credential-gate' });
  const input = el('input', {
    type: 'password',
    autocomplete: 'off',
    'aria-label': 'Access token',
    placeholder: 'Paste access token',
  });
  const failure = el('p', { class: 'gate-failure' });
  failure.hidden = true;
  const submit = el('button', {
    type: 'submit',
    class: 'credential-submit',
    'aria-label': 'Enter Exulanica',
    disabled: true,
  }, [el('span', { 'aria-hidden': 'true', text: '→' })]);
  input.addEventListener('input', () => {
    submit.disabled = input.value.trim().length === 0;
  });

  const controls = el('div', { class: 'credential-controls' }, [
    el('div', { class: 'credential-entry' }, [input]), submit,
  ]);
  // A guest comes in with the code they were given (or none, where the server asks none).
  const guestFailure = el('p', { class: 'gate-failure', role: 'alert' });
  guestFailure.hidden = true;
  const code = el('input', {
    type: 'text', class: 'guest-code', autocomplete: 'off', spellcheck: 'false',
    'aria-label': 'Entry code', placeholder: 'Entry code',
  }) as HTMLInputElement;
  const guestEnter = el('button', {
    type: 'button', class: 'guest-enter', 'data-action': 'gate.guest',
    text: guestMode === 'open' ? 'Enter as a guest' : 'Enter', disabled: guestMode === 'code',
  }) as HTMLButtonElement;
  code.addEventListener('input', () => { guestEnter.disabled = code.value.trim().length === 0; });
  const enterGuest = (): void => {
    if (guestEnter.disabled || deps.enterAsGuest === undefined) return;
    guestEnter.disabled = true;
    guestFailure.hidden = true;
    void deps.enterAsGuest(guestMode === 'code' ? code.value.trim() : null).catch((error: unknown) => {
      guestFailure.hidden = false;
      guestFailure.textContent = guestRefusalWords(error);
      guestEnter.disabled = guestMode === 'code' && code.value.trim().length === 0;
    });
  };
  guestEnter.addEventListener('click', enterGuest);
  code.addEventListener('keydown', (event) => {
    // Enter here is the guest's, never the developer token's submit.
    if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); enterGuest(); }
  });
  const guest = guestMode === 'off' ? null : el('div', { class: 'guest-entry' }, [
    el('div', { class: 'guest-entry-row' }, guestMode === 'code' ? [code, guestEnter] : [guestEnter]),
    guestFailure,
  ]);

  // "Or" only where there is something for it to be the alternative to.
  const operator = el('div', { class: 'credential-operator' }, configured || guest !== null
    ? [
      el('div', { class: 'credential-divider', role: 'separator' }, [
        el('span', { text: 'or, for developers' }),
      ]),
      controls,
    ]
    : [controls]);

  const google = el('button', { type: 'button', class: 'account-sign-in' }, [
    el('span', { class: 'account-sign-in-label', text: 'Continue with Google' }),
    el('span', { class: 'account-sign-in-arrow', 'aria-hidden': 'true', text: '→' }),
  ]);
  google.addEventListener('click', () => deps.signIn());

  form.append(
    el('p', { class: 'gate-wordmark', text: 'Exulanica' }),
    ...(guest !== null
      ? [el('p', { class: 'gate-note', text: guestMode === 'code' ? 'Enter with the code you were given.' : 'Come in as a guest.' })]
      : configured ? [el('p', { class: 'gate-note', text: 'Enter your personal world.' })] : []),
    el('div', { class: 'credential-action' }, [
      ...(guest !== null ? [guest] : []),
      ...(configured ? [google] : []),
      operator,
      failure,
    ]),
  );
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const token = input.value.trim();
    if (token.length === 0) return;
    failure.hidden = true;
    void deps.enter(token).catch((error: unknown) => {
      failure.hidden = false;
      failure.textContent =
        error instanceof ApiError && error.isUnauthenticated
          ? 'That token is not accepted here. Check it, or ask the person who runs this installation for one.'
          : problemSentence(error, {}, {
            happened: 'Exulanica could not be opened with that token.',
            next: 'Try again in a moment.',
          });
    });
  });
  return form;
}
