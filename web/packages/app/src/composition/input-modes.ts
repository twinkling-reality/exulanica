/**
 * The two input modes, the one key that calls the Companion, and every listener a mount owns.
 *
 * The mode follows the browser's pointer lock state and is never guessed at: the browser drops
 * the lock on Escape and on focus loss without telling the application first, so a mode the
 * application tracked itself would be wrong within seconds of the user tabbing away.
 *
 * **Every listener here hangs off one AbortController held in session state.** `mount` runs again
 * after every committed write and again on a hot reload, and a listener added without one of
 * these survives the mount that added it. Two of them turn one key press into two toggles, which
 * is a summon immediately undone by a dismiss and looks exactly like a key that does nothing.
 * That is why the canvas listeners live here rather than beside the surfaces that use them: the
 * inspector is rebuilt on each mount and the old one is simply discarded, so a listener
 * registered beside it would outlive its owner.
 */

import type { GraphSnapshot } from '@exulanica/graph-client';
import { decodeFacets } from '@exulanica/world-index';

import type { MountedAtlas } from '../atlas.js';
import type { AtlasCommand } from '../ui/atlas-commands.js';
import type { buildDetail } from '../ui/detail.js';
import type { FirstUseGuidance, FirstUseMode } from '../ui/first-use-guidance.js';
import type { MapPeek } from '../ui/map-peek.js';
import type { WorldChrome } from '../ui/world-chrome.js';
import type { buildWorldIndex } from '../ui/world-index.js';
import { commandForKeystroke, type WorldShellEvent, type WorldShellState } from '../world-shell.js';
import type { MountedCompanion } from './companion.js';
import type { AppEnvironment, SessionState } from './session-state.js';
import type { MountedStatusAndInspector } from './status-and-inspector.js';

export interface InputModeDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly snapshot: GraphSnapshot;
  readonly atlas: MountedAtlas;
  readonly companion: MountedCompanion;
  readonly status: MountedStatusAndInspector;
  readonly chrome: WorldChrome;
  readonly worldIndex: ReturnType<typeof buildWorldIndex>;
  readonly detail: ReturnType<typeof buildDetail>;
  readonly mapPeek: MapPeek;
  readonly firstUse: FirstUseGuidance;
  /** The shell state, read fresh: it changes under this module rather than being owned by it. */
  readonly shellState: () => WorldShellState;
  readonly dispatchShell: (event: WorldShellEvent) => void;
  readonly handleAtlasCommand: (command: AtlasCommand) => void;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
  readonly travelUsesReducedMotion: () => boolean;
  readonly setInputMode: (mode: FirstUseMode) => void;
  readonly reflectFirstUse: () => void;
  readonly applyPreferences: (next: SessionState['preferences']) => void;
}

export interface MountedInputModes {
  dispose(): void;
}

/**
 * Drop the previous mount's listeners.
 *
 * Also runs on the empty-world path, which binds nothing new: a keydown handler that survived
 * would still be acting on a shell whose children have been replaced.
 */
export function disposeMountListeners(state: SessionState): void {
  state.mountListeners?.abort();
  state.mountListeners = null;
}

