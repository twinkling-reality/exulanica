// The film's take: one headless Chrome page, recorded the whole time by its own screencast (no
// screen-recording permission), driven through the app the way a person uses it, with a mark for each
// moment so a cut list (scripts/demo/cut_film.py) names stretches by what happened, not by guessed seconds.
//
//   node scripts/demo/film_take.mjs <take document> --out <new folder> [--url http://localhost:19532/]
//        [--port 19533] [--hold <file>] [--hold-minutes 30]
//
// The take document (profile exulanica.film-take/v1) is data; this script names no world, being or model:
//   {"profile": "exulanica.film-take/v1", "title": <the world's name>, "sentence": <said to the Companion>,
//    "minds": [{"being": <as Who decides lists it>, "model": <as Who decides names it>}, ...],
//    "speed": <the clock's speed while it plays>, "alive_seconds": <how long it plays>,
//    "step_back_ms": <how long the viewer walks back after the things appear>,
//    "card": {"being": <whose card opens>, "look": <a look to show>, "look_back": <the look to return to>,
//             "swap_mind": <a model to give it, or null>}}
//
// Steps, each marked in marks.json (seconds from the recording's first frame): world-open, named,
// asked, question, plan-shown, placed, reopened, people-in, framed, minds-chosen, playing, alive-end, then,
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
import { spawnSync } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { open } from '../rehearsal/cdp.mjs';

const TAKE_PROFILE = 'exulanica.film-take/v1';
const [document, ...rest] = process.argv.slice(2);
if (!document || document.startsWith('--')) throw new Error('name the take document first');
const args = Object.fromEntries(rest.reduce((pairs, value, index, all) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), all[index + 1]]);
  return pairs;
}, []));
const take = JSON.parse(readFileSync(document, 'utf8'));
if (take.profile !== TAKE_PROFILE) throw new Error(`${document} is not an ${TAKE_PROFILE} document`);
for (const key of ['title', 'sentence', 'minds', 'speed', 'alive_seconds', 'step_back_ms', 'card']) {
  if (take[key] === undefined) throw new Error(`the take document states no ${key}`);
}
const out = args.out;
if (!out) throw new Error('name a new folder with --out');
if (existsSync(out)) throw new Error(`${out} exists; name a new folder`);
const url = args.url ?? 'http://localhost:19532/';
const port = Number(args.port ?? 19533);
const title = take.title;
const sentence = take.sentence;
const minds = take.minds.map((mind) => [mind.being, mind.model]);
const speed = String(take.speed);
const aliveSeconds = Number(take.alive_seconds);
const stepBackMs = Number(take.step_back_ms);
const hold = args.hold ?? null;
const holdMinutes = Number(args['hold-minutes'] ?? 30);
const being = take.card.being;
const look = take.card.look;
const lookBack = take.card.look_back;
const swapMind = take.card.swap_mind ?? null;
const [width, height] = [1920, 1080];

