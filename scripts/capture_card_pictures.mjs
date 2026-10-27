/**
 * The browser half of the capture of Create's starter card pictures; scripts/capture_card_pictures.py
 * runs it and writes the record. No package beyond Node's own, on scripts/rehearsal/cdp.mjs.
 *
 *   node scripts/capture_card_pictures.mjs --page <origin> --port <port> --profile <dir> --out <dir> <card>...
 *
 * For each card key (`recipe:small_town`, `kind:town`), in one headless Chrome on the running page:
 * opens Create a world (a fresh install opens on it), presses the card through the page's own route,
 * waits for the world view to open and for the first view the page keeps of the new world (the frame
 * `keepFirstViewPicture` takes once the world is drawn, in localStorage under the page's own key),
 * then scales that frame to the card's size as a JPEG and writes it to `--out` as `<card>.jpg`, the
 * colon a hyphen. Prints one JSON document: each card with the entry it made and its file.
 * Nothing is substituted: a card the page does not offer, a world that does not open, or a first
 * view never kept stops the run, naming the card.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { open } from './rehearsal/cdp.mjs';

/** The key the page keeps a world's first view under (web/packages/app/src/composition/world-pictures.ts). */
const KEPT_PREFIX = 'exulanica.world-picture.v1.';
/** The card tile's picture: 16:9, over three times the largest card Create's strip draws (200 wide); blurred, it also fills the page behind. */
const SIZE = Object.freeze({ width: 640, height: 360 });
const QUALITY = 0.82;
/** How long a card's world may take to open, and its first view to be kept (measured 31 to 72 s). */
const OPEN_MS = 120_000;
const KEPT_MS = 300_000;
/** A world view needs the GPU: SwiftShader draws nothing the page would keep. */
const GPU_FLAGS = ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist'];

const { values: options, positionals: cards } = parseArgs({
  allowPositionals: true,
  options: { page: { type: 'string' }, port: { type: 'string' }, profile: { type: 'string' }, out: { type: 'string' } },
});
for (const name of ['page', 'port', 'profile', 'out']) {
  if (!options[name]) throw new Error(`--${name} is required`);
}
if (cards.length === 0) throw new Error('name at least one card');

const origin = new URL(options.page).origin;
const page = await open({ port: Number(options.port), profile: options.profile, appOrigin: origin, flags: GPU_FLAGS });
const made = [];
try {
  mkdirSync(options.out, { recursive: true });
  for (const card of cards) {
    const offered = `document.querySelector('.wu-strip-card[data-key=' + ${JSON.stringify(JSON.stringify(card))} + ']')`;
    // The old document answers until the new one replaces it: wait for a new time origin first.
    const before = await page.evaluate('performance.timeOrigin');
    await page.navigate(`${origin}/`);
    await page.waitFor(`performance.timeOrigin !== ${before}`, OPEN_MS, 'the page to load');
    await page.waitFor(`document.querySelector('.your-worlds-create, .wu-strip-card') !== null`, OPEN_MS, 'the front door or Create');
    if (!(await page.evaluate(`document.querySelector('.wu-strip-card') !== null`))) {
      await page.click(`document.querySelector('.your-worlds-create')`, 'Create a world');
    }
    await page.waitFor(`${offered} !== null`, OPEN_MS, `Create to offer ${card}`);
    await page.click(offered, card);
    const entry = await page.waitFor(`new URL(location.href).searchParams.get('entry')`, OPEN_MS, `${card}'s world to open`);
    const key = JSON.stringify(KEPT_PREFIX + entry);
    await page.waitFor(`localStorage.getItem(${key}) !== null`, KEPT_MS, `${card}'s first view to be kept`);
    const scaled = await page.evaluate(`new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = ${SIZE.width}; canvas.height = ${SIZE.height};
        canvas.getContext('2d').drawImage(image, 0, 0, ${SIZE.width}, ${SIZE.height});
        resolve(canvas.toDataURL('image/jpeg', ${QUALITY}).split(',')[1]);
      };
      image.onerror = () => reject(new Error('the kept first view did not load'));
      image.src = localStorage.getItem(${key});
    })`);
    const file = join(options.out, `${card.replace(':', '-')}.jpg`);
    writeFileSync(file, Buffer.from(scaled, 'base64'));
    made.push({ card, entry_id: entry, file });
  }
} finally {
  await page.close();
}
console.log(JSON.stringify({ cards: made }));
