// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { enterAsGuest, readBrowserAccount } from '../src/account-session.js';
import { buildCredentialGate } from '../src/ui/credential-gate.js';

/** The gate the page builds from what `GET /api/auth/session` answered. */
async function gateAfter(response: Response) {
  const account = await readBrowserAccount(async () => response);
  if (account.kind === 'authenticated') throw new Error('a signed-in session meets no gate');
  const signIn = vi.fn();
  const gate = buildCredentialGate({ accounts: account.kind, signIn, enter: vi.fn(async () => undefined) });
  return { gate, signIn };
}

describe('the credential gate', () => {
  it('offers Google sign-in where the server has accounts and this browser is signed out', async () => {
    const { gate, signIn } = await gateAfter(new Response(JSON.stringify({
      code: 'authentication_failed', detail: 'Sign-in or session was not accepted',
    }), { status: 401 }));
    const google = gate.querySelector<HTMLButtonElement>('button.account-sign-in');
    expect(google).not.toBeNull();
    expect(google?.textContent).toContain('Continue with Google');
    expect(google?.disabled).toBe(false);
    google?.click();
    expect(signIn).toHaveBeenCalledTimes(1);
    expect(gate.querySelector('[role="separator"]')?.textContent).toBe('or, for developers');
    expect(gate.querySelector('input[aria-label="Access token"]')).not.toBeNull();
  });

  it('offers no Google sign-in where the server has no accounts, only the token entry', async () => {
    const { gate } = await gateAfter(new Response(JSON.stringify({
      code: 'account_unavailable', detail: 'Google sign-in is not configured or unavailable',
    }), { status: 503 }));
    expect(gate.querySelector('button.account-sign-in')).toBeNull();
    expect(gate.textContent).not.toContain('Google');
    // No "or" with nothing before it.
    expect(gate.querySelector('[role="separator"]')).toBeNull();
    expect(gate.querySelector('input[aria-label="Access token"]')).not.toBeNull();
    expect(gate.querySelector('button[aria-label="Enter Exulanica"]')).not.toBeNull();
  });
});

describe('a guest coming in with a code', () => {
  /** The gate after a signed-out answer stating guests come in with a code and Google is off. */
  async function guestGate(enter: (code: string | null) => Promise<void>, guest: 'code' | 'open' = 'code') {
    const account = await readBrowserAccount(async () => new Response(JSON.stringify({
      code: 'authentication_failed', detail: 'Sign-in or session was not accepted',
      sign_in: { google: false, guest },
    }), { status: 401 }));
    if (account.kind === 'authenticated') throw new Error('a signed-in session meets no gate');
    const enterAsGuest = vi.fn(enter);
    const gate = buildCredentialGate({
      accounts: account.kind, modes: account.signIn ?? null, signIn: vi.fn(), enter: vi.fn(async () => undefined), enterAsGuest,
    });
    document.body.replaceChildren(gate);
    const code = gate.querySelector<HTMLInputElement>('input[aria-label="Entry code"]');
    const button = gate.querySelector<HTMLButtonElement>('[data-action="gate.guest"]')!;
    return { gate, code, button, enterAsGuest };
  }
  const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
  const refusedWith = async (error: ApiError): Promise<string> => {
    const { gate, code, button } = await guestGate(async () => { throw error; });
    code!.value = 'judge-code';
    code!.dispatchEvent(new Event('input'));
    button.click();
    await settle();
    return gate.querySelector('.guest-entry .gate-failure')?.textContent ?? '';
  };

  it('offers the code entry the server states, first, with no Google where it is off, and sends the code', async () => {
    const { gate, code, button, enterAsGuest } = await guestGate(async () => undefined);
    expect(gate.querySelector('button.account-sign-in')).toBeNull();
    expect(gate.querySelector('.gate-note')?.textContent).toBe('Enter with the code you were given.');
    expect(button.disabled).toBe(true);
    code!.value = '  judge-code ';
    code!.dispatchEvent(new Event('input'));
    expect(button.disabled).toBe(false);
    // Enter in the field is the guest's, not the developer token's submit.
    code!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }));
    expect(enterAsGuest).toHaveBeenCalledWith('judge-code');
    expect(gate.querySelector('input[aria-label="Access token"]')).not.toBeNull();
  });

  it('says a wrong code, a full day, guests off and a server that could not answer, each in words', async () => {
    expect(await refusedWith(new ApiError(403, 'guest_entry_code_wrong', 'that code does not open this server')))
      .toBe('That code does not open this server. Check it and try again.');
    expect(await refusedWith(new ApiError(429, 'guest_entries_exhausted', 'this server has admitted all its guests for today', { retry_after_seconds: 5 * 3600 + 120 })))
      .toBe('This server has let in all the guests it can today. Try again in about 5 hours.');
    expect(await refusedWith(new ApiError(503, 'guest_entry_off', 'this server does not admit guests')))
      .toBe('This server does not let guests in.');
    expect(await refusedWith(new ApiError(503, 'guest_entry_unavailable', 'try again shortly')))
      .toBe('This server could not let a guest in just now. Try again in a moment.');
  });

  it('enters with no code where the server asks none, and posts the code as the route takes it', async () => {
    const { code, button, enterAsGuest: entered } = await guestGate(async () => undefined, 'open');
    expect(code).toBeNull();
    expect(button.textContent).toBe('Enter as a guest');
    button.click();
    expect(entered).toHaveBeenCalledWith(null);
    const fetcher = vi.fn(async () => new Response('{}', { status: 201 }));
    await enterAsGuest('judge-code', fetcher as unknown as typeof fetch);
    expect(fetcher).toHaveBeenCalledWith('/api/auth/guest', expect.objectContaining({
      method: 'POST', credentials: 'include', body: JSON.stringify({ code: 'judge-code' }),
    }));
  });
});
