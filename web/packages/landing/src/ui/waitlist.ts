/**
 * The one place on the public site that asks the visitor for something.
 *
 * It is a form, not a reading surface, so it is set like the application's own access gate rather
 * than in the Purpose and Capabilities voice: one line of plain text, a pill holding the field,
 * and a circular arrow beside it. No visible heading, because the station that brought the visitor
 * here is already called Join the waitlist. The large reading measure belongs to pages somebody
 * reads; this is a page somebody uses. The gate's proportions are reproduced rather than imported,
 * because the two live in different packages, but the values match: the landing palette and the
 * shared light palette carry the same hexes. The page holds no list of its own, so the endpoint is
 * deployment-owned exactly as the Atlas handoff is, and a build without one says the list is not
 * open rather than presenting a control that quietly drops an address.
 *
 * The request is sent as `application/x-www-form-urlencoded`, which is what a hosted form endpoint
 * accepts by default and which the fetch specification counts as a simple request, so the browser
 * sends no CORS preflight that the provider would also have to answer. A provider wanting JSON
 * needs `encode` changed here and nowhere else.
 */

import { el } from './dom.js';

/** Exchanged for a real network call in tests, which must never post anything anywhere. */
export type WaitlistSubmit = (endpoint: URL, email: string) => Promise<boolean>;

export interface WaitlistOptions {
  readonly endpoint: URL | null;
  readonly submit?: WaitlistSubmit;
}

/*
 * The field name the endpoint expects, which is the provider's to decide and not ours.
 *
 * Kit's own HTML embed for this form posts `email_address`; a body keyed `email` is accepted with
 * a 200 and silently subscribes nobody, which is the worst failure available here because the page
 * would thank a visitor it had dropped. Read the provider's embed markup before changing this.
 */
const EMAIL_FIELD = 'email_address';

const encode = (email: string): string =>
  `${EMAIL_FIELD}=${encodeURIComponent(email)}`;

const postEmail: WaitlistSubmit = async (endpoint, email) => {
  try {
    const response = await fetch(endpoint.href, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: encode(email),
    });
    if (!response.ok) return false;
    /*
     * A 200 is not a subscription. Kit answers this endpoint with its own status in the body
     * (`{"status":"success", ...}` was observed against the live form), so a provider that reports
     * a rejected address inside a 200 must not be read as a success and thanked for.
     */
    try {
      const body: unknown = await response.json();
      if (typeof body === 'object' && body !== null && 'status' in body) {
        return (body as { status?: unknown }).status === 'success';
      }
    } catch {
      // A provider that answers 200 with no JSON at all is taken at its word.
    }
    return true;
  } catch {
    // A refused connection, a DNS failure, or a provider that answers without CORS headers all
    // arrive here. None of them tell the visitor anything useful, so all of them read the same.
    return false;
  }
};

export function buildWaitlist(options: WaitlistOptions): HTMLElement {
  const submit = options.submit ?? postEmail;
  const { endpoint } = options;

  let sending = false;

  const status = el('p', {
    class: 'waitlist-status',
    id: 'waitlist-status',
    role: 'status',
    'aria-live': 'polite',
  });

  const field = el('input', {
    class: 'waitlist-field',
    id: 'waitlist-email',
    type: 'email',
    name: 'email',
    required: 'required',
    autocomplete: 'email',
    inputmode: 'email',
    spellcheck: 'false',
    placeholder: 'you@example.com',
    'aria-describedby': status.id,
  }) as HTMLInputElement;

  const button = el(
    'button',
    {
      class: 'waitlist-submit',
      id: 'waitlist-submit',
      type: 'submit',
      'aria-label': 'Join the waitlist',
    },
    [el('span', { 'aria-hidden': 'true', text: '\u2192' })],
  ) as HTMLButtonElement;
  // Nothing to send until something is typed, which is how the access gate holds its own arrow.
  button.disabled = true;

  const form = el('form', { class: 'waitlist-form', id: 'waitlist-form', novalidate: 'novalidate' }, [
    el('label', { class: 'sr-only', for: field.id, text: 'Email address' }),
    el('div', { class: 'waitlist-entry' }, [field]),
    button,
  ]) as HTMLFormElement;

  // An unconfigured build says nothing. A visitor has no use for the reason a control is shut, and
  // a line apologising for the build is a worse thing to read than a quiet field.
  if (endpoint === null) field.disabled = true;

  field.addEventListener('input', () => {
    if (endpoint === null || sending) return;
    button.disabled = field.value.trim() === '';
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (endpoint === null || sending) return;

    const email = field.value.trim();
    // `novalidate` keeps the browser's own bubble out of a page that has its own status line;
    // the constraint itself is still the input's, not a second address grammar invented here.
    if (email === '' || !field.checkValidity()) {
      status.textContent = 'That does not look like an email address.';
      field.focus();
      return;
    }

    sending = true;
    button.disabled = true;
    field.disabled = true;
    status.textContent = 'Sending.';

    void submit(endpoint, email).then((ok) => {
      sending = false;
      if (ok) {
        // The field is spent. Replacing it keeps a second submission from looking available.
        form.hidden = true;
        /*
         * The form auto-confirms, so the address is on the list the moment this resolves and there
         * is nothing left for the visitor to do. This line said "check your email to confirm" while
         * the form still ran double opt-in. Either sentence is false under the other setting, so
         * anyone changing auto-confirm in Kit has to change this with it.
         */
        status.textContent = 'You are on the list. You will hear when Exulanica opens.';
        status.classList.add('waitlist-status-done');
        return;
      }
      button.disabled = field.value.trim() === '';
      field.disabled = false;
      status.textContent = 'That did not send. Please try again in a moment.';
      field.focus();
    });
  });

  return el(
    'section',
    {
      id: 'waitlist',
      class: 'pane pane-information pane-waitlist',
      tabindex: '-1',
      'aria-labelledby': 'waitlist-title',
    },
    [
      el('div', { class: 'waitlist-gate' }, [
        /*
         * The title is for screen readers only. The station the visitor just pressed said "Join
         * the waitlist", and repeating it in bold above the field is the same sentence twice with
         * the second one shouting. One line of plain text carries the whole surface.
         */
        el('h1', { id: 'waitlist-title', class: 'sr-only', text: 'Join the waitlist' }),
        el('p', {
          class: 'waitlist-line',
          text: 'Leave an address and hear when Exulanica opens.',
        }),
        form,
        status,
      ]),
    ],
  );
}
