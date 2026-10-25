// A History moment's picture, as data in and data out (moment-framing.v5.json): the society read a
// page is served rewritten to the moment's recorded people, and the camera that frames who it is
// about. Pure, so verify-moment-framing.mjs checks it in Node; the scene preview's moment mode
// (front-door-preview.ts) draws by it, and moment-pictures.ts names the recipe it kept a picture by.
// moment-framing.v1.json to v4.json stay beside it: the recipes the pictures kept under their names were
// drawn by (v3 frames as v2 does and waits for the near subjects to be drawn in full, `wait_ms.near`; v4 draws
// as v3 does with the moment's read made whole: steps in whole millimetres, everyone else indoors on every engine;
// v5 keeps the one who acted or spoke the most prominent: no bystander larger, the camera stepping back for them;
// v6 frames as v5 does with a near thing's cover compared first (`sight.foreground.first`): a framing with something
// near the camera over more than the frame's share, a street tree's crown above it, loses to any clear one).
import framing from './moment-framing.v6.json' with { type: 'json' };

/** The framing recipe; each figure a world could want different is a field of the file. */
export const MOMENT_FRAMING = Object.freeze(framing);

/** Where a moment's scene waits for its preview frame, by a key the frame's address carries. */
export const MOMENT_SCENE_KEY = 'exulanica.moment-scene.v1:';
/** The message the preview frame answers with: the picture's bytes, or null. */
export const MOMENT_PICTURE_MESSAGE = 'exulanica.moment-picture';
/** The message a page sends a preview frame that has drawn a moment: draw this next moment of the same version. */
export const MOMENT_ASK_MESSAGE = 'exulanica.moment-ask';

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const point = (value) => Array.isArray(value) && value.length === 2 && value.every(finite);

/**
 * The served society read (`GET /world/versions/{v}/society`, raw JSON) as the moment's tick drew
 * it: the moment's people where it recorded them, doing what it recorded (merged over the served
 * record, so every field the read's parser asks for stays), each with a step `walk_hint_m` long (in whole
 * millimetres, as the read's parser asks) that
 * ends there, so they face the way they last walked and stand still; everyone else indoors (in their
 * location where the record keeps one), so the crowd draws only the moment's people. The read's other
 * fields are kept as served (the population, the clock). A scene without people, or a read without
 * inhabitants, comes back as it was.
 */
export function momentSociety(body, scene, recipe = MOMENT_FRAMING) {
  const people = Array.isArray(scene?.people) ? scene.people.filter((one) => one && typeof one.id === 'string' && point(one.position_mm)) : [];
  const inhabitants = body?.state?.inhabitants;
  if (people.length === 0 || !Array.isArray(inhabitants)) return body;
  const recorded = new Map(people.map((one) => [one.id, one]));
  const hint = recipe.walk_hint_m * 1000;
  // Indoors where the record keeps it: in its location where the location says it (the living society's
  // record), else on the person (a society of things, whose location names only where they stand).
  const indoors = (person, inside) => (person.location && typeof person.location === 'object' && 'indoors' in person.location
    ? { ...person, location: { ...person.location, indoors: inside } }
    : { ...person, indoors: inside });
  const placed = inhabitants.map((person) => {
    const one = recorded.get(person?.id);
    if (!one) return indoors(person, true);
    const [east, south] = one.position_mm;
    const path = Array.isArray(one.path_mm) ? one.path_mm.filter(point) : [];
    const from = path.length > 1 ? path[path.length - 2] : null;
    const along = from ? Math.hypot(east - from[0], south - from[1]) : 0;
    const motion = along > 0
      ? [[Math.round(east - ((east - from[0]) / along) * hint), Math.round(south - ((south - from[1]) / along) * hint)], [east, south]]
      : [[east, south]];
    const next = indoors({ ...person, position_mm: [east, south], motion_path_mm: motion }, false);
    // What they were doing: the served record's own action, with what the moment recorded of it.
    if (one.action && typeof one.action === 'object' && typeof one.action.kind === 'string') {
      next.action = { ...(person.action && typeof person.action === 'object' ? person.action : { status: 'active' }), ...one.action };
    }
    if (typeof one.partner_id === 'string' && 'partner_id' in person) next.partner_id = one.partner_id;
    return next;
  });
  return { ...body, state: { ...body.state, inhabitants: placed } };
}

