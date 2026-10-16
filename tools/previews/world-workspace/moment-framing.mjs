// A History moment's picture, as data in and data out (moment-framing.v1.json): the society read a
// page is served rewritten to the moment's recorded people, and the camera that frames who it is
// about. Pure, so verify-moment-framing.mjs checks it in Node; the scene preview's moment mode
// (front-door-preview.ts) draws by it, and moment-pictures.ts names the recipe it kept a picture by.
import framing from './moment-framing.v1.json' with { type: 'json' };

/** The framing recipe; each figure a world could want different is a field of the file. */
export const MOMENT_FRAMING = Object.freeze(framing);

/** Where a moment's scene waits for its preview frame, by a key the frame's address carries. */
export const MOMENT_SCENE_KEY = 'exulanica.moment-scene.v1:';
/** The message the preview frame answers with: the picture's bytes, or null. */
export const MOMENT_PICTURE_MESSAGE = 'exulanica.moment-picture';

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const point = (value) => Array.isArray(value) && value.length === 2 && value.every(finite);

/**
 * The served society read (`GET /world/versions/{v}/society`, raw JSON) as the moment's tick drew
 * it: the moment's people where it recorded them, doing what it recorded (merged over the served
 * record, so every field the read's parser asks for stays), each with a step `walk_hint_m` long that
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
  // Indoors as the record says it: in its location where it has one, else on the person.
  const indoors = (person, inside) => (person.location && typeof person.location === 'object'
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
      ? [[east - ((east - from[0]) / along) * hint, south - ((south - from[1]) / along) * hint], [east, south]]
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
 * `side_degrees` unless given). Back far enough that the tallest subject (its drawn height, else
 * `subject_height_m`) fills `tallest_share` of the frame's height through the recipe's lens, and the
 * group with `room_m` beside it fits the frame's width, held between the least and most distance. At
 * eye height raised by `raise` metres, looking at `look_at_height_m` above their feet, turned so the
 * group's centre sits on a third of the frame (`third`: 1 the left third, -1 the right, 0 the
 * middle). Facing -z is yaw 0, as the controls turn. Null without a subject.
 */
export function framingPose(anchors, recipe = MOMENT_FRAMING, { side = recipe.side_degrees, raise = 0 } = {}) {
  const drawn = (anchors ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (drawn.length === 0) return null;
  const centre = drawn.reduce((sum, one) => ({ x: sum.x + one.x / drawn.length, y: sum.y + one.y / drawn.length, z: sum.z + one.z / drawn.length }), { x: 0, y: 0, z: 0 });
  const spread = Math.max(0, ...drawn.map((one) => Math.hypot(one.x - centre.x, one.z - centre.z))) * 2;
  const lens = lensOf(recipe);
  const d = recipe.distance_m;
  // The tallest as drawn where the anchors say (`height`, metres), else the recipe's figure.
  const heights = drawn.map((one) => one.height).filter((height) => finite(height) && height > 0);
  const tallest = heights.length > 0 ? Math.max(...heights) : recipe.subject_height_m;
  const byHeight = tallest / (recipe.tallest_share * 2 * Math.tan(lens.vertical));
  const byWidth = (spread + 2 * d.room_m) / (2 * Math.tan(lens.horizontal));
  const distance = Math.min(d.most, Math.max(d.least, byHeight, byWidth));
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
  const camera = { x: centre.x + view.x * distance, y: centre.y + recipe.eye_height_m + raise, z: centre.z + view.z * distance };
  const target = { x: centre.x, y: centre.y + recipe.look_at_height_m, z: centre.z };
  // Turning right (a smaller yaw) by a third of the half width puts the group on the left third.
  const thirdTurn = Math.atan(Math.tan(lens.horizontal) / 3) * Math.sign(recipe.third ?? 0);
  const yaw = Math.atan2(-(target.x - camera.x), -(target.z - camera.z)) - thirdTurn;
  const pitch = Math.atan2(target.y - camera.y, Math.hypot(target.x - camera.x, target.z - camera.z));
  return { x: camera.x, y: camera.y, z: camera.z, yaw, pitch };
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
 * The framing that sees the moment's subjects: the recipe's sides and raised heights (`sight`), each
 * judged by `seen(camera, point)` at every subject's feet, waist and head (`points_m` above where
 * they stand) and at the ground `ground_ahead_m` short of their middle toward the camera, and by
 * `covered(pose)`, the share of the frame something nearer than them covers (foregroundShare), at
 * most the recipe's `foreground.share`. A side from which any subject's face does not show (more
 * than `face_limit_deg` round from it, faceAngle) is never chosen. Of the rest, those that pass every
 * test, and of those the one that shows the faces best (the smallest worst face angle; the first of
 * equals); where none passes every test, the one that passes the most, then the faces. `seen` is the
 * scene's answer: whether nothing stands between the camera and the point. Null without a subject,
 * or where no side shows every face: the page keeps its quiet tile.
 * @param {(pose: { x: number, y: number, z: number, yaw: number, pitch: number }) => number} [covered]
 */
export function framingInSight(anchors, seen, recipe = MOMENT_FRAMING, covered = (_pose) => 0) {
  const drawn = (anchors ?? []).filter((one) => one && [one.x, one.y, one.z].every(finite));
  if (drawn.length === 0) return null;
  const subjects = drawn.flatMap((one) => recipe.sight.points_m.map((height) => ({ x: one.x, y: one.y + height, z: one.z })));
  const centre = drawn.reduce((sum, one) => ({ x: sum.x + one.x / drawn.length, y: sum.y + one.y / drawn.length, z: sum.z + one.z / drawn.length }), { x: 0, y: 0, z: 0 });
  // The ground in front of them, toward this camera, a little above it so the ground itself is no wall.
  const ahead = (pose) => {
    const dx = pose.x - centre.x, dz = pose.z - centre.z, length = Math.hypot(dx, dz) || 1;
    return (recipe.sight.ground_ahead_m ?? []).map((by) => ({ x: centre.x + (dx / length) * by, y: centre.y + 0.1, z: centre.z + (dz / length) * by }));
  };
  const limit = recipe.sight.face_limit_deg ?? 180;
  let best = null;
  for (const raise of recipe.sight.raise_m) {
    for (const side of recipe.sight.sides_degrees) {
      const pose = framingPose(drawn, recipe, { side, raise });
      const faces = drawn.map((one) => faceAngle(one, pose)).filter((angle) => angle !== null);
      const worst = faces.length > 0 ? Math.max(...faces) : 0;
      if (worst > limit) continue;
      const points = [...subjects, ...ahead(pose)];
      // Something near the camera over more than the recipe's share of the frame counts as one more unseen point.
      const clear = covered(pose) <= recipe.sight.foreground.share;
      const passed = points.filter((point) => seen(pose, point)).length + (clear ? 1 : 0);
      if (best === null || passed > best.passed || (passed === best.passed && worst < best.worst)) best = { pose, passed, worst };
    }
  }
  return best?.pose ?? null;
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
