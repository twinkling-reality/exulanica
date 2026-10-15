import { holdTerrainOccupancy, type TerrainOccupancyLease } from './terrain-occupancy.js';
import type { TerrainOccupancyProof } from '@exulanica/atlas-core';
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
 *
 * A site made on land (`exulanica.site-drawing/v5`) names its land's chunks and backdrop by digest;
 * each is read through the world's version (`GET .../land/chunks/{x}/{y}`, `.../land/backdrop`) and
 * held to the digest its drawing names (`readSiteLand`) before the site is mounted, and the same
 * land serves every look it is redrawn in. Land that cannot be read, or is not the land named, is
 * not drawn and is not stood in for: the site is not drawn, and the page says so.
 *
 * A site on land may stand on a landscape (`docs/landscape-contract.md`): volumes placed round it,
 * such as sea stacks and floating islands. Its saved entry does not say so, so the page asks for the
 * landscape (`GET .../landscape`) of every site on land, and a 404 means it has none. The landscape
 * drawing is held to its route's digest and to this site's drawing, receipt and land, and each chunk
 * of the level a volume is drawn at to the digest the landscape names (`readSiteVolumes`). Volumes
 * stand off the site and are never walked, so a landscape that cannot be read does not stop the
 * site: it is drawn without them, and `landscape.reason` says why.
 */

import type { GeneratedSiteMount, SiteDrawing, SiteLand, SiteVolumes, StructuredSiteDrawing, TerrainSiteDrawing } from '@exulanica/atlas-react/generated-site';
import { accessHeaders, type Credentials } from '../config.js';
import { say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import type { WorldLookChoice } from '../world-look.js';
import type { SavedWorldEntry } from '../world-entry-api.js';
import type { WorldStylePackBinding } from '../world-style-api.js';
import { GENERATED_WORLD_WAITING_ATTRIBUTE } from './generated-world-ready.js';
import type { SightBlocker } from './arrival-view.js';
import type { AppEnvironment } from './session-state.js';
import { siteSightRings } from './sight.js';
import { WORLD_LOOK_ATTRIBUTE, swappableDrawing, type WorldLookState } from './world-look-redraw.js';
import { rememberSiteSeats } from './site-furniture.js';

function isTerrainSiteDrawing(drawing: SiteDrawing): drawing is TerrainSiteDrawing {
  return drawing.profile === 'exulanica.site-drawing/v3' || drawing.profile === 'exulanica.site-drawing/v4';
}

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
  /** The SHA-256 of the drawing as its route served it (its ETag): a changed world reads another. */
  readonly drawingSha256?: string;
  readonly look: WorldLookState;
  /** The same drawing in another look: nothing is read or checked again. Throws, changing nothing, when the pack cannot be read. */
  readonly relook: (choice: WorldLookChoice) => Promise<{ readonly mount: GeneratedSiteMount; readonly look: WorldLookState }>;
  /** The volumes a site on a landscape places round it: how many are drawn, or why none are; absent for a site on no landscape. */
  readonly landscape?: { readonly volumes: number; readonly reason: string | null };
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
  currentEntry?: () => SavedWorldEntry | null,
): Promise<SiteWorld | null> {
  if (entry.generatedSite == null && entry.generatedTerrain == null) return null;
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
  if (isTerrainSiteDrawing(drawing)) {
    const terrain = entry.generatedTerrain;
    if (terrain == null || (terrain.dressingSha256 !== undefined && terrain.dressingSha256 !== (drawing.profile === 'exulanica.site-drawing/v4' ? drawing.dressingSha256 : undefined)) || terrain.regionId !== drawing.regionId || terrain.geometrySha256 !== drawing.terrain.geometry.sha256
        || terrain.contactSha256 !== drawing.terrain.sha256 || terrain.arrivalMm.some((v, i) => v !== drawing.arrival.positionMm[i])
        || terrain.arrivalFacingMm.some((v, i) => v !== drawing.arrival.facingMm[i])) throw new Error("This world's terrain drawing differs from its saved entry.");
  } else if (entry.generatedSite == null) throw new Error("This world's drawing is not its declared terrain.");
  const land = isTerrainSiteDrawing(drawing) || drawing.land === undefined ? null : await loadSiteLand(access, entry, drawing);
  const landscape = land === null || isTerrainSiteDrawing(drawing) ? null : await loadSiteLandscape(access, entry, drawing, actual, waiting, wait);
  const world = { ...await siteInLook(access, drawing, new TextEncoder().encode(text).byteLength, search, bound, entry, currentEntry, land, landscape?.volumes ?? null), drawingSha256: actual };
  return landscape === null || landscape.state === null ? world : { ...world, landscape: landscape.state };
}