/** The lens's half angles, radians: vertical from `fov_deg`, horizontal by the picture's shape. */
export function lensOf(recipe = MOMENT_FRAMING, fovDeg = recipe.fov_deg) {
  const vertical = (fovDeg * Math.PI) / 360;
  const [width, height] = recipe.size_px;
  return { vertical, horizontal: Math.atan(Math.tan(vertical) * (width / height)) };
}

/**
 * The camera that frames the moment's subjects, from where they are drawn (render space, metres:
 * x east, y up, z south; an anchor may carry `height`, as drawn, and `heading`, the way it faces:
 * radians about +Y with -Z forward, the crowd's convention). Beside the line between
 * the first two subjects, or in front of a lone one that has a heading, `side` degrees round from square on (the recipe's
 * `side_degrees` unless given). Back far enough that no subject (its drawn height, else
 * `subject_height_m`) stands taller than `tallest_share` of the frame's height through the recipe's
 * lens, measured where each stands (one nearer the camera than the group's middle stands taller),
 * and the group with `room_m` beside it fits the frame's width, held between the least and most
 * distance, and `back` metres further within the most; then further back, still within the most, until every subject's feet stand at least
 * `foot_margin` of the frame's height above its foot. At eye height raised by `raise` metres,
 * looking at `look_at_height_m` above their feet, turned so the group's centre sits on a third of the
 * frame (`third`: 1 the left third, -1 the right, 0 the middle). Facing -z is yaw 0, as the controls
 * turn. Null without a subject.
 */
