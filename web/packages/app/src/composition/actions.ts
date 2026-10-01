/**
 * The action host for a mounted world: the registry's entries bound to what this world can do,
 * the world's capability descriptors read from the server, and the surfaces that render them (the
 * tool rail, the world clock in the top bar and the command palette).
 *
 * Bindings are the same calls the older controls make (the objects panel, the People panel, the
 * shell's surfaces), so a click in the rail and a click in a panel are one action with one
 * receipt. Capabilities are read when the world mounts, after each saved change and when the
 * people of the world arrive or leave; until the first read, an action with an operation is
 * `unknown`, never assumed available.
 */

import type { TransportOptions } from '@exulanica/graph-client';
import { CapabilitiesClient, type WorldCapabilities } from '../capabilities-api.js';
import {
  buildClock,
  buildPalette,
  buildRail,
  type ActionBinding,
  type ActionHost,
  type Palette,
} from '../ui/actions/surfaces.js';
import { button, toastStack } from '../ui/system/components.js';
import type { Layout } from '../ui/system/layout.js';
import type { PeopleControls } from './environment-selection.js';
import { operationAvailability } from '../ui/actions/registry.js';
import type { ObjectOperation } from '../ui/object-placement.js';
import type { PeopleOperation } from '../ui/world-inhabitants.js';
import { PLAYBACK_SPEEDS, type SocietyPlaybackSpeed } from '../society-control-api.js';

export interface MountActionsDeps {
  readonly layout: Layout;
  readonly credentials: TransportOptions;
  readonly worldId: string | null;
  /** The version the open world's saved entry points at now; it moves with every saved change. */
  readonly versionId: () => string | null;
  readonly bindings: Readonly<Record<string, ActionBinding>>;
  readonly people: PeopleControls;
  /** Where the clock sits in the top bar; it is inserted before this node. */
  readonly clockSlot: HTMLElement | null;
  /** Where the palette's button sits in the top bar; it is inserted before this node. */
  readonly searchSlot: HTMLElement | null;
}

/** The writes the objects panel offers, by the route each performs. */
const OBJECT_OPERATIONS: Readonly<Record<ObjectOperation, string>> = {
  place: 'POST /world/versions/{version_id}/compositions/apply',
  arrange: 'POST /world/versions/{version_id}/arrangements/apply',
  move: 'POST /world/versions/{version_id}/objects/{object_id}/move',
  remove: 'POST /world/versions/{version_id}/objects/{object_id}/remove',
  behaviour: 'POST /world/versions/{version_id}/objects/{object_id}/behaviour',
  undo: 'POST /world/versions/{version_id}/objects/undo',
};

/** The writes the People panel offers, by the route each performs. */
const PEOPLE_OPERATIONS: Readonly<Record<PeopleOperation, string>> = {
  create: 'POST /world/versions/{version_id}/society',
  presence: 'POST /world/versions/{version_id}/society/presence',
  control: 'PUT /world/versions/{version_id}/society/control',
  step: 'POST /world/versions/{version_id}/society/control/steps',
  direct: 'POST /world/versions/{version_id}/society/actions',
};

export interface MountedActions {
  readonly host: ActionHost;
  /**
   * Why the world refuses one of the objects panel's writes, in words, or null when it does not
   * (or when nothing has been read yet: the operation still decides when it runs).
   */
  objectGate(operation: ObjectOperation): string | null;
  /** The same, for the People panel's writes. */
  peopleGate(operation: PeopleOperation): string | null;
  readonly palette: Palette;
  /** Read the capabilities again (after a saved change). */
  refresh(): void;
  /** Tell every surface to redraw from the current state. */
  changed(): void;
  dispose(): void;
}

const CAPABILITY_RETRY_MS = 15_000;

export function mountActions(deps: MountActionsDeps): MountedActions {
  const client = deps.worldId === null ? null : new CapabilitiesClient({ ...deps.credentials, worldId: deps.worldId });
  let capabilities: WorldCapabilities | null = null;
  let disposed = false;
  let reading = 0;
  let retry: number | null = null;
  const listeners = new Set<() => void>();
  const changed = (): void => { for (const listener of listeners) listener(); };

  const read = async (): Promise<void> => {
    const versionId = deps.versionId();
    if (client === null || versionId === null || disposed) return;
    const ticket = ++reading;
    if (retry !== null) { window.clearTimeout(retry); retry = null; }
    try {
      const next = await client.version(versionId);
      if (disposed || ticket !== reading) return;
      capabilities = next;
    } catch {
      // A failed read leaves operations unknown rather than guessed; it is tried again.
      if (disposed || ticket !== reading) return;
      capabilities = null;
      retry = window.setTimeout(() => void read(), CAPABILITY_RETRY_MS);
    }
    changed();
  };

  /** Words for a write the world refuses now, or null (also before anything is read). */
  const refusedWords = (operation: string): string | null => {
    const found = operationAvailability(operation, capabilities);
    if (found.state === 'available' || found.state === 'unknown' || found.words === null) return null;
    return `${found.words.happened} ${found.words.next}`;
  };

  const toasts = toastStack();
  const host: ActionHost = {
    binding: (id) => deps.bindings[id],
    capabilities: () => capabilities,
    onChange: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    toasts,
  };

  const rail = buildRail(host);
  const palette = buildPalette(host);
  const clock = buildClock(host, () => {
    const now = deps.people.clock();
    return {
      present: now.society === 'present',
      minute: now.minute,
      mode: now.mode,
      speed: now.speed,
      speeds: PLAYBACK_SPEEDS,
    };
  }, (speed) => void deps.people.setSpeed(speed as SocietyPlaybackSpeed));

  deps.layout.place('tool-rail', rail.root);
  deps.layout.place('toast', toasts.root);
  deps.layout.place('overlay', palette.root, { close: () => palette.close() });
  if (deps.clockSlot !== null) deps.clockSlot.before(clock.root);
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  const search = button({
    label: 'Search', icon: 'search', variant: 'quiet', shortcut: mac ? '⌘K' : 'Ctrl K', className: 'x-search-actions',
    onClick: () => palette.open(),
  });
  search.setAttribute('aria-label', 'Search actions');
  if (deps.searchSlot !== null) deps.searchSlot.before(search);
  const releaseLayout = deps.layout.onChange(changed);

  // The people arriving or leaving changes what the world offers (playback, steps, models).
  let society = deps.people.clock().society;
  const releasePeople = deps.people.onChange(() => {
    const now = deps.people.clock().society;
    if (now !== society) { society = now; void read(); }
    changed();
  });

  const onKey = (event: KeyboardEvent): void => {
    if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey) || event.altKey) return;
    event.preventDefault();
    if (palette.isOpen()) palette.close();
    else {
      if (document.pointerLockElement !== null) document.exitPointerLock();
      palette.open();
    }
  };
  window.addEventListener('keydown', onKey);

  void read();
  return {
    host,
    objectGate: (operation) => refusedWords(OBJECT_OPERATIONS[operation]),
    peopleGate: (operation) => refusedWords(PEOPLE_OPERATIONS[operation]),
    palette,
    refresh: () => void read(),
    changed,
    dispose() {
      disposed = true;
      if (retry !== null) window.clearTimeout(retry);
      window.removeEventListener('keydown', onKey);
      releasePeople();
      releaseLayout();
      search.remove();
      clock.root.remove();
      rail.dispose();
      clock.dispose();
      palette.dispose();
      listeners.clear();
    },
  };
}
