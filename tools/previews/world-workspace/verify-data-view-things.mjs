// Checks data-view-things.mjs in Node: a made town's things and their words from its tiles' records, which kind
// of record a point stands on, where a tag hangs and which tags show. Run: node verify-data-view-things.mjs
import assert from 'node:assert/strict';
import { SPLIT, neededDensity, surfaceIndex, surfaceSamples, takenCount, trianglesNear } from './data-view-samples.mjs';
import { bigEnough, boxOfExtent, easedAlbedoChunk, creatureWords, keepStep, kindMaker, personLines, placeTags, pointBoxes, pointKinds, streetLine, surfaceOf, tagAnchors, thingWords, townThings, walkerBoxes } from './data-view-things.mjs';

const extent = (x0, y0, z0, x1, y1, z1) => ({ min_x_mm: x0, min_y_mm: y0, min_z_mm: z0, max_x_mm: x1, max_y_mm: y1, max_z_mm: z1 });
const record = (kind, identity, fields, membership = 'owned') => ({ kind, identity, membership, fields: { identity, ...fields } });

// Words, in the shipped catalogs' words: a premises by its use class ("residential" is home), a tree and a piece of
// furniture as build mode names them, in lower case where the catalog capitalises, a street by its own name.
assert.equal(thingWords(record('city.premises', 'a', { use_class: 'residential' })), 'home');
assert.equal(thingWords(record('city.premises', 'a', { use_class: 'cafe' })), 'cafe');
assert.equal(thingWords(record('city.premises', 'a', { use_class: 'not-a-use' })), null);
assert.equal(thingWords(record('city.street_tree', 'a', { species: 'fraxinus_pennsylvanica' })), 'street tree · green ash');
assert.equal(thingWords(record('city.street_tree', 'a', { species: 'not-a-species' })), 'street tree');
assert.equal(thingWords(record('city.street_furniture', 'a', { furniture_class: 'street_lamp' })), 'street lamp');
assert.equal(thingWords(record('city.street_furniture', 'a', { furniture_class: 'bench' })), 'bench');
assert.equal(thingWords(record('city.street', 'a', { name_text: 'Granary Way' })), 'street · Granary Way');
assert.equal(thingWords(record('city.street', 'a', { name_text: '  ' })), null);
assert.equal(thingWords(record('city.facade', 'a', {})), null);

// The renderer's frame: x east, z up and y north are its x, y and -z, in metres.
assert.deepEqual(boxOfExtent(extent(101337, 74400, 13458, 107181, 86403, 20212)), { min: [101.337, 13.458, -86.403], max: [107.181, 20.212, -74.4] });
assert.equal(boxOfExtent({ min_x_mm: 1 }), null);

// Things: owned records, and the streets every tile carries as halo, once each across tiles; a drawn range's own
// extent where one draws it, else the extent the record states (a street, drawn as its segments).
const home = record('city.premises', '11111111-1111-5111-8111-111111111111', { use_class: 'residential', extent: extent(0, 0, 0, 10000, 10000, 9000) });
const halo = record('city.street_tree', '22222222-2222-5222-8222-222222222222', { species: 'fraxinus_pennsylvanica', extent: extent(0, 0, 0, 1, 1, 1) }, 'halo');
const street = record('city.street', '33333333-3333-5333-8333-333333333333', { name_text: 'Granary Way', extent: extent(0, 53000, 7894, 256000, 74750, 8503) });
const facade = record('city.facade', '44444444-4444-5444-8444-444444444444', { extent: extent(0, 0, 0, 1, 1, 1) });
const ranges = [{ record: 0, state: 'drawn', extentMm: { min: [1000, 2000, 0], max: [9000, 9000, 8000] } }];
const things = townThings([{ records: [home, halo, street, facade], ranges }, { records: [home], ranges: [] }]);
assert.deepEqual(things.map((thing) => [thing.words, thing.hang]), [['home', 'face'], ['street · Granary Way', 'line']]);
assert.deepEqual([things[0].min, things[0].max], [[1, 0, -9], [9, 8, -2]]);
assert.equal(things[0].id, 'city.premises:11111111-1111-5111-8111-111111111111');
const haloStreet = record('city.street', '66666666-6666-5666-8666-666666666666', { name_text: 'Kiln Place', extent: extent(74600, 8000, 7800, 91400, 120000, 8400) }, 'halo');
assert.deepEqual(townThings([{ records: [halo, haloStreet], ranges: [] }, { records: [haloStreet], ranges: [] }]).map((thing) => thing.words), ['street · Kiln Place']);

