// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { parsePieceRequests, watchPieceRequests, type PieceRequestsRead } from '../src/composition/piece-requests.js';

/*
 * New pieces after the person's yes (GEN's G4): the world's piece requests are read every 15 s while
 * any the plan made waits; a held line says what is being made and whether the piece maker runs; each
 * outcome is said once, applied with Take back. Shapes as GEN's routes answer them
 * (exulanica/api/routes/piece_requests.py, exulanica/generation/store.py document()).
 */
const request = (id: string, label: string, state: string, lookStep: Record<string, unknown> | null = null) => ({
  piece_request_id: id, world_id: 'world:test', kind: { key: label, version: 1, sha256: 'a'.repeat(64), label },
  state, look_step: lookStep,
});
const answer = (requests: unknown[], session: Record<string, unknown> = { state: 'running', until: '2026-10-09T23:30:00Z', detail: 'x' }) =>
  parsePieceRequests({ piece_requests: requests, session });

function watcher(reads: PieceRequestsRead[]) {
  const queue = [...reads];
  const client = {
    list: vi.fn(async () => (queue.length > 1 ? queue.shift()! : queue[0]!)),
    takeBack: vi.fn(async () => undefined),
  };
  const hold = vi.fn();
  const toasts = { show: vi.fn(() => document.createElement('div')) };
  let tick: () => void = () => undefined;
  const stopTimer = vi.fn();
  const stop = watchPieceRequests({
    ids: ['p-1', 'p-2'], client, hold, toasts,
    every: (run) => { tick = run; return stopTimer; },
  });
  return { client, hold, toasts, stop, stopTimer, next: async () => { tick(); for (let i = 0; i < 5; i += 1) await Promise.resolve(); } };
}
const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };

describe('new pieces after the yes', () => {
  it('holds a waiting line while they are made, then says what arrived with Take back, and stops reading', async () => {
    const w = watcher([
      answer([request('p-1', 'well', 'queued'), request('p-2', 'gate', 'requested'), request('p-9', 'sword', 'queued')]),
      answer([request('p-1', 'well', 'done', { kind: 'applied', reason: null }), request('p-2', 'gate', 'done', { kind: 'not_applied', reason: 'no_piece_within' })]),
    ]);
    await settle();
    // Only the plan's own requests, never another of the world's.
    expect(w.hold.mock.calls.at(-1)![0]).toMatch(/^Making new pieces for the well and the gate\. The piece maker runs until /u);
    await w.next();
    const said = w.toasts.show.mock.calls.map((call) => (call as unknown as [{ message: string }])[0].message);
    expect(said).toEqual([
      'New pieces arrived for the well.',
      'The new pieces for the gate were not used: none of them fitted the size the thing has.',
    ]);
    // Every request has its outcome: the line goes and nothing more is read.
    expect(w.hold).toHaveBeenLastCalledWith(null);
    expect(w.stopTimer).toHaveBeenCalled();
    // Take back on the arrived notice takes the pieces back out of the look.
    const arrived = (w.toasts.show.mock.calls[0] as unknown as [{ action: { label: string; run: () => void } }])[0];
    expect(arrived.action.label).toBe('Take back');
    arrived.action.run();
    await settle();
    expect(w.client.takeBack).toHaveBeenCalledWith('p-1');
  });

  it('says it waits for the piece maker while it is not running, and takes the line away when stopped', async () => {
    const w = watcher([answer([request('p-1', 'well', 'requested'), request('p-2', 'gate', 'requested')], { state: 'off', detail: 'x' })]);
    await settle();
    expect(w.hold).toHaveBeenLastCalledWith('Making new pieces for the well and the gate. Waiting for the piece maker to start.');
    w.stop();
    expect(w.hold).toHaveBeenLastCalledWith(null);
  });
});