export function mountInputModes(deps: InputModeDependencies): MountedInputModes {
  const { env, state, atlas: mounted, companion, status } = deps;
  const current = deps.snapshot;

  mounted.binding.onInspectionChange = (view) => {
    if (view === null) status.hideInspector();
  };
  mounted.binding.mapOverlay?.setActive(deps.shellState().camera === 'map');
  mounted.binding.onMapTarget = (islandId) => {
    const resolution = mounted.binding.navigateToIsland(islandId, deps.travelUsesReducedMotion());
    if (!resolution.ok) {
      deps.showTravelStatus('No safe arrival point is available in that region.', 'failure');
      return;
    }
    deps.dispatchShell({ type: 'show-world' });
    deps.showTravelStatus(deps.travelUsesReducedMotion() ? 'Located the region.' : 'Moving to the region…');
  };
  mounted.binding.onNavigationArrive = (target) => {
    if (target.kind === 'anchor') {
      const index = mounted.binding.table.indexOf.get(target.anchorId);
      if (index !== undefined) mounted.binding.focusAnchor(index);
    }
    deps.showTravelStatus(target.kind === 'anchor' ? 'Located the source.' : 'The memory is in focus.');
  };

  function reflectMode(next: 'traverse' | 'converse'): void {
    deps.setInputMode(next);
    deps.chrome.setMode(next);
    if (next === 'traverse') mounted.binding.releaseFocusedAnchor();
    if (next === 'traverse' && (deps.shellState().primary !== 'world' || deps.shellState().camera !== 'ground')) {
      deps.dispatchShell({ type: 'show-world' });
    }
    // The prompt says what is true right now. With the mouse free the useful instruction is how
    // to get into the world; once inside it is how to call the Companion. An open conversation
    // outranks both and is left alone.
    if (companion.panel.state() === 'open') return;
    companion.panel.setState(next === 'traverse' ? 'summon' : 'enter');
    deps.firstUse.observeMode(next);
    deps.reflectFirstUse();
  }
  mounted.binding.controls.onModeChange = reflectMode;
  reflectMode(mounted.binding.controls.mode);

  mounted.binding.controls.onSummon = () => companion.toggle();
  mounted.binding.controls.onInteract = () => {
    const index = mounted.binding.engageFocusedAnchor();
    if (index === null) return;
    const anchor = mounted.binding.table.anchors[index];
    const occurrence = anchor === undefined
      ? undefined
      : current.occurrences.find((value) => value.occurrenceId === anchor.occurrenceId);
    if (occurrence === undefined) {
      mounted.binding.releaseFocusedAnchor();
      deps.showTravelStatus('This memory reference is unavailable.', 'failure');
      return;
    }
    state.selected = occurrence.occurrenceId;
    deps.detail.showOccurrence(occurrence);
    deps.worldIndex.render(current, state.indexFacets, state.selected);
    if (deps.shellState().primary !== 'index') deps.dispatchShell({ type: 'toggle-index' });
    deps.dispatchShell({ type: 'show-detail', id: occurrence.occurrenceId });
  };

  disposeMountListeners(state);
  state.mountListeners = new AbortController();
  const signal = state.mountListeners.signal;
  /*
   * CLICK-TO-EVIDENCE, bound here and not beside the function that resolves it.
   *
   * The listener is on the shared world canvas, which the inspector does not own, so it has to
   * hang off `mountListeners` like every other listener outside a mounted element.
   *
   * Guarded on the inspector being open, so traverse is untouched: while traversing,
   * `inspectionView` is null and `resolveEvidenceAt` returns before reading anything.
   * `pointerup` rather than `pointerdown`, so a drag that happens to end over the canvas is not
   * taken as a click on a surface the visitor never pointed at.
   */
  env.canvas.addEventListener(
    'pointerup',
    (event) => {
      if (event.button !== 0 || status.inspectorRoot.hidden) return;
      status.resolveEvidenceAt(event.clientX, event.clientY);
    },
    { signal },
  );
  env.canvas.addEventListener(
    'webglcontextlost',
    (event) => {
      event.preventDefault();
      deps.dispatchShell({ type: 'show-index' });
      deps.showTravelStatus(
        'The 3D renderer became unavailable. The complete World Index remains available.',
        'failure',
      );
    },
    { signal },
  );
  window.addEventListener(
    'keydown',
    (event) => {
      const target = event.target;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable);
      /*
       * Escape steps back by exactly one, and only once the browser has finished with it.
       *
       * While the pointer is locked Escape belongs to the user agent: it releases the mouse and
       * we neither see nor want it, which is the rule the renderer controls are built around.
       * Released, it has no browser job left, and the key everyone already tries for "out of
       * this" becomes the way out. One press, one level: the exchange, then the entry, then the
       * plate. Backspace keeps its meaning for people who learned it, but nobody guesses it.
       */
      if (event.code === 'Escape' && document.pointerLockElement === null) {
        // Search is the innermost thing open, so it is the first thing Escape takes back.
        if (deps.shellState().primary === 'index' && deps.worldIndex.closeSearch()) {
          event.preventDefault();
          return;
        }
        if (companion.panel.state() === 'open') {
          event.preventDefault();
          companion.dismiss();
          return;
        }
        if (deps.shellState().detailId !== null) {
          event.preventDefault();
          deps.dispatchShell({ type: 'close-detail' });
          return;
        }
        if (deps.shellState().primary !== 'world') {
          event.preventDefault();
          deps.dispatchShell({ type: 'show-world' });
          return;
        }
      }
      const command = commandForKeystroke({
        code: event.code,
        key: event.key,
        modified: event.altKey || event.ctrlKey || event.metaKey,
        typing,
      });
      if (
        !typing && companion.panel.state() === 'open' &&
        !event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyE'
      ) {
        if (companion.panel.openEvidence()) {
          event.preventDefault();
          return;
        }
      }
      if (
        !typing && deps.shellState().primary === 'index' &&
        !event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyS'
      ) {
        event.preventDefault();
        deps.worldIndex.focusSearch();
        return;
      }
      if (command === 'toggle-index') {
        event.preventDefault();
        deps.handleAtlasCommand('index');
        return;
      }
      if (command === 'toggle-map') {
        event.preventDefault();
        // Tap or hold is decided on the way back up, so the key does nothing yet.
        deps.mapPeek.press();
        return;
      }
      if (command === 'toggle-options') {
        event.preventDefault();
        deps.handleAtlasCommand('options');
        return;
      }
      if (command === 'toggle-controls') {
        event.preventDefault();
        deps.handleAtlasCommand('controls');
        return;
      }
      if (command === 'selection-back' && deps.shellState().detailId !== null) {
        event.preventDefault();
        deps.dispatchShell({ type: 'close-detail' });
        return;
      }
      // Not while the user is typing an answer into the Companion or a name into the index.
      if (typing) return;
      // Answering by number, which is the only way to answer while the pointer is locked: there
      // is no cursor to click with, and releasing the lock to reply would mean leaving the world
      // for every question. Unavailable options return null and the key does nothing, rather than
      // selecting the next one along and committing something nobody chose.
      if (/^Digit[1-9]$/.test(event.code)) {
        if (companion.panel.pressNumber(Number(event.code.slice(5)))) event.preventDefault();
        return;
      }
    },
    { signal },
  );
  window.addEventListener(
    'keyup',
    (event: KeyboardEvent) => {
      if (event.code === 'KeyM') deps.mapPeek.release();
    },
    { signal },
  );
  // A hold that loses the window never receives its keyup, and a look must not become a journey.
  window.addEventListener('blur', () => deps.mapPeek.abort(), { signal });
  window.addEventListener(
    'popstate',
    () => {
      state.indexFacets = decodeFacets(window.location.search);
      deps.worldIndex.render(current, state.indexFacets, state.selected);
    },
    { signal },
  );
  env.systemAppearance.addEventListener(
    'change',
    () => deps.applyPreferences(state.preferences),
    { signal },
  );

  return { dispose: () => disposeMountListeners(state) };
}