// The boxes a point may stand in: a drawn range's own extent, a record no range draws by the extent it states, halo
// records and kinds no point stands on left out.
const lane = record('city.lane', '55555555-5555-5555-8555-555555555555', { extent: extent(0, 0, 0, 5000, 5000, 100) });
const boxes = pointBoxes([{ records: [facade, street, halo, home, lane], ranges: [{ record: 0, kind: 'city.facade', state: 'drawn', extentMm: { min: [0, 0, 0], max: [1, 1, 1] } }] }]);
assert.deepEqual(boxes.map((box) => box.kind), ['city.facade', 'city.street', 'city.premises', 'city.lane']);
assert.deepEqual([boxes[0].min, boxes[0].max], [[0, 0, -0.001], [0.001, 0.001, -0]]);

// Surfaces, by the names a town's meshes carry: a style pack's roles, the tile's own sets, the land; a tree's pit is
// ground, not a tree; the land's backdrop is its own surface (dark, no points); the sky and anything unnamed stay as they are.
assert.equal(surfaceOf('style-pack:wall.brick_running_bond', 'generated-tile:cc0.brick-running-bond'), 'wall');
assert.equal(surfaceOf('generated-tile:cc0.float-glazing', 'generated-tile:cc0.float-glazing'), 'wall');
assert.equal(surfaceOf('style-pack:swatch:glass_lit', 'style-pack:pieces'), 'wall');
assert.equal(surfaceOf('generated-tile:cc0.broadleaf-foliage', 'generated-tile:cc0.broadleaf-foliage'), 'plant');
assert.equal(surfaceOf('site-land:surfaces:town-land:ground', 'generated-tile:cc0.tree-pit-soil'), 'ground');
assert.equal(surfaceOf('site-land:surfaces:town-land:ground', 'site-land:chunk:0:1'), 'ground');
assert.equal(surfaceOf('style-pack:road.kerb_stone', 'generated-tile:cc0.kerb-stone'), 'kerb');
assert.equal(surfaceOf('style-pack:road.carriageway_asphalt', 'generated-tile:cc0.carriageway-asphalt'), 'road');
assert.equal(surfaceOf('style-pack:path.footway_paving', 'generated-tile:cc0.footway-paving'), 'path');
assert.equal(surfaceOf('Untitled', 'lamp'), 'furniture');
assert.equal(surfaceOf('style-pack:swatch:tyre', 'style-pack:vehicle.sedan'), 'vehicle');
assert.equal(surfaceOf('site-land:backdrop', 'site-land:backdrop'), 'backdrop');
assert.equal(surfaceOf('Untitled', 'district-sky-fill'), 'sky');
assert.equal(surfaceOf('Untitled', 'Untitled'), 'object');
assert.equal(surfaceOf('Untitled', 'wheel'), 'object');
assert.equal(surfaceOf('far-person:#603829#68543a#2a4c7b#3c556c#0f0d0f', 'character-far-body'), 'person');
assert.equal(surfaceOf('character:skin/young_asian_male', 'body'), 'person');

