/** Public signup form. Addresses go directly to the configured hosted form provider. */
import { el } from './dom.js';
import { icon } from './icons.js';
import { action } from './action.js';

/** Replaced in tests so verification never subscribes an address. */
export type WaitlistSubmit = (endpoint: URL, email: string) => Promise<boolean>;

export interface WaitlistOptions {
  readonly endpoint: URL | null;
  readonly submit?: WaitlistSubmit;
}

const postEmail: WaitlistSubmit = async (endpoint, email) => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(endpoint.href, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      // Kit's embed names this field email_address. A field named email can silently fail.
      body: new URLSearchParams({ email_address: email }).toString(),
      signal: controller.signal,
    });
    if (!response.ok) return false;
    const body: unknown = await response.json();
    // An HTTP success alone does not establish that Kit accepted a subscription.
    return typeof body === 'object' && body !== null && 'status' in body
      && (body as { status?: unknown }).status === 'success';
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
};

export function buildWaitlist(options: WaitlistOptions): HTMLElement {
  const submit = options.submit ?? postEmail;
  const { endpoint } = options;
  let sending = false;
  let subscribed = false;

  const status = el('p', {
    class: 'waitlist-status', id: 'waitlist-status', role: 'status', 'aria-live': 'polite',
  });
  const field = el('input', {
    class: 'waitlist-field', id: 'waitlist-email', type: 'email', name: 'email_address',
    required: 'required', autocomplete: 'email', inputmode: 'email', spellcheck: 'false',
    placeholder: 'Your email address', 'aria-describedby': status.id,
  }) as HTMLInputElement;
  const button = el('button', {
    class: 'waitlist-submit', id: 'waitlist-submit', type: 'submit', 'aria-label': 'Join Waitlist',
  }, [icon('arrow')]) as HTMLButtonElement;
  button.disabled = true;

  const form = el('form', { class: 'waitlist-form', id: 'waitlist-form', novalidate: 'novalidate' }, [
    el('label', { class: 'sr-only', for: field.id, text: 'Email address' }),
    el('div', { class: 'waitlist-entry' }, [field]), button,
  ]) as HTMLFormElement;

  if (endpoint === null) {
    form.hidden = true;
    field.disabled = true;
    status.textContent = 'The waitlist is temporarily unavailable. Please check back soon.';
  }

  field.addEventListener('input', () => {
    if (endpoint === null || sending || subscribed) return;
    button.disabled = field.value.trim() === '';
    field.removeAttribute('aria-invalid');
    status.textContent = '';
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (endpoint === null || sending || subscribed) return;
    const email = field.value.trim();
    field.value = email;
    if (email === '' || !field.checkValidity()) {
      status.textContent = 'Enter a valid email address.';
      field.setAttribute('aria-invalid', 'true');
      field.focus();
      return;
    }

    sending = true;
    field.removeAttribute('aria-invalid');
    form.setAttribute('aria-busy', 'true');
    button.disabled = true;
    field.disabled = true;
    status.textContent = 'Joining…';

    // The injected boundary may reject as well as return false. Both must restore a retryable form.
    void Promise.resolve().then(() => submit(endpoint, email)).catch(() => false).then((ok) => {
      sending = false;
      form.removeAttribute('aria-busy');
      if (ok) {
        subscribed = true;
        form.hidden = true;
        status.textContent = 'You’re on the list. We’ll let you know when Exulanica opens.';
        status.classList.add('waitlist-status-done');
        return;
      }
      button.disabled = field.value.trim() === '';
      field.disabled = false;
      status.textContent = 'We couldn’t add you just yet. Please try again.';
      field.focus();
    });
  });

  const returnLink = action('Explore worlds', '/worlds', true);
  returnLink.classList.add('waitlist-return');
  return el('section', {
    id: 'waitlist', class: 'pane pane-information pane-waitlist', tabindex: '-1',
    'aria-labelledby': 'waitlist-title',
  }, [el('div', { class: 'waitlist-gate' }, [
    el('h1', { id: 'waitlist-title', class: 'waitlist-title', text: 'Join Exulanica.' }),
    el('p', { class: 'waitlist-line', text: 'Hear when access opens.' }),
    form, status,
    returnLink,
  ])]);
}
