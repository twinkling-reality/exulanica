// The Integrations page (ROOT's mock, integrations-owner.html and -guest.html, and the user's yes of 27 October): on
// Create's dark plane, "Integrations" over one row per service this server reads. Each row's mark, name and one plain
// line are the served catalog's (GET /integrations); its state, with a dot lit when on and ringed where it is not on
// this server, and its one action come from the live reads (integration-words.mjs's integrationRows). Models opens the
// model picker that exists as a list, Guide opens the service's guide elsewhere, Connect asks the chosen world's
// follower to keep it in a project (POST /world/github-projects), and End ends a grant through the door's own revoke.
// A guest's page reads the host's figures from the session's allowance and makes no door, GitHub or spending read. The
// look is world-ui-integrations.css's, over create-world.css's plane.
import { DoorBridgesClient, type DoorBridge } from '../../../web/packages/app/src/door-bridges-api.ts';
import { DoorGrantsClient, type DoorGrant } from '../../../web/packages/app/src/door-grants-api.ts';
import { SocietyModelsClient } from '../../../web/packages/app/src/society-models-api.ts';
import { worldPath } from '../../../web/packages/app/src/world-scope.ts';
import { button } from '../../../web/packages/app/src/ui/system/components.ts';
import { accessHeaders, type Credentials } from '../../../web/packages/app/src/config.ts';
import type { SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api.ts';
import { createPage, createTitle, quietCommand } from './world-ui-create.ts';
import { tabStops } from './create-world.ts';
import { wrapStop } from './create-steps.mjs';
import { INTEGRATION_WORDS, alreadyEnded, guideAddress, integrationRows, markShapes, namesFor, standingGrants } from './integration-words.mjs';
import { mountModelGallery } from './model-gallery.ts';
import { called } from './character-words.mjs';
import { mountUiScale } from './world-ui.ts';
import './world-ui-integrations.css';

type Json = Record<string, any>;

/** A row as integrationRows gives it. */
interface Row {
  readonly key: string;
  readonly name: string;
  readonly line: string;
  readonly mark: readonly Json[];
  readonly state: { readonly words: string; readonly kind: 'on' | 'off' | 'na' | 'refused' } | null;
  readonly action: { readonly kind: 'models' | 'guide' | 'connect' | 'end'; readonly word: string } & Json | null;
}

/** A grant that stands, as the page keeps it (standingGrants). */
interface Grant {
  readonly grantId: string;
  readonly worldId: string;
  readonly versionId: string | null;
  readonly bridge: string;
  readonly named: string | null;
  readonly ai: boolean;
  readonly things: readonly string[];
}

/** A standing grant with whom it decides for by name. */
type Standing = Grant & { readonly names: readonly string[] };

/** What main.ts's front door holds while the page is open. */
export interface IntegrationsSurface {
  readonly isConnected: boolean;
  remove(): void;
}

/** What the page needs from the front door. */
export interface IntegrationsOptions {
  readonly credentials: Credentials;
  /** The saved worlds, whose grants the page reads and whose titles its lines name. */
  readonly entries: readonly SavedWorldEntry[];
  /** The front door's chosen world, which Connect asks to keep and Models lists the models of; null for none. */
  readonly chosen?: () => SavedWorldEntry | null;
}

const SVG = 'http://www.w3.org/2000/svg';
const TITLE_ID = 'wu-int-title';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

/** A read with the page's own credentials, as Create's reads are made. */
async function readJson(access: Credentials, path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(access.baseUrl + path, { headers: { ...accessHeaders(access), Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok) throw Object.assign(new Error('read'), { status: response.status });
  return response.json();
}

/** A write with the page's own credentials; throws with the problem's code where it is refused. */
async function writeJson(access: Credentials, path: string, body: unknown, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(access.baseUrl + path, {
    method: 'POST', headers: { ...accessHeaders(access), Accept: 'application/json', 'Content-Type': 'application/json' }, credentials: 'same-origin',
    cache: 'no-store', signal, body: JSON.stringify(body),
  });
  const answer = await response.json().catch(() => null) as Json | null;
  if (!response.ok) throw Object.assign(new Error('write'), { status: response.status, code: answer?.['code'] ?? null });
  return answer;
}

/** A version's society, read once for every grant that names it. */
const societyPath = (worldId: string, versionId: string): string => worldPath(`/world/versions/${encodeURIComponent(versionId)}/society`, worldId);

/**
 * The grants that stand in any of `worldIds`, each with whom it decides for by name in the society its version holds.
 * Throws where any read does not answer, so a row is never made from part of them.
 */
async function readStanding(credentials: Credentials, worldIds: readonly string[], signal: AbortSignal): Promise<Standing[]> {
  const reads = await Promise.all(worldIds.map(worldId => new DoorGrantsClient({ ...credentials, worldId, signal }).read()));
  const grants = standingGrants(reads.flatMap((read: ReadonlyMap<string, DoorGrant>) => [...read.values()])) as readonly Grant[];
  const societies = new Map<string, unknown>();
  for (const grant of grants) {
    if (grant.versionId === null) continue;
    const key = `${grant.worldId}\n${grant.versionId}`;
    if (!societies.has(key)) societies.set(key, await readJson(credentials, societyPath(grant.worldId, grant.versionId), signal).catch(() => null));
  }
  return grants.map(grant => ({ ...grant, names: grant.versionId === null ? [] : namesFor(societies.get(`${grant.worldId}\n${grant.versionId}`), grant) }));
}

/** A row's mark: the catalog's line drawing, drawn as shapes, never a picture. */
function markOf(mark: readonly Json[]): HTMLElement {
  const frame = element('span', 'wu-int-mark');
  frame.setAttribute('aria-hidden', 'true');
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  for (const shape of markShapes(mark) as readonly { tag: string; attributes: readonly [string, string][] }[]) {
    const drawn = document.createElementNS(SVG, shape.tag);
    for (const [name, value] of shape.attributes) drawn.setAttribute(name, value);
    svg.append(drawn);
  }
  frame.append(svg);
  return frame;
}

/**
 * Offers "Integrations" beside "Create a world" once `offer` (the drafts offer the front door read) says whose page this
 * is: the install owner's own (own_key), or a guest's, who sees what this server offers them.
 */
export function offerIntegrations(row: HTMLElement, offer: Readonly<Record<string, unknown>> | null, options: IntegrationsOptions): HTMLButtonElement | null {
  if (typeof offer?.['own_key'] !== 'boolean' || !row.isConnected || row.querySelector('.ux-entry-integrations')) return null;
  const guest = offer['own_key'] !== true;
  const notes = (offer['notes'] ?? null) as Json | null;
  const opener = button({ label: INTEGRATION_WORDS.button, variant: 'secondary', size: 'lg', className: 'entry-command ux-entry-integrations' });
  opener.addEventListener('click', () => { mountIntegrations({ ...options, guest, notes, onClose: () => opener.focus({ preventScroll: true }) }); });
  row.append(opener);
  return opener;
}

/**
 * Opens the Integrations page over the front door, a guest's where `guest` (own_key false). `notes` is the drafts
 * offer's web notes, as the front door read it. `onClose` hears it go (Esc or Your worlds).
 */
export function mountIntegrations({ credentials, entries, chosen = () => null, onClose, guest = false, notes = null }: IntegrationsOptions & {
  readonly onClose: () => void; readonly guest?: boolean; readonly notes?: Json | null;
}): IntegrationsSurface {
  const lifetime = new AbortController();
  const signal = lifetime.signal;
  const page = createPage({ labelledBy: TITLE_ID });
  page.form('integrations');
  const host = element('div', 'wu-root wu-create-host wu-int-host');
  host.append(page.root);
  document.body.append(host);
  mountUiScale(host, signal);
  let closed = false;
  const close = (): void => {
    if (closed) return;
    closed = true;
    lifetime.abort();
    gallery.close();
    host.remove();
    onClose();
  };
  page.corner.append(quietCommand({ onPress: close, place: 'corner' }));
  const list = element('ul', 'wu-int-list');
  list.setAttribute('aria-labelledby', TITLE_ID);
  page.column.append(createTitle(INTEGRATION_WORDS.title, TITLE_ID), list);

  const worlds = new Map(entries.map(entry => [entry.worldId, entry.title]));
  const picked = (): { worldId: string; versionId: string; title: string } | null => {
    const entry = chosen();
    return entry ? { worldId: entry.worldId, versionId: entry.authoredVersionId, title: entry.title } : null;
  };
  // Each read the rows need, null until it answers (a guest's door, GitHub and spending reads are never made).
  const reads: Json = {
    catalog: null, models: null, notes, allowance: null, spending: null, keeping: null, bridges: null, standing: null,
    worlds, chosen: null, ended: new Map<string, string>(), connected: null, guest,
  };
  let busy = false;

  // The model picker that exists, opened over this page as a list: nobody to choose for, so nothing is chosen.
  let societyModels: unknown = null;
  const gallery = mountModelGallery({
    root: host, read: () => societyModels as never, still: () => null, portrait: () => null, fromServer: () => guest,
    about: () => ({ who: called({ name: null, kind: null }), doing: null, current: null }),
    refusal: () => '', chosen: () => {}, closed: () => list.querySelector<HTMLElement>('.wu-int-act[data-kind="models"]')?.focus({ preventScroll: true }),
  });

  const act = async (row: Row): Promise<void> => {
    const action = row.action;
    if (!action || busy) return;
    if (action.kind === 'guide') { window.open(guideAddress(reads.catalog, action['guide']), '_blank', 'noopener'); return; }
    if (action.kind === 'models') {
      const entry = chosen();
      if (!entry) return;
      busy = true;
      try {
        societyModels = await new SocietyModelsClient({ ...credentials, worldId: entry.worldId }).read(entry.authoredVersionId);
        if (!signal.aborted) gallery.open({ key: entry.entryId, scene: { id: '' } });
      } catch { /* No models read: the list does not open. */ } finally { busy = false; }
      return;
    }
    busy = true;
    try {
      if (action.kind === 'end') {
        try {
          await new DoorGrantsClient({ ...credentials, worldId: action['worldId'], signal }).revoke(action['grantId']);
          reads['ended'].set(action['grantId'], 'ended');
        } catch (error) {
          if (signal.aborted) return;
          reads['ended'].set(action['grantId'], alreadyEnded((error as Json | null)?.['code']) ? 'ended' : 'refused');
        }
      } else if (action.kind === 'connect') {
        const world = picked();
        if (!world) return;
        try {
          await writeJson(credentials, worldPath('/world/github-projects', world.worldId), { version_id: world.versionId, readable: false }, signal);
          reads['connected'] = world.title;
        } catch {
          if (signal.aborted) return;
          reads['connected'] = 'refused';
        }
      }
    } finally {
      busy = false;
    }
    if (!signal.aborted) draw();
  };

  const drawRow = (row: Row): HTMLElement => {
    const item = element('li', 'wu-int-row');
    item.dataset['key'] = row.key;
    const words = element('span', 'wu-int-words');
    words.append(element('span', 'wu-int-name', row.name), element('span', 'wu-int-line', row.line));
    const state = element('span', 'wu-int-state');
    state.setAttribute('role', 'status');
    if (row.state) {
      state.dataset['kind'] = row.state.kind;
      const dot = element('i');
      dot.setAttribute('aria-hidden', 'true');
      state.append(dot, row.state.words);
    }
    let control: HTMLElement;
    if (row.action) {
      const pressed = element('button', 'wu-int-act', row.action.word);
      pressed.type = 'button';
      pressed.dataset['kind'] = row.action.kind;
      pressed.setAttribute('aria-describedby', `wu-int-name-${row.key.replace(/[^a-z0-9-]/giu, '-')}`);
      pressed.addEventListener('click', () => void act(row));
      control = pressed;
    } else control = element('span', 'wu-int-act wu-int-none');
    words.firstElementChild!.id = `wu-int-name-${row.key.replace(/[^a-z0-9-]/giu, '-')}`;
    item.append(markOf(row.mark), words, state, control);
    return item;
  };

  const draw = (): void => {
    reads['chosen'] = picked();
    const hadFocus = list.contains(document.activeElement) ? (document.activeElement as HTMLElement).closest<HTMLElement>('.wu-int-row')?.dataset['key'] ?? null : null;
    list.replaceChildren(...(integrationRows(reads) as readonly Row[]).map(drawRow));
    if (hadFocus) list.querySelector<HTMLElement>(`.wu-int-row[data-key="${CSS.escape(hadFocus)}"] .wu-int-act`)?.focus({ preventScroll: true });
  };

  // Keys: the model list over the page hears its own first; Tab stays on this page; Esc goes back to Your worlds; nothing
  // reaches the front door under it.
  host.addEventListener('keydown', (event) => {
    if (gallery.isOpen) { if (gallery.key(event)) event.stopPropagation(); return; }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.code === 'Tab') {
      const next = wrapStop(tabStops(page.root), document.activeElement, event.shiftKey);
      event.stopPropagation();
      if (next !== null) { event.preventDefault(); next.focus(); }
      return;
    }
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    event.stopPropagation();
  });
  page.root.tabIndex = -1;
  draw();
  page.root.focus({ preventScroll: true });

  const settle = (key: string, read: Promise<unknown>): void => {
    void read.then((value) => { reads[key] = value; }, () => { reads[key] = null; }).finally(() => { if (!signal.aborted) draw(); });
  };
  settle('catalog', readJson(credentials, '/integrations', signal));
  settle('models', readJson(credentials, '/models', signal).then(value => {
    const served = (value as { models?: unknown } | null)?.models;
    if (!Array.isArray(served)) throw new Error('models');
    return served;
  }));
  if (guest) {
    settle('allowance', readJson(credentials, '/auth/session', signal).then(value => (value as Json | null)?.['allowance'] ?? null));
  } else {
    settle('spending', readJson(credentials, '/spending', signal).then(value => (value as Json | null)?.['providers'] ?? null));
    settle('keeping', readJson(credentials, '/world/github-projects/kept', signal));
    settle('bridges', new DoorBridgesClient({ ...credentials, signal }).read().then((read: ReadonlyMap<string, DoorBridge>) => [...read.values()]));
    settle('standing', readStanding(credentials, [...new Set(entries.map(entry => entry.worldId))], signal));
  }

  return {
    get isConnected() { return page.root.isConnected && !closed; },
    remove: close,
  };
}
