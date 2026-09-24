// What the rehearsal needs to know about the application's own surfaces, in one place: how a page
// load passes the credential gate, when the world is ready, and how a person reaches the panels.
// Selectors are the product's own classes and accessible names; a label a person reads is matched
// by its text only where the product offers nothing else.

import { setTimeout as sleep } from 'node:timers/promises';

// How long a page load may take to reach the gate or a mounted world. The application fetches its
// graph, saved world, style catalog and geometry before it mounts; this is an allowance for a busy
// machine, not a measurement.
const MOUNT_TIMEOUT_MS = 90_000;
// A write the page confirms: the world's own check and the write together.
const WRITE_TIMEOUT_MS = 30_000;

/** A visible button whose trimmed text is exactly `text`, inside `scope` (an expression). */
export const BUTTON = (text, scope = 'document') =>
  `[...${scope}.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(text)} && b.checkVisibility())`;
/** A visible button whose text starts with `text`, for labels that carry a count or a key. */
export const BUTTON_STARTING = (text, scope = 'document') =>
  `[...${scope}.querySelectorAll('button')].find(b => b.textContent.trim().startsWith(${JSON.stringify(text)}) && b.checkVisibility())`;
export const TITLE_FIELD = `document.querySelector('input[aria-label="World title"]')`;
export const OBJECT_PANEL = `document.querySelector('aside.object-placement')`;
export const OPEN_CONFIRM = `document.querySelector('aside.confirm:not([hidden])')`;
export const WORLD_MENU_BUTTON = `document.querySelector('button.world-open-menu')`;
export const menuEntry = (command) => `document.querySelector('section.world-menu button.world-menu-entry[data-command="${command}"]')`;

/** The world is mounted: the booting mark is gone and the title field is on the page. */
export const WORLD_READY = `(() => { const shell = document.querySelector('#shell');
  return !!shell && !shell.hasAttribute('data-booting') && !document.querySelector('#shell .startup-thinking')
    && !!document.querySelector('input[aria-label="World title"]'); })()`;
const GATE_OR_WORLD = `document.querySelector('form.credential-gate') ? 'gate'
  : (${WORLD_READY} ? 'world' : (document.querySelector('#shell')?.getAttribute('data-world-state') || null))`;

/**
 * Load the application and pass its credential gate with the run's token, the way an operator
 * does: the production build keeps no token, so every page load asks again. Returns what the
 * first surface was.
 */
export async function enter(ctx, load) {
  const { page } = ctx;
  // A reload leaves the old document answering for a moment, and the old document was a ready
  // world; waiting for a new time origin makes every read below read the new page.
  const before = await page.evaluate('performance.timeOrigin').catch(() => null);
  await load();
  await page.waitFor(`performance.timeOrigin !== ${JSON.stringify(before)}`, MOUNT_TIMEOUT_MS, 'the new page to load');
  const first = await page.waitFor(GATE_OR_WORLD, MOUNT_TIMEOUT_MS, 'the credential gate or the world');
  if (first === 'gate') {
    await page.typeInto(`document.querySelector('input[aria-label="Access token"]')`, ctx.token);
    await page.click(`document.querySelector('button[aria-label="Enter Exulanica"]')`, 'Enter Exulanica');
  } else if (first !== 'world') {
    throw new Error(`the application opened on its "${first}" surface instead of a world`);
  }
  await waitForWorld(page);
  return first;
}

export async function waitForWorld(page) {
  const state = await page.waitFor(`${WORLD_READY} ? 'ready' : (document.querySelector('#shell')?.getAttribute('data-world-state') === 'error' ? 'error' : null)`,
    MOUNT_TIMEOUT_MS, 'the world to mount');
  if (state === 'error') {
    const said = await page.evaluate(`document.querySelector('#shell')?.innerText.slice(0, 300) ?? ''`);
    throw new Error(`the world did not load: ${said}`);
  }
  // Two frames after the mark clears, so the renderer has drawn what the state says.
  await sleep(1200);
}

export const open = (ctx) => enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url));
export const reload = (ctx) => enter(ctx, () => ctx.page.reload());

