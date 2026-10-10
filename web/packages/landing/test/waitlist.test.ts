// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';

import { resolveWaitlistDestination } from '../src/waitlist-destination.js';
import { buildWaitlist } from '../src/ui/waitlist.js';

const HERE = 'https://exulanica.example/';

describe('the waitlist endpoint', () => {
  it('stays closed until a deployment names one', () => {
    for (const configured of [undefined, '', '   ']) {
      expect(
        resolveWaitlistDestination({ configured, development: false, landingHref: HERE }),
      ).toBeNull();
    }
  });

  it('refuses an endpoint that would put an address on the wire in clear text', () => {
    const http = resolveWaitlistDestination({
      configured: 'http://forms.example/subscribe',
      development: false,
      landingHref: HERE,
    });
    expect(http).toBeNull();

    // Development keeps one exception, and only for a host that is the developer's own machine.
    expect(
      resolveWaitlistDestination({
        configured: 'http://forms.example/subscribe',
        development: true,
        landingHref: HERE,
      }),
    ).toBeNull();
    expect(
      resolveWaitlistDestination({
        configured: 'http://127.0.0.1:9999/subscribe',
        development: true,
        landingHref: HERE,
      })?.href,
    ).toBe('http://127.0.0.1:9999/subscribe');
    expect(
      resolveWaitlistDestination({
        configured: 'http://127.0.0.1:9999/subscribe',
        development: false,
        landingHref: HERE,
      }),
    ).toBeNull();
  });

  it('accepts https, absolute or relative to the landing page, and nothing exotic', () => {
    expect(
      resolveWaitlistDestination({
        configured: 'https://forms.example/f/abc',
        development: false,
        landingHref: HERE,
      })?.href,
    ).toBe('https://forms.example/f/abc');
    expect(
      resolveWaitlistDestination({ configured: '/subscribe', development: false, landingHref: HERE })
        ?.href,
    ).toBe('https://exulanica.example/subscribe');
    for (const hostile of ['javascript:alert(1)', 'mailto:a@b.c', 'ftp://forms.example/f']) {
      expect(
        resolveWaitlistDestination({
          configured: hostile,
          development: false,
          landingHref: HERE,
        }),
      ).toBeNull();
    }

    /*
     * A bare token is a relative path, not a malformed URL, so it resolves against the landing
     * page and stays https. That is the same reading the Atlas handoff gives it, and it is the
     * behaviour a deployment configuring `subscribe` on its own origin depends on.
     */
    expect(
      resolveWaitlistDestination({
        configured: 'subscribe',
        development: false,
        landingHref: HERE,
      })?.href,
    ).toBe('https://exulanica.example/subscribe');
  });
});

const field = (page: HTMLElement) => page.querySelector<HTMLInputElement>('#waitlist-email')!;
const button = (page: HTMLElement) => page.querySelector<HTMLButtonElement>('#waitlist-submit')!;
const status = (page: HTMLElement) => page.querySelector<HTMLElement>('#waitlist-status')!;
const send = (page: HTMLElement): void => {
  page
    .querySelector<HTMLFormElement>('#waitlist-form')!
    .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
};

