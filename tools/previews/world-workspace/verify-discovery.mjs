import assert from 'node:assert/strict';
import { DISCOVERY, inspectionReach } from './discovery-policy.mjs';

// The name tag and [E] Inspect show for the subject at the reticle only within reach, with a wider
// edge to leave than to enter so the prompt does not flicker at the boundary.
assert(inspectionReach(5.9));
assert(!inspectionReach(46));
assert(inspectionReach(6.5, true) && !inspectionReach(6.5, false));
assert(!inspectionReach(7.1, true));
assert(!inspectionReach(NaN) && !inspectionReach(-1));
assert(DISCOVERY.leastExtentPx > 0);

const result = { verified_at_utc: new Date().toISOString(), pass: true, scope: 'Inspect reach with its leaving edge' };
console.log(JSON.stringify(result));
