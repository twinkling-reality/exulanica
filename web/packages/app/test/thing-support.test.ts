import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseSiteDrawing } from '@exulanica/atlas-react/generated-site';
import type { SiteDrawing, StructuredSiteDrawing } from '@exulanica/atlas-react/generated-site';
import { parseVersion, type AlternateVersion } from '../src/world-objects-api.js';
import type { ThingSupportAvailability } from '../src/thing-support-api.js';
import { holdSupportedThings, observeSupportVersions, supportMatchesSource, SUPPORT_LEASE_MS, SUPPORT_TIMEOUT_MS } from '../src/composition/thing-support.js';
const drawing = parseSiteDrawing(JSON.parse(readFileSync(new URL('../../atlas-react/test/fixtures/site-support.v2.json', import.meta.url), 'utf8')).drawing) as StructuredSiteDrawing;
const retained = parseVersion(JSON.parse(readFileSync(new URL('./fixtures/world-version-supported.v6.json', import.meta.url), 'utf8')));
// Retained fixtures come from different worlds; this synthetic adapter case binds its placement to the drawing.
const thing = {...retained.things![0]!, support: {...retained.things![0]!.support!, worldId: drawing.worldId,
  receiptSha256: drawing.receiptSha256, networkSha256: drawing.support!.document.document_sha256}};
const version: AlternateVersion = {...retained, worldId: drawing.worldId, things: [thing]};
const answer = (id = thing.thingId): ThingSupportAvailability => ({versionId: version.versionId, thingId: id,
  stateSha256: version.stateSha256, support: thing.support, availability: 'available'});
const deferred = <T>() => { let resolve!: (v: T) => void; const promise = new Promise<T>(r => {resolve = r;}); return {promise, resolve}; };
afterEach(() => vi.useRealTimers());
function setup(read = vi.fn(async (_v: string, id: string, _s: AbortSignal) => answer(id))) {
  let source: SiteDrawing | null = drawing;
  const versions = observeSupportVersions(), changed = vi.fn();
  const held = holdSupportedThings({read, versions, source: () => source, changed});
  return {held, read, versions, changed, source: (next: SiteDrawing | null) => {source = next;}};
}
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
describe('source-bound supported thing display', () => {
  it('requires mounted source, saved height and current per-thing response', async () => {
    const s = setup(); s.held.setVersion(version); await flush(); expect(s.held.available(thing)).toBe(true);
    for (const field of ['worldId', 'sourceSnapshotId', 'receiptSha256', 'networkSha256', 'regionId', 'surfaceId'] as const) {
      expect(supportMatchesSource({...thing, support: {...thing.support, [field]: 'wrong'}}, version, drawing)).toBe(false);
    }
    expect(s.held.available({...thing, transform: {...thing.transform, yMm: 0}})).toBe(false);
    expect(supportMatchesSource({...thing, transform: {...thing.transform, scaleMilli: 2000}}, version, drawing)).toBe(false);
    s.source(null); expect(s.held.available(thing)).toBe(false); s.held.destroy();
  });
  it.each(['state', 'support', 'unavailable'])('withholds %s responses', async field => {
    const s = setup(vi.fn(async () => ({...answer(), ...(field === 'state' ? {stateSha256: '0'.repeat(64)}
      : field === 'support' ? {support: {...thing.support, surfaceId: 'other'}} : {availability: 'unavailable' as const})})));
    s.held.setVersion(version); await flush(); expect(s.held.available(thing)).toBe(false); s.held.destroy();
  });
  it('revokes before an async paint and rejects late old replies, including ABA edit sequence', async () => {
    const pending = deferred<ThingSupportAvailability>();
    const s = setup(vi.fn(async () => pending.promise)); s.versions.observe(version); s.held.setVersion(version);
    s.versions.observe({...version, editSeq: version.editSeq + 1});
    pending.resolve(answer()); await flush(); expect(s.held.available(thing)).toBe(false);
    s.versions.observe(version); // A delayed earlier client read cannot reverse the observed edit.
    s.held.setVersion(version); await flush(); expect(s.held.available(thing)).toBe(false); s.held.destroy();
  });
  it('revokes a visible item on lost authority and restores only after a fresh version read', async () => {
    const s = setup(); s.versions.observe(version); s.held.setVersion(version); await flush(); expect(s.held.available(thing)).toBe(true);
    s.versions.observe(null); expect(s.held.available(thing)).toBe(false);
    s.versions.observe(version); s.held.setVersion(version); await flush();
    expect(s.held.available(thing)).toBe(true); s.held.destroy();
  });
  it('revokes immediately when a same-state read says the kind is gone, and ignores a late earlier read', async () => {
    const s = setup(); s.versions.observe(version); s.held.setVersion(version); await flush();
    expect(s.held.available(thing)).toBe(true);
    const erased = {...version, things: [{...thing, gone: true}]};
    s.versions.observe(erased); expect(s.held.available(thing)).toBe(false);
    s.versions.observe(version); s.held.setVersion(version); await flush();
    expect(s.held.available(thing)).toBe(false);
    s.held.setVersion(erased); await flush(); expect(s.read).toHaveBeenCalledTimes(1);
    s.held.destroy();
  });
  it('bounds a stalled refresh and never grants a timed-out or disposed response', async () => {
    vi.useFakeTimers({toFake: ['setTimeout', 'clearTimeout', 'performance']}); const pending = deferred<ThingSupportAvailability>(); let calls = 0;
    const s = setup(vi.fn(async () => ++calls === 1 ? answer() : pending.promise));
    s.held.setVersion(version); await flush(); expect(s.held.available(thing)).toBe(true);
    await vi.advanceTimersByTimeAsync(2000 + SUPPORT_TIMEOUT_MS); expect(s.held.available(thing)).toBe(false);
    s.held.destroy(); pending.resolve(answer()); await flush(); expect(s.held.available(thing)).toBe(false); expect(vi.getTimerCount()).toBe(0);
  });
  it('bounds concurrency and expires each item from request start while the remaining round is slow', async () => {
    vi.useFakeTimers({toFake: ['setTimeout', 'clearTimeout', 'performance']}); let running = 0, maximum = 0;
    const first = deferred<ThingSupportAvailability>();
    const s = setup(vi.fn(async (_v, id, signal) => {
      running++; maximum = Math.max(maximum, running);
      if (id === '0') {const response = await first.promise; running--; return response;}
      return new Promise<ThingSupportAvailability>((_resolve, reject) => signal.addEventListener('abort', () => {running--; reject(new Error('aborted'));}, {once: true}));
    }));
    const many = {...version, things: Array.from({length: 20}, (_, i) => ({...thing, thingId: String(i)}))};
    s.held.setVersion(many); await vi.advanceTimersByTimeAsync(1000); first.resolve(answer('0')); await flush();
    expect(s.held.available(many.things[0]!)).toBe(true);
    await vi.advanceTimersByTimeAsync(SUPPORT_LEASE_MS - 1000);
    expect(s.held.available(many.things[0]!)).toBe(false); expect(maximum).toBeLessThanOrEqual(4);
    s.held.destroy(); await flush(); expect(vi.getTimerCount()).toBe(0);
  });
});