/**
 * The volumes a site on land's landscape places round it, read through its world's version: the
 * landscape drawing, held to its route's digest and to this site's drawing (`drawingSha256`),
 * world and land, then every chunk of the level each volume is drawn at, held to the digest the
 * landscape names. None, with no state, for a site on no landscape (404); none, with the reason,
 * for a landscape that cannot be read, since the site is drawn without its volumes.
 */
async function loadSiteLandscape(
  access: Credentials,
  entry: SavedWorldEntry,
  drawing: StructuredSiteDrawing,
  drawingSha256: string,
  waiting: () => void,
  wait: (ms: number) => Promise<void>,
): Promise<{ readonly volumes: SiteVolumes | null; readonly state: { readonly volumes: number; readonly reason: string | null } | null }> {
  const query = new URLSearchParams({ world_id: entry.worldId });
  const version = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`;
  const ask = async (path: string): Promise<Response> => {
    let response: Response;
    for (let asked = 1; ; asked += 1) {
      response = await fetch(`${version}/${path}`, {
        headers: { ...accessHeaders(access), Accept: 'application/json' },
        credentials: 'same-origin',
      });
      if (asked >= DRAWING_ASKS || !(await stillMaking(response))) return response;
      waiting();
      await wait(waitMs(response));
    }
  };
  try {
    const response = await ask(`landscape?${query.toString()}`);
    if (response.status === 404) {
      const problem = await response.json().catch(() => null) as { code?: unknown } | null;
      if (problem?.code === 'landscape_unavailable') return { volumes: null, state: null };
    }
    if (!response.ok) throw new Error(`This world's landscape could not be read: HTTP ${response.status}.`);
    const [{ readSiteVolumes, siteVolumeChunks }, { sha256Hex }, { readLandscapeDrawing }] = await Promise.all([
      import('@exulanica/atlas-react/generated-site'),
      import('@exulanica/atlas-react/playcanvas'),
      import('@exulanica/atlas-core'),
    ]);
    const text = await response.text();
    let bytes = new TextEncoder().encode(text).byteLength;
    const stated = response.headers.get('ETag')?.replaceAll('"', '') ?? undefined;
    if (stated === undefined) throw new Error("This world's landscape arrived with no digest.");
    const landscape = readLandscapeDrawing(JSON.parse(text), sha256Hex, stated);
    if (landscape.worldId !== entry.worldId || landscape.siteDrawingSha256 !== drawingSha256 || landscape.landSha256 !== drawing.land!.landSha256) {
      throw new Error("This world's landscape names another drawing, world or land than its site's.");
    }
    const refs = siteVolumeChunks(landscape);
    const bodies = new Map(await Promise.all(refs.map(async (ref) => {
      const chunk = await ask(`landscape/chunk?${new URLSearchParams({ sha256: ref.sha256, world_id: entry.worldId }).toString()}`);
      if (!chunk.ok) throw new Error(`This world's landscape chunk could not be read: HTTP ${chunk.status}.`);
      if (chunk.headers.get('ETag')?.replaceAll('"', '') !== ref.sha256) throw new Error("This world's landscape chunk arrived as a document its landscape does not name.");
      const body = await chunk.text();
      bytes += new TextEncoder().encode(body).byteLength;
      return [ref.sha256, JSON.parse(body) as unknown] as const;
    })));
    const volumes = readSiteVolumes(landscape, bodies, sha256Hex, bytes);
    return { volumes, state: { volumes: volumes.volumes.length, reason: null } };
  } catch (error) {
    return { volumes: null, state: { volumes: 0, reason: error instanceof Error ? error.message : String(error) } };
  }
}

