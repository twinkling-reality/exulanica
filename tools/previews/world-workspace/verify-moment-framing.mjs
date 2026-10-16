// Checks moment-framing.mjs in Node: the society read rewritten to a moment's people, and the camera
// that frames them, from the recipe file. Run: node verify-moment-framing.mjs
import assert from 'node:assert/strict';
import { MOMENT_FRAMING, faceAngle, foregroundShare, frameRays, framingInSight, framingPose, lensOf, momentSociety, overviewDistance } from './moment-framing.mjs';

assert.equal(MOMENT_FRAMING.recipe, 'moment-framing/v1');
// R23: a moment's picture at the card's 2x (600 x 340); a portrait at 3x of its 52 px orb, on the tile's ground.
assert.deepEqual(MOMENT_FRAMING.size_px, [600, 340]);
assert.equal(MOMENT_FRAMING.portrait.size_px, 156);

// The moment's people as recorded, a short last step ending where they stood; everyone else indoors.
const body = {
  population_size: 3, current_tick: 9,
  state: { tick: 9, minute_of_day: 400, inhabitants: [
    { id: 'teo', position_mm: [0, 0], motion_path_mm: [[0, 0]], action: { kind: 'visit', status: 'active', reason: 'arrived', destination_id: 'fixture:a', remaining_ticks: 3 }, location: { edge: null, indoors: false } },
    { id: 'ines', position_mm: [5000, 0], motion_path_mm: [[5000, 0]] },
    { id: 'marco', position_mm: [90000, 0], motion_path_mm: [[90000, 0]], location: { edge: null, indoors: false } },
  ] },
};
const scene = { people: [
  { id: 'teo', position_mm: [1000, 2000], path_mm: [[1000, 0], [1000, 2000]], action: { kind: 'talk' }, partner_id: 'ines' },
  { id: 'ines', position_mm: [2000, 2000], path_mm: [], action: { kind: 'rest', target_id: 'bench-1', activity: 'rest' } },
] };
const drawn = momentSociety(body, scene);
const [teo, ines, marco] = drawn.state.inhabitants;
assert.deepEqual(teo.position_mm, [1000, 2000]);
assert.deepEqual(teo.motion_path_mm, [[1000, 1950], [1000, 2000]]);
// The served action's own fields stay, under what the moment recorded.
assert.deepEqual(teo.action, { kind: 'talk', status: 'active', reason: 'arrived', destination_id: 'fixture:a', remaining_ticks: 3 });
// A partner is set only where the record has the field.
assert.equal('partner_id' in teo, false);
assert.equal(teo.location.indoors, false);
assert.deepEqual(ines.motion_path_mm, [[2000, 2000]]);
assert.equal(ines.action.target_id, 'bench-1');
assert.equal(ines.action.activity, 'rest');
assert.equal(ines.action.status, 'active');
assert.equal(ines.indoors, false);
// Indoors in the location where the record keeps one.
assert.equal(marco.location.indoors, true);
assert.equal('indoors' in marco, false);
// The read's own fields stay as served; the served body itself is not changed.
assert.equal(drawn.population_size, 3);
assert.equal(drawn.state.minute_of_day, 400);
assert.deepEqual(body.state.inhabitants[0].position_mm, [0, 0]);
// No people, or no inhabitants: the read as it was.
assert.equal(momentSociety(body, { people: [] }), body);
assert.equal(momentSociety({ state: {} }, scene).state.inhabitants, undefined);

