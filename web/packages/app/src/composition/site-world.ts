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
 *
 * A site is drawn in the look the page chooses for any world (`worldLookChoice` in `../world-look.ts`):
 * the address's, else the pack its appearance names, else the host's default. The pack is read and
 * its pieces fetched before the site is mounted; its default light preset lights the site, and
 * `packSiteDresser` dresses each slot by its look role (`docs/style-pack-contract.md`, section 7.1).
 * A pack the page cannot read is not stood in for: the site opens in the tile look in the engine's
 * own colours, and the shell's `data-world-look` attribute states the pack asked for, what chose it
 * and why it was not drawn. While the site is open it can be redrawn in another pack at once
 * (`./world-look-redraw.ts`): its drawing, already read and checked, is mounted again in the new
 * pack's light and dressing on the same host, so the person stays where they stand.
 */

import type { GeneratedSiteMount, SiteDrawing } from '@exulanica/atlas-react/generated-site';
import { accessHeaders, type Credentials } from '../config.js';
import { say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import type { WorldLookChoice } from '../world-look.js';
import type { SavedWorldEntry } from '../world-entry-api.js';
import type { WorldStylePackBinding } from '../world-style-api.js';
import { GENERATED_WORLD_WAITING_ATTRIBUTE } from './generated-world-ready.js';
import type { AppEnvironment } from './session-state.js';
import { WORLD_LOOK_ATTRIBUTE, swappableDrawing, type WorldLookState } from './world-look-redraw.js';

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

/** A site world read and mounted in its look, and how to mount the same drawing in another. */
export interface SiteWorld {
  readonly mount: GeneratedSiteMount;
  readonly look: WorldLookState;
  /** The same drawing in another look: nothing is read or checked again. Throws, changing nothing, when the pack cannot be read. */
  readonly relook: (choice: WorldLookChoice) => Promise<{ readonly mount: GeneratedSiteMount; readonly look: WorldLookState }>;
}

/**
 * Read a site world's drawing and hold it to the digest its route names, asking again while the
 * server says it is still being made (`waiting` is told before each wait), then mount it in the look
 * `search` and the world's appearance (`bound`) choose.
 */
export async function loadSiteWorld(
  access: Credentials,
  entry: SavedWorldEntry,
  waiting: () => void = () => {},
  wait: (ms: number) => Promise<void> = sleep,
  search: string = typeof window === 'undefined' ? '' : window.location.search,
  bound: WorldStylePackBinding | null = null,
): Promise<SiteWorld | null> {
  if (entry.generatedSite == null) return null;
  const query = new URLSearchParams({ world_id: entry.worldId });
  const url = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`
    + `/site?${query.toString()}`;
  let response: Response;
  for (let ask = 1; ; ask += 1) {
    response = await fetch(url, {
      headers: { ...accessHeaders(access), Accept: 'application/json' },
      credentials: 'same-origin',
    });
    if (ask >= DRAWING_ASKS || !(await stillMaking(response))) break;
    waiting();
    await wait(waitMs(response));
  }
  if (!response.ok) throw new Error(`This world's drawing could not be read: HTTP ${response.status}.`);
  const text = await response.text();
  const [{ parseSiteDrawing }, { canonicalJson, sha256Hex }] = await Promise.all([
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
  return siteInLook(access, drawing, new TextEncoder().encode(text).byteLength, search, bound);
}

/**
 * A checked drawing mounted in the look the page chooses: the pack read, its pieces fetched and its
 * dresser given to the mount; a pack that cannot be read leaves the tile look, undressed, and says why.
 */
async function siteInLook(
  access: Credentials,
  drawing: SiteDrawing,
  servedBytes: number,
  search: string,
  bound: WorldStylePackBinding | null,
): Promise<SiteWorld> {
  const [{ siteMount }, worldLook, { SURFACE_MATERIALS: materials }, { ROOF_FORMS: roofForms }, { SURFACE_PATTERNS: patterns }] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('../world-look.js'),
    import('../surface-materials.js'),
    import('../roof-forms.js'),
    import('../surface-patterns.js'),
  ]);
  /** The pack a choice draws: its own, or for the default the pack the host's list marks so, by its digest. */
  const resolved = async (choice: WorldLookChoice): Promise<WorldLookChoice> => {
    if (choice.source !== 'default') return choice;
    const listed = worldLook.listedDefault(await worldLook.listedStylePacks(access));
    if (listed === undefined) throw new Error('The host lists no default style pack');
    return { ...choice, packId: listed.pack_id, manifestSha256: listed.manifest_sha256 };
  };
  /** The mount in a resolved choice's pack, or in the tile look for none. Throws when the pack cannot be read. */
  const mounted = async (choice: WorldLookChoice): Promise<GeneratedSiteMount> => {
    if (choice.packId === null) return siteMount(drawing, { servedBytes, materials, roofForms });
    const [library, { packSiteDresser }] = await Promise.all([
      import('../texture-library.js').then((module) => module.committedTextureLibrary()),
      import('@exulanica/atlas-react/style-pack'),
    ]);
    const prepared = await worldLook.prepareWorldLook(access, choice.packId, library.textureManifest, [], choice.manifestSha256, null, choice.setting ?? null);
    const dress = packSiteDresser({ pack: prepared.pack, families: prepared.families, pieces: prepared.pieces, shading: prepared.look.shading, materials, patterns });
    return siteMount(drawing, { servedBytes, look: prepared.look, dress, materials, roofForms });
  };
  let choice = worldLook.worldLookChoice(search, bound);
  let mount: GeneratedSiteMount;
  let reason: string | null = null;
  try {
    choice = await resolved(choice);
    mount = await mounted(choice);
  } catch (error) {
    reason = error instanceof Error ? error.message : String(error);
    mount = siteMount(drawing, { servedBytes, materials, roofForms });
  }
  return {
    mount,
    look: { pack: choice.packId, source: choice.source, drawn: reason === null && choice.packId !== null, reason },
    async relook(asked) {
      const next = await resolved(asked);
      return { mount: await mounted(next), look: { pack: next.packId, source: next.source, drawn: next.packId !== null, reason: null } };
    },
  };
}

/**
 * The site as the page mounts it, with a look that can be swapped while it stays mounted: what
 * `redrawWorldLook` draws in while this world is attached.
 */
export function switchableSite(world: SiteWorld, stated: (look: WorldLookState) => void, shell: Element): GeneratedSiteMount {
  const drawing = swappableDrawing(world.mount, world.relook, (next) => next.mount, (next) => {
    stated({ ...next.look, source: 'redraw' });
  }, shell);
  return { ...world.mount, attach: (host) => drawing.attach(host) };
}

/** The site to mount for a saved world made from a world kind, or null, with words, when it is not drawn. */
export async function openSiteWorld(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
  bound: WorldStylePackBinding | null = null,
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
    const world = await loadSiteWorld(access, entry, waiting, undefined, undefined, bound);
    env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
    if (world === null) return null;
    const stated = (look: WorldLookState): void => env.shell.setAttribute(WORLD_LOOK_ATTRIBUTE, JSON.stringify(look));
    stated(world.look);
    return switchableSite(world, stated, env.shell);
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