/**
 * The land a site on land names, read through its world's version: every chunk and the backdrop,
 * each held to the digest its route names and to the one the drawing names.
 */
async function loadSiteLand(access: Credentials, entry: SavedWorldEntry, drawing: StructuredSiteDrawing): Promise<SiteLand> {
  const [{ readSiteLand }, { sha256Hex }] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('@exulanica/atlas-react/playcanvas'),
  ]);
  const section = drawing.land!;
  const query = new URLSearchParams({ world_id: entry.worldId });
  const version = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`;
  let bytes = 0;
  const read = async (path: string, sha256: string): Promise<unknown> => {
    const response = await fetch(`${version}/${path}?${query.toString()}`, {
      headers: { ...accessHeaders(access), Accept: 'application/json' },
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`This world's land could not be read: HTTP ${response.status}.`);
    if (response.headers.get('ETag')?.replaceAll('"', '') !== sha256) throw new Error("This world's land arrived as a document its drawing does not name.");
    const text = await response.text();
    bytes += new TextEncoder().encode(text).byteLength;
    return JSON.parse(text);
  };
  const [chunks, backdrop] = await Promise.all([
    Promise.all(section.chunks.map(async ({ chunk: [x, y], sha256 }) => [`${x},${y}`, await read(`land/chunks/${x}/${y}`, sha256)] as const)),
    read('land/backdrop', section.backdropSha256),
  ]);
  return readSiteLand(drawing, new Map(chunks), backdrop, sha256Hex, bytes);
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
  entry: SavedWorldEntry,
  currentEntry?: () => SavedWorldEntry | null,
  land: SiteLand | null = null,
  landscape: SiteVolumes | null = null,
): Promise<SiteWorld> {
  const [{ siteMount, createDressingReadiness }, worldLook, { SURFACE_MATERIALS: materials }, { ROOF_FORMS: roofForms }, { SURFACE_PATTERNS: patterns }, { SITE_SCENERY: scenery }, { SITE_INTERIOR: interior }, { GROUND_BORDERS: borders }, { RENDER_BUDGET: renderBudget }, { SURFACE_FINISH: finish }] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('../world-look.js'),
    import('../surface-materials.js'),
    import('../roof-forms.js'),
    import('../surface-patterns.js'),
    import('../site-scenery.js'),
    import('../site-interior.js'),
    import('../ground-borders.js'),
    import('../render-budget.js'),
    import('../surface-finish.js'),
  ]);
  const preparedDressing = drawing.profile === 'exulanica.site-drawing/v4' ? await import('./terrain-dressing.js').then(module => module.loadTerrainDressing(access, drawing.dressing)) : undefined;
  const dressingReadiness = createDressingReadiness();
  const terrainLease = await readTerrainOccupancy(access, entry, drawing, currentEntry);
  const terrainOccupancy = terrainLease.read;
  const terrainOptions = isTerrainSiteDrawing(drawing) ? {terrainOccupancy, dressingReadiness, ...(preparedDressing === undefined ? {} : {preparedDressing})} : {};
  // A site on land is mounted on its land in every look it is drawn in.
  const landOptions = land === null ? {} : { land, landSurfaces: (await import('../land-surfaces.js')).LAND_SURFACES, ...(landscape === null ? {} : { landscape }) };
  const measure = new URLSearchParams(search).has('measure') ? { measure: true } : {};
  const seated = (seats: Parameters<typeof rememberSiteSeats>[2]): (() => void) => rememberSiteSeats(entry.entryId, entry.authoredVersionId!, seats);
  /** The pack a choice draws: its own, or for the default the pack the host's list marks so, by its digest. */
  const resolved = async (choice: WorldLookChoice): Promise<WorldLookChoice> => {
    if (choice.source !== 'default') return choice;
    const listed = worldLook.listedDefault(await worldLook.listedStylePacks(access));
    if (listed === undefined) throw new Error('The host lists no default style pack');
    return { ...choice, packId: listed.pack_id, manifestSha256: listed.manifest_sha256 };
  };
  /** The mount in a resolved choice's pack, or in the tile look for none. Throws when the pack cannot be read. */
  const mounted = async (choice: WorldLookChoice): Promise<GeneratedSiteMount> => {
    if (choice.packId === null) return siteMount(drawing, { ...measure, ...terrainOptions, ...landOptions, seated, servedBytes, materials, roofForms, scenery, interior, renderBudget });
    const [library, { packSiteDresser, packTextureSetId, preparePackTexture }, { prepareTextureSet }, { parseTextureSetManifest, resolveSurfaceLookRole }] = await Promise.all([
      import('../texture-library.js').then((module) => module.committedTextureLibrary()),
      import('@exulanica/atlas-react/style-pack'),
      import('@exulanica/atlas-react/generated-tile'),
      import('@exulanica/atlas-core'),
    ]);
    const prepared = await worldLook.prepareWorldLook(access, choice.packId, library.textureManifest, [], choice.manifestSha256, choice.ownBase ?? null, choice.setting ?? null, choice.own ?? false);
    if (isTerrainSiteDrawing(drawing)) return siteMount(drawing, { ...measure, ...terrainOptions, servedBytes, look: prepared.look, renderBudget });
    const manifest = parseTextureSetManifest(library.textureManifest);
    const surfaces = drawing.slots.map(slot => resolveSurfaceLookRole(prepared.pack, slot, prepared.families, slot.primitive === 'none' ? 'module' : 'either', materials));
    const setIds = new Set(surfaces.flatMap(surface => (surface?.kind === 'surface' && 'texture_set' in surface.surface ? [surface.surface.texture_set] : [])));
    // The pack's own textures its slots name, drawn under their own ids beside the library's sets.
    const packTextures = new Set(surfaces.flatMap(surface => (surface?.kind === 'surface' && 'texture' in surface.surface ? [surface.surface.texture] : [])));
    const textures = new Map(await Promise.all([
      ...[...setIds].map(async setId => [setId, await prepareTextureSet(manifest, setId, entry => library.textureSet(entry.contentSha256))] as const),
      ...[...packTextures].map(async key => [packTextureSetId(key), await preparePackTexture(prepared.pack, key, prepared.packFile)] as const),
    ]));
    const dress = packSiteDresser({ textures, look: prepared.look, pack: prepared.pack, families: prepared.families, pieces: prepared.pieces, shading: prepared.look.shading, materials, patterns, borders, finish, ...('landSurfaces' in landOptions ? { landSurfaces: landOptions.landSurfaces } : {}) });
    return siteMount(drawing, { ...measure, ...terrainOptions, ...landOptions, seated, servedBytes, look: prepared.look, dress, materials, roofForms, scenery, interior, renderBudget });
  };
  let choice = worldLook.worldLookChoice(search, bound);
  let mount: GeneratedSiteMount;
  let reason: string | null = null;
  try {
    choice = await resolved(choice);
    mount = await mounted(choice);
  } catch (error) {
    reason = error instanceof Error ? error.message : String(error);
    mount = siteMount(drawing, { ...measure, ...terrainOptions, ...landOptions, seated, servedBytes, materials, roofForms, scenery, interior, renderBudget });
  }
  return {
    mount: leasedMount(mount, terrainLease),
    look: { pack: choice.packId, source: choice.source, drawn: reason === null && choice.packId !== null, reason },
    async relook(asked) {
      const next = await resolved(asked);
      return { mount: leasedMount(await mounted(next), terrainLease), look: { pack: next.packId, source: next.source, drawn: next.packId !== null, reason: null } };
    },
  };
}

