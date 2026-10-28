/**
 * A made town in the data view, as data in and data out: the things a person names (a home or a shop,
 * a street tree, a bench or a street lamp, a street), each with its box and its words, read from the
 * records of the town's own tiles; which kind of record a point drawn on the town's surfaces stands on;
 * where a thing's tag may hang; and which tags show. Pure, so verify-data-view-things.mjs checks it in
 * Node; world-data-view.ts draws it.
 *
 * Words come from the shipped catalogs: a premises by its use class's label in the society's catalog
 * (residential is "home"), a street tree and a piece of street furniture as build mode names them
 * (town-thing-names.mjs), a street by the name it states. A creature its workspace made is named from
 * its kind's own record, with the model that made it.
 */
import uses from '../../../assets/catalogs/society/society-use-class.v3.json' with { type: 'json' };
import { thingName } from './build-words.mjs';
import { townThingName } from './town-thing-names.mjs';

const USE_WORDS = new Map(uses.entries.map((entry) => [entry.key, entry.label]));

/** A record's stated millimetres (x east, y north, z up) in the renderer's metres (x, y up, z south). */
export function boxOfExtent(extent) {
  if (!extent || ![extent.min_x_mm, extent.min_y_mm, extent.min_z_mm, extent.max_x_mm, extent.max_y_mm, extent.max_z_mm].every(Number.isFinite)) return null;
  return {
    min: [extent.min_x_mm / 1000, extent.min_z_mm / 1000, -extent.max_y_mm / 1000],
    max: [extent.max_x_mm / 1000, extent.max_z_mm / 1000, -extent.min_y_mm / 1000],
  };
}

/** A drawn range's own extent ({ min, max } in the same millimetres) as a box in the renderer's metres. */
function boxOfDrawn(extentMm) {
  if (!extentMm?.min || !extentMm?.max) return null;
  const [x0, y0, z0] = extentMm.min, [x1, y1, z1] = extentMm.max;
  return boxOfExtent({ min_x_mm: x0, min_y_mm: y0, min_z_mm: z0, max_x_mm: x1, max_y_mm: y1, max_z_mm: z1 });
}

const lowerFirst = (words) => words.slice(0, 1).toLowerCase() + words.slice(1);

/**
 * What a record is called in its tag, or null for a record that is not a thing a person names (a
 * facade, a lane, the ground): "home" or "cafe", "street tree · green ash", "street lamp",
 * "street · Granary Way".
 */
export function thingWords(record) {
  const fields = record?.fields ?? {};
  if (record?.kind === 'city.premises') return USE_WORDS.get(fields.use_class) ?? null;
  if (record?.kind === 'city.street_tree') {
    const name = townThingName(record);
    return name === 'Street tree' ? 'street tree' : `street tree · ${name}`;
  }
  if (record?.kind === 'city.street_furniture') return lowerFirst(townThingName(record));
  if (record?.kind === 'city.street') return typeof fields.name_text === 'string' && fields.name_text.trim() ? `street · ${fields.name_text.trim()}` : null;
  return null;
}

/**
 * Where a thing's tag hangs: a premises on a face it turns to the eye, at its own floor and up to 2 m
 * above; a street along its middle line; anything else over its top.
 */
export const TAG_HANG = Object.freeze({ 'city.premises': 'face', 'city.street': 'line' });

/**
 * Every thing of a town's tiles the data view boxes and tags, once each: `tiles` is each tile's header
 * records and drawn ranges ({ records, ranges }); a drawn range gives its record's own drawn extent, a
 * record no range draws (a street, drawn as its segments) the extent it states. A tile's halo records are
 * its neighbours' and are left to them, except a street: no tile owns a street, every tile its segments
 * cross carries it as halo, and its segments are what is drawn. Each thing is
 * { id, kind, words, min, max, hang }, `id` the record's kind and identity.
 * @returns {Array<{ id: string, kind: string, words: string, min: number[], max: number[], hang: string }>}
 */