/** The person's one saved world and the version it opens at, read with the run's token. */
export async function savedWorld(ctx) {
  const listed = await ctx.api('GET', '/world-entries');
  if (listed.status !== 200 || !Array.isArray(listed.body)) {
    throw new Error(`GET /world-entries answered ${listed.status}`);
  }
  const entries = listed.body;
  const entry = entries.length === 1 ? entries[0] : null;
  const version = entry === null ? null : (await ctx.api('GET',
    `/world/versions/${entry.authored_version_id}?world_id=${encodeURIComponent(entry.world_id)}`)).body;
  return { entries, entry, version };
}

export const liveObjects = (version) => (version?.objects ?? []).filter((o) => !o.removed);

/** Give the world canvas the keyboard with a trusted click on a point where the canvas is on top. */
export async function focusCanvas(page) {
  const point = await page.evaluate(`(() => {
    const atlas = document.getElementById('atlas');
    const candidates = [[0.5, 0.85], [0.25, 0.85], [0.75, 0.85], [0.5, 0.65], [0.15, 0.5]];
    for (const [fx, fy] of candidates) {
      const x = Math.round(innerWidth * fx), y = Math.round(innerHeight * fy);
      if (document.elementFromPoint(x, y) === atlas) return { x, y };
    }
    return null; })()`);
  if (point !== null) await page.clickAt(point.x, point.y);
  await sleep(300);
  return { point, focused: await page.evaluate(`document.activeElement?.id === 'atlas'`) };
}

/** Open the World menu and choose one of its entries by the product's command name. */
export async function chooseMenu(page, command) {
  await page.click(WORLD_MENU_BUTTON, 'the World menu');
  await page.waitFor(`${menuEntry(command)}?.checkVisibility() ?? false`, 10_000, `the ${command} entry of the World menu`);
  await page.click(menuEntry(command), `the World menu's ${command} entry`);
}

/** Wait for the confirmation the page shows before a write, and return its text. */
export async function confirmation(page, what) {
  await page.waitFor(`${OPEN_CONFIRM}?.checkVisibility() ?? false`, WRITE_TIMEOUT_MS, `the confirmation before ${what}`);
  return page.evaluate(`${OPEN_CONFIRM}.innerText`);
}

/** Press Confirm in the open confirmation once it is enabled, and wait for it to close. */
export async function confirm(page, what) {
  const button = `${OPEN_CONFIRM}?.querySelector('.confirm-actions button.primary')`;
  await page.waitFor(`!!(${button}) && !(${button}).disabled`, WRITE_TIMEOUT_MS, `Confirm to be offered for ${what}`);
  await page.click(button, `Confirm (${what})`);
  await page.waitFor(`!(${OPEN_CONFIRM}) || !${OPEN_CONFIRM}.checkVisibility()`, WRITE_TIMEOUT_MS, `the confirmation for ${what} to close`);
}

export async function openObjects(page) {
  if (!await page.evaluate(`${OBJECT_PANEL}?.checkVisibility() ?? false`)) {
    await page.click(`document.querySelector('aside.world-identity button.world-add-object')`, 'Add object');
  }
  await page.waitFor(`${OBJECT_PANEL}?.checkVisibility() ?? false`, 10_000, 'the objects panel');
}

/** The rows of the objects panel as a person reads them: title and motion words. */
export const objectRows = (page) => page.evaluate(`[...document.querySelectorAll('aside.object-placement li.object-placement-item')]
  .map(li => ({ title: li.querySelector('.object-placement-choose strong')?.textContent.trim() ?? null,
    motion: li.querySelector('.object-placement-motion')?.textContent.trim() ?? null,
    selected: li.dataset.selected ?? null }))`);

/** The status line of the objects panel. */
export const objectStatus = (page) => page.evaluate(`document.querySelector('aside.object-placement p.object-placement-status')?.textContent.trim() ?? null`);

/** The first placeholder a saved-name resolver should have replaced, or null. */
export const PLACEHOLDER = /\[(?:person|voice|place|object|conversation|event) [A-Z]+\]/i;