/**
 * The site as the page mounts it, with a look that can be swapped while it stays mounted: what
 * `redrawWorldLook` draws in while this world is attached.
 */
export function switchableSite(
  world: SiteWorld,
  stated: (look: WorldLookState) => void,
  shell: Element,
  /** How to read the world again and hand on its plan of sight: given, the site can be drawn again while open (`openSite`). */
  reading?: { readonly read: (entry: SavedWorldEntry) => Promise<SiteWorld | null>; readonly standing: (blockers: readonly SightBlocker[]) => void },
): GeneratedSiteMount {
  const drawing = swappableDrawing(world.mount, world.relook, (next) => next.mount, (next) => {
    stated({ ...next.look, source: 'redraw' });
  }, shell);
  let shown = world;
  // One redraw at a time, in the order asked, so an older reading never goes up after a newer one.
  let redrawing: Promise<unknown> = Promise.resolve();
  const site: OpenSite = {
    drawing: () => shown.mount.drawing,
    redraw(entry, walk) {
      const run = redrawing.then(async (): Promise<boolean> => {
        if (reading === undefined) return false;
        const next = await reading.read(entry);
        if (next === null || (next.drawingSha256 !== undefined && next.drawingSha256 === shown.drawingSha256)) return false;
        if (!(await drawing.replace(next))) return false;
        shown = next;
        reading.standing(sightOf(next));
        walk(next.mount.navigationWorld);
        return true;
      });
      redrawing = run.catch(() => false);
      return run;
    },
  };
  return {
    ...world.mount,
    attach: (host) => {
      const attachment = drawing.attach(host);
      openSite = site;
      const dispose = attachment.dispose;
      return Object.assign(attachment, {
        dispose() {
          if (openSite === site) openSite = null;
          dispose.call(attachment);
        },
      });
    },
  };
}

