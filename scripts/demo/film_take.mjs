// The film's take: one headless Chrome page, recorded the whole time by its own screencast (no
// screen-recording permission), driven through the app the way a person uses it, with a mark for each
// moment so a cut list (scripts/demo/cut_film.py) names stretches by what happened, not by guessed seconds.
//
//   node scripts/demo/film_take.mjs <take document> --out <new folder> [--url http://localhost:19532/]
//        [--port 19533] [--hold <file>] [--hold-minutes 30] [--page <the app's words and selectors>]
//
// The take document (profile exulanica.film-take/v1) is data; this script names no world, being or model:
//   {"profile": "exulanica.film-take/v1", "title": <the world's name>, "sentence": <said to the Companion>,
//    "minds": [{"being": <as Who decides lists it>, "model": <as Who decides names it>}, ...],
//    "speed": <the clock's speed while it plays>, "alive_seconds": <how long it plays>,
//    "step_back_ms": <how long the viewer walks back after the things appear>,
//    "frame": <optional: keys held in turn instead of the step back, [{"key": "KeyW" | "KeyA" | "KeyS" | "KeyD" |
//              "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "KeyC", "ms": <how long>}, ...]: the viewer
//              walks and turns (C changes between its own eyes and a view from behind it), for example back,
//              off the path people walk through the arrival point, and toward the things>,
//    "card": {"being": <whose card opens>, "look": <a look to show>, "look_back": <the look to return to>,
//             "swap_mind": <a model to give it, or null>}}
// With "world": {"describe": <a town said in the person's own words>} the take opens on Create a world:
// the words are typed into Describe it, an open model drafts the town's values, the person uses them and
// creates the town, and everything after happens in that town instead of the workspace's first world
// (marks create-a-world, described, drafted, values-used, town-building, then world-open once it is drawn).
// Where the page says which look the words asked for, the drafted mark carries that line, and the
// values-used mark the look the town will be drawn in.
// With "world": {"open": <the title of a saved world>} the take opens that world by its card instead (a town
// made and looked at beforehand: a town differs on every making, so where to stand and how to frame it are
// found first); the world keeps its name and the document's "title" must be that title.
// "until" (optional, a mark's name) ends the take once that mark is made, for a take that only shows a
// world being made (one that ends at world-open, named or stood states only its title beside its world).
// "stand" (optional, keys held in turn as in "frame") moves the person before they say the sentence: the
// Companion puts things a few metres ahead of where they stand, facing the way they face, so in a town they
// step onto the footway and look along it first (mark stood).
// "creatures" (optional, [{"words": <a creature in the person's own words>, "stand": <optional keys held
// first, as in "frame">}, ...]) has the person make each in Make a creature before the people are brought
// in, so the society takes each in as one of its beings from its first minute: the words are typed, an open
// model drafts its body, and it comes to stand in front of them (mark creature-made, with the page's own
// sentence). take_run.sh starts the stack with creature drafting on for such a take.
// "card" may state only "being": the card opens and How we know is shown, and no look or mind is changed.
// A take document may also hold "scene", "doors" and "hold": take_run.sh and take_hold.sh read those (the
// stack's doors, what happens outside the page during the hold); this script does not.
//
// Steps, each marked in marks.json (seconds from the recording's first frame): world-open, named,
// (stood,) asked, question, plan-shown, placed, reopened, (creature-made,) people-in, framed, minds-chosen, playing, alive-end, then,
// with --hold, hold-start and hold-end (the recording runs while something outside, such as a game's
// crossing, happens; it ends when the file exists or after --hold-minutes; a request written to
// <hold>.say meanwhile is typed to the Companion and confirmed: asked-plan, asked-done or asked-refused),
// card, look-swapped,
// how-we-know, look-back, mind-swapped, end. A step that fails is marked "failed: <step>" with the reason;
// the recording keeps what happened and the take stops there.
//
// Writes take.mp4 (30 frames a second from the frames' own timestamps), marks.json, stats.json,
// pictures/ (one still per mark) and companion-traffic.json (the Companion's answers as the page received
// them, whose execution blocks carry each call's receipt; never a header). The JPEG frames are deleted
// once the take is made. It reads no token: a launch.py development stack serves the app with its
// credential built in. Chrome's default GL drew about 50 frames a second at 1920x1080 on the Mac this
// was made on; SwiftShader drew under one, so this script asks for no software renderer.