export function townThings(tiles) {
  const things = new Map();
  for (const { records = [], ranges = [] } of tiles) {
    const drawn = new Map();
    for (const range of ranges) if (range?.state === 'drawn') drawn.set(range.record, range);
    records.forEach((record, index) => {
      if (record?.membership === 'halo' && record?.kind !== 'city.street') return;
      const words = thingWords(record);
      const identity = record?.fields?.identity ?? record?.identity;
      if (words === null || typeof identity !== 'string') return;
      const id = `${record.kind}:${identity}`;
      if (things.has(id)) return;
      const range = drawn.get(index);
      const box = range ? boxOfDrawn(range.extentMm) : boxOfExtent(record.fields?.extent);
      if (box === null) return;
      things.set(id, { id, kind: record.kind, words, min: box.min, max: box.max, hang: TAG_HANG[record.kind] ?? 'top' });
    });
  }
  return [...things.values()];
}

/**
 * The record kinds a point on a town's surfaces may stand on, the most particular first: a point
 * takes the first whose box holds it among the kinds its surface can be.
 */
export const POINT_KINDS = Object.freeze({
  wall: Object.freeze(['city.vitrine', 'city.entrance', 'city.ground_bay', 'city.rooftop_object', 'city.facade', 'city.premises', 'city.massing']),
  road: Object.freeze(['city.crossing', 'city.lane', 'city.junction', 'city.street_segment', 'city.street']),
  path: Object.freeze(['city.street_segment', 'city.street']),
  kerb: Object.freeze(['city.curb_edge']),
  plant: Object.freeze(['city.street_tree']),
  furniture: Object.freeze(['city.street_furniture']),
  ground: Object.freeze(['city.parcel', 'city.block', 'city.terrain']),
});

/**
 * What a point stands on where no box holds it, by its surface: the land beyond the town is the land's, its water
 * the land's water (no record of a town's tiles states water, so no box holds a point on it), a walker drawn from
 * afar is a person, and anything the names do not tell is an object.
 */
export const POINT_FALLBACK = Object.freeze({
  wall: 'city.massing', road: 'city.lane', path: 'city.street_segment', kerb: 'city.curb_edge',
  plant: 'city.street_tree', furniture: 'city.street_furniture', ground: 'city.terrain', water: 'land.water',
  vehicle: 'object', backdrop: 'city.terrain', person: 'person', object: 'object',
});

/**
 * The look's ground beyond a town on level ground: one plane round the world, kilometres wide, below every street
 * (generated-tile/environment.ts). A town on its own land draws none.
 */
export const EDGE = /generated-tile:edge-ground/u;

/**
 * What the look's ground beyond a town on level ground (EDGE) stands for: the sea where the world's setting is by the
 * sea (its ground part "sea": "open sea beyond the last street", setting-parts.v4.json), else the ground. `setting`:
 * the world's own setting (exulanica.world-setting/v1), or anything else where it states none.
 */
export function edgeOf(setting) {
  const parts = setting !== null && typeof setting === 'object' && Array.isArray(setting.parts) ? setting.parts : [];
  return parts.some((part) => part?.axis === 'ground' && part?.key === 'sea') ? 'water' : 'ground';
}

/**
 * Which surface a drawn mesh is, from its material's and its entity's names: a style pack names its materials by
 * role ("style-pack:wall.brick_running_bond", "style-pack:road.kerb_stone"), the tile its own sets
 * ("generated-tile:cc0.broadleaf-foliage"). Every surface goes to data: the land's backdrop, beyond the town, as
 * the land; its water (the sea, a lake, a cascade's pools and falls, "site-land:water:sea", as the land draws it
 * or a style pack dresses it, "style-pack:land-water:sea:sea", and a pack's own water, "style-pack:material:water.sea")
 * as water; the look's ground beyond a town on level ground (EDGE) as `edge` says (edgeOf); a walker drawn from afar
 * as a person; one the names do not tell as an object; and the sky goes dark with no points of its own.
 */
