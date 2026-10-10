// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';

/** The same guard under the browser environment, whose `fetch` is its own (web/vitest.setup.ts). */

interface Reach { readonly host: string; readonly port: number | null; readonly test: string }
const guard = (globalThis as unknown as {
  __exulanicaNetworkGuard: { forgive(): readonly Reach[] };
}).__exulanicaNetworkGuard;

describe('the network guard in the browser environment', () => {
  it('refuses the page\'s own fetch for another host and names the test', async () => {
    await expect(window.fetch('https://reached-on-purpose.example.test/list')).rejects.toThrow();

    expect(guard.forgive()).toEqual([{
      host: 'reached-on-purpose.example.test', port: 443,
      test: 'the network guard in the browser environment > refuses the page\'s own fetch for another host and names the test',
    }]);
  });
});