// A point takes the most particular box that holds it among the kinds its surface can be, else its surface's own.
const kinds = pointKinds([
  { kind: 'city.facade', min: [0, 0, -2], max: [10, 9, 0] },
  { kind: 'city.vitrine', min: [2, 0, -1], max: [4, 3, 0] },
  { kind: 'city.lane', min: [0, 0, 0], max: [10, 0.2, 6] },
  { kind: 'city.street_segment', min: [0, 0, 0], max: [20, 0.3, 10] },
]);
assert.equal(kinds.kindAt('wall', 3, 1, -0.5), 'city.vitrine');
assert.equal(kinds.kindAt('wall', 8, 6, -1), 'city.facade');
assert.equal(kinds.kindAt('wall', 40, 6, -1), 'city.massing');
assert.equal(kinds.kindAt('road', 5, 0.1, 3), 'city.lane');
assert.equal(kinds.kindAt('road', 15, 0.1, 8), 'city.street_segment');
assert.equal(kinds.kindAt('plant', 3, 1, -0.5), 'city.street_tree');
assert.equal(kinds.kindAt('vehicle', 3, 1, -0.5), 'object');

// A premises's tag hangs on a face it turns to the eye, nearest first, at its floor plus up to 2 m; anything else over its top.
const shop = { min: [0, 8, -20], max: [10, 13, -10], hang: 'face' };
assert.deepEqual(tagAnchors(shop, [5, 10, 0]), [[5, 10, -10]]);
assert.deepEqual(tagAnchors(shop, [20, 10, 0]).map((at) => at.map((v) => +v.toFixed(3))), [[10, 10, -15], [5, 10, -10]]);
assert.deepEqual(tagAnchors({ min: [0, 0, 0], max: [2, 6, 2], hang: 'top' }, [9, 9, 9]), [[1, 6, 1]]);
const line = streetLine({ min: [0, 7.9, -74.75], max: [256, 8.5, -53] }, 64);
assert.deepEqual(line.map((at) => at.map((v) => +v.toFixed(3))), [[32, 8.5, -63.875], [96, 8.5, -63.875], [160, 8.5, -63.875], [224, 8.5, -63.875]]);

// Tags: nearest first, none over another, none past the margin, at most `most`.
const tag = (key, x, y, distance) => ({ key, x, y, width: 100, height: 20, distance });
const shown = placeTags([tag('far', 10, 10, 30), tag('near', 50, 15, 5), tag('edge', 1890, 10, 1), tag('apart', 400, 10, 40)], { width: 1920, height: 1080, most: 2 });
assert.deepEqual(shown.map((one) => one.key), ['near', 'apart']);

// No tag covers a walker's face or body but its own walker's tag: a thing's tag moves to its next place clear of them,
// or shows not at all, and the nearer thing's tag is placed first.
const walker = walkerBoxes({ owner: 'person:a', x: 500, y: 400, distance: 10 }, 771);
assert.equal(walker.length, 1);
assert.ok(Math.abs(walker[0].height - 1.85 * 77.1) < 1e-6 && Math.abs(walker[0].x - (500 - 0.3 * 77.1)) < 1e-6);
const around = placeTags([
  { key: 'person:a', x: 470, y: 370, width: 60, height: 20, distance: 10 },
  { key: 'street', x: 480, y: 450, also: [{ x: 480, y: 500 }, { x: 800, y: 450 }], width: 120, height: 18, distance: 8 },
  { key: 'bin', x: 490, y: 500, width: 40, height: 18, distance: 12 },
], { width: 1920, height: 1080, blocked: walker });
assert.deepEqual(around.map((one) => [one.key, one.x, one.y]), [['street', 800, 450], ['person:a', 470, 370]]);

// A small thing far off drops its tag: a litter bin's half metre at 20 m is under 28 px; a bench's two metres is not.
assert.equal(bigEnough(0.5, 20, 771), false);
assert.equal(bigEnough(2, 20, 771), true);