export function surfaceOf(material = '', entity = '', edge = 'ground') {
  const name = `${entity} ${material}`;
  if (/backdrop/u.test(name)) return 'backdrop';
  if (/sky/u.test(name)) return 'sky';
  if (/far-person|character-far-body|(^|\s)character:/u.test(name)) return 'person';
  if (/style-pack:vehicle\./u.test(name)) return 'vehicle';
  if (EDGE.test(name)) return edge;
  if (/site-land:water|land-water|(^|[\s:])water\./u.test(name)) return 'water';
  // The ground first: a tree's pit is ground, and the land's own surfaces are.
  if (/town-land|site-land|tree-pit/u.test(name)) return 'ground';
  if (/foliage|bark/u.test(name)) return 'plant';
  if (/kerb|curb/u.test(name)) return 'kerb';
  if (/carriageway|asphalt|road\./u.test(name)) return 'road';
  if (/footway|path\./u.test(name)) return 'path';
  if (/(^|\s)(lamp|post)(\s|$)|furniture/u.test(name)) return 'furniture';
  if (/wall\.|roof\.|glazing|storefront|swatch:(frame|glass)/u.test(name)) return 'wall';
  return 'object';
}

/**
 * The boxes a point may stand in, from a town's tiles ({ records, ranges }): each drawn range's own drawn extent,
 * and the extent each record of a kind a point may stand on states where no range draws it (a street, a block,
 * a parcel), each { kind, min, max } in the renderer's metres.
 */
export function pointBoxes(tiles) {
  const kinds = new Set(Object.values(POINT_KINDS).flat());
  const boxes = [];
  for (const { records = [], ranges = [] } of tiles) {
    const drawn = new Set();
    for (const range of ranges) {
      if (range?.state !== 'drawn' || !kinds.has(range.kind)) continue;
      const box = boxOfDrawn(range.extentMm);
      if (box !== null) { boxes.push({ kind: range.kind, ...box }); drawn.add(range.record); }
    }
    records.forEach((record, index) => {
      if (drawn.has(index) || record?.membership === 'halo' || !kinds.has(record?.kind)) return;
      const box = boxOfExtent(record.fields?.extent);
      if (box !== null) boxes.push({ kind: record.kind, ...box });
    });
  }
  return boxes;
}

/**
 * The records' boxes by kind on a grid in plan (`cell` metres), so a point asks only the boxes near it.
 * `boxes`: [{ kind, min, max }]. Answers kindAt(surface, x, y, z): the kind of the first box holding
 * the point (within `pad` metres) among those its surface can be, else the surface's fallback.
 */
export function pointKinds(boxes, { cell = 8, pad = 0.15 } = {}) {
  // Each box holds, for every surface, how particular its kind is there (its place in POINT_KINDS, or none), so a
  // point asks numbers, not words.
  const surfaces = Object.keys(POINT_KINDS);
  const grid = new Map();
  const key = (i, k) => (i + 32768) * 65536 + (k + 32768);
  for (const box of boxes) {
    const held = { kind: box.kind, min: box.min, max: box.max, rank: surfaces.map((surface) => POINT_KINDS[surface].indexOf(box.kind)) };
    for (let i = Math.floor((box.min[0] - pad) / cell); i <= Math.floor((box.max[0] + pad) / cell); i += 1) {
      for (let k = Math.floor((box.min[2] - pad) / cell); k <= Math.floor((box.max[2] + pad) / cell); k += 1) {
        const at = key(i, k);
        if (!grid.has(at)) grid.set(at, []);
        grid.get(at).push(held);
      }
    }
  }
  return {
    kindAt(surface, x, y, z) {
      const which = surfaces.indexOf(surface);
      const near = which < 0 ? undefined : grid.get(key(Math.floor(x / cell), Math.floor(z / cell)));
      let best = null, rank = Infinity;
      if (near !== undefined) {
        for (const box of near) {
          const order = box.rank[which];
          if (order < 0 || order >= rank) continue;
          if (x < box.min[0] - pad || x > box.max[0] + pad || y < box.min[1] - pad || y > box.max[1] + pad || z < box.min[2] - pad || z > box.max[2] + pad) continue;
          best = box.kind; rank = order;
          if (order === 0) break;
        }
      }
      return best ?? POINT_FALLBACK[surface] ?? null;
    },
  };
}