/** Every box a site's drawing draws across the eye height a person walks it at: what hides a being there. */
function sightOf(world: SiteWorld): SightBlocker[] {
  const drawing = world.mount.drawing;
  if (isTerrainSiteDrawing(drawing)) return [];
  const eyeMm = world.mount.navigationWorld.eyeHeight * 1000;
  return world.mount.land === undefined ? siteSightRings(drawing, eyeMm) : siteSightRings(drawing, eyeMm, world.mount.land.groundMm);
}

/**
 * The site world open now, drawn again from a new reading after a person changed one of its made
 * parts: its drawing as it stands (what points at its parts reads it), and `redraw`, which reads the
 * entry's version again and, when its drawing changed, draws it in place in the look the world shows
 * now, hands on what hides a being and gives its walking world to `walk`. True when it drew again.
 */
export interface OpenSite {
  readonly drawing: () => SiteDrawing;
  redraw(entry: SavedWorldEntry, walk: (world: GeneratedSiteMount['navigationWorld']) => void): Promise<boolean>;
}
let openSite: OpenSite | null = null;
/** The site world open now, or null. */
export const currentOpenSite = (): OpenSite | null => openSite;

/** The site to mount for a saved world made from a world kind, or null, with words, when it is not drawn. */
export async function openSiteWorld(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
  bound: WorldStylePackBinding | null = null,
  /** Handed the place's plan of what stands in a sight line, once its drawing is read and will be drawn. */
  standing: (blockers: readonly SightBlocker[]) => void = () => undefined,
  currentEntry?: () => SavedWorldEntry | null,
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
    const world = await loadSiteWorld(access, entry, waiting, undefined, undefined, bound, currentEntry);
    env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
    if (world === null) return null;
    // Every box the drawing draws across the eye height a person walks it at.
    if (!isTerrainSiteDrawing(world.mount.drawing)) standing(sightOf(world));
    const stated = (look: WorldLookState): void => env.shell.setAttribute(WORLD_LOOK_ATTRIBUTE, JSON.stringify(look));
    stated(world.look);
    // A site drawn on a plan (not terrain) is drawn again after a person changes one of its made parts.
    const reading = isTerrainSiteDrawing(world.mount.drawing) ? undefined : {
      read: (next: SavedWorldEntry) => loadSiteWorld(access, next, () => {}, undefined, undefined, bound, currentEntry),
      standing,
    };
    return switchableSite(world, stated, env.shell, reading);
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

/** A proof is valid only while this mount still observes the exact entry it was read for. */
async function readTerrainOccupancy(access: Credentials, entry: SavedWorldEntry, drawing: SiteDrawing,
  currentEntry?: () => SavedWorldEntry | null): Promise<TerrainOccupancyLease> {
  const unavailable: TerrainOccupancyProof = Object.freeze({status: 'unavailable'});
  const absent: TerrainOccupancyLease = {read: () => unavailable, attach: () => () => undefined};
  if (!isTerrainSiteDrawing(drawing) || currentEntry === undefined) return absent;
  let revoked = false;
  const stillCurrent = (): boolean => {
    const current = currentEntry();
    if (current === null || current.worldId !== entry.worldId || current.entryId !== entry.entryId
        || current.authoredVersionId !== entry.authoredVersionId || current.authoredStateSha256 !== entry.authoredStateSha256
        || current.currentAuthoredStateSha256 !== entry.authoredStateSha256
        || current.authoredEditSeq !== entry.authoredEditSeq || current.currentAuthoredEditSeq !== entry.authoredEditSeq
        || current.sourceSnapshotId !== entry.sourceSnapshotId || current.sourceSnapshotSha256 !== entry.sourceSnapshotSha256
        || current.generatedTerrain?.geometrySha256 !== drawing.terrain.geometry.sha256 || current.generatedTerrain?.contactSha256 !== drawing.terrain.sha256
        || current.generatedTerrain?.dressingSha256 !== entry.generatedTerrain?.dressingSha256
        || current.availability !== 'available') revoked = true;
    return !revoked;
  };
  if (!stillCurrent()) return absent;
  return holdTerrainOccupancy(async signal => {
  try {
    const query = new URLSearchParams({world_id: entry.worldId, expected_state_sha256: entry.authoredStateSha256});
    const response = await fetch(`${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}/terrain-contact?${query}`, {
      headers: {...accessHeaders(access), Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store', signal,
    });
    if (!response.ok || !stillCurrent()) return unavailable;
    const proof = await response.json() as Record<string, unknown>;
    const dressed = drawing.profile === 'exulanica.site-drawing/v4';
    const fields = 'profile world_id version_id source_snapshot_id receipt_sha256 geometry_sha256 contact_sha256 authored_state_sha256 status reason' + (dressed ? ' dressing_sha256' : '');
    if (proof === null || typeof proof !== 'object' || Object.keys(proof).sort().join(' ') !== fields.split(' ').sort().join(' ')
        || proof['profile'] !== (dressed ? 'exulanica.terrain-source-proof/v2' : 'exulanica.terrain-source-proof/v1')
        || (dressed && proof['dressing_sha256'] !== drawing.dressingSha256) || proof['status'] !== 'verified' || proof['reason'] !== null
        || proof['world_id'] !== entry.worldId || proof['version_id'] !== entry.authoredVersionId
        || proof['source_snapshot_id'] !== entry.sourceSnapshotId || proof['authored_state_sha256'] !== entry.authoredStateSha256
        || proof['receipt_sha256'] !== drawing.receiptSha256 || proof['geometry_sha256'] !== drawing.terrain.geometry.sha256
        || proof['contact_sha256'] !== drawing.terrain.sha256) return unavailable;
    const accepted: TerrainOccupancyProof = Object.freeze({status: 'verified', worldId: entry.worldId,
      versionId: entry.authoredVersionId, receiptSha256: drawing.receiptSha256, geometrySha256: drawing.terrain.geometry.sha256,
      contactSha256: drawing.terrain.sha256, authoredStateSha256: entry.authoredStateSha256});
    return stillCurrent() ? accepted : unavailable;
  } catch { return unavailable; }
  }, stillCurrent);
}

function leasedMount(mount: GeneratedSiteMount, lease: TerrainOccupancyLease): GeneratedSiteMount {
  return {...mount, attach(host) {
    const stop = lease.attach();
    try {
      const attachment = mount.attach(host);
      return {...attachment, get metrics() {return attachment.metrics;}, dispose() {stop(); attachment.dispose();}};
    } catch (error) {stop(); throw error;}
  }};
}
