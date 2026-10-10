import dns from 'node:dns';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { describe, expect, it, vi } from 'vitest';

/**
 * The guard every test file runs under (web/vitest.setup.ts): a reach for a host that is not this
 * machine is refused before any lookup and recorded with the running test's name, and the test is
 * failed by that name when it ends. These tests reach out on purpose and answer for it themselves.
 */

interface Reach { readonly host: string; readonly port: number | null; readonly test: string }
interface NetworkGuard {
  reaches(): readonly Reach[];
  forgive(): readonly Reach[];
  words(reaches: readonly Reach[]): string;
}
const guard = (globalThis as unknown as { __exulanicaNetworkGuard: NetworkGuard }).__exulanicaNetworkGuard;

describe('the network guard', () => {
  it('refuses a reach for another host before any lookup, and names the test that made it', async () => {
    const lookup = vi.spyOn(dns, 'lookup');

    await expect(fetch('https://reached-on-purpose.example.test/list')).rejects.toThrow();

    expect(lookup).not.toHaveBeenCalled();
    lookup.mockRestore();
    const reaches = guard.forgive();
    expect(reaches).toEqual([{
      host: 'reached-on-purpose.example.test', port: 443,
      test: 'the network guard > refuses a reach for another host before any lookup, and names the test that made it',
    }]);
    // What the test would have been failed with, had it not answered for the reach here.
    expect(guard.words(reaches)).toContain('reached-on-purpose.example.test:443, asked for during: the network guard > refuses a reach');
    expect(guard.words(reaches)).toContain('Stub what the code under test asks for');
  });

  it('refuses a plain connection and a request made without fetch as well', async () => {
    const failed = await new Promise<Error>((resolve) => {
      http.get('http://reached-on-purpose.example.test:8080/x').on('error', resolve);
    });

    expect(failed.message).toContain('a test may not reach reached-on-purpose.example.test');
    expect(guard.forgive().map((reach) => `${reach.host}:${reach.port}`)).toEqual(['reached-on-purpose.example.test:8080']);
  });

  it('lets a test talk to a server on this machine', async () => {
    const server = http.createServer((_request, response) => { response.end('here'); });
    await new Promise<void>((resolve) => { server.listen(0, '127.0.0.1', resolve); });
    try {
      const { port } = server.address() as AddressInfo;

      expect(await (await fetch(`http://127.0.0.1:${port}/`)).text()).toBe('here');
      expect(await (await fetch(`http://localhost:${port}/`).catch(() => fetch(`http://127.0.0.1:${port}/`))).text()).toBe('here');

      expect(guard.reaches()).toEqual([]);
    } finally {
      await new Promise<void>((resolve) => { server.close(() => resolve()); });
    }
  });
});
