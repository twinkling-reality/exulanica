// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EvidenceCache, type EvidenceSource } from '../src/evidence.js';

/**
 * The cache's hold on a photograph's bytes: every URL it makes is one it can revoke.
 *
 * A blob URL keeps a photograph's bytes alive until it is revoked, so a URL the cache made and
 * then lost track of is a copy of somebody's photograph that no deletion reaches. These count
 * every URL made and every URL revoked.
 */

let made: string[] = [];
let revoked: string[] = [];

beforeEach(() => {
  made = [];
  revoked = [];
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => {
    const url = `blob:test/${made.length + 1}`;
    made.push(url);
    return url;
  });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation((url: string) => {
    revoked.push(url);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** A source whose reads the test finishes when it chooses, counting each one. */
function slowSource(): { readonly source: EvidenceSource; readonly reads: string[]; finish(): void } {
  const reads: string[] = [];
  const waiting: (() => void)[] = [];
  return {
    source: {
      evidenceBytes: (handle) => {
        reads.push(handle);
        return new Promise<Blob>((resolve) => {
          waiting.push(() => resolve(new Blob(['photograph'], { type: 'image/jpeg' })));
        });
      },
    },
    reads,
    finish: () => {
      for (const resolve of waiting.splice(0)) resolve();
    },
  };
}

describe('opening a photograph whose read is still under way', () => {
  it('shares the read, so one URL is made and it is the one the cache holds', async () => {
    const { source, reads, finish } = slowSource();
    const cache = new EvidenceCache(source);
    const first = cache.open('span-a');
    const second = cache.open('span-a');
    finish();
    const [a, b] = await Promise.all([first, second]);

    expect(reads).toEqual(['span-a']);
    expect(made).toHaveLength(1);
    expect(a).toEqual(b);
    expect(a.ok && a.url).toBe(made[0]);

    // Everything it made, it can take back.
    cache.dispose();
    expect(revoked).toEqual(made);
  });

  it('makes no URL for a read that lands after the view that asked was closed', async () => {
    const { source, finish } = slowSource();
    const cache = new EvidenceCache(source);
    const opening = cache.open('span-a');
    cache.dispose();
    finish();

    expect((await opening).ok).toBe(false);
    expect(made).toEqual([]);
  });

  it('reads again after a read that failed, since a failure holds nothing', async () => {
    let attempt = 0;
    const cache = new EvidenceCache({
      evidenceBytes: async () => {
        attempt += 1;
        if (attempt === 1) throw new Error('the request failed');
        return new Blob(['photograph'], { type: 'image/jpeg' });
      },
    });

    expect((await cache.open('span-a')).ok).toBe(false);
    expect((await cache.open('span-a')).ok).toBe(true);
    expect(attempt).toBe(2);
  });
});
