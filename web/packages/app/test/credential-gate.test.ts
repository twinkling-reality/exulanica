// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { readBrowserAccount } from '../src/account-session.js';
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