// A person: their name, and the model that decides for them under it when one does.
assert.deepEqual(personLines({ name: 'Ines Varga', model: 'Nemotron 3 Super 120B' }), ['Ines Varga', 'Nemotron 3 Super 120B']);
assert.deepEqual(personLines({ name: 'Ines Varga', model: null }), ['Ines Varga']);
assert.deepEqual(personLines({ name: '' }), ['someone']);

// The GPU's share of the points, by measured frame time: down a quarter while a frame in four is slow, never below the
// floor; a step down kept only where the next frames are quicker, else undone and none tried for 30 s; up a seventh once
// nine in ten are quick and four seconds have passed since the last step down; too few frames change nothing.
const frames = (ms, count = 60) => Array.from({ length: count }, () => ms);
const slow = [...frames(16.7, 40), ...frames(33.3, 20)];
const step = (fields) => keepStep({ keep: 1, floor: 1 / 3, now: 9000, downAt: -Infinity, ...fields });
assert.deepEqual(step({ intervals: frames(16.7) }), { keep: 1, downAt: -Infinity, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ intervals: slow }), { keep: 0.75, downAt: 9000, tried: { keep: 1, slow: 33.3 }, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.75, intervals: frames(16.7), tried: { keep: 1, slow: 33.3 }, downAt: 9000 }), { keep: 0.75, downAt: 9000, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.75, intervals: slow, tried: { keep: 1, slow: 33.3 }, downAt: 8000 }), { keep: 1, downAt: 8000, tried: null, heldUntil: 39000 });
assert.deepEqual(step({ intervals: slow, heldUntil: 39000 }), { keep: 1, downAt: -Infinity, tried: null, heldUntil: 39000 });
assert.deepEqual(step({ keep: 0.4, intervals: frames(33.3), downAt: 0 }), { keep: 1 / 3, downAt: 9000, tried: { keep: 0.4, slow: 33.3 }, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 1 / 3, intervals: frames(33.3), downAt: 0 }), { keep: 1 / 3, downAt: 0, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.5, intervals: frames(16.7), downAt: 6000 }), { keep: 0.5, downAt: 6000, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.5, intervals: frames(16.7), downAt: 4000 }), { keep: 4 / 7, downAt: 4000, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.95, intervals: frames(8.3), downAt: 0 }), { keep: 1, downAt: 0, tried: null, heldUntil: -Infinity });
assert.deepEqual(step({ keep: 0.75, intervals: frames(33.3, 19), downAt: 0 }), { keep: 0.75, downAt: 0, tried: null, heldUntil: -Infinity });

