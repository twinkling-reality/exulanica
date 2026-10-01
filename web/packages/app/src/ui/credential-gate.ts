import { ApiError } from '@exulanica/graph-client';
import { problemSentence } from './words/problems.js';
import type { BrowserAccountState } from '../account-session.js';
import { el } from './dom.js';

/**
 * The gate a person meets before a world: Google sign-in where this server has accounts, and the
 * developer-token entry.
 *
 * GOOGLE IS OFFERED ONLY WHERE THE SERVER SAID ACCOUNTS ARE CONFIGURED. `GET /auth/session`
 * answers 401 for a signed-out browser on a server with accounts, and 503 where it has none; a
 * failed read is treated as the latter. Without accounts the sign-in route answers 503 too, so a
 * button there is a dead end, and a button that cannot work is worse than no button.
 */
export function buildCredentialGate(deps: {
  readonly accounts: Exclude<BrowserAccountState['kind'], 'authenticated'>;
  readonly signIn: () => void;
  readonly enter: (token: string) => Promise<void>;
}): HTMLFormElement {
  const configured = deps.accounts === 'signed-out';
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
  // "Or" only where there is something for it to be the alternative to.
  const operator = el('div', { class: 'credential-operator' }, configured
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
    ...(configured ? [el('p', { class: 'gate-note', text: 'Enter your personal world.' })] : []),
    el('div', { class: 'credential-action' }, [
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
