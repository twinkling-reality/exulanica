import assert from 'node:assert/strict';
import { assignmentSubject } from './entity-properties.mjs';

// Who a model may be chosen for. A town's resident has no offer: its row's own person-role link and
// that role's capability decide. A being with an offer keeps today's check: offer, link and role agree.
const version = 'v1';
const role = (over = {}) => ({ key: 'society_decision', subject: 'person', available: true,
  capability: { permitted: true, state: 'available', bind: { version_id: version, role_key: 'society_decision' } }, ...over });
const inventory = (roles = [role()]) => ({ version_id: version, roles });
const resident = { scene: { type: 'being', id: 's1' }, roleInstances: [{ role_key: 'society_decision', subject_id: 's1' }] };

assert.deepEqual(assignmentSubject(inventory(), resident, null), { subjectId: 's1', roleKey: 'society_decision' });
// Refused where the role's write is not permitted, not available, for another version, or not a person's.
assert.equal(assignmentSubject(inventory([role({ capability: { ...role().capability, permitted: false } })]), resident, null), null);
assert.equal(assignmentSubject(inventory([role({ available: false })]), resident, null), null);
assert.equal(assignmentSubject(inventory([role({ capability: { ...role().capability, bind: { version_id: 'v0' } } })]), resident, null), null);
assert.equal(assignmentSubject(inventory([role({ subject: 'signal' })]), resident, null), null);
// The link must name this row's own being.
assert.equal(assignmentSubject(inventory(), { ...resident, roleInstances: [{ role_key: 'society_decision', subject_id: 'other' }] }, null), null);
assert.equal(assignmentSubject(inventory(), { ...resident, roleInstances: [] }, null), null);

// A being with an offer: its minds.choose action must be available, permitted and bound to the same subject.
const offer = (over = {}) => ({ actions: [{ id: 'minds.choose', state: 'available', permitted: true,
  runs_by: { bind: { version_id: version, role_key: 'society_decision', subject_id: 's1' } }, ...over }] });
assert.deepEqual(assignmentSubject(inventory(), resident, offer()), { subjectId: 's1', roleKey: 'society_decision' });
assert.equal(assignmentSubject(inventory(), resident, offer({ permitted: false })), null);
assert.equal(assignmentSubject(inventory(), resident, { actions: [] }), null, 'an offer without the action is not read as a resident');

console.log('Assignment checks passed: a resident by its role link, a being with an offer by its offer.');
