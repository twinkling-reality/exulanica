// How often the world workspace asks again, by itself, for a subject whose read failed. The first
// automatic retry waits a second, each further failure doubles the wait up to a 30 second cap, and a
// read that succeeds clears it. A read the person asks for (Inspect) is never held back.

export const READ_BACKOFF = Object.freeze({ firstMs: 1000, maximumMs: 30000 });

export function createReadBackoff(rule = READ_BACKOFF) {
  const held = new Map();
  return {
    /** Whether an automatic read of `key` may be sent at `now` (milliseconds). */
    ready(key, now) { const one = held.get(key); return !one || now >= one.until; },
    failed(key, now) {
      const failures = (held.get(key)?.failures || 0) + 1;
      held.set(key, { failures, until: now + Math.min(rule.maximumMs, rule.firstMs * 2 ** (failures - 1)) });
    },
    succeeded(key) { held.delete(key); },
  };
}
