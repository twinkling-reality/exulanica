// The Integrations page (DESIGN's build sheet of 24 October, frames r30-integrations-a and -b; WORDS.md "The
// Integrations page" and its rulings of 11:16 on 25 October): one light page over the front door, opened from
// "Integrations" beside "Create a world". Each row is the catalog's
// (integrations.v1.json) and says what this install serves now: the models read's refusal of each provider, the
// bridges the door admits, the AI grants that stand in any saved world and whom each decides for, by the names their
// society gives them. Nothing is set up here. Enter opens a row's guide elsewhere; the one action is Del, which ends
// the one AI grant that stands through the door's own revoke and then says who decides again, as the record shows.
// A guest's page, or a hosted account's (frame r30-integrations-c), says only what this server offers, from the models
// read alone: no door read, no grant, no Del. Words and rules are integration-words.mjs's; the look is
// world-ui-integrations.css's.
import { DoorBridgesClient, type DoorBridge } from '../../../web/packages/app/src/door-bridges-api.ts';
import { DoorGrantsClient, type DoorGrant } from '../../../web/packages/app/src/door-grants-api.ts';
import { worldPath } from '../../../web/packages/app/src/world-scope.ts';
import { button } from '../../../web/packages/app/src/ui/system/components.ts';
import { accessHeaders, type Credentials } from '../../../web/packages/app/src/config.ts';
import type { SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api.ts';
import { lightHint, lightPage, quietCommand } from './world-ui-create.ts';
import { tabStops } from './create-world.ts';
import { wrapStop } from './create-steps.mjs';
import {
  INTEGRATIONS, INTEGRATION_WORDS, alreadyEnded, catalogRows, endable, endedState, guestRow, guestState, guideAddress, handedBackLine, markShapes,
  namesFor, namesOf, refusedLine, releasedSubjects, rowState, severalLine, standingGrants, stepRow,
} from './integration-words.mjs';
import { mountUiScale } from './world-ui.ts';
import './world-ui-integrations.css';

/** A row of the catalog, as catalogRows gives it. */
interface Row {
  readonly key: string;
  readonly group: string;
  readonly name: string;
  readonly line: string;
  readonly from: { readonly provider?: string; readonly door?: string; readonly ai?: boolean };
  readonly connects: string;
  readonly reads: string;
  readonly goes_to: string;
  readonly ends?: { readonly ended: string; readonly one: string; readonly several: string; readonly refused: string };
  readonly guide: { readonly document: string; readonly heading: string };
  readonly mark: readonly Readonly<Record<string, Readonly<Record<string, string | number>>>>[];
}

/** A grant that stands, as the page keeps it (standingGrants), with whom it decides for by name. */
interface Standing {
  readonly grantId: string;
  readonly worldId: string;
  readonly versionId: string | null;
  readonly ai: boolean;
  readonly things: readonly string[];
  readonly names: readonly string[];
}

/** What the page read: each null where its read did not answer, and the rows it decides say nothing. */
interface Reads {
  readonly models: readonly unknown[] | null;
  readonly bridges: readonly DoorBridge[] | null;
  readonly standing: readonly Standing[] | null;
}

/** What main.ts's front door holds while the page is open. */
export interface IntegrationsSurface {
  readonly isConnected: boolean;
  remove(): void;
}

/** What the page needs from the front door. */
export interface IntegrationsOptions {
  readonly credentials: Credentials;
  /** The saved worlds, whose grants the page reads. */
  readonly entries: readonly SavedWorldEntry[];
  /** The chosen world's still picture, faded behind the page; null for none. */
  readonly picture: () => string | null;
}

const SVG = 'http://www.w3.org/2000/svg';

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

/** A version's society, read once for every grant that names it. */
const societyPath = (worldId: string, versionId: string): string => worldPath(`/world/versions/${encodeURIComponent(versionId)}/society`, worldId);

/**
 * The grants that stand in any of `worldIds`, the AI grants' with whom they decide for by name; and each version's
 * society read, by world and version, for the names the ended line says. Throws where any read does not answer, so a
 * count is never made from part of them.
 */
async function readStanding(credentials: Credentials, worldIds: readonly string[], signal: AbortSignal): Promise<{ standing: Standing[]; societies: Map<string, unknown> }> {
  const reads = await Promise.all(worldIds.map(worldId => new DoorGrantsClient({ ...credentials, worldId, signal }).read()));
  const grants: readonly Omit<Standing, 'names'>[] = standingGrants(reads.flatMap((read: ReadonlyMap<string, DoorGrant>) => [...read.values()]));
  const societies = new Map<string, unknown>();
  for (const grant of grants) {
    if (!grant.ai || grant.versionId === null) continue;
    const key = `${grant.worldId}\n${grant.versionId}`;
    if (!societies.has(key)) societies.set(key, await readJson(credentials, societyPath(grant.worldId, grant.versionId), signal));
  }
  const standing = grants.map(grant => ({
    ...grant, names: grant.ai && grant.versionId !== null ? namesFor(societies.get(`${grant.worldId}\n${grant.versionId}`), grant) : [],
  }));
  return { standing, societies };
}

/** A row's mark: the catalog's line drawing, drawn as shapes, never a picture. */
function markOf(row: Row): HTMLElement {
  const frame = element('span', 'wu-int-mark');
  frame.setAttribute('aria-hidden', 'true');
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  for (const shape of markShapes(row.mark) as readonly { tag: string; attributes: readonly [string, string][] }[]) {
    const drawn = document.createElementNS(SVG, shape.tag);
    for (const [name, value] of shape.attributes) drawn.setAttribute(name, value);
    svg.append(drawn);
  }
  frame.append(svg);
  return frame;
}

/**
 * Offers "Integrations" beside "Create a world" in the front door's glass once `offer` (the draft offer the front door
 * read) says whose page this is: the install owner's own page, or a guest's or hosted account's read-only page, where
 * nothing is set up.
 */
export function offerIntegrations(row: HTMLElement, offer: Readonly<Record<string, unknown>> | null, options: IntegrationsOptions): HTMLButtonElement | null {
  if (typeof offer?.['own_key'] !== 'boolean' || !row.isConnected || row.querySelector('.ux-entry-integrations')) return null;
  const guest = offer['own_key'] !== true;
  const opener = button({ label: INTEGRATION_WORDS.button, variant: 'secondary', size: 'lg', className: 'entry-command ux-entry-integrations' });
  opener.addEventListener('click', () => { mountIntegrations({ ...options, guest, onClose: () => opener.focus({ preventScroll: true }) }); });
  row.append(opener);
  return opener;
}

/**
 * Opens the Integrations page over the front door, a guest's where `guest` (own_key false). `onClose` hears it go (Esc
 * or Back).
 */
export function mountIntegrations({ credentials, entries, picture, onClose, guest = false }: IntegrationsOptions & { readonly onClose: () => void; readonly guest?: boolean }): IntegrationsSurface {
  const lifetime = new AbortController();
  const signal = lifetime.signal;
  const page = lightPage({ form: 'integrations', picture: picture(), labelledBy: 'wu-int-title' });
  const host = element('div', 'wu-root wu-integrations-host');
  host.append(page.root);
  document.body.append(host);
  mountUiScale(host, signal);
  let closed = false;
  const close = (): void => {
    if (closed) return;
    closed = true;
    lifetime.abort();
    host.remove();
    onClose();
  };

  const title = element('h1', 'wu-light-title', guest ? INTEGRATION_WORDS.guestTitle : INTEGRATION_WORDS.title);
  title.id = 'wu-int-title';
  page.head.append(element('p', 'wu-int-over', INTEGRATION_WORDS.overLabel), title, element('p', 'wu-int-sub', guest ? INTEGRATION_WORDS.guestSub : INTEGRATION_WORDS.sub), element('p', 'wu-int-small', INTEGRATION_WORDS.small));

  const rows = (guest ? catalogRows(INTEGRATIONS).map(guestRow) : catalogRows(INTEGRATIONS)) as readonly Row[];
  let reads: Reads | null = null;
  let societies = new Map<string, unknown>();
  /** The row each key and the open lines are for, by its key. */
  let focusKey = rows[0]?.key ?? '';
  /** Whom the record shows handed back on each row whose grant Del ended, until the page is opened again. */
  const ended = new Map<string, readonly string[]>();
  /** The rows whose end the server refused or did not answer: their grant still stands. */
  const refused = new Set<string>();
  let ending = false;

  /** The rows this install shows: all of them until the reads answer, then each one whose state it can give. */
  const shown = (): readonly Row[] => (reads === null ? rows : rows.filter(row => stateOf(row) !== null));
  /** A row's state: undefined where its read has not answered, null where the row is left out. */
  const stateOf = (row: Row): { words: string; on: boolean } | null | undefined => {
    if (reads === null) return undefined;
    if (guest) return reads.models === null ? undefined : guestState(row, reads.models);
    const needed = row.from.provider ? reads.models : row.from.door === 'bridges' ? reads.bridges : reads.standing;
    if (needed === null) return undefined;
    return rowState(row, { models: reads.models ?? [], bridges: reads.bridges ?? [], standing: reads.standing ?? [] });
  };

  const list = element('div', 'wu-int-list');
  page.lower.append(list);
  // Enter's key is a press like Del and Esc (fold-in e): the quiet command's look, as a link to the focused row's guide.
  const guideLink = element('a', 'wu-qcmd wu-int-guide');
  guideLink.dataset['place'] = 'row';
  guideLink.target = '_blank';
  guideLink.rel = 'noopener';

  /** The key row: ↑ ↓ Choose, Enter How to set it up ↗, Del End this grant where one stands, Esc Back. */
  const drawKeys = (row: Row | undefined): void => {
    const choose = lightHint('↑ ↓', INTEGRATION_WORDS.choose, 'ArrowUp ArrowDown');
    const setUp = lightHint('Enter', INTEGRATION_WORDS.setUp, 'Enter');
    guideLink.replaceChildren(...setUp.childNodes);
    guideLink.setAttribute('aria-keyshortcuts', 'Enter');
    if (row) guideLink.href = guideAddress(INTEGRATIONS, row.guide);
    const keys: HTMLElement[] = [choose, guideLink];
    if (row && endable(row, reads?.standing ?? []) && !ended.has(row.key)) {
      keys.push(quietCommand({ key: 'Del', word: INTEGRATION_WORDS.end, shortcut: 'Delete', place: 'row', onPress: () => void endGrant(row) }));
    }
    keys.push(quietCommand({ key: 'Esc', word: INTEGRATION_WORDS.back, shortcut: 'Escape', place: 'row', onPress: close }));
    page.keys.replaceChildren(...keys);
  };

  const draw = (): void => {
    const visible = shown();
    if (!visible.some(row => row.key === focusKey)) focusKey = visible[0]?.key ?? '';
    const hadFocus = list.contains(document.activeElement);
    const groups = INTEGRATIONS.groups.map((group: { key: string; label: string }) => {
      const own = visible.filter(row => row.group === group.key);
      if (!own.length) return null;
      const label = element('p', 'wu-int-label', group.label);
      label.id = `wu-int-group-${group.key}`;
      const section = element('section', 'wu-int-group');
      section.setAttribute('aria-labelledby', label.id);
      section.append(label, ...own.map(drawRow));
      return section;
    }).filter((section: HTMLElement | null): section is HTMLElement => section !== null);
    list.replaceChildren(...groups);
    drawKeys(visible.find(row => row.key === focusKey));
    if (hadFocus) list.querySelector<HTMLElement>('.wu-int-row[data-focus="true"]')?.focus({ preventScroll: true });
  };

  const drawRow = (row: Row): HTMLElement => {
    const focused = row.key === focusKey;
    const item = element('article', 'wu-int-row');
    item.dataset['key'] = row.key;
    item.dataset['focus'] = String(focused);
    item.tabIndex = focused ? 0 : -1;
    item.setAttribute('aria-labelledby', `wu-int-name-${row.key}`);
    const name = element('p', 'wu-int-name', row.name);
    name.id = `wu-int-name-${row.key}`;
    const words = element('div', 'wu-int-words');
    words.append(name, element('p', 'wu-int-line', row.line));
    const state = element('p', 'wu-int-state');
    const handedBack = ended.get(row.key);
    const now = handedBack === undefined ? stateOf(row) : { words: endedState(row), on: false };
    if (now) {
      state.dataset['on'] = String(now.on);
      if (now.on) state.append(element('span', 'wu-int-dot'));
      state.append(now.words);
    }
    state.setAttribute('role', 'status');
    item.append(markOf(row), words, state);
    if (focused) {
      const open = element('dl', 'wu-int-open');
      for (const [label, value] of [[INTEGRATION_WORDS.connects, row.connects], [INTEGRATION_WORDS.reads, row.reads], [INTEGRATION_WORDS.goesTo, row.goes_to]] as const) {
        open.append(element('dt', '', label), element('dd', '', value));
      }
      item.append(open);
      const faint = handedBack !== undefined ? handedBackLine(row, handedBack)
        : refused.has(row.key) ? refusedLine(row) : severalLine(row, reads?.standing ?? []);
      if (faint) item.append(element('p', 'wu-int-faint', faint));
    }
    item.addEventListener('click', () => { if (focusKey !== row.key) { focusKey = row.key; draw(); } item.ownerDocument.querySelector<HTMLElement>(`.wu-int-row[data-key="${row.key}"]`)?.focus({ preventScroll: true }); });
    return item;
  };

  /**
   * Ends the row's one standing grant through the door's revoke, then names whom the record shows handed back. A
   * refused or unanswered end leaves the grant standing and says so; one refused because it had already ended says
   * it ended.
   */
  const endGrant = async (row: Row): Promise<void> => {
    const grant = endable(row, reads?.standing ?? []) as Standing | null;
    if (!grant || ending || ended.has(row.key)) return;
    ending = true;
    try {
      await new DoorGrantsClient({ ...credentials, worldId: grant.worldId, signal }).revoke(grant.grantId);
      let names: readonly string[] = [];
      if (grant.versionId !== null && grant.things.length) {
        const history = await readJson(credentials, worldPath(`/world/versions/${encodeURIComponent(grant.versionId)}/society/models/history`, grant.worldId), signal).catch(() => null);
        names = namesOf(societies.get(`${grant.worldId}\n${grant.versionId}`), releasedSubjects(history, grant.things));
      }
      if (signal.aborted) return;
      refused.delete(row.key);
      ended.set(row.key, names);
    } catch (error) {
      if (signal.aborted) return;
      const code = (error as { readonly code?: unknown } | null)?.code;
      if (alreadyEnded(code)) { refused.delete(row.key); ended.set(row.key, []); } else refused.add(row.key);
    } finally {
      ending = false;
    }
    draw();
  };

  // Keys: ↑ ↓ choose a row, Enter opens its guide, Del ends its one grant, Esc goes back; Tab stays on this page, and
  // nothing reaches the front door under it.
  page.root.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.code === 'Tab') {
      const next = wrapStop(tabStops(page.root), document.activeElement, event.shiftKey);
      event.stopPropagation();
      if (next !== null) { event.preventDefault(); next.focus(); }
      return;
    }
    const visible = shown();
    const at = visible.findIndex(row => row.key === focusKey);
    const row = visible[at];
    if (event.key === 'Escape') close();
    else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      focusKey = visible[stepRow(at, visible.length, event.key)]?.key ?? focusKey;
      draw();
      list.querySelector<HTMLElement>('.wu-int-row[data-focus="true"]')?.focus({ preventScroll: true });
    } else if (event.key === 'Enter' && row && !(document.activeElement instanceof HTMLButtonElement || document.activeElement instanceof HTMLAnchorElement)) {
      window.open(guideAddress(INTEGRATIONS, row.guide), '_blank', 'noopener');
    } else if ((event.key === 'Delete' || event.key === 'Backspace') && row) void endGrant(row);
    else { event.stopPropagation(); return; }
    event.preventDefault();
    event.stopPropagation();
  });
  page.root.tabIndex = -1;

  draw();
  page.root.focus({ preventScroll: true });
  list.querySelector<HTMLElement>('.wu-int-row[data-focus="true"]')?.focus({ preventScroll: true });

  const worldIds = [...new Set(entries.map(entry => entry.worldId))];
  // A guest's page reads the models alone: it makes no door read, so it lists no grant and settles none.
  void Promise.allSettled([
    readJson(credentials, '/models', signal),
    guest ? Promise.resolve(new Map<string, DoorBridge>()) : new DoorBridgesClient({ ...credentials, signal }).read(),
    guest ? Promise.resolve({ standing: [], societies: new Map<string, unknown>() }) : readStanding(credentials, worldIds, signal),
  ]).then(([models, bridges, standing]) => {
    if (signal.aborted) return;
    const served = models.status === 'fulfilled' ? (models.value as { models?: unknown }).models : null;
    if (standing.status === 'fulfilled') societies = standing.value.societies;
    reads = {
      models: Array.isArray(served) ? served : null,
      bridges: bridges.status === 'fulfilled' ? [...bridges.value.values()] : null,
      standing: standing.status === 'fulfilled' ? standing.value.standing : null,
    };
    draw();
  });

  return {
    get isConnected() { return page.root.isConnected && !closed; },
    remove: close,
  };
}