/**
 * The points a thing's tag may hang from, nearest the eye first. A premises: the middle of each face
 * it turns to the eye, at its own floor and up to 2 m above. Anything else: the middle of its top.
 */
export function tagAnchors(thing, eye) {
  const middle = [0, 1, 2].map((axis) => (thing.min[axis] + thing.max[axis]) / 2);
  if (thing.hang !== 'face') return [[middle[0], thing.max[1], middle[2]]];
  const height = thing.min[1] + Math.min(2, (thing.max[1] - thing.min[1]) / 2);
  const faces = [];
  for (const axis of [0, 2]) {
    for (const [face, side] of [[thing.min[axis], -1], [thing.max[axis], 1]]) {
      if ((eye[axis] - face) * side <= 0) continue;
      const at = [middle[0], height, middle[2]];
      at[axis] = face;
      faces.push(at);
    }
  }
  const away = (at) => Math.hypot(at[0] - eye[0], at[1] - eye[1], at[2] - eye[2]);
  return faces.sort((a, b) => away(a) - away(b));
}

/**
 * Points along a street's middle line every `step` metres, at the top of what it states (its kerbs' height, over
 * its carriageway): where its tag may hang, never under the road it names.
 */
export function streetLine(thing, step = 4) {
  const along = thing.max[0] - thing.min[0] >= thing.max[2] - thing.min[2] ? 0 : 2;
  const across = 2 - along;
  const length = thing.max[along] - thing.min[along];
  const count = Math.max(2, Math.floor(length / step));
  return Array.from({ length: count }, (_, index) => {
    const at = [0, thing.max[1], 0];
    at[along] = thing.min[along] + (length * (index + 0.5)) / count;
    at[across] = (thing.min[across] + thing.max[across]) / 2;
    return at;
  });
}

/**
 * Which tags show and where: nearest first, each at the first of its places (its own top left `x` and `y`, then each
 * of `also`) that lies within the screen's `margin`, over no tag kept before it (`gap` pixels apart) and over none of
 * the `blocked` boxes (a walker's face and body) but its own (a box's `owner` is the key of the tag it may carry), at
 * most `most`. `tags`: [{ key, x, y, also?, width, height, distance }] in CSS pixels; the screen is `width` by
 * `height`. Answers the tags kept, nearest first, each at the place it was kept at.
 */
export function placeTags(tags, { width, height, margin = 8, gap = 4, most = 48, blocked = [] }) {
  const kept = [];
  const over = (a, b, pad) => a.x < b.x + b.width + pad && a.x + a.width + pad > b.x && a.y < b.y + b.height + pad && a.y + a.height + pad > b.y;
  for (const tag of [...tags].sort((a, b) => a.distance - b.distance)) {
    if (kept.length >= most) break;
    for (const at of [{ x: tag.x, y: tag.y }, ...(tag.also ?? [])]) {
      const box = { ...tag, x: at.x, y: at.y };
      if (box.x < margin || box.y < margin || box.x + box.width > width - margin || box.y + box.height > height - margin) continue;
      if (kept.some((other) => over(box, other, gap)) || blocked.some((one) => one.owner !== tag.key && over(box, one, 0))) continue;
      kept.push(box);
      break;
    }
  }
  return kept;
}

/**
 * The boxes no other tag may cover for a walker seen at `head` (the point just over their head, CSS pixels and its
 * distance in metres) with `pixels` CSS pixels to the radian: their face, and their body down to their feet, each a
 * walker's width across (`wide` metres) and their height (`tall` metres) seen from where they stand.
 */
export function walkerBoxes({ owner, x, y, distance }, pixels, { wide = 0.6, tall = 1.85 } = {}) {
  const scale = pixels / Math.max(distance, 0.5);
  const width = wide * scale, height = tall * scale;
  return [{ owner, x: x - width / 2, y, width, height }];
}

/** Whether a thing seen `distance` metres away, `size` metres across at most, stands at least `least` CSS pixels across. */
export function bigEnough(size, distance, pixels, least = 28) {
  return (size * pixels) / Math.max(distance, 0.5) >= least;
}