export function framingPose(anchors, recipe = MOMENT_FRAMING, { side = recipe.side_degrees, raise = 0, back = 0 } = {}) {
  const drawn = (anchors ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (drawn.length === 0) return null;
  const centre = drawn.reduce((sum, one) => ({ x: sum.x + one.x / drawn.length, y: sum.y + one.y / drawn.length, z: sum.z + one.z / drawn.length }), { x: 0, y: 0, z: 0 });
  const spread = Math.max(0, ...drawn.map((one) => Math.hypot(one.x - centre.x, one.z - centre.z))) * 2;
  const lens = lensOf(recipe);
  const d = recipe.distance_m;
  // Square on to the line between the first two subjects; one subject alone is seen from in front, the
  // way it faces, or from the south where it has no heading.
  let across = { x: 0, z: 1 };
  if (drawn.length === 1 && finite(drawn[0].heading)) {
    across = { x: -Math.sin(drawn[0].heading), z: -Math.cos(drawn[0].heading) };
  } else if (drawn.length > 1) {
    const dx = drawn[1].x - drawn[0].x, dz = drawn[1].z - drawn[0].z, length = Math.hypot(dx, dz);
    if (length > 1e-6) across = { x: -dz / length, z: dx / length };
  }
  const turn = (side * Math.PI) / 180;
  const view = { x: across.x * Math.cos(turn) - across.z * Math.sin(turn), z: across.x * Math.sin(turn) + across.z * Math.cos(turn) };
  // Each subject as drawn where the anchors say (`height`, metres), else the recipe's figure, at its own
  // distance: one standing `along` metres nearer the camera than the middle is that much nearer.
  const heightOf = (one) => (finite(one.height) && one.height > 0 ? one.height : recipe.subject_height_m);
  const byHeight = Math.max(...drawn.map((one) => heightOf(one) / (recipe.tallest_share * 2 * Math.tan(lens.vertical))
    + (one.x - centre.x) * view.x + (one.z - centre.z) * view.z));
  const byWidth = (spread + 2 * d.room_m) / (2 * Math.tan(lens.horizontal));
  const thirdTurn = Math.atan(Math.tan(lens.horizontal) / 3) * Math.sign(recipe.third ?? 0);
  const poseAt = (distance) => {
    const camera = { x: centre.x + view.x * distance, y: centre.y + recipe.eye_height_m + raise, z: centre.z + view.z * distance };
    const target = { x: centre.x, y: centre.y + recipe.look_at_height_m, z: centre.z };
    // Turning right (a smaller yaw) by a third of the half width puts the group on the left third.
    const yaw = Math.atan2(-(target.x - camera.x), -(target.z - camera.z)) - thirdTurn;
    const pitch = Math.atan2(target.y - camera.y, Math.hypot(target.x - camera.x, target.z - camera.z));
    return { x: camera.x, y: camera.y, z: camera.z, yaw, pitch };
  };
  // How high in the frame a point stands: 1 at its top, -1 at its foot (null behind the camera).
  const heightInFrame = (pose, point) => {
    const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
    const v = [point.x - pose.x, point.y - pose.y, point.z - pose.z];
    const depth = -sy * cp * v[0] + sp * v[1] - cy * cp * v[2];
    return depth > 0 ? (sy * sp * v[0] + cp * v[1] + cy * sp * v[2]) / (depth * Math.tan(lens.vertical)) : null;
  };
  const lowest = -1 + 2 * (recipe.foot_margin ?? 0);
  // `back` metres further, within the most, for a framing that steps back to keep bystanders in the band.
  let distance = Math.min(d.most, Math.max(d.least, byHeight, byWidth) + back);
  let pose = poseAt(distance);
  while (distance < d.most && drawn.some((one) => (heightInFrame(pose, one) ?? -Infinity) < lowest)) {
    distance = Math.min(d.most, distance + 0.05);
    pose = poseAt(distance);
  }
  return pose;
}

/**
 * The same framing again from where the subjects stand now: `chosen` is a pose framingInSight answered
 * (its `frame` says how many subjects it framed, from which side, height and third), `anchors` the
 * subjects as drawn now, in the same order. A pose with no `frame` is answered as it is.
 */
export function reframe(chosen, anchors, recipe = MOMENT_FRAMING) {
  const frame = chosen?.frame;
  if (!frame) return chosen;
  const now = (anchors ?? []).slice(0, frame.subjects).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (now.length !== frame.subjects) return chosen;
  const again = framingPose(now, frame.third === recipe.third ? recipe : { ...recipe, third: frame.third }, { side: frame.side, raise: frame.raise, back: frame.back ?? 0 });
  return again ?? chosen;
}

/**
 * The directions, unit vectors in render space, through a grid of `grid` points across the frame a
 * camera at `pose` sees through the recipe's lens: the samples the foreground test casts.
 */
export function frameRays(pose, recipe = MOMENT_FRAMING, grid = recipe.sight.foreground.grid) {
  const lens = lensOf(recipe);
  const [columns, rows] = grid;
  const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
  const forward = [-sy * cp, sp, -cy * cp], right = [cy, 0, -sy], up = [sy * sp, cp, cy * sp];
  const rays = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const nx = ((column + 0.5) / columns) * 2 - 1, ny = 1 - ((row + 0.5) / rows) * 2;
      const tx = nx * Math.tan(lens.horizontal), ty = ny * Math.tan(lens.vertical);
      const ray = [0, 1, 2].map((axis) => forward[axis] + right[axis] * tx + up[axis] * ty);
      const length = Math.hypot(...ray);
      rays.push(ray.map((value) => value / length));
    }
  }
  return rays;
}

/**
 * The share of the frame something nearer than the people covers: of the frame's rays, those that
 * meet the scene (`hit(origin, direction)` gives the distance, or Infinity) more than `nearer_m`
 * short of the group and more than `above_ground_m` above the people's ground (the ground before
 * them is not in the way).
 */