describe('the waitlist surface', () => {
  it('keeps the page accessible and free of the dashes the reading surfaces refuse', () => {
    const page = buildWaitlist({ endpoint: null });
    expect(page.id).toBe('waitlist');
    const heading = page.querySelector('h1');
    expect(heading?.textContent).toBe('Join Exulanica.');
    expect(heading?.classList.contains('sr-only')).toBe(false);
    expect(page.getAttribute('aria-labelledby')).toBe(heading?.id);
    expect(page.querySelectorAll('h2')).toHaveLength(0);
    expect(page.querySelector('.reading-copy')).toBeNull();
    expect(page.querySelectorAll('.waitlist-line')).toHaveLength(1);
    // Written as escapes rather than as the characters, so the repository itself carries
    // no em dash or en dash while still forbidding them on the page.
    expect(page.textContent).not.toMatch(/[\u2014\u2013]/);
    // The field is nameless to the eye and named to a screen reader.
    expect(page.querySelector(`label[for="${field(page).id}"]`)?.textContent).toBe('Email address');
    expect(field(page).getAttribute('aria-describedby')).toBe(status(page).id);
  });

  it('explains unavailability and hides the form when no endpoint is configured', () => {
    const submit = vi.fn();
    const page = buildWaitlist({ endpoint: null, submit });
    expect(field(page).disabled).toBe(true);
    expect(button(page).disabled).toBe(true);
    expect(status(page).textContent).toContain('temporarily unavailable');
    expect(page.querySelector<HTMLFormElement>('#waitlist-form')!.hidden).toBe(true);
    expect(page.textContent).not.toMatch(/build/i);

    field(page).value = 'someone@example.com';
    send(page);
    expect(submit).not.toHaveBeenCalled();
  });

  it('refuses an address the field itself calls invalid, without posting it', async () => {
    const submit = vi.fn(async () => true);
    const page = buildWaitlist({ endpoint: new URL('https://forms.example/f'), submit });
    for (const bad of ['', '   ', 'not-an-address']) {
      field(page).value = bad;
      send(page);
      await Promise.resolve();
      expect(submit).not.toHaveBeenCalled();
      expect(status(page).textContent).not.toBe('');
    }
  });

  it('sends a valid address once and then retires the field', async () => {
    const endpoint = new URL('https://forms.example/f');
    const submit = vi.fn(async () => true);
    const page = buildWaitlist({ endpoint, submit });

    field(page).value = '  someone@example.com  ';
    send(page);
    await vi.waitFor(() => expect(submit).toHaveBeenCalledWith(endpoint, 'someone@example.com'));
    // While the request is out the control is shut, so a second press cannot post twice.
    expect(button(page).disabled).toBe(true);
    send(page);
    expect(submit).toHaveBeenCalledTimes(1);

    // The Kit form auto-confirms, so the address is live on the list when this resolves and the
    // surface must not send the visitor off to an email that asks nothing of them.
    await vi.waitFor(() => expect(status(page).textContent).toContain('on the list'));
    expect(status(page).textContent).not.toMatch(/confirm/i);
    expect(page.querySelector<HTMLFormElement>('#waitlist-form')!.hidden).toBe(true);
    send(page);
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('gives the field back when the endpoint refuses, so the address is not lost', async () => {
    const submit = vi.fn(async () => false);
    const page = buildWaitlist({ endpoint: new URL('https://forms.example/f'), submit });

    field(page).value = 'someone@example.com';
    send(page);
    await vi.waitFor(() => expect(status(page).textContent).toContain('Please try again'));
    expect(button(page).disabled).toBe(false);
    expect(field(page).disabled).toBe(false);
    expect(page.querySelector<HTMLFormElement>('#waitlist-form')!.hidden).toBe(false);
    expect(field(page).value).toBe('someone@example.com');
  });
});


afterEach(() => vi.unstubAllGlobals());

describe('the provider boundary', () => {
  it.each([
    { ok: true, json: async () => ({ status: 'success' }), accepted: true },
    { ok: true, json: async () => ({ status: 'error' }), accepted: false },
    { ok: true, json: async () => ({}), accepted: false },
    { ok: true, json: async () => { throw new Error('HTML response'); }, accepted: false },
    { ok: false, json: async () => ({ status: 'success' }), accepted: false },
  ])('requires an explicit provider success: $accepted', async ({ ok, json, accepted }) => {
    const fetch = vi.fn(async () => ({ ok, json }));
    vi.stubGlobal('fetch', fetch);
    const page = buildWaitlist({ endpoint: new URL('https://forms.example/f') });
    field(page).value = 'someone+signup@example.com';
    send(page);
    await vi.waitFor(() => expect(status(page).textContent).not.toBe('Joining…'));
    expect(fetch).toHaveBeenCalledWith('https://forms.example/f', expect.objectContaining({
      method: 'POST', body: 'email_address=someone%2Bsignup%40example.com',
    }));
    expect(page.querySelector<HTMLFormElement>('#waitlist-form')!.hidden).toBe(accepted);
    if (!accepted) expect(field(page).disabled).toBe(false);
  });

  it('restores the form when a request rejects and permits a retry', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(true);
    const page = buildWaitlist({ endpoint: new URL('https://forms.example/f'), submit });
    field(page).value = 'someone@example.com';
    send(page);
    await vi.waitFor(() => expect(status(page).textContent).toContain('Please try again'));
    expect(field(page).value).toBe('someone@example.com');
    expect(button(page).disabled).toBe(false);
    send(page);
    await vi.waitFor(() => expect(status(page).textContent).toContain('on the list'));
    expect(submit).toHaveBeenCalledTimes(2);
  });
});
