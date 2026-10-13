import assert from 'node:assert/strict';
import { DISCOVERY, attentionCandidates, discoveryPresentation, inspectionReach, promptPresentation, layoutDiscovery, markerAt } from './discovery-policy.mjs';

const rule = { beingLeastPx: 22, screenShare: .08 };
assert(inspectionReach(5.9));
assert(!inspectionReach(46));
assert(inspectionReach(6.5, true) && !inspectionReach(6.5, false));
assert(!inspectionReach(7.1, true));
assert(promptPresentation(1).height > promptPresentation(6).height);
assert(promptPresentation(1).key > promptPresentation(6).key);
assert(promptPresentation(1).opacity > promptPresentation(6).opacity);
const view = { width: 800, height: 600 };
const candidate = (key, x, distance = 10, overrides = {}) => ({ key, x, y: 200, z: 10, distance, extent: 10, visible: true, nameWidth: 180, nameHeight: 36, row: { key }, ...overrides });
const far = discoveryPresentation(5, false, rule.beingLeastPx), near = discoveryPresentation(70, false, rule.beingLeastPx);
assert(far.glyph < near.glyph && far.opacity < near.opacity && !far.named && near.named);
const focusedFar = discoveryPresentation(5, true, rule.beingLeastPx), focusedNear = discoveryPresentation(100, true, rule.beingLeastPx);
assert(focusedFar.glyph < focusedNear.glyph && focusedFar.opacity < focusedNear.opacity);
assert.equal(discoveryPresentation(DISCOVERY.leastExtentPx - .1, false, 22), null);
assert.equal(discoveryPresentation(NaN, false, 22), null);
assert.equal(discoveryPresentation(5, true, 22).named, true);
assert.equal(discoveryPresentation(.5, true, 22).named, true); // A selected subject has no discovery-size cutoff.
const crowded = Array.from({length: 100}, (_, i) => candidate('entity-' + i, 100 + i * 6, i + 1));
assert.equal(attentionCandidates(crowded, view).length, 1);
assert.equal(attentionCandidates(crowded, view, 'entity-20').length, 2);
assert.equal(attentionCandidates(crowded, view, 'entity-20')[0].key, 'entity-20');

const markers = layoutDiscovery([candidate('far', 100, 60), candidate('near', 300, 3)], view, rule);
assert.deepEqual(markers.map(item => item.key), ['near', 'far']); // Discovery needs no hover target.
assert.equal(markerAt(markers, { x: 115, y: 180 }).key, 'far'); // Padded target, independent of a body ray.
assert.equal(markerAt(markers, { x: 140, y: 180 }), null);
assert.equal(layoutDiscovery([candidate('wall', 100, 10, { visible: false }), candidate('behind', 200, 10, { z: -1 }), candidate('edge', 3)], view, rule).length, 0);

const collision = [candidate('back', 101, 50), candidate('front', 100, 2)];
assert.deepEqual(layoutDiscovery(collision, view, rule).map(item => item.key), ['front']);
assert.deepEqual(layoutDiscovery(collision, view, rule, 'back').map(item => item.key), ['back']);
const names = layoutDiscovery([candidate('a', 200, 2, { extent: 100 }), candidate('b', 300, 3, { extent: 100 })], view, rule);
assert.equal(names.filter(item => item.named).length, 1); // Both markers survive; overlapping names do not.
assert.equal(layoutDiscovery([candidate('a', 200, 2, { extent: 100 })], view, { ...rule, screenShare: .001 })[0].named, false);
assert.equal(layoutDiscovery([candidate('a', 200, 2, { extent: 100 })], view, { ...rule, screenShare: .001 }, 'a')[0].named, true);

const result = { verified_at_utc: new Date().toISOString(), pass: true, scope: 'Progressive discovery, pointer hit area, obstruction and viewport gates, marker/name overlap, focused-target priority' };
console.log(JSON.stringify(result));