// The camera: beside the line between two subjects, back so the tallest fills the recipe's share of
// the frame's height through its lens (3 to 5 m), at eye height, looking at their middle, the group
// on a third.
const R = MOMENT_FRAMING;
const lens = lensOf(R);
const square = { ...R, side_degrees: 0, third: 0 };
const pose = framingPose([{ x: 0, y: 0, z: 0 }, { x: 2, y: 0, z: 0 }], square);
const away = Math.hypot(pose.x - 1, pose.z);
assert.ok(Math.abs(pose.x - 1) < 1e-9, 'square on to the middle');
const share = R.subject_height_m / (2 * away * Math.tan(lens.vertical));
assert.ok(away >= R.distance_m.least && away <= R.distance_m.most, `${away} m away`);
assert.ok(Math.abs(share - R.tallest_share) < 0.01, `the tallest fills ${share} of the frame`);
assert.ok(Math.abs(pose.y - R.eye_height_m) < 1e-9);
assert.ok(Math.abs(pose.yaw) < 1e-9, 'looking toward -z, at the subjects');
assert.ok(pose.pitch < 0, 'a little down, to their middle');
// A taller subject as drawn stands the camera further back, so the tallest still fills the same share.
const tall = framingPose([{ x: 0, y: 0, z: 0, height: 2.1 }, { x: 2, y: 0, z: 0, height: 1.6 }], square);
assert.ok(Math.abs(2.1 / (2 * Math.hypot(tall.x - 1, tall.z) * Math.tan(lens.vertical)) - R.tallest_share) < 0.01);
// On the left third: turned right (a smaller yaw) by the angle of a third of the half width.
const thirds = framingPose([{ x: 0, y: 0, z: 0 }, { x: 2, y: 0, z: 0 }], { ...R, side_degrees: 0 });
assert.ok(Math.abs(thirds.yaw + Math.atan(Math.tan(lens.horizontal) / 3)) < 1e-9);
// Held between the least and most distance; a wide group is taken whole up to the most; one subject is
// seen from the south; none, no camera.
const far = framingPose([{ x: 0, y: 0, z: 0 }, { x: 40, y: 0, z: 0 }], square);
assert.ok(Math.abs(Math.hypot(far.x - 20, far.z) - R.distance_m.most) < 1e-9);
const alone = framingPose([{ x: 3, y: 1, z: 4 }], square);
assert.ok(alone.z > 4 && Math.abs(alone.x - 3) < 1e-9);
// One subject that walked east is seen from in front: from the east, looking west.
const walker = framingPose([{ x: 3, y: 0, z: 4, heading: -Math.PI / 2 }], square);
assert.ok(walker.x > 3 && Math.abs(walker.z - 4) < 1e-9 && Math.abs(walker.yaw - Math.PI / 2) < 1e-9);
assert.equal(framingPose([]), null);

// The frame's rays: through the middle of the frame along the camera's forward; at the edges, the lens.
const rays = frameRays({ x: 0, y: 0, z: 0, yaw: 0, pitch: 0 }, R, [3, 3]);
assert.deepEqual(rays[4].map((v) => +v.toFixed(9)), [0, 0, -1]);
assert.ok(Math.abs(Math.atan2(rays[5][0], -rays[5][2]) - Math.atan(Math.tan(lens.horizontal) * 2 / 3)) < 1e-9);
// The foreground: a wall nearer than the people over the lower half covers about half the frame; the
// ground before them covers none; nothing, none.
const people = [{ x: 0, y: 0, z: -4 }];
const eye = { x: 0, y: 1.5, z: 0, yaw: 0, pitch: 0 };
assert.equal(foregroundShare(eye, people, () => Infinity), 0);
const nearWall = (origin, direction) => (direction[1] < 0 ? 1.5 / Math.hypot(direction[0], direction[2]) : Infinity);
assert.ok(foregroundShare(eye, people, nearWall) > 0.4, 'a near wall below the eye');
const groundOnly = (origin, direction) => (direction[1] < 0 ? -origin[1] / direction[1] : Infinity);
assert.equal(foregroundShare(eye, people, groundOnly), 0, 'the ground is not in the way');

