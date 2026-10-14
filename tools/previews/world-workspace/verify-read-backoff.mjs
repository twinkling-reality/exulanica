import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createReadBackoff } from './read-backoff.mjs';

// The discovery loop passes about six times a second. Against a read that always fails, 90 seconds
// of passes send one read at 0, 1, 3, 7, 15, 31 and 63 seconds: 7, where every pass reading sends 540.
const passes = (backoff, fails = () => true) => {
  let reads = 0;
  for (let pass = 0; pass < 540; pass++) {
    const now = pass * 1000 / 6;
    if (!backoff.ready('duck', now)) continue;
    reads++;
    if (fails(now)) backoff.failed('duck', now); else backoff.succeeded('duck');
  }
  return reads;
};
assert.equal(passes(createReadBackoff()), 7);
// One subject's failures never hold back another's.
const shared = createReadBackoff();
shared.failed('duck', 0);
assert.equal(shared.ready('duck', 500), false);
assert.equal(shared.ready('knight', 500), true);
// A success clears the wait and its doubling: the next failure waits a second again.
const recovering = createReadBackoff();
for (const now of [0, 1000, 3000, 7000]) recovering.failed('duck', now);
assert.equal(recovering.ready('duck', 14000), false);
recovering.succeeded('duck');
assert.equal(recovering.ready('duck', 14000), true);
recovering.failed('duck', 14000);
assert.equal(recovering.ready('duck', 14999), false);
assert.equal(recovering.ready('duck', 15000), true);
// The workspace consults the policy at each automatic read, and only there: a read the person asks
// for (`entityOffer(row, true)`) is never held back.
const source = readFileSync(new URL('./contextual-world.ts', import.meta.url), 'utf8');
const automatic = source.split('\n').filter(line => /void entityOffer\(/.test(line));
assert.equal(automatic.length, 2);
for (const line of automatic) assert.match(line, /readBackoff\.ready\(/);
for (const line of source.split('\n').filter(line => /entityOffer\([^)]*, true\)/.test(line))) assert.doesNotMatch(line, /readBackoff/);
console.log('Read backoff checks passed: 7 reads in 90 s of failing passes, per-subject waits, reset on success, automatic reads gated.');
