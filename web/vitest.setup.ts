/**
 * No test reaches a host that is not this machine.
 *
 * Every connection a test's process opens, whichever client opens it (Node's `fetch`, the browser
 * environment's own, `http`, a socket), goes through `net.Socket.prototype.connect`. Here that
 * refuses any host but a local one before a name is looked up, records the host with the name of
 * the test running then, and the test is failed by that name when it ends. A reach that arrives
 * after the last test fails the file.
 *
 * A test that stubs what it asks for never gets here. One that does not used to pass anyway: the
 * lookup of a made-up host failed after a wait that depended on the machine, and a read that was
 * meant to be stubbed went unnoticed until a busy machine made it slow.
 */

import net from 'node:net';
import { afterAll, afterEach, expect } from 'vitest';

interface Reach {
  readonly host: string;
  readonly port: number | null;
  /** The test running when the connection was asked for, as the runner names it. */
  readonly test: string;
}

interface NetworkGuard {
  /** The reaches recorded and not yet answered for. */
  reaches(): readonly Reach[];
  /** Take the recorded reaches, so the test that made them on purpose is not failed for them. */
  forgive(): readonly Reach[];
  /** What a failed test is told. */
  words(reaches: readonly Reach[]): string;
}

const OUTSIDE_A_TEST = '(outside a test)';
const recorded: Reach[] = [];

function local(host: string): boolean {
  const name = host.toLowerCase().replace(/^\[|\]$/g, '');
  return name === 'localhost' || name.endsWith('.localhost') || name === '::1' || name === '0.0.0.0'
    || name === '::' || /^127(\.\d{1,3}){3}$/.test(name) || name === '::ffff:127.0.0.1';
}

/** The host and port a `connect` call names, however it was called; null host for a local path. */
function asked(args: readonly unknown[]): { host: string | null; port: number | null } {
  // `net.connect` hands its arguments on as one normalised array, options first.
  const first = Array.isArray(args[0]) ? (args[0] as unknown[])[0] : args[0];
  if (typeof first === 'string') return { host: null, port: null };
  if (typeof first === 'number') return { host: typeof args[1] === 'string' ? args[1] : 'localhost', port: first };
  const options = (first ?? {}) as { host?: unknown; port?: unknown; path?: unknown };
  if (typeof options.path === 'string') return { host: null, port: null };
  return {
    host: typeof options.host === 'string' && options.host.length > 0 ? options.host : 'localhost',
    port: typeof options.port === 'number' ? options.port : Number(options.port) || null,
  };
}

function words(reaches: readonly Reach[]): string {
  const lines = reaches.map((reach) => `  ${reach.host}${reach.port === null ? '' : `:${reach.port}`}, asked for during: ${reach.test}`);
  return [
    'A test reached for a host that is not this machine. Stub what the code under test asks for;',
    'the connection was refused before any lookup (web/vitest.setup.ts):',
    ...lines,
  ].join('\n');
}

const guard: NetworkGuard = {
  reaches: () => [...recorded],
  forgive: () => recorded.splice(0),
  words,
};

const KEY = '__exulanicaNetworkGuard';
const held = globalThis as unknown as Record<string, NetworkGuard | undefined>;

if (held[KEY] === undefined) {
  held[KEY] = guard;
  const connect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function guarded(this: net.Socket, ...args: unknown[]): net.Socket {
    const { host, port } = asked(args);
    if (host === null || local(host)) return (connect as (...a: unknown[]) => net.Socket).apply(this, args);
    recorded.push({ host, port, test: expect.getState().currentTestName ?? OUTSIDE_A_TEST });
    const refusal = Object.assign(new Error(`a test may not reach ${host}: it is not this machine`), { code: 'ECONNREFUSED' });
    process.nextTick(() => this.destroy(refusal));
    return this;
  } as typeof net.Socket.prototype.connect;
}

afterEach(() => {
  const mine = held[KEY]!.forgive();
  if (mine.length > 0) throw new Error(held[KEY]!.words(mine));
});

afterAll(() => {
  const late = held[KEY]!.forgive();
  if (late.length > 0) throw new Error(held[KEY]!.words(late));
});