// A creature its workspace made, from its kind's own record: its name over the model the record's origin says made it,
// as the models read names that model; where the record names no model, or no read names it, the plain words build
// mode calls it by, and "creature" until its label is read.
const nemotron = { kind: 'model', provider: 'nebius_token_factory', model_id: 'nvidia/nemotron-3-super-120b-a12b', prompt_version: 'creature-v1', prompt_sha256: null, words_sha256: null, execution_sha256: null };
const drafted = { label: 'Little yellow robot duck', origin: { profile: 'exulanica.origin/v1', class: 'drafted', by: nemotron } };
assert.deepEqual(kindMaker(drafted), { provider: 'nebius_token_factory', modelId: 'nvidia/nemotron-3-super-120b-a12b' });
assert.equal(kindMaker({ origin: { class: 'drafted', by: { ...nemotron, model_id: null } } }), null);
assert.equal(kindMaker({ origin: { class: 'authored', by: { kind: 'account', account_id: '44444444-4444-4444-8444-444444444444' } } }), null);
assert.equal(kindMaker({ label: 'Well' }), null);
assert.equal(kindMaker(null), null);
const models = [
  { provider: 'nebius_token_factory', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' },
  { provider: 'nebius_token_factory', modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' },
];
const duck = { source: 'workspace', sha256: 'a'.repeat(64) };
const duckLabel = (kind) => (kind === duck ? 'Little yellow robot duck' : null);
const made = (fields) => creatureWords({ kind: duck, name: 'Little yellow robot duck', maker: kindMaker(drafted), models, kindLabel: duckLabel, ...fields });
assert.deepEqual(made({}), { name: 'Little yellow robot duck', model: 'Nemotron 3 Super 120B' });
assert.deepEqual(personLines(made({ name: 'Little yellow robot duck 2' })), ['Little yellow robot duck 2', 'Nemotron 3 Super 120B']);
assert.deepEqual(made({ maker: null }), { name: 'little yellow robot duck', model: null });
assert.deepEqual(made({ models: null }), { name: 'little yellow robot duck', model: null });
assert.deepEqual(made({ maker: { provider: 'another_provider', modelId: 'nvidia/nemotron-3-super-120b-a12b' } }), { name: 'little yellow robot duck', model: null });
assert.deepEqual(made({ maker: { provider: null, modelId: 'nvidia/nemotron-3-super-120b-a12b' } }), { name: 'Little yellow robot duck', model: 'Nemotron 3 Super 120B' });
assert.deepEqual(made({ name: null, kindLabel: () => null }), { name: 'creature', model: null });

// A surface's samples, taken for the eye. A street 120 m long in 1 m squares, seen from 1.7 m over it looking along
// it, the way the point shader draws them (each drawn once its density is reached at its distance and its angle to
// the eye, counted by its depth along the view within the cone): as many points to the square pixel at the eye's feet
// as further out, within a band of the target, and a set taken for a far eye the same samples a near eye takes.
{
  const size = 120, corners = [], order = [];
  for (let z = 0; z <= size; z += 1) for (let x = 0; x <= 40; x += 1) corners.push(x - 20, 0, -z);
  for (let z = 0; z < size; z += 1) for (let x = 0; x < 40; x += 1) { const a = z * 41 + x; order.push(a, a + 1, a + 42, a, a + 42, a + 41); }
  const street = { positions: Float32Array.from(corners), indices: Uint32Array.from(order), matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], key: 3, kind: () => 'city.lane' };
  const eye = [0, 1.7, 0], pixels = 771.3, cone = Math.cos((30 * Math.PI) / 180);
  const look = { at: eye, pixels, density: 0.04, facingFloor: 0.15, cone, nearest: 2.5 };
  const near = surfaceSamples(street, { ...look, slack: 0.5, within: 8.5 }, { at: eye, ...SPLIT }, trianglesNear(surfaceIndex(street), eye, 8.5));
  const far = surfaceSamples(street, { ...look, slack: 8, within: Infinity, nearest: 32 }, { at: eye, ...SPLIT });
  // Drawn as the shader draws them: per band of 108 rows of a 1920 x 1080 frame, points to the square pixel.
  const bands = new Array(10).fill(0);
  for (const [{ groups }, from, to] of [[near, 0, 8], [far, 32, Infinity]]) {
    const group = groups.get('city.lane');
    for (let i = 0; i < group.densities.length; i += 1) {
      const x = group.positions[i * 3] - eye[0], y = group.positions[i * 3 + 1] - eye[1], z = group.positions[i * 3 + 2] - eye[2];
      const distance = Math.hypot(x, y, z), depth = -z;
      if (distance < from || distance >= to || depth <= 0.05) continue;
      const nearest = Math.max(distance, look.nearest);
      const want = look.density * pixels * pixels * Math.max(Math.abs(y) / distance, look.facingFloor) * nearest / Math.max(depth, cone * nearest) ** 3;
      if (group.densities[i] > want) continue;
      const row = 540 - (pixels * y) / depth, column = 960 + (pixels * x) / depth;
      if (row >= 0 && row < 1080 && column >= 480 && column < 1440) bands[Math.floor(row / 108)] += 1 / (960 * 108);
    }
  }
  // The rows the near set draws (the eye's feet, out to 8 m) as dense as the target, give or take a third.
  for (const band of bands.slice(7)) assert.ok(band > 0.04 * 0.67 && band < 0.04 * 1.5, `near band ${band}`);
  // The street further out (the far set), denser still where it lies edge on, never sparser than the target.
  assert.ok(bands[5] >= 0.04 * 0.67, `far band ${bands[5]}`);
  // The far eye's samples are the near eye's: every far sample of the first triangles is among the near ones, in place.
  const nearOnes = new Set(), farGroup = far.groups.get('city.lane'), nearGroup = near.groups.get('city.lane');
  for (let i = 0; i < nearGroup.densities.length; i += 1) nearOnes.add(nearGroup.positions.slice(i * 3, i * 3 + 3).join(',') + '@' + nearGroup.densities[i]);
  let shared = 0;
  for (let i = 0; i < farGroup.densities.length; i += 1) {
    const x = farGroup.positions[i * 3], z = farGroup.positions[i * 3 + 2];
    if (Math.hypot(x, z) > 6) continue;
    assert.ok(nearOnes.has(farGroup.positions.slice(i * 3, i * 3 + 3).join(',') + '@' + farGroup.densities[i]), 'a far sample is a near one');
    shared += 1;
  }
  assert.ok(shared > 100, `shared ${shared}`);
  // A part nothing sees has no samples, and a set reaches only the triangles near enough.
  const hidden = surfaceSamples({ ...street, hidden: () => true }, { ...look, slack: 0.5, within: 8.5 }, { at: eye, ...SPLIT });
  assert.equal(hidden.count, 0);
  assert.ok(trianglesNear(surfaceIndex(street), [0, 1.7, -200], 8).length === 0);
  // How many of a triangle's sequence a density takes, and the density a part needs, nearer and facing more.
  assert.equal(takenCount(2, 0.5, 0.2), 0);
  assert.equal(takenCount(2, 0.5, 1), 2);
  const need = (fields) => neededDensity({ distance: 10, facing: 0.5, slack: 1, pixels, density: 0.04, facingFloor: 0.15, nearest: 2.5, cone, ...fields });
  assert.ok(need({ distance: 5 }) > need({}) && need({ facing: 1 }) > need({}) && need({ slack: 3 }) > need({}));
  // Nothing nearer than `nearest` is asked denser than there.
  assert.equal(need({ distance: 0.5, facing: 1 }), need({ distance: 2, facing: 1 }));
}

// A colour chunk of a material's own, eased whole in its dark copy: its one colour function renamed and called first,
// then all it made eased by the data view's uniform, so a band of colour it mixes in (the land's rock on a slope) goes
// dark with the rest; a chunk with no one colour function is left as it is.
{
  const land = 'uniform vec3 material_diffuse;\nvoid exuLandBase() {\n\tdAlbedo = material_diffuse.rgb;\n}\nvoid getAlbedo() {\n\texuLandBase();\n\tdAlbedo = mix(dAlbedo, vec3(0.42, 0.3, 0.2), slope);\n}\n';
  const eased = easedAlbedoChunk(land);
  assert.ok(eased.startsWith('uniform vec3 material_diffuse;'));
  assert.equal(eased.split('void getAlbedo() {').length, 2);
  assert.ok(eased.includes('void exuDataViewAlbedo() {\n\texuLandBase();\n\tdAlbedo = mix(dAlbedo, vec3(0.42, 0.3, 0.2), slope);'));
  assert.ok(eased.trimEnd().endsWith('void getAlbedo() {\n\texuDataViewAlbedo();\n\tdAlbedo *= uDataViewAlbedo;\n}'));
  assert.ok(eased.indexOf('uniform float uDataViewAlbedo;') > eased.indexOf('void exuDataViewAlbedo() {'));
  assert.equal(easedAlbedoChunk('void main() {}'), null);
  assert.equal(easedAlbedoChunk(land + land), null);
  assert.equal(easedAlbedoChunk(undefined), null);
}

console.log('data-view-things: all checks pass');