import { mkdirSync, writeFileSync, existsSync, rmSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { open } from '../rehearsal/cdp.mjs';

const TAKE_PROFILE = 'exulanica.film-take/v1';
const PAGE_PROFILE = 'exulanica.film-page/v1';
const [document, ...rest] = process.argv.slice(2);
if (!document || document.startsWith('--')) throw new Error('name the take document first');
const args = Object.fromEntries(rest.reduce((pairs, value, index, all) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), all[index + 1]]);
  return pairs;
}, []));
const take = JSON.parse(readFileSync(document, 'utf8'));
if (take.profile !== TAKE_PROFILE) throw new Error(`${document} is not an ${TAKE_PROFILE} document`);
// Every word and selector of the app this driver depends on is data in one file (film_page.json beside
// this script, or the file --page names): when the interface changes that file is re-pointed, not the steps.
const pageFile = args.page ?? fileURLToPath(new URL('./film_page.json', import.meta.url));
const { profile: pageProfile, words, selectors } = JSON.parse(readFileSync(pageFile, 'utf8'));
if (pageProfile !== PAGE_PROFILE) throw new Error(`${pageFile} is not an ${PAGE_PROFILE} document`);
const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key]);
// A take that ends once its world is open or named states only what it needs up to there.
const short = ['world-open', 'named', 'stood'].includes(take.until);
for (const key of short ? ['title'] : ['title', 'sentence', 'minds', 'speed', 'alive_seconds', 'step_back_ms']) {
  if (take[key] === undefined) throw new Error(`the take document states no ${key}`);
}
const out = args.out;
if (!out) throw new Error('name a new folder with --out');
if (existsSync(out)) throw new Error(`${out} exists; name a new folder`);
const url = args.url ?? 'http://localhost:19532/';
const port = Number(args.port ?? 19533);
const title = take.title;
const sentence = take.sentence;
const minds = (take.minds ?? []).map((mind) => [mind.being, mind.model]);
const speed = String(take.speed);
const aliveSeconds = Number(take.alive_seconds);
const stepBackMs = Number(take.step_back_ms);
const FRAME_KEYS = { KeyW: 'w', KeyA: 'a', KeyS: 's', KeyD: 'd', KeyC: 'c', ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown' };
const frameKeys = take.frame ?? null;
const standKeys = take.stand ?? null;
const describedWorld = take.world?.describe ?? null;
const openedWorld = take.world?.open ?? null;
if (take.world !== undefined && [describedWorld, openedWorld].filter((text) => typeof text === 'string' && text.trim() !== '').length !== 1) {
  throw new Error('world states one of describe (the town in the words a person would type) or open (a saved world\'s title)');
}
if (openedWorld !== null && openedWorld !== take.title) throw new Error('a take that opens a saved world keeps its name: title is that world\'s title');
const until = take.until ?? null;
const creatures = take.creatures ?? [];
if (!Array.isArray(creatures) || creatures.some((one) => typeof one?.['words'] !== 'string' || one['words'].trim() === '')) {
  throw new Error('creatures lists the creatures the person makes, each {"words": <in their own words>}');
}
for (const [name, keys] of [['frame', frameKeys], ['stand', standKeys], ...creatures.map((one) => ['a creature\'s stand', one.stand ?? null])]) {
  if (keys !== null && (!Array.isArray(keys) || keys.some((held) => !(held.key in FRAME_KEYS) || !(Number(held.ms) > 0)))) {
    throw new Error(`${name} lists the keys the viewer moves by (W, A, S, D, C and the arrows), each held some ms`);
  }
}
const hold = args.hold ?? null;
const holdMinutes = Number(args['hold-minutes'] ?? 30);
const being = take.card?.being;
const look = take.card?.look;
const lookBack = take.card?.look_back;
const swapMind = take.card?.swap_mind ?? null;
const [width, height] = [1920, 1080];

mkdirSync(join(out, 'frames'), { recursive: true });
mkdirSync(join(out, 'pictures'), { recursive: true });
const say = (line) => console.log(`${new Date().toTimeString().slice(0, 8)} ${line}`);
const page = await open({ port, profile: join(out, 'chrome-profile'), appOrigin: new URL(url).origin, flags: [] });
const frames = [];
const marks = [];
let first = null;
let lastStamp = null;
// Thrown once the mark the take document's "until" names is made: the take ends there, as asked.
class TakeEnds extends Error {}
const mark = async (name, detail = null) => {
  const t = lastStamp === null || first === null ? 0 : lastStamp - first;
  marks.push({ mark: name, t: Number(t.toFixed(3)), at: new Date().toISOString(), ...(detail ? { detail } : {}) });
  say(`mark ${name}${detail ? ` (${detail})` : ''}`);
  await page.screenshot(join(out, 'pictures'), `${String(marks.length).padStart(2, '0')}-${name.replace(/[^a-z0-9-]+/gi, '-')}`).catch(() => null);
  if (name === until) {
    await sleep(3_000);
    throw new TakeEnds(name);
  }
};
// Element expressions, each the visible element whose words are the ones given.
const visible = 'e => e.offsetParent !== null || e.getClientRects().length > 0';
const button = (text) => `[...document.querySelectorAll('button')].filter(${visible}).find(b => (b.innerText || '').trim() === ${JSON.stringify(text)} || (b.getAttribute('aria-label') || '') === ${JSON.stringify(text)})`;
const buttonStarting = (text) => `[...document.querySelectorAll('button')].filter(${visible}).find(b => (b.innerText || '').trim().startsWith(${JSON.stringify(text)}) || (b.getAttribute('aria-label') || '').startsWith(${JSON.stringify(text)}))`;
const labelStarting = (text) => `[...document.querySelectorAll('label')].filter(${visible}).find(l => (l.innerText || '').trim().startsWith(${JSON.stringify(text)}))`;
const anyWords = (text) => `[...document.querySelectorAll('body *')].some(e => e.children.length === 0 && (e.textContent || '').includes(${JSON.stringify(text)}) && e.getClientRects().length > 0)`;
// Words shown by any visible element, its own words beside an icon included ("Not done" sits beside one).
const shownWords = (text) => `[...document.querySelectorAll('body *')].some(e => e.getClientRects().length > 0 && (e.children.length === 0 ? (e.textContent || '') : [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')).includes(${JSON.stringify(text)}))`;
// The plan panel's own Close, not another panel's or a notice's.
// Any of several wordings the page may show.
const anyOf = (list, shown = anyWords) => `(${list.map((text) => shown(text)).join(' || ')})`;
const css = (selector) => `document.querySelector(${JSON.stringify(selector)})`;
// The plan panel's own Close, not another panel's or a notice's.
const planClose = `[...document.querySelectorAll('button')].filter(${visible}).find(b => (b.innerText || '').trim() === ${JSON.stringify(words.close)} && (() => { for (let e = b.parentElement; e && e !== document.body; e = e.parentElement) if ((e.innerText || '').includes(${JSON.stringify(words.plan_heading)})) return true; return false; })())`;
const titleInput = `[...document.querySelectorAll('input')].find(i => i.getAttribute('aria-label') === ${JSON.stringify(words.world_title)})`;
// The world's canvas takes the keyboard at a click where nothing lies over it.
const focusWorld = async () => {
  const point = await page.evaluate(`(() => { const atlas = ${css(selectors.world_canvas)};
    for (const [fx, fy] of [[0.5, 0.85], [0.25, 0.85], [0.75, 0.85], [0.5, 0.65]]) {
      const x = Math.round(innerWidth * fx), y = Math.round(innerHeight * fy);
      if (document.elementFromPoint(x, y) === atlas) return { x, y };
    }
    return null; })()`);
  if (point !== null) await page.clickAt(point.x, point.y);
  await sleep(400);
};
const step = async (name, run) => {
  try { await run(); } catch (error) {
    if (!(error instanceof TakeEnds)) await mark(`failed: ${name}`, String(error.message).slice(0, 300));
    throw error;
  }
};
// A saved world's card on the list of worlds, by its title.
const worldCard = (name) => `[...document.querySelectorAll(${JSON.stringify(selectors.world_card)})].find(b => (b.innerText || '').includes(${JSON.stringify(name)}))`;
const worldIsOpen = `!!(${titleInput}) && (${titleInput}).offsetParent !== null`;
// From the list of worlds to an open one: the card of the named world where the list shows it, then Open
// where the page offers it. A slow page may open the world before Open is looked for, or draw the list
// late, so each is waited for and neither is required.
async function openFromList(page, name) {
  if (await page.evaluate(worldIsOpen)) return;
  if (name !== null && await page.evaluate(`!!(${worldCard(name)})`)) {
    await page.click(worldCard(name), `the card of ${name}`).catch(() => null);
    await sleep(600);
  }
  const offered = await page.waitFor(`(${worldIsOpen}) ? 'open' : !!(${buttonStarting(words.open_world)}) ? 'offered' : null`, 60_000, 'Open, or the open world');
  if (offered === 'offered') await page.click(buttonStarting(words.open_world), 'Open').catch(() => null);
  await page.waitFor(worldIsOpen, 90_000, 'the open world');
}

// The Companion's field for a person's own words. An empty world's Companion shows it at once; where the
// Companion opens on a question (a town's does) the field is there but hidden until "Other…" is pressed.
const companionField = `([...document.querySelectorAll(${JSON.stringify(selectors.companion_field)})].find(${visible}) ?? null)`;
const companionOther = `([...document.querySelectorAll(${JSON.stringify(selectors.companion_other)})].find(${visible}) ?? null)`;
async function companionInput() {
  if (!(await page.evaluate(`!!${companionField} || !!${companionOther}`))) await page.click(buttonStarting(words.companion), 'the Companion');
  await page.waitFor(`!!${companionField} || !!${companionOther}`, 15_000, 'the Companion');
  if (!(await page.evaluate(`!!${companionField}`))) await page.click(companionOther, 'Other, in your own words');
  await page.waitFor(`!!${companionField}`, 15_000, 'the Companion input');
  await page.click(companionField, 'the Companion input');
  return companionField;
}

// A person's request typed to the Companion: confirmed when it plans steps, kept as said otherwise.
async function ask(request) {
  // A plan still open from an earlier request would be read as this one's answer.
  if (await page.evaluate(`!!(${planClose})`)) await page.click(planClose, 'Close the earlier plan');
  const input = await companionInput();
  await page.typeInto(input, request);
  await sleep(600);
  await page.key('Enter', 'Enter', { text: '\r' });
  // The Companion says it is working, then shows a plan to confirm or an answer ending in its
  // provenance line ("... read that in ..."): a being's line on screen is never taken for the answer.
  const working = shownWords(words.companion_working);
  const confirm = button(words.confirm);
  await page.waitFor(`${working} || !!(${confirm})`, 10_000, 'the Companion working').catch(() => null);
  await page.waitFor(`!${working} && (!!(${confirm}) || ${anyOf(words.companion_answered, shownWords)})`, 60_000, 'the plan or an answer');
  if (await page.evaluate(`!!(${confirm})`)) {
    await mark('asked-plan', request);
    await sleep(2_000);
    await page.click(confirm, 'Confirm the request');
    await page.waitFor(`${shownWords(words.plan_done)} || ${shownWords(words.plan_partly)} || ${shownWords(words.plan_not_done)}`, 180_000, 'the request carried out');
    await mark('asked-done', await page.evaluate(`${shownWords(words.plan_done)} ? 'every step happened' : ${shownWords(words.plan_partly)} ? 'partly done' : 'not done'`));
  } else {
    await mark('asked-refused', request);
    // A question left open (the Companion asking what it needs first) is closed, not left over the world.
    const cancel = button(words.cancel);
    if (await page.evaluate(`!!(${cancel})`)) await page.click(cancel, 'Cancel the question').catch(() => null);
  }
  await sleep(1_500);
  if (await page.evaluate(`!!(${planClose})`)) await page.click(planClose, 'Close the plan');
  await page.key('Escape', 'Escape');
}

// A town of the person's own: Create a world, the town said in their words, an open model's draft of its
// values shown beside what it took from the words, and the town made from them and drawn.
async function makeWorld(town) {
  const description = css(selectors.description);
  const area = `${description}?.querySelector(${JSON.stringify(selectors.description_field)})`;
  const use = `${description}?.querySelector(${JSON.stringify(selectors.description_use)})`;
  const waiting = css(selectors.town_waiting);
  await page.click(buttonStarting(words.create_a_world), 'Create a world');
  await page.waitFor(`!!(${area})`, 30_000, 'Describe it');
  await sleep(1_000);
  await mark('create-a-world');
  await sleep(1_500);
  await page.click(area, 'the description');
  await page.typeInto(area, town);
  await page.evaluate(`(${area}).dispatchEvent(new Event('input', {bubbles: true}))`);
  await sleep(500);
  await mark('described', town);
  await sleep(2_000);
  await page.click(`${description}.querySelector(${JSON.stringify(selectors.description_draft)})`, 'Draft the values');
  const drafted = await page.waitFor(`(${use}) ? 'drafted' : (${description}?.textContent ?? '').includes(${JSON.stringify(words.no_draft)}) ? 'refused' : null`, 120_000, 'the draft');
  if (drafted !== 'drafted') throw new Error(`no draft was made: ${(await page.evaluate(`${description}.innerText`)).slice(-200)}`);
  await sleep(800);
  // The look the words asked for, as the page says it (the open model that chose it and the words), if it does.
  await mark('drafted', await page.evaluate(`(${description}.querySelector(${JSON.stringify(selectors.description_look)})?.innerText ?? '').trim() || null`));
  await sleep(4_000);
  await page.click(use, 'Use these values');
  await sleep(1_500);
  await mark('values-used', await page.evaluate(`(${css(selectors.look_row_title)}?.textContent ?? '').trim() || null`));
  await sleep(1_500);
  await page.click(css(selectors.town_make), 'Create this town');
  await page.waitFor(`!!(${waiting})`, 30_000, 'the town being built').catch(() => null);
  await sleep(2_000);
  await mark('town-building');
  await page.waitFor(`!(${waiting}) && !!(${titleInput}) && (${titleInput}).offsetParent !== null`, 900_000, 'the town drawn');
}

let failed = null;
try {
  await page.connection.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  page.connection.on((method, params) => {
    if (method !== 'Page.screencastFrame') return;
    const stamp = params.metadata.timestamp;
    first ??= stamp;
    lastStamp = stamp;
    const file = `frame-${String(frames.length).padStart(6, '0')}.jpg`;
    writeFileSync(join(out, 'frames', file), Buffer.from(params.data, 'base64'));
    frames.push({ file, t: stamp - first });
    page.connection.send('Page.screencastFrameAck', { sessionId: params.sessionId }).catch(() => {});
  });
  await page.connection.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: width, maxHeight: height, everyNthFrame: 1 });
  await page.navigate(url);

  await step('world-open', async () => {
    await page.waitFor(`!!(${titleInput}) || !!(${buttonStarting(words.open_world)})`, 60_000, 'the world list or an open world');
    if (describedWorld !== null) {
      await makeWorld(describedWorld);
    } else {
      await openFromList(page, openedWorld);
    }
    await sleep(4_000);
    await mark('world-open');
  });
  if (openedWorld === null) {
    await step('named', async () => {
      await page.typeInto(titleInput, title);
      await page.click(button(words.save_title), 'Save the title');
      await page.waitFor(`${anyWords(words.title_saved)} && !(${button(words.save_title)})`, 15_000, 'the title saved');
      await mark('named');
    });
  }
  if (standKeys !== null) {
    await step('stood', async () => {
      await focusWorld();
      for (const held of standKeys) {
        await page.key(held.key, FRAME_KEYS[held.key], { holdMs: Number(held.ms) });
        await sleep(300);
      }
      await sleep(800);
      await mark('stood');
    });
  }
  await step('asked', async () => {
    const input = await companionInput();
    await page.typeInto(input, sentence);
    await sleep(800);
    await page.key('Enter', 'Enter', { text: '\r' });
    await mark('asked');
  });
  await step('question', async () => {
    await page.waitFor(`!!(${button(words.invented)})`, 120_000, 'the origin question');
    await mark('question');
    await sleep(1_500);
    await page.click(button(words.invented), 'Invented for this world');
  });
  await step('plan-shown', async () => {
    await page.waitFor(`!!(${button(words.confirm)})`, 60_000, 'Check this plan');
    await mark('plan-shown');
    await sleep(3_500);
    await page.click(button(words.confirm), 'Confirm');
  });
  await step('placed', async () => {
    await page.waitFor(`${anyWords(words.plan_done)} || ${anyWords(words.plan_partly)}`, 120_000, 'the plan carried out');
    if (await page.evaluate(anyWords(words.plan_partly))) throw new Error('the plan was partly done');
    await mark('placed');
    await sleep(2_500);
    await page.click(button(words.close), 'Close the plan');
    await page.key('Escape', 'Escape');
  });
  await step('reopened', async () => {
    // The page reads which society a world takes when it opens the world; one opened before anything
    // was placed asks for the purposeful society, so it is opened again now that things stand in it.
    await page.navigate(url);
    await page.waitFor(`!!(${titleInput}) || !!(${buttonStarting(words.open_world)})`, 60_000, 'the world list or an open world');
    // The list may hold other worlds: the take's own is the one it named, chosen by its card.
    await openFromList(page, title);
    await sleep(4_000);
    await mark('reopened', await page.evaluate(`(${titleInput})?.value ?? ''`));
  });
  for (const creature of creatures) {
    await step('creature-made', async () => {
      // Make a creature: the person's own words, an open model's draft of its body, and the creature
      // placed in front of them; the page says which in one sentence.
      const field = css(selectors.creature_words);
      if (creature.stand !== undefined) {
        // Where the person stands for this one: it is placed a few metres ahead of them. A click on
        // open sky gives the world the keyboard without picking what stands in front.
        await page.key('Escape', 'Escape');
        await page.clickAt(width / 2, Math.round(height * 0.18));
        await sleep(400);
        for (const held of creature.stand) {
          await page.key(held.key, FRAME_KEYS[held.key], { holdMs: Number(held.ms) });
          await sleep(300);
        }
        await sleep(600);
      }
      await page.click(buttonStarting(words.make_a_creature), 'Make a creature');
      await page.waitFor(`!!(${field}) && (${field}).offsetParent !== null`, 15_000, 'Describe a creature');
      await sleep(1_000);
      await page.click(field, 'the creature\'s description');
      await page.typeInto(field, creature.words);
      await sleep(1_200);
      await page.click(css(selectors.creature_make), 'Make');
      const status = `(${css(selectors.creature_status)}?.textContent ?? '').trim()`;
      const stands = `(${status}).endsWith(${JSON.stringify(words.creature_stands)})`;
      // The sheet says it is imagining, then placing, then that it stands; anything else it ends on is why not.
      const ended = await page.waitFor(`${stands} ? 'made' : (${status}) !== '' && !${anyOf(words.creature_working, (text) => `(${status}).startsWith(${JSON.stringify(text)})`)} ? 'not made' : null`, 180_000, 'the creature made');
      const said = await page.evaluate(status);
      if (ended !== 'made') throw new Error(`the creature was not made: ${said}`);
      await mark('creature-made', said);
      await sleep(2_500);
      await page.click(button(words.back_to_world), 'Back to the world');
      await sleep(1_500);
    });
  }
  await step('people-in', async () => {
    await page.click(buttonStarting(words.people), 'People');
    const bring = css(selectors.bring_people_in);
    await page.waitFor(`!!(${bring})`, 15_000, 'Bring people in');
    await page.click(bring, 'Bring people in');
    await page.waitFor(`${anyOf(words.society_started)} || ${anyWords(words.society_refused)}`, 60_000, 'a society to live in');
    if (await page.evaluate(anyWords(words.society_refused))) throw new Error('the page was refused a society');
    await mark('people-in');
    await page.click(button(words.close), 'Close people').catch(() => null);
  });
  await step('framed', async () => {
    // Keys move the viewer only while the world's canvas has focus and no panel holds the keyboard:
    // a click on open sky gives it focus, then the viewer steps back from what stands just ahead.
    await page.key('Escape', 'Escape');
    await page.clickAt(width / 2, Math.round(height * 0.18));
    await sleep(400);
    if (frameKeys === null) {
      await page.key('KeyS', 's', { holdMs: stepBackMs });
    } else {
      for (const held of frameKeys) {
        await page.key(held.key, FRAME_KEYS[held.key], { holdMs: Number(held.ms) });
        await sleep(300);
      }
    }
    await sleep(1_000);
    await mark('framed', await page.evaluate("document.activeElement ? document.activeElement.tagName : 'none'"));
  });
  await step('minds-chosen', async () => {
    for (const [person, model] of minds) {
      // The rail button toggles the panel: press it only while the model list is not showing.
      if (!(await page.evaluate(`!!(${labelStarting(model)})`))) await page.click(buttonStarting(words.who_decides), 'Who decides');
      await page.click(labelStarting(model), model);
      await sleep(600);
      // The people list shows at once for a model already chosen once; otherwise this button opens it.
      if (!(await page.evaluate(`!!(${labelStarting(person)})`))) {
        await page.click(button(words.choose_people), 'Choose people to decide for');
      }
      await page.click(labelStarting(person), person);
      await page.click(buttonStarting(fill(words.let_decide, { model })), `Let ${model} decide`);
      await page.waitFor(anyWords(fill(words.decided_by, { model })), 30_000, `${person} decided by ${model}`);
    }
    await mark('minds-chosen', minds.map(([p, m]) => `${p}: ${m}`).join('; '));
    await page.click(button(words.close), 'Close who decides').catch(() => null);
  });
  await step('playing', async () => {
    const select = `[...document.querySelectorAll('select')].find(s => [...s.options].some(o => o.textContent.includes(${JSON.stringify(words.speed_option)})))`;
    await page.waitFor(`!!(${select})`, 15_000, 'the speed choice');
    // The speed choice's options are "1× speed" and so on, each valued by its number.
    await page.setValue(select, speed);
    const play = `[...([...document.querySelectorAll('[role=toolbar]')].find(t => t.getAttribute('aria-label') === ${JSON.stringify(words.clock)})?.querySelectorAll('button') ?? [])].find(b => b.getAttribute('aria-label') === ${JSON.stringify(words.play)})`;
    // Choosing the speed sends the control first; Play is offered again once that answer is in.
    await page.waitFor(`!!(${play}) && !(${play}).disabled`, 30_000, 'Play offered');
    await page.click(play, 'Play in the world clock');
    await page.waitFor(`!(${play})`, 15_000, 'the world playing');
    await mark('playing', `${speed}x`);
  });
  await sleep(aliveSeconds * 1000);
  await mark('alive-end');
  if (hold) {
    await mark('hold-start', hold);
    const deadline = Date.now() + holdMinutes * 60_000;
    // While it holds, a request written to <hold>.say is the person's: typed to the Companion in this
    // recorded page, its plan checked and confirmed, and marked with its words and what became of it.
    const sayFile = `${hold}.say`;
    while (!existsSync(hold) && Date.now() < deadline) {
      if (existsSync(sayFile)) {
        const request = readFileSync(sayFile, 'utf8').trim();
        rmSync(sayFile, { force: true });
        if (request) {
          await ask(request).catch(async (error) => {
            await mark('asked-failed', `${request}: ${String(error.message).slice(0, 200)}`);
            if (await page.evaluate(`!!(${planClose})`).catch(() => false)) await page.click(planClose, 'Close the plan').catch(() => null);
          });
        }
      }
      await sleep(2_000);
    }
    await mark('hold-end', existsSync(hold) ? 'the file exists' : 'the limit');
  }
  if (being !== undefined) await step('card', async () => {
    // A being may have walked out of view: choose it in People's picker, else click its label.
    const pill = buttonStarting(fill(words.being_label, { being: being.toLowerCase() }));
    if (!(await page.evaluate(`!!(${pill})`))) {
      await page.click(buttonStarting(words.people), 'People');
      const picker = `[...document.querySelectorAll('select')].find(s => (s.getAttribute('aria-label') || '').startsWith(${JSON.stringify(words.inspect)}))`;
      await page.waitFor(`!!(${picker}) && [...(${picker}).options].some(o => o.textContent.trim().startsWith(${JSON.stringify(being)}))`, 15_000, `${being} in People's picker`);
      const value = await page.evaluate(`[...(${picker}).options].find(o => o.textContent.trim().startsWith(${JSON.stringify(being)})).value`);
      await page.setValue(picker, value);
    } else {
      await page.click(pill, `${being}'s label`);
    }
    await page.waitFor(anyOf(words.card_shown), 15_000, `${being}'s card`);
    await mark('card');
    await sleep(3_500);
  });
  // The Change beside a heading of the card (its look, its mind), found from the heading outward.
  const changeBeside = (heading) => `(() => { const section = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && (e.textContent || '').trim().toLowerCase() === ${JSON.stringify(heading)} && e.offsetParent !== null); let box = section; for (let i = 0; i < 4 && box; i += 1) { const b = [...box.parentElement.querySelectorAll('button')].find(x => x.innerText.trim() === ${JSON.stringify(words.change)}); if (b) return b; box = box.parentElement; } return null; })()`;
  const lookChange = changeBeside(words.looks_heading);
  const choice = (name, children) => `[...document.querySelectorAll(${JSON.stringify(selectors.choice)})].filter(${visible}).find(e => e.children.length <= ${children} && (e.innerText || '').trim().startsWith(${JSON.stringify(name)}))`;
  if (look !== undefined) await step('look-swapped', async () => {
    await page.click(lookChange, 'Change beside Looks like');
    await page.click(choice(look, 3), look);
    await page.waitFor(anyWords(words.look_changed), 20_000, 'the look changed');
    await mark('look-swapped', look);
    await sleep(2_000);
  });
  if (being !== undefined) await step('how-we-know', async () => {
    await page.click(`[...document.querySelectorAll(${JSON.stringify(selectors.disclosure)})].filter(${visible}).find(e => (e.innerText || '').trim() === ${JSON.stringify(words.how_we_know)})`, 'How we know');
    await sleep(500);
    await mark('how-we-know');
    await sleep(4_000);
  });
  if (lookBack !== undefined) await step('look-back', async () => {
    await page.click(lookChange, 'Change beside Looks like');
    await page.click(choice(lookBack, 3), lookBack);
    await sleep(2_000);
    await mark('look-back', lookBack);
  });
  if (swapMind) {
    await step('mind-swapped', async () => {
      await page.click(changeBeside(words.mind_heading), 'Change beside Mind');
      // The minds are offered as choices like the looks: the one whose words begin with the model's name.
      await page.click(choice(swapMind, 4), swapMind);
      // The page says the new mind decides from the being's next choice, or, where the server's model
      // allowance is down to its reserved part, that the choice is recorded and the routine goes on for now.
      const held = anyWords(fill(words.mind_recorded, { model: swapMind }));
      await page.waitFor(`${anyOf(words.mind_changed)} || ${held}`, 20_000, `${being} given ${swapMind}`);
      await mark('mind-swapped', (await page.evaluate(held)) ? `${swapMind}, recorded; its own routine for now` : swapMind);
      await sleep(20_000);
    });
  }
  await mark('end');
} catch (error) {
  if (error instanceof TakeEnds) {
    say(`the take ends at ${error.message}, as its document says`);
  } else {
    failed = String(error.message);
    say(`the take stopped: ${failed}`);
  }
} finally {
  await page.connection.send('Page.stopScreencast').catch(() => null);
  await sleep(500);
  writeFileSync(join(out, 'marks.json'), JSON.stringify(marks, null, 1) + '\n');
  // The Companion's answers as the page received them (their execution blocks carry each call's
  // receipt: model, tokens, cost), so the take's plan cost is read from what was served. No header.
  try {
    const traffic = (await page.traffic(null)).filter((entry) => entry.path.startsWith('/api/selection/'));
    writeFileSync(join(out, 'companion-traffic.json'), JSON.stringify(traffic, null, 1) + '\n');
  } catch (error) { say(`companion traffic not kept: ${error.message}`); }
  if (frames.length > 1) {
    const lines = [];
    frames.forEach((frame, index) => {
      const next = frames[index + 1];
      // Two frames may arrive out of their own order: a frame is never given less than a millisecond.
      lines.push(`file 'frames/${frame.file}'`, `duration ${Math.max(0.001, next ? next.t - frame.t : 1 / 30).toFixed(4)}`);
    });
    lines.push(`file 'frames/${frames.at(-1).file}'`);
    writeFileSync(join(out, 'frames.txt'), lines.join('\n') + '\n');
    const made = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', 'frames.txt',
      '-vf', `fps=30,scale=${width}:${height}:flags=lanczos,format=yuv420p`, '-c:v', 'libx264', '-crf', '18', '-movflags', '+faststart', 'take.mp4'],
      { cwd: out, encoding: 'utf8' });
    const span = frames.at(-1).t;
    const stats = { frames: frames.length, seconds: Number(span.toFixed(3)), frames_per_second: Number(((frames.length - 1) / span).toFixed(2)),
      take: made.status === 0 ? 'take.mp4' : `ffmpeg failed: ${made.stderr.slice(0, 300)}`, stopped: failed };
    writeFileSync(join(out, 'stats.json'), JSON.stringify(stats, null, 1) + '\n');
    say(`take: ${JSON.stringify(stats)}`);
    if (made.status === 0) rmSync(join(out, 'frames'), { recursive: true, force: true });
  }
  await page.close();
  // Chrome may still be writing its profile as it exits: the removal is retried, and a folder left
  // behind is no failure of the take.
  try {
    rmSync(join(out, 'chrome-profile'), { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  } catch (error) {
    say(`the browser's profile folder stays: ${String(error.code ?? error.message)}`);
  }
}
process.exit(failed ? 1 : 0);
