/**
 * The visual gate harness: walk the product, measure what it drew, capture what a person saw.
 *
 *   cd web && npx tsx ../scripts/capture_visual_gate.mjs --out <scratch dir> --label run-1
 *
 * It opens the running application at 1440 by 900 in headless Chrome over the DevTools protocol,
 * with no package beyond Node's own WebSocket, and never substitutes a page or a handler:
 *
 *   1. waits for the product's own shell to mount a world, and halts on a credential gate, an
 *      empty world or an error surface rather than scoring something else;
 *   2. turns the player to the route heading by writing the controls' yaw, the one value mouse
 *      look would have written, and never writes a position;
 *   3. at the start, midpoint and endpoint, summons the Companion with a trusted X key and
 *      captures the shell with the Companion and the reticle on screen;
 *   4. between captures, dismisses the Companion with a trusted Escape, because the product gives
 *      the keyboard to one owner at a time and walking is off while the Companion is open; gives
 *      the world canvas focus with a trusted click when it does not have it, the gesture the
 *      product's own arrival prompt asks for ("Click to enter"), because keyboard walking without
 *      pointer lock needs that focus; and walks with trusted W key events through the product's
 *      own movement, collision and support resolution, recording every frame of the live player
 *      state;
 *   5. reads the drawn triangles, the listeners on the window, the document and the canvas, the
 *      product's own validation report and the network, and measures the eight mechanical keys
 *      with @exulanica/loom-gate. The judged key is left for the named human judge.
 *
 * It reads no credential and writes none. The API's refusal of an anonymous read is probed
 * without one, and request headers are never recorded.
 *
 * WHICH PAGE IT SCORED is stated by --target, and the page is checked against that target's own
 * rule: its path, the parameters it is reached with, and the exact title the PRODUCT states for it
 * (read from the product's source, never written here). A page that matches no target, a title that
 * cannot be derived, a pose the run chose rather than one a committed file states, a page that
 * states no way to read the rings its tile carries, or a route rule with no rings to choose between
 * all halt rather than scoring something easier, and the last two are separate halts because a page
 * that was never asked and a tile that states none are different facts.
 * The targets are declared in TARGETS below and in
 * exulanica/evaluation/gate_keys.py, and a test holds the two lists to each other.
 *
 * Environment it needs: the app dev server (default http://127.0.0.1:5188/) proxying /api to a
 * running API. Exit 0 with a run record, 3 with halt.json when a precondition of the gate fails.
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  CAPTURE_LABELS,
  GATE_KEY_SET_VERSION,
  MELBOURNE_ENVELOPE,
  ROUTE_RULE,
  THRESHOLDS,
  keySet,
  measureScene,
  mechanicalMeasurements,
  planRoute,
  rankedRoutes,
} from '../web/packages/loom-gate/src/index.ts';
import { OWD_MAGIC, decodeOwd } from '../web/packages/loom-tess/src/core/index.ts';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWPORT = Object.freeze({ width: 1440, height: 900 });

/**
 * The pages this harness may score, and how each is recognised.
 *
 * A target is a page plus the conditions that make a run of it comparable to another run of the
 * same page. It is a closed list for the reason the record's list is: a pattern would let the next
 * page through for free. `exulanica/evaluation/gate_keys.py` declares the same two, and
 * `tests/test_visual_gate_targets.py` holds the two lists to each other in both directions, so
 * neither can gain a target the other does not have.
 *
 * No title is written here. Each is read from the product's own source, so a page check cannot
 * drift from what the product shows, and a target whose title cannot be found halts rather than
 * comparing against nothing: an empty expectation equals an empty title.
 */
const TARGETS = Object.freeze({
  'owned-district': Object.freeze({
    path: '/',
    requiredParameters: Object.freeze([]),
    selectorParameters: Object.freeze([]),
    titleSymbol: 'PRODUCT_TITLE',
    binds: 'owned-district-artifact',
  }),
  'generated-tile-evaluation': Object.freeze({
    path: '/',
    requiredParameters: Object.freeze(['preview']),
    selectorParameters: Object.freeze(['tile', 'baked_tile', 'city']),
    titleSymbol: 'PREVIEW_TITLE',
    binds: 'tile-containers',
  }),
});

const TITLE_SOURCE = 'web/packages/app/src/config.ts';

/** The title the product itself states for a target, or a halt naming what it looked for. */
function titleOf(target) {
  const source = readFileSync(join(ROOT, TITLE_SOURCE), 'utf8');
  const pattern = new RegExp(`const ${TARGETS[target].titleSymbol} = '([^']+)';`);
  const found = pattern.exec(source);
  if (found === null) {
    throw new Halt(
      `${TITLE_SOURCE} no longer states ${TARGETS[target].titleSymbol}, so there is no title to ` +
      'check the page against; the gate will not fall back to a literal',
    );
  }
  return found[1];
}

class Halt extends Error {}

/**
 * What a run has established by the time it stops, written beside a halt as well as beside a record.
 *
 * A halt that says only why it stopped is a reason with no subject: the next reader cannot tell
 * which page it was pointed at or which tile it had loaded, and a figure with no identity beside it
 * becomes a claim about "the conformance tile" that means a different tile next week.
 */
const observed = {};

/** The four values a stated walk is made of, in the frame the file states them in. */
const WALK_PARAMETERS = Object.freeze(['pose_x_mm', 'pose_y_mm', 'facing_dx', 'facing_dy']);

/**
 * The walk a committed file states: integer millimetres of the city frame and an integer facing,
 * read out of the preview route the file writes.
 *
 * Strict because the file is prose. A reader that took the first thing it recognised would take a
 * pose from an example, from a superseded paragraph or from a second walk, and nothing downstream
 * could tell. Zero refuses, more than one distinct pose refuses, and both refusals say what was
 * found. It does not re-state the product's own rules about what a pose may be: the product refuses
 * a malformed one, and a gate that repeats those rules here would be a second source for them.
 */
export function statedWalkOf(text) {
  const found = new Map();
  for (const run of text.matchAll(/[^\s`'"]*pose_x_mm=[^\s`'"]*/g)) {
    const query = run[0].includes('?') ? run[0].slice(run[0].indexOf('?') + 1) : run[0];
    const parameters = new URLSearchParams(query);
    const values = WALK_PARAMETERS.map((name) => parameters.get(name));
    if (values.some((value) => value === null || !/^-?\d+$/.test(value))) continue;
    found.set(values.join(','), values.map(Number));
  }
  if (found.size === 0) {
    throw new Halt(
      `no walk is stated there: nothing in the file states all of ${WALK_PARAMETERS.join(', ')} as whole numbers`,
    );
  }
  if (found.size > 1) {
    throw new Halt(
      `${found.size} different walks are stated there (${[...found.keys()].join(' and ')}); a scored ` +
      'run will not choose between them',
    );
  }
  const [xMm, yMm, facingDx, facingDy] = [...found.values()][0];
  return { xMm, yMm, facingDx, facingDy };
}

/**
 * The rectangle a walk is bounded by, as the four values the route rule declares, and refused when
 * it bounds nothing.
 *
 * TWO DIFFERENT FAULTS HERE AND NEITHER GUARD CATCHES THE OTHER, which is why both are written.
 *
 * A SHORT array is a type fault. `planRoute` declares exactly four values; an array of unknown
 * length can carry three, and the fourth is then `undefined`, which a bounds test reads as no bound
 * at all on that side. Nothing in this repository type-checks this file today, so the tuple below
 * is what a checker would need to see, and a run is not the place to find out.
 *
 * A DEGENERATE rectangle is a VALUE fault, and no type refuses it: `[0, 0, 0, 0]` is four perfectly
 * good numbers. That is what the generated target passed before it read the field from the page, so
 * every heading pointing away from the origin had an unbounded clear run, and no test failed because
 * no generated run had ever reached the rule. The first record made with it would have described a
 * walk in a field the product never allowed. Only this check refuses that, so saying the type would
 * have caught it would be a guard claiming another's work.
 */
function fieldBounds(west, north, east, south, from) {
  const stated = [west, north, east, south];
  if (!stated.every((value) => Number.isFinite(value))) {
    throw new Halt(`${from} states bounds ${JSON.stringify(stated)}, which are not four finite numbers`);
  }
  if (!(east > west) || !(south > north)) {
    throw new Halt(
      `${from} states a rectangle of no extent, ${JSON.stringify(stated)}: a walk bounded by it is ` +
      'bounded by nothing, and every heading away from its centre would have an unbounded clear run',
    );
  }
  return /** @type {[number, number, number, number]} */ ([west, north, east, south]);
}

/**
 * The one number the route rule returns that a record does not state, and why.
 *
 * `yaw` is the heading in radians, which the record states as `headingMillidegrees` instead: an
 * integer, in the unit the rule chose the heading in, so two runs of one walk cannot differ by a
 * float. Naming it here rather than skipping it silently is the whole point of the check below.
 */
export const ROUTE_NUMBERS_NOT_RECORDED = Object.freeze(['yaw']);

/**
 * A record's route section, checked BOTH WAYS against what the route rule actually returned.
 *
 * MEASURED 2026-09-18: `candidatesWithFrontage` was assigned twice in the literal below, and the
 * later, derived value won silently, so the first record this gate ever wrote would have stated
 * every qualifying heading where the rule counted two. Nothing in this repository could have seen
 * it: no tsconfig reaches `scripts/`, so the harness is type-checked by nothing; `node --check`
 * accepts a repeated key because it is legal JavaScript; and there is no JavaScript linter here.
 * A positive control confirms the class is catchable rather than invisible: the same two lines in a
 * `.ts` file fail tsc with TS1117.
 *
 * BOTH WAYS, because one way is an enumeration wearing a smaller disguise. Comparing only the
 * fields the record happens to carry cannot see a field the record DROPS, and a record silently
 * missing a count is as wrong as one stating it differently. So the set of the rule's numbers the
 * record states must equal the set the rule returned, less the ones named above, and every one of
 * them must hold the value the rule returned.
 */
export function checkedRouteRecord(plan, stated) {
  const numbers = Object.entries(plan)
    .filter(([, value]) => typeof value === 'number')
    .map(([name]) => name);
  const expected = numbers.filter((name) => !ROUTE_NUMBERS_NOT_RECORDED.includes(name)).sort();
  const carried = numbers.filter((name) => Object.hasOwn(stated, name)).sort();
  if (carried.join(',') !== expected.join(',')) {
    throw new Halt(
      `the record states ${carried.join(', ') || 'none'} of the route rule's numbers, and it must ` +
      `state exactly ${expected.join(', ')}; ${ROUTE_NUMBERS_NOT_RECORDED.join(', ')} ${
        ROUTE_NUMBERS_NOT_RECORDED.length === 1 ? 'is' : 'are'} deliberately not recorded`,
    );
  }
  for (const name of expected) {
    if (stated[name] !== plan[name]) {
      throw new Halt(`the record states ${name} ${stated[name]} and the route rule returned ${plan[name]}`);
    }
  }
  return stated;
}

/**
 * What a record says about the route: what the rule decided, and what it decided over.
 *
 * Built here rather than inside the record literal so that a test can exercise THIS, which is the
 * thing that can be wrong. The check above only fires where it is called, and it is called on a
 * path no run reaches until a walk completes.
 */
export function routeRecordOf(plan, measured) {
  return checkedRouteRecord(plan, {
    rule: plan.rule,
    // What bounded the walk, and how it was derived from what the product states.
    field: measured.field,
    startMm: [Math.round(plan.start[0] * 1000), Math.round(plan.start[1] * 1000)],
    headingMillidegrees: plan.headingMillidegrees,
    clearRunMm: plan.clearRunMm,
    frontageSamples: plan.frontageSamples,
    frontageBothSidesSamples: plan.frontageBothSidesSamples,
    meanFrontageSkewMillionths: plan.meanFrontageSkewMillionths,
    candidatesTried: plan.candidatesTried,
    candidatesQualified: plan.candidatesQualified,
    // HOW MANY QUALIFYING HEADINGS HAD FRONTAGE ON BOTH SIDES AT ANY SAMPLE, counted by the rule
    // itself. Zero means the first tie-break was equal for every candidate and a later one chose,
    // so the heading is the rule's fallback and not its preference. Without it a record shows a
    // heading that reads as a decision either way.
    candidatesWithFrontage: plan.candidatesWithFrontage,
    obstacles: measured.obstacles,
    routeRings: measured.routeRings,
    // What the runtime refused and why, so the count above is never a quietly smaller set.
    routeRingsRefused: measured.routeRingsRefused,
    // WHICH OF THE RULE'S PREFERENCES THE GROUND TURNED DOWN, and where each lost support. Zero
    // means this walk is the rule's own first choice. Without it a record states a heading and no
    // reader can tell a route that was preferred from one that was third, which is the same thing
    // `candidatesWithFrontage` exists to say about the tie-break.
    headingsRefusedForNoGround: measured.groundRefused.length,
    groundRefused: measured.groundRefused,
    routeGround: measured.routeGround,
    fieldBoundsCm: measured.fieldBoundsCm,
  });
}

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0 && process.argv[index + 1] !== undefined) return process.argv[index + 1];
  if (fallback === undefined) throw new Halt(`--${name} is required`);
  return fallback;
}

const options = {
  app: argument('app', 'http://127.0.0.1:5188/'),
  target: argument('target', 'owned-district'),
  artifact: argument('artifact', 'assets/owned-world/flatiron/flatiron-owned-district.json'),
  renderer: argument('renderer', 'web/packages/atlas-react/src/playcanvas/owned-district-runtime.ts'),
  // The committed file that states where this walk begins. The gate reads the pose from it and
  // binds its digest, so a scored frame is one somebody stated in advance rather than one this run
  // chose. Empty means no walk was stated, which is only allowed when the URL states no pose either.
  walk: argument('walk', ''),
  // Required to run, checked where the run begins rather than where the module loads, so the
  // readers above can be imported without a directory to write into.
  out: argument('out', ''),
  label: argument('label', 'run'),
  // WHICH PAGE SERVED THIS RUN, as a STATEMENT and not a binding. A record binds the containers, the
  // artifact, the renderer path and this harness by digest, and says NOTHING about the tree the
  // application itself was built from. MEASURED 2026-09-18: a corridor run was served from a lane
  // worktree two merges behind main and only a container version refusal revealed it; a page from
  // any tree can serve a scored target and no field would say which. These two are what the runner
  // was told, so a reader can at least see what was claimed. Binding it needs the page to state its
  // own commit, which is an app change and a follow-up.
  servedBy: argument('served-by', ''),
  servedFrom: argument('served-from', ''),
  port: Number(argument('cdp-port', '9351')),
  // The product caps its own measuring window at 60 seconds.
  validationSeconds: Number(argument('validation-seconds', '60')),
};
const appUrl = new URL(options.app);
const appOrigin = appUrl.origin;

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const phaseStarted = Date.now();
const phase = (name) => process.stderr.write(`[${((Date.now() - phaseStarted) / 1000).toFixed(1)} s] ${name}\n`);
const repoPath = (path) => (isAbsolute(path) ? path : join(ROOT, path));