/**
 * A person's tag: their name, and under it the model that decides for them when one does (the words
 * the look tag uses for who decides), else nothing under it.
 */
export function personLines({ name, model = null }) {
  const lines = [typeof name === 'string' && name.trim() ? name.trim() : 'someone'];
  if (typeof model === 'string' && model.trim()) lines.push(model.trim());
  return lines;
}

/**
 * The share of a town's points the GPU draws, stepped by its measured frame time (`intervals`: ms between drawn frames
 * since the last step): down by a quarter while one frame in four takes longer than `slowMs`, never below `floor` (the
 * share that draws as many points as before version 3 of the style); up by a seventh, never above 1, once nine in ten
 * come within `fastMs` and `settleMs` have passed since it last stepped down. A step down is a trial (`tried`): where
 * the next frames are not quicker by a millisecond, the points were not what made them slow, so the share goes back
 * and no step down is tried again for `holdMs`. Fewer than 20 intervals change nothing.
 */
export function keepStep({ keep, floor, intervals, now, downAt, tried = null, heldUntil = -Infinity, slowMs = 18.5, fastMs = 17.2, settleMs = 4000, holdMs = 30000 }) {
  const same = { keep, downAt, tried, heldUntil };
  if (intervals.length < 20) return same;
  const sorted = [...intervals].sort((a, b) => a - b);
  const share = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  if (tried !== null) {
    if (share(0.75) < tried.slow - 1) return { keep, downAt, tried: null, heldUntil };
    return { keep: tried.keep, downAt, tried: null, heldUntil: now + holdMs };
  }
  if (share(0.75) > slowMs && keep > floor && now >= heldUntil) return { keep: Math.max(floor, keep * 0.75), downAt: now, tried: { keep, slow: share(0.75) }, heldUntil };
  if (share(0.9) <= fastMs && keep < 1 && now - downAt >= settleMs) return { keep: Math.min(1, keep * 8 / 7), downAt, tried: null, heldUntil };
  return same;
}

/**
 * The model a kind's own record says made it: its origin's maker (exulanica.origin/v1's `by`) where a model made the
 * kind and the record names which, by provider and identifier; null where it names none (an older record names its
 * model only through its receipts) or a person or a program made it.
 */
export function kindMaker(document) {
  const by = document?.origin?.by;
  if (by?.kind !== 'model' || typeof by.model_id !== 'string' || !by.model_id.trim()) return null;
  return { provider: typeof by.provider === 'string' && by.provider ? by.provider : null, modelId: by.model_id };
}

/**
 * A creature its workspace made, in a person's tag (personLines), from its own records: its name as the page calls it
 * ("Little yellow robot duck") over the model its kind's record says made it (kindMaker), named as the models read
 * names that model ("Nemotron 3 Super 120B"). Where the record names no model, or no read names it, the plain words
 * build mode calls it by (thingName: "little yellow robot duck", "creature" until its label is read), alone.
 */
export function creatureWords({ kind, name, maker, models, kindLabel }) {
  const model = maker ? (models ?? []).find((one) => one.modelId === maker.modelId && (maker.provider === null || one.provider === maker.provider))?.name : null;
  return typeof model === 'string' && model && typeof name === 'string' && name ? { name, model } : { name: thingName({ kind }, kindLabel), model: null };
}

/**
 * A dark copy's colour chunk eased whole, or null where the chunk has no one colour function: where a material's own
 * colour chunk mixes colours of its own over its colour (the land's bands of sand, planting and rock on its slopes,
 * land-slope.ts), darkening its colour leaves those colours standing. The chunk's colour function is renamed and
 * called first, and whatever it made is then eased toward none by `uDataViewAlbedo`, which the data view sets.
 */
export function easedAlbedoChunk(chunk) {
  const colour = 'void getAlbedo() {';
  if (typeof chunk !== 'string' || chunk.split(colour).length !== 2) return null;
  return `${chunk.replace(colour, 'void exuDataViewAlbedo() {')}
uniform float uDataViewAlbedo;
void getAlbedo() {
\texuDataViewAlbedo();
\tdAlbedo *= uDataViewAlbedo;
}
`;
}
