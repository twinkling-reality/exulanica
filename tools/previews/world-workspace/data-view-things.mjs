/**
 * A made town in the data view, as data in and data out: the things a person names (a home or a shop,
 * a street tree, a bench or a street lamp, a street), each with its box and its words, read from the
 * records of the town's own tiles; which kind of record a point drawn on the town's surfaces stands on;
 * where a thing's tag may hang; and which tags show. Pure, so verify-data-view-things.mjs checks it in
 * Node; world-data-view.ts draws it.
 *
 * Words come from the shipped catalogs: a premises by its use class's label in the society's catalog
 * (residential is "home"), a street tree and a piece of street furniture as build mode names them
 * (town-thing-names.mjs), a street by the name it states.
 */
import uses from '../../../assets/catalogs/society/society-use-class.v3.json' with { type: 'json' };
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

/** What a point stands on where no box holds it, by its surface. */
export const POINT_FALLBACK = Object.freeze({
  wall: 'city.massing', road: 'city.lane', path: 'city.street_segment', kerb: 'city.curb_edge',
  plant: 'city.street_tree', furniture: 'city.street_furniture', ground: 'city.terrain', vehicle: 'object',
});

/**
 * Which surface a drawn mesh is, from its material's and its entity's names, or null for one the data
 * view leaves as it is (the sky, a person): a style pack names its materials by role
 * ("style-pack:wall.brick_running_bond", "style-pack:road.kerb_stone"), the tile its own sets
 * ("generated-tile:cc0.broadleaf-foliage"). The land's backdrop, beyond the town, goes dark with the
 * rest and has no points of its own.
 */
export function surfaceOf(material = '', entity = '') {
  const name = `${entity} ${material}`;
  if (/backdrop/u.test(name)) return 'backdrop';
  if (/sky/u.test(name)) return null;
  if (/style-pack:vehicle\./u.test(name)) return 'vehicle';
  // The ground first: a tree's pit is ground, and the land's own surfaces and its water are.
  if (/town-land|site-land|tree-pit|water/u.test(name)) return 'ground';
  if (/foliage|bark/u.test(name)) return 'plant';
  if (/kerb|curb/u.test(name)) return 'kerb';
  if (/carriageway|asphalt|road\./u.test(name)) return 'road';
  if (/footway|path\./u.test(name)) return 'path';
  if (/(^|\s)(lamp|post)(\s|$)|furniture/u.test(name)) return 'furniture';
  if (/wall\.|roof\.|glazing|storefront|swatch:(frame|glass)/u.test(name)) return 'wall';
  return null;
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
  const grid = new Map();
  const key = (i, k) => `${i},${k}`;
  for (const box of boxes) {
    for (let i = Math.floor((box.min[0] - pad) / cell); i <= Math.floor((box.max[0] + pad) / cell); i += 1) {
      for (let k = Math.floor((box.min[2] - pad) / cell); k <= Math.floor((box.max[2] + pad) / cell); k += 1) {
        const at = key(i, k);
        if (!grid.has(at)) grid.set(at, []);
        grid.get(at).push(box);
      }
    }
  }
  return {
    kindAt(surface, x, y, z) {
      const kinds = POINT_KINDS[surface] ?? [];
      const near = grid.get(key(Math.floor(x / cell), Math.floor(z / cell))) ?? [];
      let best = null, rank = Infinity;
      for (const box of near) {
        const order = kinds.indexOf(box.kind);
        if (order < 0 || order >= rank) continue;
        if (x < box.min[0] - pad || x > box.max[0] + pad || y < box.min[1] - pad || y > box.max[1] + pad || z < box.min[2] - pad || z > box.max[2] + pad) continue;
        best = box.kind; rank = order;
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
 * Which tags show: nearest first, none over another (`gap` pixels apart) and none past the screen's
 * `margin`, at most `most`. `tags`: [{ key, x, y, width, height, distance }], x and y the tag's top left
 * in CSS pixels; the screen is `width` by `height`. Answers the tags kept, nearest first.
 */
export function placeTags(tags, { width, height, margin = 8, gap = 4, most = 48 }) {
  const kept = [];
  for (const tag of [...tags].sort((a, b) => a.distance - b.distance)) {
    if (kept.length >= most) break;
    if (tag.x < margin || tag.y < margin || tag.x + tag.width > width - margin || tag.y + tag.height > height - margin) continue;
    const over = kept.some((other) => tag.x < other.x + other.width + gap && tag.x + tag.width + gap > other.x
      && tag.y < other.y + other.height + gap && tag.y + tag.height + gap > other.y);
    if (!over) kept.push(tag);
  }
  return kept;
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