export function foregroundShare(pose, anchors, hit, recipe = MOMENT_FRAMING) {
  const drawn = (anchors ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (drawn.length === 0) return 0;
  const rule = recipe.sight.foreground;
  const ground = Math.min(...drawn.map((one) => one.y));
  const near = Math.min(...drawn.map((one) => Math.hypot(one.x - pose.x, one.z - pose.z))) - rule.nearer_m;
  const rays = frameRays(pose, recipe);
  let covered = 0;
  for (const ray of rays) {
    const distance = hit([pose.x, pose.y, pose.z], ray);
    if (!(distance < Infinity)) continue;
    const plan = distance * Math.hypot(ray[0], ray[2]);
    if (plan < near && pose.y + ray[1] * distance > ground + rule.above_ground_m) covered += 1;
  }
  return covered / rays.length;
}

/**
 * How far round from a subject's face the camera stands, in degrees: 0 straight in front, 90 a
 * profile, 180 from behind; null for a subject with no heading.
 */
export function faceAngle(anchor, pose) {
  if (!finite(anchor?.heading)) return null;
  const ahead = { x: -Math.sin(anchor.heading), z: -Math.cos(anchor.heading) };
  const dx = pose.x - anchor.x, dz = pose.z - anchor.z, length = Math.hypot(dx, dz);
  if (length < 1e-9) return 0;
  const cosine = Math.max(-1, Math.min(1, (ahead.x * dx + ahead.z * dz) / length));
  return (Math.acos(cosine) * 180) / Math.PI;
}

/**
 * The framing that sees the moment's subjects. The first two standing farther apart than the
 * recipe's `pair_most_m` (more than its lens fits at its framing) are not framed together: the first,
 * who acted or spoke, is framed alone, in front of the way they face, and never so that the frame's
 * edge cuts the other (framedWhole): on the recipe's third, else the other third, else another side
 * within the face limit. Otherwise the recipe's sides and
 * raised heights (`sight`), each judged by the faces it shows: a subject's face shows from a side no
 * more than `face_limit_deg` round from it (faceAngle; a subject with no heading shows from every side),
 * and a side that shows none of them is never chosen. Of the rest, those that show the most faces;
 * of those, the ones that pass the most of the sight tests: `seen(camera, point)` at every subject's
 * feet, waist and head (`points_m` above where they stand) and at the ground `ground_ahead_m` short of
 * their middle toward the camera, and `covered(pose, subjects)`, the share of the frame something nearer
 * than the framed subjects covers (foregroundShare), at most the recipe's `foreground.share`; of those,
 * the one whose worst shown face is turned least (the first of equals). Where no side shows a face of
 * the pair, the first is framed alone. `seen` is the scene's answer: whether nothing stands between the
 * camera and the point. `bystanders`, the moment's other people as drawn: of the sides that show the most faces,
 * those from which the fewest stand nearer and larger than the band allows (standsInBand), and by the least,
 * before the sight tests. Null only without a subject: the page keeps its quiet tile.
 * @param {(pose: { x: number, y: number, z: number, yaw: number, pitch: number }, subjects: readonly object[]) => number} [covered]
 */
export function framingInSight(anchors, seen, recipe = MOMENT_FRAMING, covered = (_pose, _subjects) => 0, bystanders = []) {
  const drawn = (anchors ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (drawn.length === 0) return null;
  const near = (bystanders ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  const apart = drawn.length > 1 && Math.hypot(drawn[1].x - drawn[0].x, drawn[1].z - drawn[0].z) > (recipe.pair_most_m ?? Infinity);
  const framed = apart ? null : bestSide(drawn, seen, recipe, covered, [], near);
  return framed ?? bestSide(drawn.slice(0, 1), seen, recipe, covered, drawn.slice(1), near);
}

/**
 * Whether `one` (an anchor with its drawn `height`, else `subject_height_m`) stands within the frame's size
 * band from `pose`: out of the frame, or no taller than `tallest_share` of its height, nor taller in it than
 * `actor` (the one who acted or spoke) where one is given, with its feet at least `foot_margin` of it above
 * its foot. A person in a moment's scene who is not framed (a bystander) is held to it, so nobody stands
 * nearer and larger than the people the picture is about, and the one who acted or spoke stands largest.
 */
export function standsInBand(pose, one, recipe = MOMENT_FRAMING, actor = null) {
  const lens = lensOf(recipe);
  const tall = finite(one.height) && one.height > 0 ? one.height : recipe.subject_height_m;
  if (!framedInside(pose, one, tall, lens)) return true;
  const limit = actor ? Math.min(recipe.tallest_share, tallnessFrom(pose, actor, recipe)) : recipe.tallest_share;
  if (tallnessFrom(pose, one, recipe) > limit + 1e-9) return false;
  const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
  const v = [one.x - pose.x, one.y - pose.y, one.z - pose.z];
  const depth = -sy * cp * v[0] + sp * v[1] - cy * cp * v[2];
  const feet = depth > 0 ? (sy * sp * v[0] + cp * v[1] + cy * sp * v[2]) / (depth * Math.tan(lens.vertical)) : -Infinity;
  return feet >= -1 + 2 * (recipe.foot_margin ?? 0) - 1e-9;
}

/** How tall a person (its drawn `height`, else `subject_height_m`) stands in the frame from `pose`, as a share of its height. */
function tallnessFrom(pose, one, recipe) {
  const tall = finite(one.height) && one.height > 0 ? one.height : recipe.subject_height_m;
  return tall / (2 * Math.max(1e-6, Math.hypot(one.x - pose.x, one.z - pose.z)) * Math.tan(lensOf(recipe).vertical));
}

/**
 * Whether any of a person lies inside the frame: their upright line from feet to head, where it stands across the
 * frame, reaches into its height (one so near that feet and head both fall outside still fills the frame).
 */
function framedInside(pose, one, tall, lens) {
  const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
  const ends = [one.y, one.y + tall].map((y) => {
    const v = [one.x - pose.x, y - pose.y, one.z - pose.z];
    const depth = -sy * cp * v[0] + sp * v[1] - cy * cp * v[2];
    if (depth <= 0) return null;
    return {
      across: (cy * v[0] - sy * v[2]) / (depth * Math.tan(lens.horizontal)),
      high: (sy * sp * v[0] + cp * v[1] + cy * sp * v[2]) / (depth * Math.tan(lens.vertical)),
    };
  }).filter(Boolean);
  if (ends.length === 0) return false;
  const low = Math.min(...ends.map((end) => end.high)), top = Math.max(...ends.map((end) => end.high));
  return ends.some((end) => Math.abs(end.across) <= 1) && low <= 1 && top >= -1;
}

/**
 * Whether `other` (an anchor; its `outline`, points of the box it is drawn by, else its feet and its
 * head at its `height` or the recipe's `subject_height_m`) is wholly in the frame a camera at `pose`
 * sees through the recipe's lens, or wholly out of it: never cut by the frame's edge.
 */
export function framedWhole(pose, other, recipe = MOMENT_FRAMING) {
  const lens = lensOf(recipe);
  const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
  const forward = [-sy * cp, sp, -cy * cp], right = [cy, 0, -sy], up = [sy * sp, cp, cy * sp];
  const tall = finite(other.height) && other.height > 0 ? other.height : recipe.subject_height_m;
  const points = Array.isArray(other.outline) && other.outline.length > 0 ? other.outline
    : [{ x: other.x, y: other.y, z: other.z }, { x: other.x, y: other.y + tall, z: other.z }];
  const inside = points.filter((point) => {
    const v = [point.x - pose.x, point.y - pose.y, point.z - pose.z];
    const depth = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2];
    if (depth <= 0) return false;
    const across = (v[0] * right[0] + v[2] * right[2]) / (depth * Math.tan(lens.horizontal));
    const high = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / (depth * Math.tan(lens.vertical));
    return Math.abs(across) <= 1 && Math.abs(high) <= 1;
  }).length;
  return inside === 0 || inside === points.length;
}

/**
 * The side framingInSight chooses for these subjects, or null where no side shows any of their faces.
 * With `others` (the subjects not framed) or `bystanders`, on the recipe's third or the other one, and only
 * where every other is wholly in or out of the frame (framedWhole), where none is as though there were no
 * others; among the sides that show the most faces, those where the fewest bystanders stand out of the size
 * band (standsInBand), and by the least, come first.
 */
function bestSide(drawn, seen, recipe, covered, others, bystanders = []) {
  const thirds = others.length > 0 || bystanders.length > 0 ? [...new Set([recipe.third ?? 0, -(recipe.third ?? 0)])] : [recipe.third ?? 0];
  const whole = (pose) => others.every((other) => framedWhole(pose, other, recipe));
  // The bystanders out of the band from a pose (above it, or larger than the one who acted or spoke): how many,
  // and by how much of the frame's height together.
  const actor = drawn[0];
  const outOfBand = (pose) => {
    const out = bystanders.filter((one) => !standsInBand(pose, one, recipe, actor));
    const limit = Math.min(recipe.tallest_share, tallnessFrom(pose, actor, recipe));
    return { count: out.length, excess: out.reduce((sum, one) => sum + Math.max(0, tallnessFrom(pose, one, recipe) - limit), 0) };
  };
  return chooseSide(drawn, seen, recipe, covered, thirds, whole, outOfBand)
    ?? (others.length > 0 ? chooseSide(drawn, seen, recipe, covered, [recipe.third ?? 0], () => true, outOfBand) : null);
}

/** Whether `a` comes before `b`, compared value by value (the first that differs decides; equals keep the first). */
const comesBefore = (a, b) => {
  const at = a.findIndex((value, index) => value !== b[index]);
  return at !== -1 && a[at] < b[at];
};

/**
 * The best framing of the subjects over the recipe's heights, sides and `thirds`, from those `allowed`: where the
 * recipe compares the foreground first (`sight.foreground.first`), the least near cover past its share; then the most
 * faces shown; then the fewest bystanders out of the band (`outOfBand`), and by the least; then sight; then faces
 * turned least; then the nearest. With bystanders out of the band the camera may step back by `back_step_m` at a
 * time, within the most distance, while the one who acted or spoke stays at least `tallest_least` of the frame.
 */
function chooseSide(drawn, seen, recipe, covered, thirds, allowed, outOfBand = () => ({ count: 0, excess: 0 })) {
  const subjects = drawn.flatMap((one) => recipe.sight.points_m.map((height) => ({ x: one.x, y: one.y + height, z: one.z })));
  const centre = drawn.reduce((sum, one) => ({ x: sum.x + one.x / drawn.length, y: sum.y + one.y / drawn.length, z: sum.z + one.z / drawn.length }), { x: 0, y: 0, z: 0 });
  // The ground in front of them, toward this camera, a little above it so the ground itself is no wall.
  const ahead = (pose) => {
    const dx = pose.x - centre.x, dz = pose.z - centre.z, length = Math.hypot(dx, dz) || 1;
    return (recipe.sight.ground_ahead_m ?? []).map((by) => ({ x: centre.x + (dx / length) * by, y: centre.y + 0.1, z: centre.z + (dz / length) * by }));
  };
  const limit = recipe.sight.face_limit_deg ?? 180;
  const step = recipe.sight.back_step_m ?? 0;
  let best = null;
  // Judges one framing; answers whether bystanders still stand out of the band from it.
  const judge = (pose, side, raise, third, back) => {
    if (!allowed(pose)) return false;
    const angles = drawn.map((one) => faceAngle(one, pose));
    const turned = angles.filter((angle) => angle !== null && angle <= limit);
    const shown = turned.length + angles.filter((angle) => angle === null).length;
    if (shown === 0) return false;
    const worst = turned.length > 0 ? Math.max(...turned) : 0;
    const points = [...subjects, ...ahead(pose)];
    // Something near the camera over more than the recipe's share of the frame counts as one more unseen point;
    // where the recipe compares it first, how far past the share it covers decides before the faces, so a camera
    // under a tree's crown, whose sight lines to the faces are clear, never beats a clear framing.
    const share = covered(pose, drawn);
    const clear = share <= recipe.sight.foreground.share;
    const cover = recipe.sight.foreground.first ? Math.max(0, share - recipe.sight.foreground.share) : 0;
    const passed = points.filter((point) => seen(pose, point)).length + (clear ? 1 : 0);
    const band = outOfBand(pose);
    // The least near cover past the share (where first); the most faces shown; then the fewest bystanders out of
    // the band, and by the least; then sight; then faces turned least; then the nearest.
    const order = [cover, -shown, band.count, band.excess, -passed, worst, back];
    if (best === null || comesBefore(order, best.order)) best = { pose, order, side, raise, third, back };
    return band.count > 0;
  };
  for (const raise of recipe.sight.raise_m) {
    for (const side of recipe.sight.sides_degrees) {
      for (const third of thirds) {
        // Stepping back while bystanders stand out of the band, as long as the camera moves (within the most
        // distance) and the one who acted or spoke stays at the band's foot or above.
        let previous = null;
        for (let back = 0; ; back += step) {
          const pose = framingPose(drawn, third === recipe.third ? recipe : { ...recipe, third }, { side, raise, back });
          if (back > 0 && (Math.hypot(pose.x - previous.x, pose.z - previous.z) < 1e-6
            || tallnessFrom(pose, drawn[0], recipe) < (recipe.tallest_least ?? 0) - 1e-9)) break;
          previous = pose;
          if (!judge(pose, side, raise, third, back) || !(step > 0)) break;
        }
      }
    }
  }
  if (best === null) return null;
  // How it was framed, for reframe: not enumerable, so the pose compares and serialises as the camera alone.
  Object.defineProperty(best.pose, 'frame', { value: Object.freeze({ subjects: drawn.length, side: best.side, raise: best.raise, third: best.third, back: best.back }) });
  return best.pose;
}

/**
 * How far back the overview of a made world stands (the recipe's `beginning`): looking down at
 * `pitch_deg` toward the middle of a round site `radius` metres across times `surround` (its edges and
 * the water or land round it), through a lens of `fov_deg` vertical on a frame `aspect` wide, far
 * enough that every point of that circle falls inside the frame with `margin` of the frame to spare
 * on every side; at most `most_m`.
 */
export function overviewDistance(radius, beginning = MOMENT_FRAMING.beginning, aspect = 16 / 9) {
  const vertical = (beginning.fov_deg * Math.PI) / 360;
  const horizontal = Math.atan(Math.tan(vertical) * aspect);
  const pitch = (beginning.pitch_deg * Math.PI) / 180;
  const edge = 1 - 2 * beginning.margin;
  const r = radius * beginning.surround;
  // Camera at (0, D sin p, D cos p) looking at the origin; forward, right and up of that view.
  const forward = [0, -Math.sin(pitch), -Math.cos(pitch)], right = [1, 0, 0], up = [0, Math.cos(pitch), -Math.sin(pitch)];
  const fits = (distance) => {
    const eye = [0, distance * Math.sin(pitch), distance * Math.cos(pitch)];
    for (let step = 0; step < 32; step += 1) {
      const angle = (step / 32) * 2 * Math.PI;
      const v = [r * Math.cos(angle) - eye[0], -eye[1], r * Math.sin(angle) - eye[2]];
      const depth = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2];
      if (depth <= 0) return false;
      const x = (v[0] * right[0] + v[1] * right[1] + v[2] * right[2]) / (depth * Math.tan(horizontal));
      const y = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / (depth * Math.tan(vertical));
      if (Math.abs(x) > edge || Math.abs(y) > edge) return false;
    }
    return true;
  };
  let low = 0, high = beginning.most_m;
  if (!fits(high)) return high;
  for (let round = 0; round < 40; round += 1) {
    const middle = (low + high) / 2;
    if (fits(middle)) high = middle; else low = middle;
  }
  return high;
}
