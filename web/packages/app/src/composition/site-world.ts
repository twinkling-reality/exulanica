/**
 * A saved world made from a world kind, drawn from its site's served drawing.
 *
 * The server declares on the world's saved entry (`generatedSite`) the kind it was made from, the
 * one region its people live in and where a person arrives. The drawing itself is read through the
 * world's own version (`GET /world/versions/{version}/site`), which serves it only to the world
 * whose snapshot names its receipt, and names it by the SHA-256 of its canonical JSON: the page
 * holds the drawing to that digest before anything draws it. Nothing is baked: the server makes the
 * drawing in its kind worker, kept once made, and while the worker is busy the route answers 503
 * `kind_work_overran` or `kind_work_busy` with a `Retry-After`, so the page says the world is still
 * being drawn and asks again a few times (`DRAWING_ASKS`). A drawing that cannot be read or does
 * not match its digest is not drawn, and the page says so.
 *
 * A site world's region is the site's own frame: its origin the site's south-west corner, east its
 * x and south its negative y. The drawing is placed at that origin under the environment root, so
 * the world's people hang from a root at the same origin (`hostGeneratedSociety`).
 */

import type { GeneratedSiteMount } from '@exulanica/atlas-react/generated-site';
import type { Credentials } from '../config.js';
import { say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import type { SavedWorldEntry } from '../world-entry-api.js';
import { GENERATED_WORLD_WAITING_ATTRIBUTE } from './generated-world-ready.js';
import type { AppEnvironment } from './session-state.js';

/** How many times the page asks for a drawing the server's kind worker has not finished. */
export const DRAWING_ASKS = 6;
/** The longest the page waits between two asks, whatever the route's `Retry-After` says. */
const LONGEST_WAIT_MS = 10_000;
/** The refusals that mean the drawing is still being made, so asking again later reads it. */
const STILL_MAKING: ReadonlySet<string> = new Set(['kind_work_overran', 'kind_work_busy']);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => { setTimeout(resolve, ms); });
}

/** Whether a 503 says the drawing is still being made; reads its problem body. */
async function stillMaking(response: Response): Promise<boolean> {
  if (response.status !== 503) return false;
  try {
    const problem: unknown = await response.json();
    const code = typeof problem === 'object' && problem !== null ? (problem as { code?: unknown }).code : null;
    return typeof code === 'string' && STILL_MAKING.has(code);
  } catch {
    return false;
  }
}

function waitMs(response: Response): number {
  const stated = Number(response.headers.get('Retry-After') ?? '');
  const seconds = Number.isFinite(stated) && stated > 0 ? stated : 2;
  return Math.min(LONGEST_WAIT_MS, seconds * 1_000);
}

/**
 * Read a site world's drawing and hold it to the digest its route names, asking again while the
 * server says it is still being made (`waiting` is told before each wait).
 */
export async function loadSiteWorld(
  access: Credentials,
  entry: SavedWorldEntry,
  waiting: () => void = () => {},
  wait: (ms: number) => Promise<void> = sleep,
): Promise<GeneratedSiteMount | null> {
  if (entry.generatedSite == null) return null;
  const query = new URLSearchParams({ world_id: entry.worldId });
  const url = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`
    + `/site?${query.toString()}`;
  let response: Response;
  for (let ask = 1; ; ask += 1) {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${access.token}`, Accept: 'application/json' },
      credentials: 'same-origin',
    });
    if (ask >= DRAWING_ASKS || !(await stillMaking(response))) break;
    waiting();
    await wait(waitMs(response));
  }
  if (!response.ok) throw new Error(`This world's drawing could not be read: HTTP ${response.status}.`);
  const text = await response.text();
  const [{ parseSiteDrawing, siteMount }, { canonicalJson, sha256Hex }] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('@exulanica/atlas-react/playcanvas'),
  ]);
  const body: unknown = JSON.parse(text);
  const stated = response.headers.get('ETag')?.replaceAll('"', '') ?? null;
  const actual = sha256Hex(new TextEncoder().encode(canonicalJson(body)));
  if (stated === null || stated !== actual) {
    throw new Error("This world's drawing arrived as a document that is not the one its route named.");
  }
  const drawing = parseSiteDrawing(body);
  if (drawing.worldId !== entry.worldId) throw new Error("This world's drawing names another world.");
  return siteMount(drawing, { servedBytes: new TextEncoder().encode(text).byteLength });
}

/** The site to mount for a saved world made from a world kind, or null, with words, when it is not drawn. */
export async function openSiteWorld(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
): Promise<GeneratedSiteMount | null> {
  env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
  const waiting = (): void => {
    if (env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`) != null) return;
    env.shell.append(el('p', {
      class: 'reconstruction-loading', role: 'status', text: say('world.site.making'),
      [GENERATED_WORLD_WAITING_ATTRIBUTE]: 'waiting',
    }));
  };
  try {
    const mount = await loadSiteWorld(access, entry, waiting);
    env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
    return mount;
  } catch (error) {
    env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
    console.warn(error);
    env.shell.append(el('p', {
      class: 'reconstruction-loading', role: 'status', text: say('world.site.failed'),
      [GENERATED_WORLD_WAITING_ATTRIBUTE]: 'failed',
    }));
    return null;
  }
}