mkdirSync(join(out, 'frames'), { recursive: true });
mkdirSync(join(out, 'pictures'), { recursive: true });
const say = (line) => console.log(`${new Date().toTimeString().slice(0, 8)} ${line}`);
const page = await open({ port, profile: join(out, 'chrome-profile'), appOrigin: new URL(url).origin, flags: [] });
const frames = [];
const marks = [];
let first = null;
let lastStamp = null;
const mark = async (name, detail = null) => {
  const t = lastStamp === null || first === null ? 0 : lastStamp - first;
  marks.push({ mark: name, t: Number(t.toFixed(3)), at: new Date().toISOString(), ...(detail ? { detail } : {}) });
  say(`mark ${name}${detail ? ` (${detail})` : ''}`);
  await page.screenshot(join(out, 'pictures'), `${String(marks.length).padStart(2, '0')}-${name.replace(/[^a-z0-9-]+/gi, '-')}`).catch(() => null);
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
const planClose = `[...document.querySelectorAll('button')].filter(${visible}).find(b => (b.innerText || '').trim() === 'Close' && (() => { for (let e = b.parentElement; e && e !== document.body; e = e.parentElement) if ((e.innerText || '').includes('Check this plan')) return true; return false; })())`;
const titleInput = `[...document.querySelectorAll('input')].find(i => i.getAttribute('aria-label') === 'World title')`;
const step = async (name, run) => {
  try { await run(); } catch (error) {
    await mark(`failed: ${name}`, String(error.message).slice(0, 300));
    throw error;
  }
};

// A person's request typed to the Companion: confirmed when it plans steps, kept as said otherwise.
async function ask(words) {
  // A plan still open from an earlier request would be read as this one's answer.
  if (await page.evaluate(`!!(${planClose})`)) await page.click(planClose, 'Close the earlier plan');
  if (!(await page.evaluate(`!!document.querySelector('input[placeholder="Ask about your sources"]') || !!document.querySelector('input[placeholder="Your reply"]')`))) {
    await page.click(buttonStarting('Companion'), 'the Companion');
  }
  const input = `(document.querySelector('input[placeholder="Ask about your sources"]') || document.querySelector('input[placeholder="Your reply"]'))`;
  await page.waitFor(`!!(${input})`, 15_000, 'the Companion input');
  await page.click(input, 'the Companion input');
  await page.typeInto(input, words);
  await sleep(600);
  await page.key('Enter', 'Enter', { text: '\r' });
  // The Companion says it is working, then shows a plan to confirm or an answer ending in its
  // provenance line ("... read that in ..."): a being's line on screen is never taken for the answer.
  const working = shownWords('Looking through your library.');
  await page.waitFor(`${working} || !!(${button('Confirm')})`, 10_000, 'the Companion working').catch(() => null);
  await page.waitFor(`!${working} && (!!(${button('Confirm')}) || ${shownWords('read that in')} || ${shownWords('No model was asked')} || ${shownWords('A model was asked')})`, 60_000, 'the plan or an answer');
  if (await page.evaluate(`!!(${button('Confirm')})`)) {
    await mark('asked-plan', words);
    await sleep(2_000);
    await page.click(button('Confirm'), 'Confirm the request');
    await page.waitFor(`${shownWords('Every step happened')} || ${shownWords('Partly done')} || ${shownWords('Not done')}`, 180_000, 'the request carried out');
    await mark('asked-done', await page.evaluate(`${shownWords('Every step happened')} ? 'every step happened' : ${shownWords('Partly done')} ? 'partly done' : 'not done'`));
  } else {
    await mark('asked-refused', words);
  }
  await sleep(1_500);
  if (await page.evaluate(`!!(${planClose})`)) await page.click(planClose, 'Close the plan');
  await page.key('Escape', 'Escape');
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
    await page.waitFor(`!!(${titleInput}) || !!(${buttonStarting('Open')})`, 60_000, 'the world list or an open world');
    if (!(await page.evaluate(`!!(${titleInput}) && (${titleInput}).offsetParent !== null`))) await page.click(buttonStarting('Open'), 'Open');
    await page.waitFor(`!!(${titleInput}) && (${titleInput}).offsetParent !== null`, 90_000, 'the open world');
    await sleep(4_000);
    await mark('world-open');
  });
  await step('named', async () => {
    await page.typeInto(titleInput, title);
    await page.click(button('Save'), 'Save the title');
    await page.waitFor(`${anyWords('Saved')} && !(${button('Save')})`, 15_000, 'the title saved');
    await mark('named');
  });
  await step('asked', async () => {
    await page.click(buttonStarting('Companion'), 'the Companion');
    const input = `document.querySelector('input[placeholder="Ask about your sources"]')`;
    await page.waitFor(`!!(${input})`, 15_000, 'the Companion input');
    await page.click(input, 'the Companion input');
    await page.typeInto(input, sentence);
    await sleep(800);
    await page.key('Enter', 'Enter', { text: '\r' });
    await mark('asked');
  });
  await step('question', async () => {
    await page.waitFor(`!!(${button('Invented for this world')})`, 120_000, 'the origin question');
    await mark('question');
    await sleep(1_500);
    await page.click(button('Invented for this world'), 'Invented for this world');
  });
  await step('plan-shown', async () => {
    await page.waitFor(`!!(${button('Confirm')})`, 60_000, 'Check this plan');
    await mark('plan-shown');
    await sleep(3_500);
    await page.click(button('Confirm'), 'Confirm');
  });
  await step('placed', async () => {
    await page.waitFor(`${anyWords('Every step happened')} || ${anyWords('Partly done')}`, 120_000, 'the plan carried out');
    if (await page.evaluate(anyWords('Partly done'))) throw new Error('the plan was partly done');
    await mark('placed');
    await sleep(2_500);
    await page.click(button('Close'), 'Close the plan');
    await page.key('Escape', 'Escape');
  });
  await step('reopened', async () => {
    // The page reads which society a world takes when it opens the world; one opened before anything
    // was placed asks for the purposeful society, so it is opened again now that things stand in it.
    await page.navigate(url);
    await page.waitFor(`!!(${titleInput}) || !!(${buttonStarting('Open')})`, 60_000, 'the world list or an open world');
    if (!(await page.evaluate(`!!(${titleInput}) && (${titleInput}).offsetParent !== null`))) await page.click(buttonStarting('Open'), 'Open');
    await page.waitFor(`!!(${titleInput}) && (${titleInput}).offsetParent !== null`, 90_000, 'the open world');
    await sleep(4_000);
    await mark('reopened');
  });
  await step('people-in', async () => {
    await page.click(buttonStarting('People'), 'People');
    const bring = `document.querySelector('button[data-action="people.bring-in"]')`;
    await page.waitFor(`!!(${bring})`, 15_000, 'Bring people in');
    await page.click(bring, 'Bring people in');
    await page.waitFor(`${anyWords('Minute 0')} || ${anyWords('Minute 1')} || ${anyWords('were not brought in')}`, 60_000, 'a society to live in');
    if (await page.evaluate(anyWords('were not brought in'))) throw new Error('the page was refused a society');
    await mark('people-in');
    await page.click(button('Close'), 'Close people').catch(() => null);
  });
  await step('framed', async () => {
    // Keys move the viewer only while the world's canvas has focus and no panel holds the keyboard:
    // a click on open sky gives it focus, then the viewer steps back from what stands just ahead.
    await page.key('Escape', 'Escape');
    await page.clickAt(width / 2, Math.round(height * 0.18));
    await sleep(400);
    await page.key('KeyS', 's', { holdMs: stepBackMs });
    await sleep(1_000);
    await mark('framed', await page.evaluate("document.activeElement ? document.activeElement.tagName : 'none'"));
  });
  await step('minds-chosen', async () => {
    for (const [person, model] of minds) {
      // The rail button toggles the panel: press it only while the model list is not showing.
      if (!(await page.evaluate(`!!(${labelStarting(model)})`))) await page.click(buttonStarting('Who decides'), 'Who decides');
      await page.click(labelStarting(model), model);
      await sleep(600);
      // The people list shows at once for a model already chosen once; otherwise this button opens it.
      if (!(await page.evaluate(`!!(${labelStarting(person)})`))) {
        await page.click(button('Choose people to decide for'), 'Choose people to decide for');
      }
      await page.click(labelStarting(person), person);
      await page.click(buttonStarting(`Let ${model} decide`), `Let ${model} decide`);
      await page.waitFor(`${anyWords(`${model}, which you chose`)}`, 30_000, `${person} decided by ${model}`);
    }
    await mark('minds-chosen', minds.map(([p, m]) => `${p}: ${m}`).join('; '));
    await page.click(button('Close'), 'Close who decides').catch(() => null);
  });
  await step('playing', async () => {
    const select = `[...document.querySelectorAll('select')].find(s => [...s.options].some(o => /speed/.test(o.textContent)))`;
    await page.waitFor(`!!(${select})`, 15_000, 'the speed choice');
    // The speed choice's options are "1× speed" and so on, each valued by its number.
    await page.setValue(select, speed);
    const play = `[...document.querySelectorAll('[role=toolbar]')].find(t => t.getAttribute('aria-label') === 'World clock')?.querySelector('button[aria-label="Play"]')`;
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
        const words = readFileSync(sayFile, 'utf8').trim();
        rmSync(sayFile, { force: true });
        if (words) {
          await ask(words).catch(async (error) => {
            await mark('asked-failed', `${words}: ${String(error.message).slice(0, 200)}`);
            if (await page.evaluate(`!!(${planClose})`).catch(() => false)) await page.click(planClose, 'Close the plan').catch(() => null);
          });
        }
      }
      await sleep(2_000);
    }
    await mark('hold-end', existsSync(hold) ? 'the file exists' : 'the limit');
  }
  await step('card', async () => {
    // A being may have walked out of view: choose it in People's picker, else click its label.
    const pill = buttonStarting(`${being.toLowerCase()}: run by`);
    if (!(await page.evaluate(`!!(${pill})`))) {
      await page.click(buttonStarting('People'), 'People');
      const picker = `[...document.querySelectorAll('select')].find(s => /^Inspect/.test(s.getAttribute('aria-label') || ''))`;
      await page.waitFor(`!!(${picker}) && [...(${picker}).options].some(o => o.textContent.trim().startsWith(${JSON.stringify(being)}))`, 15_000, `${being} in People's picker`);
      const value = await page.evaluate(`[...(${picker}).options].find(o => o.textContent.trim().startsWith(${JSON.stringify(being)})).value`);
      await page.setValue(picker, value);
    } else {
      await page.click(pill, `${being}'s label`);
    }
    await page.waitFor(`${anyWords('LOOKS LIKE')} || ${anyWords('Looks like')}`, 15_000, `${being}'s card`);
    await mark('card');
    await sleep(3_500);
  });
  const lookChange = `(() => { const section = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && /^looks like$/i.test((e.textContent || '').trim()) && e.offsetParent !== null); let box = section; for (let i = 0; i < 4 && box; i += 1) { const b = [...box.parentElement.querySelectorAll('button')].find(x => x.innerText.trim() === 'Change'); if (b) return b; box = box.parentElement; } return null; })()`;
  await step('look-swapped', async () => {
    await page.click(lookChange, 'Change beside Looks like');
    await page.click(`[...document.querySelectorAll('button, [role=option], li, div')].filter(${visible}).find(e => e.children.length <= 3 && (e.innerText || '').trim().startsWith(${JSON.stringify(look)}))`, look);
    await page.waitFor(`${anyWords('Only its look changed')}`, 20_000, 'the look changed');
    await mark('look-swapped', look);
    await sleep(2_000);
  });
  await step('how-we-know', async () => {
    await page.click(`[...document.querySelectorAll('summary, button')].filter(${visible}).find(e => (e.innerText || '').trim() === 'How we know')`, 'How we know');
    await sleep(500);
    await mark('how-we-know');
    await sleep(4_000);
  });
  await step('look-back', async () => {
    await page.click(lookChange, 'Change beside Looks like');
    await page.click(`[...document.querySelectorAll('button, [role=option], li, div')].filter(${visible}).find(e => e.children.length <= 3 && (e.innerText || '').trim().startsWith(${JSON.stringify(lookBack)}))`, lookBack);
    await sleep(2_000);
    await mark('look-back', lookBack);
  });
  if (swapMind) {
    await step('mind-swapped', async () => {
      const mindChange = lookChange.replace('looks like', 'mind');
      await page.click(mindChange, 'Change beside Mind');
      // The minds are offered as choices like the looks: the one whose words begin with the model's name.
      await page.click(`[...document.querySelectorAll('button, [role=option], li, div')].filter(${visible}).find(e => e.children.length <= 4 && (e.innerText || '').trim().startsWith(${JSON.stringify(swapMind)}))`, swapMind);
      await page.waitFor(`${anyWords('A new mind takes over')} || ${anyWords('which you chose')}`, 20_000, `${being} given ${swapMind}`);
      await mark('mind-swapped', swapMind);
      await sleep(20_000);
    });
  }
  await mark('end');
} catch (error) {
  failed = String(error.message);
  say(`the take stopped: ${failed}`);
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
      lines.push(`file 'frames/${frame.file}'`, `duration ${(next ? next.t - frame.t : 1 / 30).toFixed(4)}`);
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
  rmSync(join(out, 'chrome-profile'), { recursive: true, force: true });
  await page.close();
}
process.exit(failed ? 1 : 0);