/** A URL as a record may carry it: repository-relative, never an absolute local path. */
function normalizeUrl(raw) {
  if (raw === undefined || raw === null || raw === '') return '<no-url>';
  let url;
  try {
    url = new URL(raw);
  } catch {
    return '<unparsed-url>';
  }
  if (url.origin !== appOrigin) return `${url.protocol}//${url.host}${url.pathname}`;
  const path = decodeURIComponent(url.pathname);
  if (path.startsWith('/@fs/')) {
    const local = relative(ROOT, path.slice('/@fs'.length));
    return local.startsWith('..') ? '<outside-repository>' : local;
  }
  if (path.startsWith('/src/') || path.startsWith('/node_modules/') || path === '/') {
    return `web/packages/app${path}`;
  }
  return path;
}

/** Free text as a record may carry it: local paths made relative or withheld. */
function sanitize(text) {
  return String(text)
    .replaceAll(`${appOrigin}/@fs${ROOT}/`, '')
    .replaceAll(`${ROOT}/`, '')
    .replace(/\/Users\/[^\s'")]*/g, '<local-path>');
}

/**
 * What the product's own shell is SHOWING, read from where the product shows it.
 *
 * MEASURED 2026-09-18, after getting this wrong once. Two corridor runs halted on "the product
 * failed to start"; the container refusal that caused it, naming the tile and the version it wanted,
 * reached nobody but a live session that happened to be watching the page. I first collected the
 * console and exception lists believing the sentence would be there, and the rerun came back with
 * both EMPTY while the page was displaying it. A PRODUCT STATES A REFUSAL TO THE PERSON IN FRONT OF
 * IT, not to a console, so this reads what the person would have read.
 *
 * It reads the element the mount wait already identifies, by the id and the state attribute that
 * wait already tests, and returns the text VERBATIM: no parsing, no matching, and none of this
 * gate's categories laid over the product's words. The halt's `reason` stays the gate's own
 * sentence and `productSurface.text` is the product's, because a record that runs the two together
 * cannot afterwards be asked which half the product actually said.
 *
 * NULL IS NOT EMPTY: null means the product's shell was not in the document at all, an empty text
 * means the shell was there and showed nothing, and those are different failures. The text is cut
 * at 2,000 characters with `textCharacters` beside it, so a cut is visible rather than silent.
 */
export const PRODUCT_SURFACE = `(() => {
  const shell = document.getElementById('shell');
  if (shell === null) return null;
  const text = shell.innerText ?? '';
  return {
    worldState: shell.getAttribute('data-world-state'),
    text: text.slice(0, 2000),
    textCharacters: text.length,
  };
})()`;

/**
 * The reader above, run against a page: the product's words sanitised of this machine's paths, and
 * NEVER a throw. It runs inside the failure handler of the mount wait, so an error escaping here
 * would leave a run reporting why the surface could not be read instead of why the product would
 * not start, which is the one thing the reader exists to preserve.
 */
export async function productSurfaceOf(session) {
  const surface = await session.evaluate(PRODUCT_SURFACE)
    .catch((error) => ({ unreadable: String(error).slice(0, 200) }));
  return surface === null || surface.text === undefined ? surface : { ...surface, text: sanitize(surface.text) };
}

/**
 * The steepest RISE between two adjacent supported samples, and how far along it is.
 *
 * A gate that only asks where support ENDS cannot tell a hole from a kerb. MEASURED by the tess lane
 * 2026-09-18: inside one tile, where terrain meets its street, a join rises 192.987 mm over 189
 * stations, against the 180 mm this world states it will climb. A walk that stops at a rise like that
 * and a walk that stops at a hole are different sentences, and the heights to tell them apart are
 * already in hand: this reads them rather than asking the page a second time.
 *
 * RISES ONLY, AND ONLY BETWEEN NEIGHBOURS. A drop is a fall and not a step, so it is not reported
 * here; and no rise is computed ACROSS a gap, because the height either side of missing ground is
 * two surfaces rather than one step, and calling that a step would invent a kerb where the ground
 * merely stops. NaN is how the product says it has no surface at a point.
 *
 * Null when fewer than two adjacent samples are supported, which is not the same as a flat route:
 * a flat route returns a rise of 0.
 */
export function steepestRiseOf(heights, spacingM) {
  let steepest = null;
  for (let step = 1; step < heights.length; step += 1) {
    if (Number.isNaN(heights[step]) || Number.isNaN(heights[step - 1])) continue;
    const rise = heights[step] - heights[step - 1];
    if (steepest === null || rise > steepest.rise) steepest = { rise, atM: step * spacingM };
  }
  if (steepest === null) return null;
  return { riseMm: Math.round(steepest.rise * 1e6) / 1000, atM: steepest.atM };
}

/**
 * How finely both support probes sample the product's surface, in metres.
 *
 * NOT A TUNING KNOB. MEASURED 2026-09-18: at 0.25 m this reported "support for the next 10 m" over a
 * 30 mm hole 15 mm ahead of a stalled walker, and that single figure misdirected a whole run's
 * diagnosis. A probe coarser than the holes it is looking for does not find fewer of them, IT
 * REPORTS THEIR ABSENCE, which is worse than not probing at all.
 *
 * Exported so a test can hold it to that: it must stay fine enough to see the hole that misled that
 * run, rather than merely being whatever it was last set to.
 */
export const PROBE_SPACING_M = 0.005;

/** The hole that was missed, in metres, kept beside the spacing it is the reason for. */
export const HOLE_THAT_WAS_MISSED_M = 0.03;

/**
 * How far the page must compose its world for this run, or null when it must not compose one.
 *
 * A tile is 128,000 mm across and the rule asks for its length plus a stopping margin, so no
 * east-west route inside one tile ever has ground for its whole length. The page fixes that by
 * fetching neighbours, and IT CANNOT KNOW HOW FAR: a route length belongs to the gate, so a page
 * holding its own copy would be inventing the gate's number. It comes from the rule's own fields
 * here rather than being typed into a URL, because a hand written 131000 is a second source for a
 * number that already exists and drifts the first time either field moves.
 *
 * NULL FOR THE COMMITTED FIXTURE, which has no store rows to compose from, and for the owned
 * district, which is not a tile at all. Asking for a world around the fixture would change what a
 * RECORDED BASELINE run fetches and make it no longer comparable with the runs before it.
 */
export function composedWorldReachMm(url, scoresOwnedDistrict, rule = ROUTE_RULE) {
  if (scoresOwnedDistrict || url.searchParams.get('city') === null) return null;
  return rule.lengthMm + rule.stopMarginMm;
}

/** The shell attribute the page states its composed world on, as data rather than as a sentence. */
const WALK_WORLD_ATTRIBUTE = 'data-generated-tile-world';

const READ_WALK_WORLD = `(() => {
  const shell = document.getElementById('shell');
  if (shell === null) return null;
  return shell.getAttribute('${WALK_WORLD_ATTRIBUTE}');
})()`;

/** The two values the page uses for whether a reach was stated, as a closed list. */
const WALK_WORLD_REACH = Object.freeze(['stated', 'unstated']);

/**
 * The page's statement of its composed world, HELD AGAINST WHAT CROSSED THE WIRE.
 *
 * The statement and the prose line beside it are both derived from one `world` object by two
 * mappings, so THEY AGREEING PROVES ONLY THAT NEITHER MAPPING HAS A TYPO. It cannot catch a shared
 * misunderstanding of what that object holds, because both operands come from one source: the test
 * that cannot fail. The containers this run bound are a GENUINELY SEPARATE observation of the same
 * fact, taken from the protocol's own record of what was requested and decoded, so that is what this
 * compares against.
 *
 * Every disagreement refuses. A record whose world binding is wrong is worse than no binding at all,
 * and `docs/evaluation/` is append only, so a wrong one is permanent.
 *
 * MEASURED 2026-09-18: this attribute's populated form had never executed anywhere. The repository
 * commits exactly ONE container, so no test can reach a composed world, and every attempt to serve a
 * second tile ends in a correct refusal before a world is built. The only assertions on it are the
 * empty case. This run is its first execution, which is the reason to check it rather than read it.
 */
export function checkedWalkWorld(statement, containers, reachWasStated) {
  if (statement === null) {
    throw new Halt(
      `the page states no ${WALK_WORLD_ATTRIBUTE}, so nothing says which containers were drawn and ` +
      'which were only stood on',
    );
  }
  let world;
  try {
    world = JSON.parse(statement);
  } catch (error) {
    throw new Halt(`the page's ${WALK_WORLD_ATTRIBUTE} is not readable as data: ${String(error).slice(0, 200)}`);
  }
  if (!WALK_WORLD_REACH.includes(world.reach)) {
    throw new Halt(
      `the page states a reach of ${JSON.stringify(world.reach)}, which is not one of ` +
      `${WALK_WORLD_REACH.join(' or ')}`,
    );
  }
  // TWO SIDES OF ONE FACT, FROM DIFFERENT PLACES. This run knows whether it asked for a world; the
  // page says whether it was told how far. A world of one tile because nobody stated a reach is a
  // different fact from a world of one tile because nothing was within reach, and if those two ever
  // disagree, neither the record's world nor its absences mean what they say.
  if (world.reach !== (reachWasStated ? 'stated' : 'unstated')) {
    throw new Halt(
      `this run ${reachWasStated ? 'stated' : 'did not state'} a reach and the page reports ` +
      `${world.reach}`,
    );
  }
  const stoodOn = world.stoodOnOnly ?? [];
  const stated = [world.drawnAndStoodOn?.containerSha256, ...stoodOn.map((one) => one.containerSha256)]
    .filter((digest) => typeof digest === 'string');
  const onTheWire = containers.map((container) => container.sha256);
  const missing = stated.filter((digest) => !onTheWire.includes(digest));
  const unstated = onTheWire.filter((digest) => !stated.includes(digest));
  if (missing.length > 0 || unstated.length > 0) {
    throw new Halt(
      `the page's world and the containers this run read do not name the same bytes: ` +
      `${missing.length} stated but never fetched (${missing.map((d) => d.slice(0, 16)).join(', ') || 'none'}), ` +
      `${unstated.length} fetched but not stated (${unstated.map((d) => d.slice(0, 16)).join(', ') || 'none'})`,
    );
  }
  // The page's own byte figure, against the bodies this run actually decoded for those digests.
  const stoodOnDigests = stoodOn.map((one) => one.containerSha256);
  const measuredBytes = containers
    .filter((container) => stoodOnDigests.includes(container.sha256))
    .reduce((sum, container) => sum + container.decodedBytes, 0);
  if (world.transferredBytes !== measuredBytes) {
    throw new Halt(
      `the page states ${world.transferredBytes} bytes for the tiles it only stood on and this run ` +
      `decoded ${measuredBytes} for them`,
    );
  }
  return {
    reach: world.reach,
    drawnAndStoodOn: world.drawnAndStoodOn ?? null,
    stoodOnOnly: stoodOn,
    statedBytes: world.transferredBytes,
    measuredBytes,
    absent: world.absent ?? [],
    checkedAgainst: 'the containers this run read from the wire',
  };
}

function listenerSource(normalized) {
  if (normalized.startsWith('web/packages/') || normalized.startsWith('web/node_modules/')) {
    return 'product';
  }
  if (normalized.startsWith('/@vite/') || normalized.startsWith('/@id/') || normalized === '/@react-refresh') {
    return 'dev-server';
  }
  return 'foreign';
}

// ---- Chrome and the protocol -------------------------------------------------------------

class Session {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.events = [];
    this.listeners = new Map();
    // A DEAD CONNECTION IS NOT AN UNANSWERED CALL, and until this was written the two were the same
    // sentence. MEASURED 2026-09-18: reading a 12.68 MB container body closed this socket outright,
    // and because nothing watched for that, the run reported `Runtime.callFunctionOn was not
    // answered within 180000 ms` about the NEXT call, which never had a chance. Three hours went
    // into a page that was healthy and a product that was innocent. The transport now fails with its
    // own name, at the first call that notices, and every waiting call is told at once rather than
    // sitting out its timeout.
    this.closed = null;
    const died = (what) => {
      if (this.closed !== null) return;
      this.closed = what;
      for (const [id, slot] of this.pending) {
        this.pending.delete(id);
        slot.reject(new Error(`${slot.method}: the debugger connection ${what}`));
      }
    };
    socket.addEventListener('close', (event) => died(
      `closed with code ${event.code}${event.reason ? ` (${event.reason})` : ''}`,
    ));
    socket.addEventListener('error', () => died('failed'));
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== undefined) {
        const slot = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (slot === undefined) return;
        if (message.error) slot.reject(new Error(`${slot.method}: ${JSON.stringify(message.error)}`));
        else slot.resolve(message.result);
        return;
      }
      this.events.push(message);
      for (const handler of this.listeners.get(message.method) ?? []) handler(message.params);
    });
  }

  on(method, handler) {
    const held = this.listeners.get(method) ?? [];
    held.push(handler);
    this.listeners.set(method, held);
  }

  send(method, params = {}, timeoutMs = 180_000) {
    if (this.closed !== null) {
      return Promise.reject(new Error(`${method}: the debugger connection ${this.closed}`));
    }
    const id = (this.nextId += 1);
    return new Promise((resolvePromise, reject) => {
      // A call the browser never answers is a failure with a name, not a silent wait.
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} was not answered within ${timeoutMs} ms`));
      }, timeoutMs);
      const settle = (fn) => (value) => {
        clearTimeout(timer);
        fn(value);
      };
      this.pending.set(id, { resolve: settle(resolvePromise), reject: settle(reject), method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return result.result.value;
  }

  async reference(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: false, awaitPromise: true });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return result.result.objectId;
  }

  async call(objectId, declaration, args = [], byValue = true) {
    const result = await this.send('Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: declaration,
      arguments: args.map((value) => ({ value })),
      returnByValue: byValue,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return byValue ? result.result.value : result.result.objectId;
  }
}

async function launchChrome(profile) {
  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${options.port}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    '--force-device-scale-factor=1',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--enable-precise-memory-info',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
    '--disable-features=Translate,MediaRouter',
    `--user-data-dir=${profile}`,
    'about:blank',
  ], { stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  chrome.stdout.on('data', (chunk) => { log += chunk.toString(); });
  chrome.stderr.on('data', (chunk) => { log += chunk.toString(); });
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const version = await (await fetch(`http://127.0.0.1:${options.port}/json/version`)).json();
      const targets = await (await fetch(`http://127.0.0.1:${options.port}/json/list`)).json();
      const page = targets.find((target) => target.type === 'page');
      if (page !== undefined) return { chrome, version, page, log: () => log };
    } catch {
      // not listening yet
    }
    await sleep(250);
  }
  chrome.kill();
  throw new Halt(`Chrome exposed no page target on ${options.port}`);
}

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolvePromise, reject) => {
    socket.addEventListener('open', resolvePromise, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  return new Session(socket);
}

async function waitFor(session, expression, label, timeoutMs) {
  const started = Date.now();
  for (;;) {
    const value = await session.evaluate(expression);
    if (value === true) return Date.now() - started;
    if (typeof value === 'string') throw new Halt(`${label}: ${value}`);
    if (Date.now() - started > timeoutMs) throw new Halt(`timed out after ${timeoutMs} ms waiting for ${label}`);
    await sleep(250);
  }
}

function toBase64(array) {
  return Buffer.from(array.buffer, array.byteOffset, array.byteLength).toString('base64');
}

function float64FromBase64(text) {
  const bytes = Buffer.from(text, 'base64');
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Float64Array(copy.buffer);
}

// ---- page-side functions, called on product objects the protocol hands back -------------------

const PAGE_BASE64 = `
  const encode = (typed) => {
    const bytes = new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength);
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  };
  const decode = (text) => {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Float64Array(bytes.buffer);
  };
`;

const READ_POSE = `function () {
  const s = this.controls.state;
  return { x: s.x, y: s.y, z: s.z, yaw: s.yaw, pitch: s.pitch,
    speed: this.controls.movementSpeed, mode: this.controls.mode,
    conversationActive: this.controls.conversationActive === true,
    enabled: this.controls.enabled === true };
}`;

const CAPTURE_STATE = `function (origin, title, path) {
  const shell = document.getElementById('shell');
  const canvas = document.getElementById('atlas');
  const box = (node) => {
    if (!node) return null;
    const r = node.getBoundingClientRect();
    const s = getComputedStyle(node);
    return { x: r.x, y: r.y, width: r.width, height: r.height, display: s.display,
      visibility: s.visibility, opacity: Number(s.opacity) };
  };
  const drawn = (b) => b !== null && b.display !== 'none' && b.visibility !== 'hidden' &&
    b.opacity > 0 && b.width > 0 && b.height > 0;
  const inViewport = (b) => b !== null && b.x < innerWidth && b.y < innerHeight &&
    b.x + b.width > 0 && b.y + b.height > 0;
  const reticle = document.querySelector('#shell .reticle');
  const reticleBox = box(reticle);
  const reticleCentred = reticle !== null && reticle.isConnected && drawn(reticleBox) &&
    Math.abs(reticleBox.x + reticleBox.width / 2 - innerWidth / 2) <= 1 &&
    Math.abs(reticleBox.y + reticleBox.height / 2 - innerHeight / 2) <= 1;
  const stage = document.querySelector('.companion-stage');
  const stageBox = box(stage);
  const encounter = document.querySelector('.companion-encounter');
  const encounterBox = box(encounter);
  const companionShown = stage !== null && stage.isConnected && stage.dataset.ready === 'true' &&
    stage.dataset.shown === 'true' && drawn(stageBox) && inViewport(stageBox) &&
    stage.querySelector('svg') !== null &&
    encounter !== null && encounter.isConnected && encounter.dataset.state === 'open' &&
    encounterBox !== null && encounterBox.width > 0 && encounterBox.height > 0;
  const worldMounted = shell !== null && !shell.hasAttribute('data-world-state') &&
    canvas instanceof HTMLCanvasElement && !canvas.hidden &&
    canvas.dataset.worldTopology !== undefined;
  // Five conditions reach one refusal, so the refusal says which of them failed: a message that
  // names a cause has to distinguish every cause that reaches it, or it sends the reader somewhere
  // the truth is not. Each entry is what was expected against what the page showed.
  const refusals = [];
  if (location.origin !== origin) refusals.push('origin ' + origin + ', page ' + location.origin);
  if (location.pathname !== path) refusals.push('path ' + JSON.stringify(path) + ', page ' + JSON.stringify(location.pathname));
  if (document.title !== title) refusals.push('title ' + JSON.stringify(title) + ', page ' + JSON.stringify(document.title));
  if (!worldMounted) refusals.push('no world mounted by #shell and #atlas');
  if (document.querySelector('.credential-gate') !== null) refusals.push('a credential gate is on the page');
  if (document.querySelector('[data-empty-world]') !== null) refusals.push('an empty world is on the page');
  const inProductShell = refusals.length === 0;
  const active = document.activeElement;
  return {
    locationPath: location.pathname,
    title: document.title,
    shellAttributes: shell === null ? null :
      Object.fromEntries([...shell.attributes].map((a) => [a.name, a.value])),
    atlasDataset: canvas === null ? null : { ...canvas.dataset },
    refusals,
    reticle: { present: reticle !== null, box: reticleBox, centred: reticleCentred },
    companion: {
      stage: stage === null ? null : { ...stage.dataset, box: stageBox },
      encounter: encounter === null ? null : { state: encounter.dataset.state, box: encounterBox },
      shown: companionShown,
    },
    inProductShell,
    worldMounted,
    credentialGate: document.querySelector('.credential-gate') !== null,
    emptyWorld: document.querySelector('[data-empty-world]') !== null,
    activeElement: active === null ? null : active.tagName.toLowerCase(),
    atlasFocused: canvas !== null && active === canvas,
    typingTarget: active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement ||
      active instanceof HTMLSelectElement || (active instanceof HTMLElement && active.isContentEditable),
    heapBytes: performance.memory?.usedJSHeapSize ?? null,
    pointerLocked: document.pointerLockElement !== null,
  };
}`;

const INSTALL_RECORDER = `function () {
  const binding = this;
  const recorder = { poses: [], recording: false, failures: [], handle: null, frameHandle: null,
    observer: null, maxDrawCalls: 0, renderedFrames: 0 };
  recorder.handle = binding.app.on('update', () => {
    if (!recorder.recording) return;
    const s = binding.controls.state;
    recorder.poses.push([s.x, s.y, s.z, s.yaw, s.pitch, binding.controls.movementSpeed]);
  });
  // The same counter the product's validation recorder reads, over the whole route rather than
  // its capped window.
  recorder.frameHandle = binding.app.on('frameend', () => {
    recorder.renderedFrames += 1;
    recorder.maxDrawCalls = Math.max(recorder.maxDrawCalls, binding.app.stats.drawCalls.total);
  });
  const status = document.querySelector('.travel-status');
  if (status !== null) {
    recorder.observer = new MutationObserver(() => {
      if (recorder.recording && !status.hidden && status.dataset.kind === 'failure') {
        recorder.failures.push(status.textContent ?? '');
      }
    });
    recorder.observer.observe(status, { attributes: true, childList: true, characterData: true, subtree: true });
  }
  return recorder;
}`;

const EXTRACT_SCENE = `async function (pcUrl) {
  ${PAGE_BASE64}
  const pc = await import(pcUrl);
  const app = this.app;
  const origin = this.renderOriginState.origin;
  const cameras = app.root.findComponents('camera').filter((c) => c.enabled && c.entity.enabled);
  const layers = new Set(cameras.flatMap((c) => c.layers));
  const culls = { [pc.CULLFACE_NONE]: 'none', [pc.CULLFACE_BACK]: 'back', [pc.CULLFACE_FRONT]: 'front', [pc.CULLFACE_FRONTANDBACK]: 'both' };
  const pathOf = (entity) => {
    const names = [];
    for (let node = entity; node !== null && node !== app.root; node = node.parent) names.unshift(node.name);
    return names.join('/');
  };
  const meshes = [];
  const environmentTextures = new Map();
  const skipped = { disabledOrHidden: 0, notInCameraLayers: 0, notTriangles: 0 };
  for (const render of app.root.findComponents('render')) {
    if (!render.enabled || !render.entity.enabled) { skipped.disabledOrHidden += render.meshInstances.length; continue; }
    if (!render.layers.some((id) => layers.has(id))) { skipped.notInCameraLayers += render.meshInstances.length; continue; }
    render.meshInstances.forEach((instance, ordinal) => {
      if (!instance.visible) { skipped.disabledOrHidden += 1; return; }
      const mesh = instance.mesh;
      const primitive = mesh.primitive[0];
      if (primitive.type !== pc.PRIMITIVE_TRIANGLES) { skipped.notTriangles += 1; return; }
      const local = new Float32Array(mesh.vertexBuffer.numVertices * 3);
      mesh.getPositions(local);
      let order;
      if (mesh.indexBuffer && mesh.indexBuffer[0]) {
        const all = new Uint32Array(mesh.indexBuffer[0].numIndices);
        mesh.getIndices(all);
        order = all.subarray(primitive.base, primitive.base + primitive.count);
      } else {
        order = new Uint32Array(primitive.count);
        for (let k = 0; k < primitive.count; k += 1) order[k] = primitive.base + k;
      }
      const m = instance.node.getWorldTransform().data;
      const world = new Float64Array(order.length * 3);
      for (let k = 0; k < order.length; k += 1) {
        const v = order[k] * 3;
        const x = local[v];
        const y = local[v + 1];
        const z = local[v + 2];
        world[k * 3] = m[0] * x + m[4] * y + m[8] * z + m[12] + origin.x;
        world[k * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13] + origin.y;
        world[k * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14] + origin.z;
      }
      const material = instance.material;
      const textures = new Set();
      for (const name of Object.getOwnPropertyNames(material)) {
        const value = material[name];
        if (value instanceof pc.Texture) textures.add(value);
      }
      for (const parameter of Object.values(material.parameters ?? {})) {
        if (parameter && parameter.data instanceof pc.Texture) textures.add(parameter.data);
      }
      let decoded = 0;
      for (const texture of textures) {
        decoded += texture.gpuSize;
        environmentTextures.set(texture, texture.gpuSize);
      }
      meshes.push({
        id: pathOf(render.entity) + '#' + ordinal,
        cull: culls[material.cull] ?? 'back',
        hasUv: mesh.vertexBuffer.format.elements.some((element) => element.name.startsWith('TEXCOORD')),
        decodedTextureBytes: decoded,
        textureCount: textures.size,
        triangles: encode(world),
      });
    });
  }
  let environmentTextureBytes = 0;
  for (const bytes of environmentTextures.values()) environmentTextureBytes += bytes;
  // What else the cameras' layers draw, which the triangle measurement above does not read.
  const owned = new Set(app.root.findComponents('render').flatMap((render) => render.meshInstances));
  const otherInstances = { triangles: 0, points: 0, lines: 0, other: 0 };
  const counted = new Set();
  for (const layerId of layers) {
    const layer = app.scene.layers.getLayerById(layerId);
    const instances = layer?.meshInstances ??
      [...(layer?.opaqueMeshInstances ?? []), ...(layer?.transparentMeshInstances ?? [])];
    for (const instance of instances) {
      if (counted.has(instance) || owned.has(instance)) continue;
      counted.add(instance);
      if (!instance.visible || instance.node?.enabled === false) continue;
      const type = instance.mesh?.primitive?.[0]?.type;
      if ([pc.PRIMITIVE_TRIANGLES, pc.PRIMITIVE_TRISTRIP, pc.PRIMITIVE_TRIFAN].includes(type)) otherInstances.triangles += 1;
      else if (type === pc.PRIMITIVE_POINTS) otherInstances.points += 1;
      else if ([pc.PRIMITIVE_LINES, pc.PRIMITIVE_LINELOOP, pc.PRIMITIVE_LINESTRIP].includes(type)) otherInstances.lines += 1;
      else otherInstances.other += 1;
    }
  }
  const layerInventory = {
    renderComponentInstancesRead: meshes.length,
    otherInstances,
    gsplatComponents: app.root.findComponents('gsplat').filter((c) => c.enabled && c.entity.enabled).length,
  };
  return {
    meshes,
    layerInventory,
    skipped,
    origin: { x: origin.x, y: origin.y, z: origin.z },
    environmentTextureBytes,
    environmentTextures: environmentTextures.size,
    deviceTextureBytes: app.graphicsDevice._vram.tex,
    deviceVram: { ...app.graphicsDevice._vram },
  };
}`;

const SAMPLE_SUPPORT = `function (pointsText) {
  ${PAGE_BASE64}
  const points = decode(pointsText);
  const heights = new Float64Array(points.length / 2);
  for (let i = 0; i < heights.length; i += 1) {
    const sample = this.navigationWorld.surface.sample(points[i * 2], points[i * 2 + 1]);
    heights[i] = sample === null ? Number.NaN : sample.height;
  }
  return encode(heights);
}`;

const READ_TILE = `function () {
  const attached = this.generatedTile;
  return attached === null || attached === undefined ? null : { ...attached.metrics };
}`;

const READ_FIELD = `function () {
  const world = this.navigationWorld;
  return { centreX: world.centre.x, centreZ: world.centre.z, fieldRadius: world.fieldRadius,
    recoveryRadius: world.recoveryRadius, maximumStepHeight: world.maximumStepHeight,
    maximumSlopeDegrees: world.maximumSlopeDegrees, surfaceSampleSpacing: world.surfaceSampleSpacing };
}`;

const READ_OBSTACLES = `function () {
  return (this.navigationWorld.polygonObstacles ?? []).map((obstacle) => ({
    id: obstacle.id,
    rings: obstacle.rings.map((ring) => ring.map((point) => [point.x, point.z])),
  }));
}`;

/**
 * The route obstruction rings a mounted tile states, and the regions it refused, or `null` where the
 * page states no hook at all.
 *
 * NOT `navigationWorld.polygonObstacles`. That field is what a movement resolver collides against,
 * and while these rings were carried in it a bench stopped a walker 344 mm from its edge against a
 * capsule radius of 340. They are stated on the tile now, so the gate reads them from the tile: the
 * same object the page's own panel reads to say how many there are.
 *
 * NULL AND EMPTY ARE DIFFERENT ANSWERS and the caller must halt differently on each. A missing hook
 * says nothing about the tile's rings; a tile that states none says everything. Reading one as the
 * other is how the field above came to be read as a tile with nothing in it.
 */
/**
 * Every surface the page drew as unavailable, counted by the reason the runtime states.
 *
 * The tile metric binds ONE TOTAL, and a total cannot be read: a surface no material record dresses
 * and a surface whose texture set could not be fetched both count there, and they are different
 * facts about a world. The record binds the breakdown so no reader has to know which kind of run
 * produced the number. Null where the page states no hook, which is not the same as a tile with
 * none, exactly as for the rings.
 */
const READ_UNAVAILABLE_SURFACES = `(() => {
  const stated = window.__exulanicaTileUnavailableSurfaces;
  return typeof stated !== 'function' ? null : stated();
})()`;

const READ_ROUTE_OBSTRUCTIONS = `(() => {
  const stated = window.__exulanicaTileRouteObstructions;
  if (typeof stated !== 'function') return null;
  const { obstacles, refused } = stated();
  return {
    obstacles: obstacles.map((obstacle) => ({
      id: obstacle.id,
      rings: obstacle.rings.map((ring) => ring.map((point) => [point.x, point.z])),
    })),
    refused: refused.map((region) => ({ kind: region.kind, identity: region.identity, reason: region.reason })),
  };
})()`;

// ---- the run ---------------------------------------------------------------------------------

async function main() {
  if (options.out === '') throw new Halt('--out is required');
  const out = resolve(options.out);
  mkdirSync(out, { recursive: true });
  const profile = join(out, `.chrome-profile-${options.label}`);
  rmSync(profile, { recursive: true, force: true });

  // The code that measures, bound by digest so a record can show it was the committed code.
  const measuredBy = [
    'scripts/capture_visual_gate.mjs',
    ...readdirSync(join(ROOT, 'web/packages/loom-gate/src'))
      .filter((name) => name.endsWith('.ts'))
      .sort()
      .map((name) => `web/packages/loom-gate/src/${name}`),
  ].map((path) => {
    const bytes = readFileSync(join(ROOT, path));
    return { path, byteSize: bytes.byteLength, sha256: sha256(bytes) };
  });
  const gateTarget = TARGETS[options.target];
  if (gateTarget === undefined) {
    throw new Halt(
      `${options.target} is not a gate target; declared targets are ${Object.keys(TARGETS).join(', ')}`,
    );
  }
  const expectedTitle = titleOf(options.target);
  const search = new URLSearchParams(appUrl.search);
  for (const name of gateTarget.requiredParameters) {
    if (search.get(name) === null) throw new Halt(`${options.target} is reached with ${name} set, and this run has no ${name}`);
  }
  const selectors = gateTarget.selectorParameters.filter((name) => search.get(name) !== null);
  if (gateTarget.selectorParameters.length > 0 && selectors.length !== 1) {
    throw new Halt(
      `${options.target} names exactly one of ${gateTarget.selectorParameters.join(', ')}; this run names ` +
      `${selectors.length === 0 ? 'none' : selectors.join(' and ')}`,
    );
  }
  // Where the camera starts is not this run's to choose: the lane a scored run judges must never
  // pick a flattering opening. A pose is admitted only when a committed file states it, the run
  // asks the page for that same pose, and the record binds the file by digest. So the URL and the
  // file must agree, and either one alone is a refusal: a URL pose with no file is a pose this run
  // chose, and a file with no URL pose is a walk the page was never asked to take.
  const posed = WALK_PARAMETERS.filter((name) => search.get(name) !== null);
  if (options.walk === '' && posed.length > 0) {
    throw new Halt(
      `a scored run refuses a pose chosen per run (${posed.join(', ')}); a stated pose is read from a ` +
      'committed file named by --walk and bound by its digest',
    );
  }
  if (options.walk !== '') {
    // RESOLVED AGAINST THE REPOSITORY, NOT AGAINST WHATEVER DIRECTORY THIS WAS STARTED IN. The
    // harness is run from `web/`, so a walk named by a repository path was looked for under `web/`
    // a run died before it began. MEASURED 2026-09-18: that cost a corridor run, and the workaround
    // was an absolute path, which is the kind of thing that ends up in somebody's notes forever.
    // A path is a repository path here because every file this flag can name is a committed one.
    const walkPath = relative(ROOT, repoPath(options.walk));
    if (walkPath.startsWith('..') || isAbsolute(walkPath)) {
      throw new Halt(`--walk ${options.walk} is outside the repository, so no committed file states it`);
    }
    const bytes = readFileSync(join(ROOT, walkPath));
    const stated = statedWalkOf(bytes.toString('utf8'));
    observed.statedWalk = {
      path: walkPath, byteSize: bytes.byteLength, sha256: sha256(bytes), ...stated,
    };
    // Compared as the integers both sides state, in the frame the file states them in. Converting
    // to the renderer's metres to compare would put a frame change inside the gate's own verdict,
    // and the renderer pose is a consequence of this one, recorded as measured rather than derived.
    const asked = Object.fromEntries(WALK_PARAMETERS.map((name) => [name, search.get(name)]));
    const wanted = { pose_x_mm: stated.xMm, pose_y_mm: stated.yMm, facing_dx: stated.facingDx, facing_dy: stated.facingDy };
    const differ = WALK_PARAMETERS.filter((name) => asked[name] === null || Number(asked[name]) !== wanted[name]);
    if (differ.length > 0) {
      throw new Halt(
        `the run asks for a different walk than ${walkPath} states: ` +
        differ.map((name) => `${name} ${asked[name] === null ? 'unset' : asked[name]} against ${wanted[name]}`).join(', '),
      );
    }
  }

  Object.assign(observed, {
    target: options.target,
    app: { origin: appOrigin, path: appUrl.pathname, search: appUrl.search },
    servedBy: { entry: options.servedBy, worktree: options.servedFrom, stated: true, bound: false },
    pageCheck: { path: gateTarget.path, title: expectedTitle, titleFrom: `${TITLE_SOURCE} ${gateTarget.titleSymbol}` },
  });
  const scoresOwnedDistrict = gateTarget.binds === 'owned-district-artifact';
  // The module that drew what is scored. A generated page is drawn by the tile runtime, so the
  // default follows the target rather than making every run of it pass the same flag.
  if (!scoresOwnedDistrict && !process.argv.includes('--renderer')) {
    options.renderer = 'web/packages/atlas-react/src/playcanvas/generated-tile/tile-runtime.ts';
  }
  const artifactBytes = scoresOwnedDistrict ? readFileSync(repoPath(options.artifact)) : null;
  const rendererBytes = readFileSync(repoPath(options.renderer));
  const artifact = artifactBytes === null ? null : JSON.parse(artifactBytes.toString('utf8'));
  if (artifact !== null && artifact.profile !== 'exulanica.owned-district/v1') {
    throw new Halt(`no adapter reads ${artifact.profile}; the corridor needs its own prism reader`);
  }
  const heights = new Map((artifact?.buildings ?? []).map((building) => [building.id, building.height_cm / 100]));
  const [west, north, east, south] = (artifact?.bounds_cm ?? [0, 0, 0, 0]).map((value) => value / 100);

  // The API behind the product's own proxy must refuse a read that carries no credential.
  const anonymous = await fetch(new URL('/api/graph', appUrl));
  const anonymousStatus = anonymous.status;
  await anonymous.arrayBuffer();

  const { chrome, version, page, log } = await launchChrome(profile);
  const session = await connect(page.webSocketDebuggerUrl);
  const network = new Map();
  // WHICH RESPONSES COULD BE A CONTAINER, in ONE place because two readers need the same answer: the
  // one that opens a stream while the response is still arriving, and the one that decides afterwards
  // what to bind. Written twice they drift, and a drift here is silent both ways: a container nobody
  // streamed, or megabytes of texture streamed for nothing.
  const couldBeContainer = (url) => {
    const path = normalizeUrl(url);
    return path.endsWith('.owd') || path.includes('/tiles/');
  };
  const streamed = new Map();
  const exceptions = [];
  const consoleErrors = [];
  const networkLogErrors = [];
  const navigations = [];
  session.on('Network.requestWillBeSent', (event) => {
    network.set(event.requestId, {
      url: event.request.url,
      method: event.request.method,
      type: event.type,
      status: null,
      encodedBytes: 0,
      decodedBytes: 0,
      finished: false,
      failed: null,
    });
  });
  session.on('Network.responseReceived', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) {
      entry.status = event.response.status;
      entry.mimeType = event.response.mimeType;
    }
  });
  // HOLD EACH CONTAINER REQUEST FOR THE INSTANT IT TAKES TO ASK FOR ITS STREAM, then let it go.
  //
  // MEASURED 2026-09-18, three times and each one differently. `Network.getResponseBody` for a
  // 12.68 MB container is answered with about 16.9 MB of base64 in ONE message and Node's own
  // WebSocket closes rather than deliver it. This Chrome has no `Network.takeResponseBodyAsStream`.
  // And opening the stream from an EVENT, whether `responseReceived` or `requestWillBeSent`, is a
  // race against a localhost response that can finish inside the round trip: it lost on the smallest
  // container of four, then on a larger one, and the run before those had read all four and was
  // simply lucky.
  //
  // Paused, the request has not been sent, so there is no race to lose: measured 4 of 4 streams
  // opened against 0 refused. THIS SUPPLIES NOTHING. The request is continued untouched and the
  // bytes are still the ones the server sent to the page, which is what the record binds; a harness
  // that fulfilled the response itself would be handing the page its own answer.
  session.on('Fetch.requestPaused', (event) => {
    const { requestId, networkId, request } = event;
    (async () => {
      try {
        if (networkId !== undefined && couldBeContainer(request.url)) {
          streamed.set(networkId, { parts: [], refused: null });
          const opened = await session.send('Network.streamResourceContent', { requestId: networkId })
            .catch((error) => ({ failed: String(error.message ?? error).slice(0, 200) }));
          if (opened.failed !== undefined) streamed.get(networkId).refused = opened.failed;
          else streamed.get(networkId).parts.push(Buffer.from(opened.bufferedData ?? '', 'base64'));
        }
      } finally {
        // ALWAYS, and before anything else can go wrong: a paused request nobody continues is a
        // page that never loads, and the gate would be reporting on a world it stopped itself.
        await session.send('Fetch.continueRequest', { requestId }).catch(() => null);
      }
    })();
  });
  session.on('Network.dataReceived', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) entry.decodedBytes += event.dataLength;
    const held = streamed.get(event.requestId);
    if (held !== undefined && event.data !== undefined) held.parts.push(Buffer.from(event.data, 'base64'));
  });
  session.on('Network.loadingFinished', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) {
      entry.finished = true;
      entry.encodedBytes = event.encodedDataLength;
    }
  });
  session.on('Network.loadingFailed', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) entry.failed = event.errorText;
  });
  session.on('Runtime.exceptionThrown', (event) => {
    const detail = event.exceptionDetails;
    exceptions.push(sanitize(String(detail.exception?.description ?? detail.text).split('\n')[0]).slice(0, 300));
  });
  session.on('Runtime.consoleAPICalled', (event) => {
    if (event.type !== 'error') return;
    consoleErrors.push(sanitize(event.args.map((arg) => String(arg.value ?? arg.description ?? '')).join(' ')).slice(0, 300));
  });
  session.on('Log.entryAdded', (event) => {
    if (event.entry.level !== 'error') return;
    const text = sanitize(`${event.entry.source}: ${event.entry.text}`).slice(0, 300);
    if (event.entry.source === 'network') networkLogErrors.push(text);
    else consoleErrors.push(text);
  });
  session.on('Page.frameNavigated', (event) => {
    if (event.frame.parentId === undefined) navigations.push(event.frame.url);
  });

  // WHAT THE BROWSER REPORTED, ATTACHED TO A HALT AND NOT ONLY TO A COMPLETED RUN.
  //
  // Until this was written, a halt recorded the FACT of a halt and nothing either the browser or the
  // product said about it. These are the SAME THREE LISTS a completed record writes under `errors`,
  // bound here by reference the moment they exist rather than copied at the end, so a halt carries
  // whatever had arrived by the time it stopped. One source, and nothing new to keep in step.
  //
  // THEY ARE NOT WHERE THE PRODUCT SAYS WHY IT REFUSED, and that is measured rather than assumed. I
  // added these first believing they would carry the corridor refusal; the rerun came back with
  // `exceptions` and `consoleErrors` both EMPTY while the page was displaying a container refusal
  // naming the tile and the version. The product states a refusal on its own surface, which
  // `productSurfaceOf` reads. An empty list here IS that measurement, so it stays.
  //
  // ABSENT AND EMPTY ARE DIFFERENT ANSWERS. No `errors` key at all means the browser never opened,
  // so nothing was ever given the chance to say anything. An empty list means it ran and said
  // nothing of that kind.
  observed.errors = { exceptions, consoleErrors, networkLogErrors };

  let containers = null;
  // Empty until the page is reached, rather than nothing at all, so a caller before then holds a
  // list with no containers in it and not a value of another shape.
  /** @type {() => Promise<any[]>} */
  let collectContainers = async () => [];
  /**
   * The bytes of a response this run streamed, or why it has none.
   *
   * REFUSED AND ABSENT AND EMPTY ARE THREE ANSWERS. Until this returned a reason, an unreadable body
   * was `null` and the collector simply moved on: when a fix of mine called a protocol method this
   * Chrome does not have, EVERY container read failed and the run wrote `containers: []` and halted
   * later for an unrelated reason. Nothing said a word. A body that cannot be read now stops the run.
   */
  const bodyOf = (requestId) => {
    const held = streamed.get(requestId);
    if (held === undefined) return { bytes: null, refused: 'this run never opened a stream for it' };
    if (held.refused !== null) return { bytes: null, refused: held.refused };
    return { bytes: Buffer.concat(held.parts), refused: null };
  };
  const halt = async (reason) => {
    const state = await session.call(await session.reference('document'), CAPTURE_STATE, [appOrigin, expectedTitle, gateTarget.path]).catch(() => null);
    const { data } = await session.send('Page.captureScreenshot', { format: 'png' }).catch(() => ({ data: null }));
    if (data !== null) writeFileSync(join(out, `${options.label}-halt.png`), Buffer.from(data, 'base64'));
    throw new Halt(`${reason}\nstate: ${JSON.stringify(state)}`);
  };

  try {
    await session.send('Page.enable');
    await session.send('Runtime.enable');
    await session.send('Log.enable');
    await session.send('Network.enable', { maxTotalBufferSize: 256_000_000, maxResourceBufferSize: 64_000_000 });
    // Only the two shapes a container is served from are paused, so nothing else the page fetches is
    // held up: this page moves about 200 MB across hundreds of responses.
    await session.send('Fetch.enable', {
      patterns: [{ urlPattern: '*/tiles/*', requestStage: 'Request' }, { urlPattern: '*.owd*', requestStage: 'Request' }],
    });
    await session.send('Emulation.setDeviceMetricsOverride', {
      width: VIEWPORT.width, height: VIEWPORT.height, deviceScaleFactor: 1, mobile: false,
    });
    await session.send('Emulation.setFocusEmulationEnabled', { enabled: true });

    const target = new URL(appUrl);
    // HOW FAR THE PAGE MUST COMPOSE ITS WORLD, stated by the rule that decides what gets walked.
    //
    // A tile is 128,000 mm across and this rule asks for 131,000, so no east-west route inside one
    // tile ever has ground for its whole length: MEASURED 2026-09-18, three qualifying headings all
    // ran out of support past the tile's own edge. The page composes neighbours to fix that, and it
    // CANNOT KNOW THIS NUMBER: a route length is the gate's, so the page would be inventing it.
    // Written here from the rule's own fields rather than typed into a URL, because a hand typed
    // 131000 is a second source for a number that already exists and would drift the first time
    // either field moved.
    //
    // ONLY FOR A RUN POINTED AT THE STORE. The committed conformance tile has no rows to compose
    // from, and asking for a world around it would change what a RECORDED BASELINE run fetches,
    // which would make that run and its predecessors no longer comparable.
    const reachMm = composedWorldReachMm(target, scoresOwnedDistrict);
    if (reachMm !== null) target.searchParams.set('walk_reach_mm', String(reachMm));
    target.searchParams.set('validation', '1');
    target.searchParams.set('validation-seconds', String(options.validationSeconds));
    target.searchParams.set('validation-warmup', '2');
    const navigatedAt = Date.now();
    await session.send('Page.navigate', { url: target.href });
    // WHAT THE PRODUCT SHOWED WHEN IT WOULD NOT START, kept apart from what this gate says about it.
    // Runs on EVERY failure of this wait, the timeout included: a wait that ran out while the page
    // was showing something is a different fact from one that ran out on a blank page, and the
    // timeout alone cannot tell them apart.
    let mountMs;
    try {
      mountMs = await waitFor(session, `(() => {
      if (document.querySelector('.credential-gate')) return 'the product showed its credential gate';
      if (document.querySelector('[data-empty-world]')) return 'the product showed its empty world';
      if (document.getElementById('shell')?.getAttribute('data-world-state') === 'error') return 'the product failed to start';
      const canvas = document.getElementById('atlas');
      return canvas instanceof HTMLCanvasElement && canvas.dataset.worldTopology !== undefined &&
        document.querySelector('#shell .reticle') !== null &&
        document.querySelector('.reconstruction-loading') === null;
    })()`, 'the product shell to mount a world', 240_000);
    } catch (error) {
      observed.productSurface = await productSurfaceOf(session);
      throw error;
    }
    phase('the shell mounted a world');
    // The direct-navigation transition and the first frames settle before anything is read.
    await sleep(3000);

    // Read from the protocol's own request log rather than the page's resource timing, whose
    // default 250-entry buffer fills with development modules before the engine module loads.
    const pcUrl = [...network.values()]
      .map((entry) => entry.url)
      .find((url) => new URL(url).pathname.endsWith('/.vite/deps/playcanvas.js')) ?? null;
    if (pcUrl === null) await halt('the page never loaded the rendering engine module');

    // The binding is reached through the engine's own update listener, read by the debugger.
    const appId = await session.reference(`(async () => (await import(${JSON.stringify(pcUrl)})).AppBase.getApplication())()`);
    const handlersId = await session.call(appId, `function () { return (this._callbacks.get('update') ?? []).map((h) => h.callback); }`, [], false);
    const handlers = await session.send('Runtime.getProperties', { objectId: handlersId, ownProperties: true });
    let bindingId = null;
    for (const property of handlers.result) {
      if (bindingId !== null || property.value?.type !== 'function') continue;
      const internal = await session.send('Runtime.getProperties', { objectId: property.value.objectId, ownProperties: false });
      const scopes = internal.internalProperties?.find((entry) => entry.name === '[[Scopes]]');
      if (scopes === undefined) continue;
      const list = await session.send('Runtime.getProperties', { objectId: scopes.value.objectId, ownProperties: true });
      for (const scope of list.result) {
        if (scope.value?.objectId === undefined) continue;
        const variables = await session.send('Runtime.getProperties', { objectId: scope.value.objectId, ownProperties: true });
        const found = variables.result.find((variable) => variable.name === 'binding');
        if (found?.value?.objectId !== undefined) {
          bindingId = found.value.objectId;
          break;
        }
      }
    }
    if (bindingId === null) await halt('the Atlas binding was not reachable from the engine update listener');
    phase('the Atlas binding was reached');
    const documentId = await session.reference('document');
    const captureState = () => session.call(documentId, CAPTURE_STATE, [appOrigin, expectedTitle, gateTarget.path]);
    const pose = () => session.call(bindingId, READ_POSE);

    const arrival = await pose();
    const before = await captureState();
    if (!before.inProductShell) {
      await halt(`the page is not the ${options.target} target: ${before.refusals.join('; ')}`);
    }

    // Every container the page fetched, read through tess's own decoder rather than through a hook
    // the page could state differently: what the run binds is what crossed the wire. Collected as
    // soon as the tile is mounted, so a run that halts before it walks still says which tile it was
    // about; a tile named without its digest means a different tile a week later.
    // It RETURNS them rather than only filling the outer variable, so a caller holds a value it can
    // see is a list. Filling a variable from inside a closure leaves every later reader looking at
    // something that might still be null, and the only thing saying otherwise is the order the
    // calls happen to be written in.
    collectContainers = async () => {
      if (containers !== null) return containers;
      containers = [];
      for (const [requestId, entry] of network) {
        // The URL narrows; the MAGIC decides. This page moves about 200 MB across hundreds of
        // responses, and reading every body over the protocol costs minutes, so only the two
        // shapes a container is served from are read: a committed golden ending .owd and a stored
        // tile under /tiles/. Both then have to carry the magic, which is what keeps a JavaScript
        // module whose path ends .owd from being read as a broken container.
        const path = normalizeUrl(entry.url);
        if (!entry.finished || entry.decodedBytes < 16 || !couldBeContainer(entry.url)) continue;
        const read = bodyOf(requestId);
        if (read.bytes === null) {
          await halt(`the page fetched ${path} and this run could not read its bytes: ${read.refused}`);
        }
        const bytes = read.bytes;
        // TWO COUNTS OF THE SAME RESPONSE, from the protocol's own byte counter and from the pieces
        // this run assembled. They are independent, so a stream that started late or dropped an
        // event cannot pass as a whole container, and a digest is never taken of part of a body.
        if (bytes.byteLength !== entry.decodedBytes) {
          await halt(
            `the bytes this run assembled for ${path} are ${bytes.byteLength} and the protocol counted ` +
            `${entry.decodedBytes}`,
          );
        }
        // A container is recognised by its own first bytes, not by its URL. The development server
        // answers a `?url` import of a tile with a JAVASCRIPT MODULE whose path still ends .owd, so
        // a suffix test reads that module as a broken container. Bytes that do not carry the magic
        // are not a container and are passed over; bytes that DO and still fail to decode are a
        // broken container and stop the run, because those are different facts.
        if (bytes.byteLength < OWD_MAGIC.length) continue;
        if (bytes.subarray(0, OWD_MAGIC.length).toString('latin1') !== OWD_MAGIC) continue;
        let header;
        try {
          ({ header } = decodeOwd(new Uint8Array(bytes)));
        } catch (error) {
          await halt(`a container the page fetched did not decode: ${String(error).slice(0, 200)}`);
        }
        const fields = header.tile.fields;
        containers.push({
          requestPath: normalizeUrl(entry.url),
          transferredBytes: entry.encodedBytes,
          decodedBytes: bytes.byteLength,
          status: entry.status,
          sha256: sha256(bytes),
          tileInputsDigest: header.tile_inputs_digest,
          citySeed: fields.city_seed,
          tile: { x: fields.tile_x, y: fields.tile_y, lod: fields.lod },
          // The container's own statement of how far it reaches, which is what bounds the obstacles
          // it carries records for.
          tileSizeMm: fields.tile_size_mm ?? null,
          grammars: header.grammars.map((grammar) => ({
            id: grammar.grammar_id, version: grammar.grammar_version, descriptorSha256: grammar.descriptor_sha256,
          })),
          renderBatchTriangles: header.projections.find((projection) => projection.name === 'render_batch')?.triangle_count ?? 0,
        });
      }
      observed.containers = containers;
      return containers;
    };

    const tileMetrics = scoresOwnedDistrict ? null : await session.call(bindingId, READ_TILE);
    observed.tile = tileMetrics;
    // The breakdown behind `unavailableSurfaces`, which the metric above states only as a total.
    const unavailableByReason = scoresOwnedDistrict ? null : await session.evaluate(READ_UNAVAILABLE_SURFACES);
    observed.unavailableSurfacesByReason = unavailableByReason;
    if (!scoresOwnedDistrict) containers = await collectContainers();
    // WHICH CONTAINERS WERE DRAWN AND WHICH WERE ONLY STOOD ON, bound from the page's own data
    // attribute and held against the bytes this run read off the wire. The composed world is
    // walkable past the edge and NOT DRAWN past it, so a record naming four containers without
    // saying what each was for would be cited for something it never measured.
    const walkWorld = scoresOwnedDistrict
      ? null
      : checkedWalkWorld(await session.evaluate(READ_WALK_WORLD), containers, reachMm !== null);
    observed.walkWorld = walkWorld;
    if (!scoresOwnedDistrict && tileMetrics === null) {
      await halt('the page mounted no generated tile, so there is nothing of that target to score');
    }

    // WHERE THE PAGE ACTUALLY OPENED, from the page rather than from this run's intention. The
    // product states it as data: an opening of 'stated' or 'default', and the four integers only
    // when stated, the attribute absent otherwise. Read as data on purpose: the page also says it
    // in a sentence, and a scored verdict that depended on that wording would pass a frame nobody
    // stated the day the sentence was reworded.
    if (!scoresOwnedDistrict) {
      const mounted = await captureState();
      const attributes = mounted.shellAttributes ?? {};
      const opening = attributes['data-generated-tile-opening'] ?? null;
      const openedAt = attributes['data-generated-tile-pose'] ?? null;
      observed.opening = { state: opening, pose: openedAt };
      if (opening === null) {
        await halt('the page states no opening, so nothing says whether its frame was one anybody stated');
      }
      if (observed.statedWalk !== undefined) {
        const walk = observed.statedWalk;
        const wanted = [walk.xMm, walk.yMm, walk.facingDx, walk.facingDy].join(',');
        if (opening !== 'stated') {
          await halt(
            `${walk.path} states a walk and the page opened at its ${opening} pose, so the frame ` +
            'scored would not be the frame anybody stated',
          );
        }
        if (openedAt !== wanted) {
          await halt(`the page opened at ${openedAt}, and ${walk.path} states ${wanted}`);
        }
      }
    }

    // TWO INPUTS, NOT ONE. The rings the route rule chooses a heading by and the rings the keys
    // measure against are different questions, and on the owned district they happen to be the same
    // set, which is why one array was enough until a second target existed.
    //
    // `prisms` are what the keys mean by a ring: BUILDING EXTERIORS with the height their own record
    // states. Three consumers read them, each verified by reading its body, not its signature:
    // planRoute for the heading, measureCapsule for capsuleRingContactSamples (skipping any prism
    // outside the capsule's height band), and classify, which marks a near-vertical triangle as
    // FACADE when it lies within a band of a prism ring edge and inside that prism's height band,
    // feeding continuousTexturedStreetAndFacades. Passing street furniture here would therefore
    // move three keys at once and nothing in a record would show it.
    //
    // `routeRings` are the route obstruction rings a TILE states, on the tile itself: plan regions a
    // walking capsule is kept clear of, with everything above head height dropped. They choose a
    // heading and measure nothing.
    //
    // THE TWO ARE READ FROM DIFFERENT PLACES, and the split is why. The owned district's rings are
    // building exteriors in the navigation world, where collision is meant. A tile's rings are not
    // collision at all, and while they sat in that same field the movement resolver stopped a walker
    // against a bench, so they are stated on the tile and the gate reads them there.
    const prisms = [];
    const statedRings = [];
    let refusedRings = [];
    if (scoresOwnedDistrict) {
      // The owned district's rings are building exteriors and take their height from the scored
      // artifact's own records, so they serve both questions there.
      const obstacles = await session.call(bindingId, READ_OBSTACLES);
      for (const obstacle of obstacles) {
        const top = heights.get(obstacle.id);
        if (top === undefined) {
          await halt(`collision obstacle ${obstacle.id} has no record in the scored artifact`);
        }
        for (const ring of obstacle.rings) prisms.push({ id: obstacle.id, ring, baseY: 0, topY: top });
      }
    } else {
      // A tile states plan regions WITHOUT a height, by design: its navigation side drops everything
      // above head height. The gate will not invent one, so these go to the route rule, which reads
      // rings and nothing else, and never to the keys, which measure solids. The named request for
      // rings that carry record identity is gate-route-obstruction-rings in the lane requirements.
      const stated = await session.evaluate(READ_ROUTE_OBSTRUCTIONS);
      // AN ABSENT HOOK IS NOT AN EMPTY SET, and reporting one as the other would send the next reader
      // to the tessellator to find out why a tile states no rings. This says what was established:
      // the page mounted a tile and states no way to read what that tile carries.
      if (stated === null) {
        await halt(
          'the page states no route obstruction hook, so nothing here says what rings the tile it ' +
          'mounted carries. This is NOT a tile with no rings: the tile was never asked. The page ' +
          'states them only on the development preview route, from the module a production build ' +
          'drops, so a page that mounted a tile and states no hook is a page built or routed ' +
          'differently from the one this gate scores.',
        );
      }
      refusedRings = stated.refused;
      for (const obstacle of stated.obstacles) {
        for (const ring of obstacle.rings) statedRings.push({ id: obstacle.id, ring });
      }
    }
    // The route rule reads collision rings: it keeps the headings a capsule can walk, then prefers
    // the one with frontage on both sides. With no rings nothing errors and nothing is decided
    // either: every heading that fits the field qualifies, both tie-breaks are equal for all of
    // them, and the answer is the lowest heading that fits. That is a default wearing the costume
    // of a decision, and a record of it would say the rule was applied. So the run stops here.
    // On the owned district the building exteriors ARE the frontage the rule looks for, so the two
    // inputs are the same set there and this run is byte-identical to one before the split. On a
    // generated target the rings are the ones the tile states on its navigation side, read from
    // the runtime, and the keys keep measuring building exteriors, of which a tile may state none.
    const routeRings = scoresOwnedDistrict ? prisms : statedRings;
    observed.buildingPrisms = prisms.length;
    observed.routeObstacleRings = routeRings.length;
    // What the runtime refused, carried beside what it kept, so a smaller set is never silent: a
    // tile that states sixteen regions and carries fourteen is a different fact from one that states
    // fourteen, and only the refusals tell the two apart.
    observed.routeObstacleRingsRefused = refusedRings;
    if (routeRings.length === 0) {
      await halt(
        'the page states no route obstruction rings, so the route rule has nothing to choose between: ' +
        'every heading would qualify equally and the walk would be the lowest heading that fits, ' +
        'which no rule chose. The page WAS asked, and answered with an empty set. A scored walk ' +
        'needs the rings the tile states, read from the runtime rather than derived here: a gate ' +
        'with its own rings scores a walk past obstacles the world does not have. Those rings ' +
        'choose a heading; they are not collision solids and nothing in them stops a body.',
      );
    }
    // THE FIELD THE WALK IS BOUNDED BY. The owned district states a rectangle in its artifact. A
    // generated tile states no artifact, and the product bounds a walk on one by a CIRCLE: the
    // navigation world's centre and fieldRadius. The rule takes a rectangle, so this passes the
    // square INSCRIBED in that circle, every point of which is inside the field the product
    // bounds. The conservative direction is the right one here: a rectangle drawn around the
    // circle would let the rule qualify a heading whose clear run leaves the world, and a route
    // chosen out there would be scored as if the product allowed it.
    // The artifact's rectangle is read only where an artifact was read. On a generated target there
    // is none, so the four values above are the `[0, 0, 0, 0]` default and asking whether THEY bound
    // anything would refuse every generated run for a rectangle it never uses. Measured: the check
    // below did exactly that on its first run, which is the check working and the placement wrong.
    let field;
    if (scoresOwnedDistrict) {
      field = fieldBounds(west, north, east, south, `the scored artifact ${options.artifact}`);
    } else {
      const bound = await session.call(bindingId, READ_FIELD);
      const half = bound.fieldRadius / Math.SQRT2;
      field = fieldBounds(
        bound.centreX - half, bound.centreZ - half, bound.centreX + half, bound.centreZ + half,
        `the page's navigation world, radius ${bound.fieldRadius} about (${bound.centreX}, ${bound.centreZ})`,
      );
      observed.field = { ...bound, inscribedHalfSideM: half, bounds: field };
      // THE TWO HORIZONS, STATED SIDE BY SIDE, because they are not the same reach and a reader who
      // assumes they are reads a clear run as a clearance.
      //
      // MEASURED 2026-09-18: a composed world gives GROUND from its neighbours and NOT THE OBSTACLES
      // STANDING ON IT. The neighbours contribute their navigation envelope and not their records,
      // so `routeObstacleRings` was 311 before composition and 311 after, while the field's radius
      // went from 94.847 m to 326.337 m. The rule then ranked 720 headings across a field three and
      // a half times wider while seeing one tile's obstacles, and the heading it chose reported a
      // clear run of 294,755 mm: PAST THE OBSTACLE HORIZON THAT FIGURE IS A DISTANCE NOBODY CHECKED
      // FOR OBSTRUCTIONS. `candidatesQualified` rose from 3 to 68 on a world whose obstacle set
      // never changed.
      //
      // THE OBSTACLE REACH IS MEASURED FROM THE RINGS THEMSELVES, never from a tile edge.
      //
      // MEASURED 2026-09-19, after this recorded the wrong quantity: the walked tile's 311 rings
      // span x 178,394 to 464,408 in city millimetres while the tile itself ends at 384,000, so they
      // reach about 80 m PAST it. A tile's own records cannot lie 80 m outside it, so the set is not
      // "one tile's obstacles"; the tess lane reports, and this lane has not read, that
      // `routeObstructionRings` applies no membership filter and the halo a tile carries for carving
      // has been feeding the obstacle set all along. 311 is a true number that does not mean what a
      // reader assumes.
      //
      // Deriving a horizon from `tile_size_mm` was the same fault in a third costume, after a route
      // window taken from a tile edge and a clear run taken from ground. The extent of the rings the
      // rule ACTUALLY HOLDS is the only honest statement of where it can see anything.
      let obstacleBounds = null;
      for (const { ring } of routeRings) {
        for (const point of ring) {
          const [x, z] = point;
          obstacleBounds = obstacleBounds === null
            ? { west: x, north: z, east: x, south: z }
            : {
              west: Math.min(obstacleBounds.west, x),
              north: Math.min(obstacleBounds.north, z),
              east: Math.max(obstacleBounds.east, x),
              south: Math.max(obstacleBounds.south, z),
            };
        }
      }
      const [groundWest, groundNorth, groundEast, groundSouth] = field;
      observed.horizons = {
        frame: 'the renderer frame in metres, the same frame as field.bounds',
        groundBounds: { west: groundWest, north: groundNorth, east: groundEast, south: groundSouth },
        groundRadiusM: bound.fieldRadius,
        obstacleBounds,
        obstacleSource: 'the rings the rule holds, whatever records they came from',
        rings: routeRings.length,
        // The question a reader actually has: is there ground the rule can rank over and see nothing
        // standing on? A `false` here is why a clear run past the obstacles is not a clearance.
        obstaclesCoverTheGround: obstacleBounds !== null
          && obstacleBounds.west <= groundWest && obstacleBounds.north <= groundNorth
          && obstacleBounds.east >= groundEast && obstacleBounds.south >= groundSouth,
      };
    }
    // THE RULE RANKS, THE GROUND REFUSES. The rule's order is taken as it comes and nothing here
    // reorders it: the walk is the FIRST heading the rule prefers that the product can actually
    // walk. The rule is never told why one was refused, because the moment qualification and
    // preference mix, the order that decides which street is looked at stops being a fact about
    // geometry. `planRoute` is this list's first entry, so a run that takes it reports exactly what
    // a run before this change reported.
    const ranked = rankedRoutes([arrival.x, arrival.z], routeRings, field);
    if (ranked.length === 0) {
      await halt('no heading from the arrival pose clears the route length; the route cannot be walked');
    }
    const preferred = ranked[0];
    // IS THERE GROUND ALONG EACH, asked of the product's own surface before a single frame is
    // captured, taking the rule's order and the first heading that has any.
    //
    // MEASURED 2026-09-18, and this is the whole reason it exists. `planRoute` qualifies a heading a
    // 0.34 m capsule can travel without touching a ring or leaving the field, and it never consults
    // support: `firstContact` takes ring edges and four field lines and nothing else. The carve that
    // makes the walkable surface removes support within the capsule radius PLUS its own integer
    // overshoot, which `ring-clearance.ts` states as under five millimetres. So any line whose
    // closest approach to a ring falls between the radius and the radius plus that overshoot
    // QUALIFIES UNDER THE RULE AND HAS NO GROUND UNDER IT. Of this tile's 36 qualifying headings, 35
    // have support for the whole route and the one that does not is the one the rule prefers: it
    // passes a bench at 343.5 mm. That walk ran 52.795 m before the product refused to move.
    //
    // THIS DOES NOT CHOOSE. It takes the rule's order as given and refuses, in order, until one has
    // ground. Every refusal is recorded with where its ground stopped, so a record says whether the
    // walk was the rule's first preference or its fourth, which is what `candidatesWithFrontage`
    // exists to say about the tie-break and what this says about the ground.
    //
    // Sampled at 5 mm rather than at the product's own 0.05 m path spacing: the unsupported run on
    // this tile is 32 mm and the walker advances about 28 mm a frame, so a probe at the product's
    // spacing can step over the thing that stops the walk. One batch per heading, about 26,000
    // points.
    //
    // THE GENERATED TARGET ONLY, and that is a limit rather than a judgement. The disagreement was
    // measured on a tile's carve; whether this check is inert on the owned district has NOT been
    // measured, because running that target needs the API and a credential this lane does not hold.
    // A check that has never been run against the one page every retained record scored must not be
    // able to refuse it. Extending it there needs the product target run before and after, with
    // every plan field pinned, which is the measurement the orchestrator has asked for.
    const walkedM = (preferred.rule.lengthMm + preferred.rule.stopMarginMm) / 1000;
    const groundProbes = Math.round(walkedM / PROBE_SPACING_M) + 1;
    /** The nearest route obstruction ring to a point, which separates a carve boundary from an edge. */
    const nearestRingTo = (x, z) => {
      let nearest = null;
      for (const { id, ring } of routeRings) {
        for (let k = 0; k < ring.length; k += 1) {
          const a = ring[k];
          const b = ring[(k + 1) % ring.length];
          const ex = b[0] - a[0];
          const ez = b[1] - a[1];
          const length2 = ex * ex + ez * ez;
          const t = length2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - a[0]) * ex + (z - a[1]) * ez) / length2));
          const metres = Math.hypot(x - (a[0] + ex * t), z - (a[1] + ez * t));
          if (nearest === null || metres < nearest.metres) nearest = { id, metres };
        }
      }
      return nearest;
    };
    /** Where the product's own surface first states no support along a candidate, or null. */
    const groundUnder = async (candidate) => {
      const points = new Float64Array(groundProbes * 2);
      for (let step = 0; step < groundProbes; step += 1) {
        points[step * 2] = candidate.start[0] + candidate.forward[0] * (step * PROBE_SPACING_M);
        points[step * 2 + 1] = candidate.start[1] + candidate.forward[1] * (step * PROBE_SPACING_M);
      }
      const heights = float64FromBase64(await session.call(bindingId, SAMPLE_SUPPORT, [toBase64(points)]));
      let firstGap = null;
      let gaps = 0;
      for (let step = 0; step < heights.length; step += 1) {
        if (!Number.isNaN(heights[step])) continue;
        gaps += 1;
        if (firstGap === null) firstGap = step * PROBE_SPACING_M;
      }
      // Measured for EVERY candidate, supported or not, because the rise is a fact about the line
      // whether or not the ground also runs out later along it.
      const steepestRise = steepestRiseOf(heights, PROBE_SPACING_M);
      if (firstGap === null) {
        return { headingMillidegrees: candidate.headingMillidegrees, supported: true, steepestRise };
      }
      const x = candidate.start[0] + candidate.forward[0] * firstGap;
      const z = candidate.start[1] + candidate.forward[1] * firstGap;
      const nearest = nearestRingTo(x, z);
      return {
        headingMillidegrees: candidate.headingMillidegrees,
        supported: false,
        firstUnsupportedAtM: firstGap,
        unsupportedProbes: gaps,
        steepestRise,
        // WHERE it runs out, and not only how far along. MEASURED 2026-09-18: three headings lost
        // support within the last 2.6 m of a 131 m route, and only the position said why: every one
        // of them was PAST THE TILE'S OWN EDGE. A distance along a heading cannot be compared with a
        // tile boundary without doing the trigonometry by hand, which is how a reader ends up
        // guessing at a mechanism instead of reading one.
        at: { xM: Number(x.toFixed(4)), zM: Number(z.toFixed(4)) },
        nearestRouteRing: nearest === null ? null : { id: nearest.id, metres: Number(nearest.metres.toFixed(4)) },
      };
    };
    let walkPlan = preferred;
    let walkedGround = null;
    const groundRefused = [];
    if (!scoresOwnedDistrict) {
      walkPlan = null;
      for (const candidate of ranked) {
        const gap = await groundUnder(candidate);
        if (gap.supported) {
          walkPlan = candidate;
          walkedGround = gap;
          break;
        }
        groundRefused.push(gap);
      }
      observed.routeGround = {
        asked: true,
        probeSpacingM: PROBE_SPACING_M,
        probesPerHeading: groundProbes,
        lengthM: walkedM,
        preferredByTheRule: preferred.headingMillidegrees,
        refusedForNoGround: groundRefused,
        walked: walkPlan === null ? null : walkPlan.headingMillidegrees,
        // The rise along the line actually walked, beside the rises of the ones refused, so a stall
        // later in the run can be read against what this check already knew about that line.
        walkedGround,
        productMaximumStepHeight: observed.field?.maximumStepHeight ?? null,
      };
      if (walkPlan === null) {
        const first = groundRefused[0];
        await halt(
          `no heading the route rule qualifies has ground along it: all ${groundRefused.length} were ` +
          `refused by the product's own navigation surface, sampled every ` +
          `${PROBE_SPACING_M * 1000} mm over ${walkedM} m. The one the rule preferred, ` +
          `${first.headingMillidegrees} millidegrees, loses support ${first.firstUnsupportedAtM.toFixed(3)} m ` +
          `along, at (${first.at.xM}, ${first.at.zM})` +
          (first.nearestRouteRing === null ? '' : `, ${first.nearestRouteRing.metres.toFixed(3)} m from a ring ` +
            `the rule qualifies past at ${THRESHOLDS.capsuleRadiusMm} mm`) +
          '. The rule reads rings and the field and never asks what holds a body up, so a line it ' +
          'offers can cross ground that is not there. WHAT REMOVED THE SUPPORT IS NOT NAMED HERE: ' +
          'the position and the distance to the nearest ring are stated so a reader can tell a ' +
          'clearance carve from ground that simply ends.' +
          (first.steepestRise === null ? '' : ` Along that line the ground also rises at most ` +
            `${first.steepestRise.riseMm} mm between samples 5 mm apart, at ${first.steepestRise.atM} m` +
            (observed.field?.maximumStepHeight === undefined ? ''
              : `, against the ${observed.field.maximumStepHeight * 1000} mm this world states it will climb`) +
            ', which is a separate fact from where the support ends.'),
        );
      }
      if (groundRefused.length > 0) {
        phase(`${groundRefused.length} heading(s) the rule preferred have no ground; walking ${walkPlan.headingMillidegrees}`);
      }
    }
    // Bound the moment it is decided, so a halt AFTER the route is chosen still says what the rule
    // decided and on what. A halt that carries the reason and not the decision leaves the next
    // reader unable to tell a rule that chose from a rule that fell back.
    observed.route = {
      // WHERE IT STARTED, because a halt that states a heading and no origin states a direction and
      // not a route, and every figure below is measured from this point.
      startMm: [Math.round(walkPlan.start[0] * 1000), Math.round(walkPlan.start[1] * 1000)],
      headingMillidegrees: walkPlan.headingMillidegrees,
      clearRunMm: walkPlan.clearRunMm,
      frontageSamples: walkPlan.frontageSamples,
      frontageBothSidesSamples: walkPlan.frontageBothSidesSamples,
      meanFrontageSkewMillionths: walkPlan.meanFrontageSkewMillionths,
      candidatesTried: walkPlan.candidatesTried,
      candidatesQualified: walkPlan.candidatesQualified,
      candidatesWithFrontage: walkPlan.candidatesWithFrontage,
      // How many headings the rule preferred to this one and the ground refused. Zero means the walk
      // is the rule's own first choice, which is what a record stating only a heading cannot say.
      headingsRefusedForNoGround: groundRefused.length,
    };
    // Everything downstream reads the plan that will be WALKED, which is the rule's own first
    // choice unless the ground refused it, and the record says which by `headingsRefusedForNoGround`.
    const plan = walkPlan;
    phase(`the route was planned at ${plan.headingMillidegrees} millidegrees`);

    const interactions = [];
    const harnessWrites = [];
    const key = async (type, code, keyName, virtual, autoRepeat = false) => {
      await session.send('Input.dispatchKeyEvent', {
        type, code, key: keyName, windowsVirtualKeyCode: virtual, nativeVirtualKeyCode: virtual,
        text: type === 'keyDown' && keyName.length === 1 ? keyName : undefined, autoRepeat,
      });
    };
    // A held physical key keeps sending repeated keydown events. The product relies on that: a
    // shell refresh clears its held-key set, and the next repeat puts the key back.
    const KEY_REPEAT = Object.freeze({ delayMs: 250, intervalMs: 33 });
    const refuseTyping = async (what) => {
      const state = await captureState();
      if (state.typingTarget) await halt(`${what}: focus is in a text field, so keys would type instead of act`);
    };

    const pointerLockSamples = [];
    const noteLock = (at, state) => pointerLockSamples.push({ at, pointerLocked: state.pointerLocked });

    // The product gives the keyboard to one owner at a time: with the Companion open, walking is
    // off. So the Companion is summoned for each capture and dismissed before each walk, each
    // time through the product's own key handlers.
    const summon = async (at) => {
      await refuseTyping('summon');
      await key('keyDown', 'KeyX', 'x', 88);
      await key('keyUp', 'KeyX', 'x', 88);
      let summoned = false;
      for (let attempt = 0; attempt < 30 && !summoned; attempt += 1) {
        await sleep(100);
        const state = await captureState();
        const controls = await pose();
        summoned = state.companion.shown && controls.conversationActive;
      }
      interactions.push({ kind: 'summon-companion', key: 'KeyX', at, carriedByProduct: summoned });
      if (!summoned) await halt(`the product did not summon the Companion on X at ${at}`);
    };
    const dismiss = async (at) => {
      await key('keyDown', 'Escape', 'Escape', 27);
      await key('keyUp', 'Escape', 'Escape', 27);
      let dismissed = false;
      for (let attempt = 0; attempt < 30 && !dismissed; attempt += 1) {
        await sleep(100);
        const state = await captureState();
        const controls = await pose();
        dismissed = state.companion.encounter?.state !== 'open' && controls.enabled &&
          !controls.conversationActive;
      }
      interactions.push({ kind: 'dismiss-companion', key: 'Escape', at, carriedByProduct: dismissed });
      if (!dismissed) await halt(`the product did not dismiss the Companion on Escape at ${at}`);
    };
    // Walking without pointer lock needs the world canvas focused. A real click on the canvas is
    // the product's own way there, and the gesture its arrival prompt asks for: its mousedown
    // handler focuses the canvas and asks for the lock.
    const focusWorld = async (at) => {
      const current = await captureState();
      if (current.atlasFocused) return;
      const point = await session.call(documentId, `function () {
        const canvas = document.getElementById('atlas');
        const cx = innerWidth / 2;
        const cy = innerHeight / 2;
        for (let ring = 0; ring <= 12; ring += 1) {
          for (let step = 0; step < Math.max(1, ring * 8); step += 1) {
            const angle = (step / Math.max(1, ring * 8)) * Math.PI * 2;
            const x = Math.round(cx + Math.cos(angle) * ring * 24);
            const y = Math.round(cy + Math.sin(angle) * ring * 24);
            if (document.elementFromPoint(x, y) === canvas) return { x, y };
          }
        }
        return null;
      }`);
      if (point === null) await halt(`no point near the centre reaches the world canvas at ${at}`);
      await session.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: point.x, y: point.y });
      await session.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button: 'left', buttons: 1, clickCount: 1 });
      await session.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button: 'left', buttons: 0, clickCount: 1 });
      let focused = false;
      let state = current;
      for (let attempt = 0; attempt < 30 && !focused; attempt += 1) {
        await sleep(100);
        state = await captureState();
        focused = state.atlasFocused;
      }
      noteLock(`after focus click at ${at}`, state);
      interactions.push({ kind: 'focus-world', input: 'left click on the world canvas', at, point, carriedByProduct: focused });
      if (!focused) await halt(`the product did not focus the world canvas on a click at ${at}`);
    };

    // Face along the route. Mouse look would write this same value; nothing writes a position.
    await session.call(bindingId, `function (yaw) { this.controls.state.yaw = yaw; return true; }`, [plan.yaw]);
    noteLock('when the heading was written', await captureState());
    harnessWrites.push({ field: 'controls.state.yaw', valueMicroradians: Math.round(plan.yaw * 1e6), why: 'mouse look needs pointer movement under a held lock, which the harness does not synthesize; the heading is written once and no position is written' });

    const recorderId = await session.call(bindingId, INSTALL_RECORDER, [], false);
    const accelTime = await session.call(bindingId, `function () { return this.controls.config.accelTime; }`);
    const [fx, fz] = plan.forward;
    const along = (p) => (p.x - arrival.x) * fx + (p.z - arrival.z) * fz;

    const settle = async () => {
      const started = Date.now();
      for (;;) {
        const p = await pose();
        if (p.speed < 0.002) return p;
        if (Date.now() - started > 5000) await halt('the player did not come to rest');
        await sleep(20);
      }
    };

    const captures = [];
    const capture = async (label) => {
      await settle();
      await summon(label);
      await session.call(bindingId, `function () { this.invalidate(); return true; }`);
      await sleep(500);
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const p0 = await pose();
        const state = await captureState();
        const stats = await session.call(appId, `function () { return { drawCalls: this.stats.drawCalls.total, frame: this.frame }; }`);
        const { data } = await session.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
        const p1 = await pose();
        const moved = Math.hypot(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z);
        if (moved > 0.001 || Math.abs(p1.yaw - p0.yaw) > 1e-6) continue;
        const bytes = Buffer.from(data, 'base64');
        const file = `${options.label}-capture-${String(captures.length + 1).padStart(2, '0')}-route-${label}.png`;
        writeFileSync(join(out, file), bytes);
        noteLock(`${label} capture`, state);
        phase(`the ${label} capture was taken`);
        captures.push({
          label,
          file,
          byteSize: bytes.byteLength,
          sha256: sha256(bytes),
          pose: p1,
          alongMetres: along(p1),
          stats,
          state,
        });
        return;
      }
      await halt(`the pose would not hold still for the ${label} capture`);
    };

    const routeLength = THRESHOLDS.routeLengthMm / 1000;
    const walkTo = async (targetAlong) => {
      await refuseTyping('walk');
      const start = await pose();
      // The rest pose opens the trace, so the walk is measured from where the player stood.
      const opened = await session.send('Runtime.callFunctionOn', {
        objectId: recorderId,
        functionDeclaration: `function (binding) {
          const s = binding.controls.state;
          this.poses.push([s.x, s.y, s.z, s.yaw, s.pitch, binding.controls.movementSpeed]);
          this.recording = true;
          return true;
        }`,
        arguments: [{ objectId: bindingId }],
        returnByValue: true,
      });
      if (opened.exceptionDetails) await halt('the trace recorder could not be started');
      await key('keyDown', 'KeyW', 'w', 87);
      const started = Date.now();
      let nextRepeat = started + KEY_REPEAT.delayMs;
      let repeats = 0;
      let releasedAt = started;
      // A stall is a lack of progress, not a slow walk: the product walks at its own pace.
      let best = along(start);
      let bestAt = started;
      try {
        for (;;) {
          const p = await pose();
          if (along(p) + p.speed * accelTime >= targetAlong) break;
          if (along(p) > best + 0.05) {
            best = along(p);
            bestAt = Date.now();
          }
          if (Date.now() - bestAt > 5000 || Date.now() - started > 600_000) {
            // A stall has several causes and a message naming one has to tell them apart. Ask the
            // product's own navigation surface what stands ahead of where it stopped: a walk that
            // ran out of support and a walk the keyboard lost are different facts, and the record
            // says which by stating where the surface ends rather than by inferring it.
            //
            // AT A SPACING THE WALK CAN FALL INTO. MEASURED 2026-09-18: this probe ran every
            // 0.25 m and reported "support for the next 10 m" over a 32 mm hole 13 mm ahead of a
            // stall, which is where the walker's next frame lands at 1.65 m/s. The product refuses
            // a desired point with no surface, so a probe coarser than one frame of walking
            // measures a population that excludes the thing that stops a walk, and the sentence it
            // produced sent a reader looking for a collision for a whole run.
            const PROBE_REACH_M = 10;
            const probes = Math.round(PROBE_REACH_M / PROBE_SPACING_M) + 1;
            const ahead = new Float64Array(probes * 2);
            for (let step = 0; step < probes; step += 1) {
              ahead[step * 2] = p.x + plan.forward[0] * (step * PROBE_SPACING_M);
              ahead[step * 2 + 1] = p.z + plan.forward[1] * (step * PROBE_SPACING_M);
            }
            const sampled = float64FromBase64(await session.call(bindingId, SAMPLE_SUPPORT, [toBase64(ahead)]));
            const supported = [...sampled].map((height, step) => ({ atM: Number((step * PROBE_SPACING_M).toFixed(3)), height }));
            const firstGap = supported.find((sample) => Number.isNaN(sample.height)) ?? null;
            // How wide the hole is, and whether the surface comes back. A gap the walk could step
            // over, a gap that pins it and an edge the surface never resumes past are three facts,
            // and only the width and the far side tell them apart.
            const resumes = firstGap === null ? null
              : supported.find((sample) => sample.atM > firstGap.atM && !Number.isNaN(sample.height)) ?? null;
            // The biggest rise between two probes one product sample spacing apart, which is what
            // the product's own path check compares, taken before any gap.
            const stride = Math.max(1, Math.round((observed.field?.surfaceSampleSpacing ?? 0.05) / PROBE_SPACING_M));
            let rise = { fromM: null, heightM: 0 };
            for (let step = stride; step < supported.length; step += stride) {
              const before = supported[step - stride].height;
              const after = supported[step].height;
              if (Number.isNaN(before) || Number.isNaN(after)) break;
              if (after - before > rise.heightM) rise = { fromM: supported[step - stride].atM, heightM: after - before };
            }
            // The nearest route obstruction ring to where it stopped, from the rings the page
            // states. A walk that stopped at a ring and a walk that stopped at a hole in the
            // surface look identical in a position, and this is what separates them.
            let nearestRing = null;
            for (const { id, ring } of routeRings) {
              for (let k = 0; k < ring.length; k += 1) {
                const a = ring[k];
                const b = ring[(k + 1) % ring.length];
                const ex = b[0] - a[0];
                const ez = b[1] - a[1];
                const length2 = ex * ex + ez * ez;
                const t = length2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a[0]) * ex + (p.z - a[1]) * ez) / length2));
                const metres = Math.hypot(p.x - (a[0] + ex * t), p.z - (a[1] + ez * t));
                if (nearestRing === null || metres < nearestRing.metres) nearestRing = { id, metres };
              }
            }
            // What the PRODUCT said, in its own words, while this walk ran. The recorder has been
            // keeping them since the walk opened and nothing read them at a stall, so a run could
            // report three causes ruled out while the product's own status line named one.
            const productSaid = await session.call(recorderId, 'function () { return this.failures.slice(-5); }');
            // How far the walk was actually moving each frame, from the product's own trace rather
            // than from any constant here: the middle of the non-zero planar steps over EVERY frame
            // recorded since the walk opened. It is the step the movement resolver asks its surface
            // about, so a hole narrower than it can still stop the walk and a reader needs both.
            //
            // Every frame, not the last few: a stall is detected after five seconds of no progress,
            // so the most recent hundreds of frames are all stationary and a window over them
            // reports that the walk was not moving, which is the thing being explained rather than
            // an explanation of it. Computed on the page, because the trace is thousands of poses.
            const perFrameMm = await session.call(recorderId, `function () {
              const steps = [];
              for (let index = 1; index < this.poses.length; index += 1) {
                const step = Math.hypot(this.poses[index][0] - this.poses[index - 1][0],
                  this.poses[index][2] - this.poses[index - 1][2]);
                if (step > 0) steps.push(step);
              }
              if (steps.length === 0) return null;
              steps.sort((a, b) => a - b);
              return Math.round(steps[Math.floor(steps.length / 2)] * 1000);
            }`);
            const field = observed.field ?? {};
            observed.stall = {
              atX: p.x, atZ: p.z,
              alongM: Number(along(p).toFixed(3)),
              targetAlongM: targetAlong,
              speed: p.speed,
              advancePerFrameMm: perFrameMm,
              supportUnderfoot: supported[0].height,
              firstUnsupportedAheadM: firstGap === null ? null : firstGap.atM,
              unsupportedResumesAtM: resumes === null ? null : resumes.atM,
              unsupportedWidthMm: firstGap === null || resumes === null ? null
                : Math.round((resumes.atM - firstGap.atM) * 1000),
              largestRiseAheadM: rise.heightM,
              largestRiseAtM: rise.fromM,
              nearestRouteRing: nearestRing === null ? null
                : { id: nearestRing.id, metres: Number(nearestRing.metres.toFixed(4)) },
              productRecoveryMessages: productSaid,
              productMaximumStepHeight: field.maximumStepHeight ?? null,
              productMaximumSlopeDegrees: field.maximumSlopeDegrees ?? null,
              metresFromFieldCentre: field.centreX === undefined ? null
                : Math.round(Math.hypot(p.x - field.centreX, p.z - field.centreZ) * 1000) / 1000,
              fieldRadius: field.fieldRadius ?? null,
              supportProbeSpacingM: PROBE_SPACING_M,
              supportProbeReachM: PROBE_REACH_M,
            };
            await halt(`the walk stalled at ${along(p).toFixed(2)} m of ${targetAlong} m ` +
              `(speed ${p.speed.toFixed(3)}, enabled ${p.enabled}, conversation ${p.conversationActive}, ` +
              `repeats ${repeats}); the product's navigation surface ` +
              (firstGap !== null
                ? `states no support from ${firstGap.atM} m ahead` +
                  (resumes === null
                    ? ', and none again within 10 m, so the surface ends there'
                    : ` to ${resumes.atM} m ahead, ${Math.round((resumes.atM - firstGap.atM) * 1000)} mm of it` +
                      (perFrameMm === null ? '' : `, and this walk was advancing ${perFrameMm} mm a frame, so its ` +
                        'next position falls in that hole and the product recovers to where it already was')) +
                  (nearestRing === null ? '' : `; the nearest route obstruction ring is ${nearestRing.metres.toFixed(3)} m away`)
                : rise.heightM > (observed.field?.maximumStepHeight ?? Infinity)
                  ? `rises ${rise.heightM.toFixed(3)} m at ${rise.fromM} m ahead, over the ` +
                    `${observed.field.maximumStepHeight} m step this world states it will climb`
                  : `states support for the next ${PROBE_REACH_M} m sampled every ` +
                    `${PROBE_SPACING_M * 1000} mm and rises at most ${rise.heightM.toFixed(3)} m, ` +
                    'so neither the surface ending nor a step it refuses stopped this walk') +
              (productSaid.length === 0 ? '' : `. The product said: ${productSaid.join(' | ')}`));
          }
          if (Date.now() >= nextRepeat) {
            await key('keyDown', 'KeyW', 'w', 87, true);
            repeats += 1;
            nextRepeat += KEY_REPEAT.intervalMs;
          }
          await sleep(4);
        }
      } finally {
        releasedAt = Date.now();
        await key('keyUp', 'KeyW', 'w', 87);
      }
      const end = await settle();
      const displacement = along(end) - along(start);
      interactions.push({
        kind: 'walk',
        key: 'KeyW',
        heldMs: releasedAt - started,
        autoRepeat: { ...KEY_REPEAT, repeatedKeyDowns: repeats },
        targetAlongMm: Math.round(targetAlong * 1000),
        displacementMillimetres: Math.round(displacement * 1000),
        carriedByProduct: displacement > 1,
      });
      if (displacement <= 1) await halt('the product did not move the player on W');
      phase(`the walk reached ${along(end).toFixed(2)} m of ${targetAlong} m`);
    };

    await capture(CAPTURE_LABELS[0]);
    await dismiss(CAPTURE_LABELS[0]);
    await focusWorld(CAPTURE_LABELS[0]);
    await walkTo(routeLength / 2);
    await capture(CAPTURE_LABELS[1]);
    await dismiss(CAPTURE_LABELS[1]);
    await focusWorld(CAPTURE_LABELS[1]);
    await walkTo(routeLength);
    await capture(CAPTURE_LABELS[2]);
    await session.call(recorderId, `function () { this.recording = false; return true; }`);
    const recorded = await session.call(recorderId, `function () {
      const out = { poses: this.poses, failures: this.failures, maxDrawCalls: this.maxDrawCalls,
        renderedFrames: this.renderedFrames };
      this.handle.off();
      this.frameHandle.off();
      this.observer?.disconnect();
      return out;
    }`);
    const poses = recorded.poses.map(([x, y, z, yaw, pitch, speed]) => ({ x, y, z, yaw, pitch, speed }));
    if (poses.length === 0) await halt('the live trace recorded no frame of the walk');
    phase(`the trace holds ${poses.length} frames`);

    const authored = await session.call(bindingId, `function () {
      return { objectIds: [...this.objects.objectIds], district: this.ownedDistrict?.metrics ?? null };
    }`);
    phase('the authored objects were read');

    // What was drawn, and the product's own support under it. The scene is held in the page and
    // read in pieces: a reply of about six megabytes was never delivered by the protocol.
    const sceneId = await session.call(bindingId, EXTRACT_SCENE, [pcUrl], false);
    const sceneInfo = await session.call(sceneId, `function () {
      return { ...this, meshes: this.meshes.map(({ triangles, ...rest }) => ({ ...rest, triangleChars: triangles.length })) };
    }`);
    const TEXT_PIECE = 1_000_000;
    const triangleTexts = [];
    for (const [index, mesh] of sceneInfo.meshes.entries()) {
      const pieces = [];
      for (let offset = 0; offset < mesh.triangleChars; offset += TEXT_PIECE) {
        pieces.push(await session.call(sceneId, `function (index, offset, size) {
          return this.meshes[index].triangles.slice(offset, offset + size);
        }`, [index, offset, TEXT_PIECE]));
      }
      const text = pieces.join('');
      if (text.length !== mesh.triangleChars) await halt(`mesh ${mesh.id} arrived incomplete`);
      triangleTexts.push(text);
    }
    const scene = {
      ...sceneInfo,
      meshes: sceneInfo.meshes.map(({ triangleChars, ...mesh }, index) => ({ ...mesh, triangles: triangleTexts[index] })),
    };
    phase(`the drawn scene was read: ${scene.meshes.length} meshes`);
    const meshes = scene.meshes.map((mesh) => ({
      id: mesh.id,
      cull: mesh.cull,
      hasUv: mesh.hasUv,
      decodedTextureBytes: mesh.decodedTextureBytes,
      triangles: float64FromBase64(mesh.triangles),
    }));
    let supportQueries = 0;
    const measured = await measureScene({
      meshes,
      prisms,
      plan,
      poses,
      sampleSupport: async (points) => {
        supportQueries += points.length / 2;
        const heights = [];
        // Batched, for the same reason the scene is read in pieces.
        for (let start = 0; start < points.length; start += 100_000) {
          const text = await session.call(bindingId, SAMPLE_SUPPORT, [toBase64(points.subarray(start, start + 100_000))]);
          for (const value of float64FromBase64(text)) heights.push(Number.isNaN(value) ? null : value);
        }
        return heights;
      },
    });

    phase('the drawn scene was measured');
    // The product's own validation report, emitted once its measuring window closes.
    const report = await (async () => {
      phase('waiting for the product validation report');
      const deadline = navigatedAt + (options.validationSeconds + 90) * 1000;
      for (;;) {
        const text = await session.evaluate(`document.getElementById('exulanica-browser-validation-report')?.textContent ?? null`);
        if (text !== null) return JSON.parse(text);
        if (Date.now() > deadline) await halt('the product never emitted its validation report');
        await sleep(1000);
      }
    })();

    // What the page drew, found on the wire by its bytes rather than by its name.
    let environment = null;
    if (scoresOwnedDistrict) {
      for (const [requestId, entry] of network) {
        if (!entry.finished || entry.decodedBytes !== artifactBytes.byteLength) continue;
        const bytes = await bodyOf(requestId);
        if (bytes === null || sha256(bytes) !== sha256(artifactBytes)) continue;
        environment = { requestPath: normalizeUrl(entry.url), transferredBytes: entry.encodedBytes, decodedBytes: bytes.byteLength, status: entry.status };
        break;
      }
      if (environment === null) await halt('the page never fetched the scored artifact byte for byte');
      phase('the scored artifact was matched on the wire');
    } else {
      const bound = await collectContainers();
      if (bound.length === 0) await halt('the page drew no container this run could bind');
      environment = bound[0];
      phase(`${bound.length} container(s) were matched on the wire`);
    }

    // Listeners on the window, the document and the world canvas, by the script that added them.
    // Read last, once every measurement that needs the binding is done, so toggling the debugger
    // domain cannot touch them.
    await session.send('Debugger.enable');
    await sleep(300);
    const scripts = new Map();
    for (const event of session.events) {
      if (event.method === 'Debugger.scriptParsed') scripts.set(event.params.scriptId, event.params.url);
    }
    const listenerInventory = [];
    const counts = { product: 0, 'dev-server': 0, foreign: 0 };
    let productWindowKeydownListeners = 0;
    for (const [targetName, expression] of [
      ['window', 'window'],
      ['document', 'document'],
      ['canvas', `document.getElementById('atlas')`],
    ]) {
      const objectId = await session.reference(expression);
      const { listeners } = await session.send('DOMDebugger.getEventListeners', { objectId });
      for (const listener of listeners) {
        const source = normalizeUrl(scripts.get(listener.scriptId));
        const kind = listenerSource(source);
        counts[kind] += 1;
        if (targetName === 'window' && listener.type === 'keydown' && kind === 'product') {
          productWindowKeydownListeners += 1;
        }
        listenerInventory.push({ target: targetName, type: listener.type, source, kind, line: listener.lineNumber });
      }
    }
    await session.send('Debugger.disable');
    phase('the listeners were inventoried');
    listenerInventory.sort((a, b) =>
      `${a.target}|${a.type}|${a.source}|${a.line}`.localeCompare(`${b.target}|${b.type}|${b.source}|${b.line}`));


    const requests = [...network.values()];
    const pathOf = (entry) => {
      try {
        return new URL(entry.url).pathname;
      } catch {
        return '';
      }
    };
    const apiResponses = {};
    for (const entry of requests) {
      const path = pathOf(entry);
      if (!path.startsWith('/api/')) continue;
      const route = path.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '{id}');
      const name = `${entry.method} ${route} ${entry.status ?? 'none'}`;
      apiResponses[name] = (apiResponses[name] ?? 0) + 1;
    }
    const previewApi = requests
      .filter((entry) => pathOf(entry).startsWith('/preview-api/'))
      .map((entry) => ({ url: normalizeUrl(entry.url), status: entry.status }));
    const graphRead = requests.some((entry) => pathOf(entry) === '/api/graph' && entry.status === 200);
    let authenticationCondition = null;
    if (previewApi.length === 0 && graphRead && anonymousStatus === 401) authenticationCondition = 'credentialed-api';
    else if (previewApi.length > 0 && !requests.some((entry) => pathOf(entry).startsWith('/api/'))) authenticationCondition = 'vite-preview-api';
    if (authenticationCondition === null) {
      await halt(`the authentication condition cannot be named: preview requests ${previewApi.length}, graph read ${graphRead}, anonymous status ${anonymousStatus}`);
    }

    const gpuError = report.renderer?.gpu_error;
    if (typeof gpuError !== 'number') await halt('the product report did not measure the GPU error state');
    const substitutedPages = navigations.filter((url) => {
      if (url === 'about:blank') return false;
      try {
        const parsed = new URL(url);
        return parsed.origin !== appOrigin || parsed.pathname !== '/';
      } catch {
        return true;
      }
    }).length;
    const observation = {
      captures: captures.map((item) => ({
        label: item.label,
        companionShown: item.state.companion.shown,
        reticleCentred: item.state.reticle.centred,
        inProductShell: item.state.inProductShell,
      })),
      foreignListeners: counts.foreign,
      productWindowKeydownListeners,
      interactionsNotCarriedByProduct: interactions.filter((item) => !item.carriedByProduct).length,
      substitutedPages,
      recoveryEvents: recorded.failures.length,
      harnessPositionWrites: harnessWrites.filter((write) => /\.(x|y|z)$/.test(write.field)).length,
      environmentTransferredBytes: environment.transferredBytes,
      environmentDecodedTextureBytes: scene.environmentTextureBytes,
      // The product's window closes before a walk at the product's pace ends, so the run's
      // maximum is the larger of its window and the whole route.
      maxDrawCalls: Math.max(report.renderer.max_draw_calls, recorded.maxDrawCalls),
      gpuErrors: gpuError === 0 ? 0 : 1,
      pageErrors: exceptions.length,
    };
    const mechanical = mechanicalMeasurements(measured, observation);
    const keys = keySet(mechanical);

    const run = {
      profile: 'exulanica.visual-gate-run/v1',
      keySet: GATE_KEY_SET_VERSION,
      label: options.label,
      app: { origin: appOrigin, path: appUrl.pathname, search: appUrl.search, validationSeconds: options.validationSeconds },
      target: options.target,
      pageCheck: { path: gateTarget.path, title: expectedTitle, titleFrom: `${TITLE_SOURCE} ${gateTarget.titleSymbol}` },
      // What served the page, STATED by the runner and not bound by anything. See the option's
      // comment: a record binds what the page drew and not the tree the page was built from.
      servedBy: { entry: options.servedBy, worktree: options.servedFrom, stated: true, bound: false },
      scored: {
        ...(scoresOwnedDistrict
          ? { artifact: { path: options.artifact, byteSize: artifactBytes.byteLength, sha256: sha256(artifactBytes), profile: artifact.profile, districtId: artifact.district_id } }
          : {
            containers,
            tile: tileMetrics,
            // What the total above is made of, by the reason the runtime states for each surface,
            // so a reader never has to know that an unfetched texture set counts in it.
            unavailableSurfacesByReason: unavailableByReason,
          }),
        renderer: { path: options.renderer, byteSize: rendererBytes.byteLength, sha256: sha256(rendererBytes) },
        measuredBy,
      },
      browser: {
        engine: `${version.Browser} over the Chrome DevTools Protocol, driven by scripts/capture_visual_gate.mjs (no Playwright)`,
        protocolVersion: version['Protocol-Version'],
        viewport: [VIEWPORT.width, VIEWPORT.height],
        deviceScaleFactor: 1,
        mountMs,
      },
      authentication: {
        condition: authenticationCondition,
        anonymousGraphReadStatus: anonymousStatus,
        apiResponses,
        previewApiRequests: previewApi,
      },
      arrival,
      // The walk somebody stated in advance, with the file it was read from, or null when this
      // run opened wherever the page opens. A record that says neither is a record that cannot
      // say whether its opening frame was reproducible.
      statedWalk: observed.statedWalk ?? null,
      // What the page itself said about its opening frame, or null on a target that states
      // none. A record carrying both can be checked by a reader; one carrying only the walk
      // this run asked for says what was intended and not what happened.
      opening: observed.opening ?? null,
      route: routeRecordOf(plan, {
        field: observed.field ?? { bounds: [west, north, east, south], from: options.artifact },
        obstacles: prisms.length,
        routeRings: routeRings.length,
        routeRingsRefused: observed.routeObstacleRingsRefused ?? [],
        horizons: observed.horizons ?? null,
        groundRefused,
        routeGround: observed.routeGround ?? null,
        // What each container was FOR, not merely that it was fetched.
        walkWorld: observed.walkWorld ?? null,
        fieldBoundsCm: artifact?.bounds_cm ?? null,
      }),
      interactions,
      harnessWrites,
      pointerLock: {
        everHeld: pointerLockSamples.some((sample) => sample.pointerLocked),
        samples: pointerLockSamples,
      },
      harnessObservers: [
        'one engine update listener that copies the controls state each frame while the walk runs',
        'one engine frameend listener that keeps the largest per-frame draw call count from the start capture to the endpoint capture',
        'one MutationObserver on the travel status that records failure messages while the walk runs',
      ],
      drawCalls: {
        productWindowMax: report.renderer.max_draw_calls,
        productWindowSeconds: options.validationSeconds,
        routeMax: recorded.maxDrawCalls,
        routeRenderedFrames: recorded.renderedFrames,
        decidingMax: Math.max(report.renderer.max_draw_calls, recorded.maxDrawCalls),
      },
      captures,
      trace: {
        frames: poses.length,
        first: poses[0],
        last: poses[poses.length - 1],
        recoveryMessages: recorded.failures,
      },
      listeners: { counts, productWindowKeydownListeners, inventory: listenerInventory },
      authoredObjects: authored,
      scene: {
        meshes: scene.meshes.map((mesh) => ({
          id: mesh.id, cull: mesh.cull, hasUv: mesh.hasUv, textureCount: mesh.textureCount,
          decodedTextureBytes: mesh.decodedTextureBytes,
          triangles: Buffer.from(mesh.triangles, 'base64').byteLength / 72,
        })),
        skipped: scene.skipped,
        layerInventory: scene.layerInventory,
        renderOrigin: scene.origin,
        environmentTextures: scene.environmentTextures,
        environmentTextureBytes: scene.environmentTextureBytes,
        deviceTextureBytes: scene.deviceTextureBytes,
        deviceVram: scene.deviceVram,
        supportQueries,
      },
      measured,
      network: {
        environment,
        requests: requests.length,
        finishedRequests: requests.filter((entry) => entry.finished).length,
        failedRequests: requests.filter((entry) => entry.failed !== null).map((entry) => ({ url: normalizeUrl(entry.url), error: entry.failed })),
        httpErrors: requests.filter((entry) => (entry.status ?? 0) >= 400).map((entry) => ({ url: normalizeUrl(entry.url), status: entry.status })),
        transferredBytes: requests.reduce((sum, entry) => sum + entry.encodedBytes, 0),
      },
      errors: { exceptions, consoleErrors, networkLogErrors },
      validationReport: report,
      budgetEnvelope: MELBOURNE_ENVELOPE,
      observation,
      mechanical,
      keys,
    };
    writeFileSync(join(out, `${options.label}-run.json`), `${JSON.stringify(run, null, 2)}\n`);
    writeFileSync(join(out, `${options.label}-trace.json`), `${JSON.stringify({
      profile: 'exulanica.visual-gate-trace/v1',
      frames: poses.map((p) => [
        Math.round(p.x * 1000), Math.round(p.y * 1000), Math.round(p.z * 1000),
        Math.round(p.yaw * 1e6), Math.round(p.pitch * 1e6), Math.round(p.speed * 1000),
      ]),
      columns: ['xMm', 'yMm', 'zMm', 'yawMicroradians', 'pitchMicroradians', 'speedMmPerSecond'],
    })}\n`);
    for (const text of JSON.stringify(run).match(/\/Users\/|Bearer |api-token/g) ?? []) {
      throw new Halt(`the run record would carry ${text}`);
    }
    console.log(JSON.stringify({ label: options.label, keys, route: run.route.headingMillidegrees, captures: captures.map((c) => c.file) }, null, 2));
  } finally {
    session.socket.close();
    const exited = new Promise((resolveExit) => chrome.once('exit', resolveExit));
    chrome.kill();
    await Promise.race([exited, sleep(5000)]);
    // Chrome can still be flushing its profile; a failed removal must never hide the run's result.
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    } catch (error) {
      console.error(`the scratch browser profile was not removed: ${error.message}`);
    }
    if (process.env.VISUAL_GATE_CHROME_LOG === '1') process.stderr.write(log());
  }
}

// Run only when this file is the program. Imported, it is the pure readers above: the stated walk
// and the target table can then be exercised without a browser, and a check nobody can exercise is
// a check nobody has seen refuse anything.
const invokedDirectly = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;

if (invokedDirectly) main().catch((error) => {
  const out = process.argv.includes('--out') ? resolve(argument('out')) : null;
  if (error instanceof Halt) {
    if (out !== null) {
      mkdirSync(out, { recursive: true });
      const halted = { halted: true, reason: error.message, label: options.label, ...observed };
      writeFileSync(join(out, `${options.label}-halt.json`), `${JSON.stringify(halted, null, 2)}\n`);
    }
    console.error(`HALT: ${error.message}`);
    process.exit(3);
  }
  console.error(error);
  process.exit(1);
});