// In sight: of the sides that show every face, those that see every subject at feet, waist and head.
const pair = [{ x: 0, y: 0, z: 0 }, { x: 2, y: 0, z: 0 }];
const open = framingInSight(pair, () => true);
assert.deepEqual(open, framingPose(pair, MOMENT_FRAMING, { side: 0 }), 'nothing in the way: square on');
// A low wall on the square side (z above the pair) hides their feet from there: the other side.
const turned = framingInSight(pair, (camera, point) => !(camera.z > 0 && point.y < 0.5));
assert.ok(turned.z < 0, 'seen from the other side');
// A wall near the camera that hides only the ground before their feet: the picture's foot would be
// that wall, so the other side.
assert.ok(framingInSight(pair, (camera, point) => !(camera.z > 0 && point.y < 0.2)).z < 0);
// A wall all round, lower than a raised eye: square on, raised.
const raising = { ...MOMENT_FRAMING, sight: { ...MOMENT_FRAMING.sight, raise_m: [0, 1.2] } };
const ring = (camera, point) => camera.y > MOMENT_FRAMING.eye_height_m + 0.5 || point.y > 0.5;
assert.deepEqual(framingInSight(pair, ring, raising), framingPose(pair, raising, { side: 0, raise: 1.2 }));
// Something near the camera over more than a tenth of the frame on the square side: the other side.
assert.ok(framingInSight(pair, () => true, MOMENT_FRAMING, (pose) => (pose.z > 0 ? 0.3 : 0)).z < 0, 'the clear side');
// Seen whole from nowhere: the framing that sees the most (heads over the wall from everywhere, and
// the second subject's feet from the far side of the line too).
assert.ok(framingInSight(pair, (camera, point) => point.y > 1 || (camera.z < 0 && point.x > 1)).z < 0, 'the side that sees the most');

// Faces: a camera stands where every face shows, the most frontal it can.
const face = (pose, people) => Math.max(...people.map((one) => faceAngle(one, pose)));
// Facing each other: square on, both turned toward the camera no further than a profile.
const talking = [{ x: 0, y: 0, z: 0, heading: -Math.PI / 2 }, { x: 2, y: 0, z: 0, heading: Math.PI / 2 }];
const profile = framingInSight(talking, () => true);
assert.deepEqual(profile, framingPose(talking, MOMENT_FRAMING, { side: 0 }));
assert.ok(face(profile, talking) <= 90, `both faces show, ${face(profile, talking)}`);
// Both facing south (+z): from the south; both facing north: from the north, never their backs.
const south = [{ ...pair[0], heading: Math.PI }, { ...pair[1], heading: Math.PI }];
assert.ok(framingInSight(south, () => true).z > 0 && face(framingInSight(south, () => true), south) < 30);
const north = [{ ...pair[0], heading: 0 }, { ...pair[1], heading: 0 }];
const fromNorth = framingInSight(north, () => true);
assert.ok(fromNorth.z < 0 && face(fromNorth, north) < 30, 'not their backs');
// Their faces show only from where the feet are hidden: still where the faces show.
assert.ok(framingInSight(north, (camera, point) => !(camera.z < 0 && point.y < 0.5)).z < 0);
// Back to back with a narrow limit: no side shows both faces, so no picture.
const backToBack = [{ x: 0, y: 0, z: 0, heading: Math.PI / 2 }, { x: 2, y: 0, z: 0, heading: -Math.PI / 2 }];
const narrow = { ...MOMENT_FRAMING, sight: { ...MOMENT_FRAMING.sight, face_limit_deg: 60 } };
assert.equal(framingInSight(backToBack, () => true, narrow), null);
assert.equal(faceAngle({ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }), null, 'no heading, no face to judge');

// The overview stands back until the site and what is round it fit the frame with its margin.
const B = MOMENT_FRAMING.beginning;
const back = overviewDistance(100);
assert.ok(back > 100 && back < B.most_m);
assert.ok(overviewDistance(200) > back * 1.9, 'twice the site, about twice as far');
assert.equal(overviewDistance(1e6), B.most_m);
assert.ok(overviewDistance(100, { ...B, margin: 0.2 }) > back, 'a wider margin, further back');
assert.ok(Math.abs(overviewDistance(100, { ...B, surround: 1 }) * B.surround - back) < 0.01, 'the surround widens the site it fits');
assert.equal(framingInSight([], () => true), null);
console.log('Moment framing checks passed: the moment\'s people as recorded, everyone else indoors, and the camera that frames them from where it sees them.');
