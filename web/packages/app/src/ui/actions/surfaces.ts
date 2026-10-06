/**
 * The surfaces that render the action registry: the tool rail, the world clock in the top bar and
 * the command palette. None of them declares an action; each draws the registry's entries for its
 * placement, with the state the host reports, and runs them through one path.
 *
 * One path: an action that is not available is not run; its words are shown. An available action
 * runs through its binding; while it runs its control is busy and nothing is said to have happened.
 * A refusal it meets is shown as the action's words for that code, with the code and the server's
 * detail only in the technical record.
 */

import { ApiError } from '@exulanica/graph-client';
import type { OperationDescriptors } from '../../capabilities-api.js';
import { el } from '../dom.js';
import {
  button,
  iconButton,
  setButtonBusy,
  stateChip,
  technicalRecord,
  toolbar,
  type ToastStack,
} from '../system/components.js';
import { icon } from '../system/icon.js';
import type { PlannedRequest } from './planned.js';
import {
  ACTIONS,
  actionsFor,
  actionSpec,
  availability,
  GROUP_LABEL,
  refusalWords,
  type ActionAvailability,
  type ActionGroup,
  type ActionSpec,
  type RefusalWords,
} from './registry.js';

export interface ActionBinding {
  run(): void | Promise<void>;
  /** Whether this world offers the action at all (photos only where a world takes photographs). */
  offered?(): boolean;
  /** Whether the surface the action opens is open now. */
  active?(): boolean;
  /** A precondition in the domain's own words (pause before advancing a minute), or null. */
  blocked?(): string | null;
}

export interface ActionHost {
  binding(id: string): ActionBinding | undefined;
  /** The descriptors read so far: the open version's and the workspace's creation ones. */
  capabilities(): OperationDescriptors | null;
  /** Called when the capabilities or the state an action reads changed; returns the unsubscribe. */
  onChange(listener: () => void): () => void;
  readonly toasts: ToastStack;
  /** Sends a request a Companion plan step was built into (`planned.ts`); absent, none is sent. */
  /** Sends a planned step's request; resolves to the status it got and its body. */
  readonly send?: (request: PlannedRequest) => Promise<{ readonly status: number; readonly body: unknown }>;
}

/** What a control for this action should show now. */
export function actionState(host: ActionHost, spec: ActionSpec): ActionAvailability & { readonly blocked: string | null } {
  const found = availability(spec, host.capabilities());
  const blocked = found.state === 'available' ? host.binding(spec.id)?.blocked?.() ?? null : null;
  return { ...found, blocked };
}

const offered = (host: ActionHost, spec: ActionSpec): boolean => {
  const binding = host.binding(spec.id);
  if (binding === undefined || binding.offered?.() === false) return false;
  // A world that never supports the operation does not offer the action in the rail or bar.
  return availability(spec, host.capabilities()).state !== 'unsupported';
};

/** Run one action through the one path. Resolves when its binding has settled. */
export async function perform(host: ActionHost, id: string, control?: HTMLButtonElement): Promise<void> {
  const spec = actionSpec(id);
  const binding = host.binding(id);
  if (binding === undefined) return;
  const state = actionState(host, spec);
  if (state.state !== 'available' || state.blocked !== null) {
    const words = state.words;
    host.toasts.show({
      tone: state.state === 'available' ? 'info' : 'caution',
      message: state.blocked ?? (words === null ? spec.hint : `${words.happened} ${words.next}`),
    });
    return;
  }
  if (control !== undefined) setButtonBusy(control, true);
  try {
    await binding.run();
  } catch (error) {
    const code = error instanceof ApiError ? error.code : null;
    const detail = error instanceof ApiError
      ? error.message.replace(`${error.code}: `, '')
      : error instanceof Error ? error.message : String(error);
    const words = refusalWords(spec, code);
    const toast = host.toasts.show({ tone: 'danger', message: `${words.happened} ${words.next}` });
    toast.querySelector('.x-toast-message')?.after(technicalRecord({ action: spec.id, code, detail }));
  } finally {
    if (control !== undefined) setButtonBusy(control, false);
  }
}

/** What sending one planned step came to. */
export type PlannedResult =
  /** Sent, and the route answered with this status and body. */
  | { readonly kind: 'ran'; readonly status: number; readonly response: unknown }
  /** Sent, and the route refused: its status where it answered, its code, and the action's words. */
  | {
    readonly kind: 'refused'; readonly status: number | null; readonly code: string | null;
    readonly detail: string; readonly words: RefusalWords;
  }
  /** Not sent: the action is not available now, in the action's words for why. */
  | { readonly kind: 'not-run'; readonly state: string; readonly code: string | null; readonly words: RefusalWords };

/**
 * Send one Companion plan step through the same path as the action's own control: the same
 * availability (the descriptor's, read in the same order), the same busy state on its control and
 * the same words for a refusal. It differs in two ways only. The request is the plan's, built
 * by `plannedRequest` from the registry entry, so the server's stale checks see the pins the
 * person confirmed; and the binding's own precondition is not asked, because a plan carries the
 * clock read its bases came from (a chain pauses before it advances). It shows no toast: the
 * plan's sheet says each step's result, and the caller decides whether a chain goes on.
 */
export async function performPlanned(
  host: ActionHost, request: PlannedRequest, control?: HTMLButtonElement,
): Promise<PlannedResult> {
  const spec = actionSpec(request.actionId);
  const found = availability(spec, host.capabilities());
  if (found.state !== 'available' || host.send === undefined) {
    return {
      kind: 'not-run', state: found.state, code: found.code,
      words: found.words ?? { happened: 'This step was not sent.', next: 'Nothing was changed.' },
    };
  }
  if (control !== undefined) setButtonBusy(control, true);
  try {
    const sent = await host.send(request);
    return { kind: 'ran', status: sent.status, response: sent.body };
  } catch (error) {
    const code = error instanceof ApiError ? error.code : null;
    const detail = error instanceof ApiError
      ? error.message.replace(`${error.code}: `, '')
      : error instanceof Error ? error.message : String(error);
    const status = error instanceof ApiError ? error.status : null;
    return { kind: 'refused', status, code, detail, words: refusalWords(spec, code) };
  } finally {
    if (control !== undefined) setButtonBusy(control, false);
  }
}

function reflectControl(host: ActionHost, spec: ActionSpec, control: HTMLButtonElement): void {
  const state = actionState(host, spec);
  const binding = host.binding(spec.id);
  const reason = state.blocked ?? (state.words === null ? null : `${state.words.happened} ${state.words.next}`);
  control.disabled = control.getAttribute('aria-busy') === 'true'
    || (state.state !== 'available' && state.state !== 'unknown') || state.blocked !== null;
  control.dataset['state'] = state.state;
  control.title = reason === null ? spec.hint : reason;
  if (binding?.active !== undefined) control.setAttribute('aria-pressed', binding.active() ? 'true' : 'false');
}

// -- The tool rail --------------------------------------------------------------------------------

const RAIL_GROUPS: readonly ActionGroup[] = ['build', 'people', 'ask', 'explore'];

export interface ActionSurface {
  readonly root: HTMLElement;
  refresh(): void;
  dispose(): void;
}

export function buildRail(host: ActionHost): ActionSurface {
  const root = toolbar({ label: 'Tools', orientation: 'vertical', className: 'x-rail x-surface' });
  root.setAttribute('role', 'toolbar');
  const controls = new Map<ActionSpec, HTMLButtonElement>();
  const draw = (): void => {
    root.replaceChildren();
    controls.clear();
    for (const group of RAIL_GROUPS) {
      const specs = actionsFor('rail').filter((spec) => spec.group === group && offered(host, spec));
      if (specs.length === 0) continue;
      root.append(el('p', { class: 'x-rail-group-label', 'aria-hidden': 'true', text: GROUP_LABEL[group] }));
      for (const spec of specs) {
        const item = el('button', {
          type: 'button', class: 'x-rail-item', 'data-action': spec.id,
          'aria-label': spec.shortcut === undefined ? spec.label : `${spec.label} (${spec.shortcut})`,
          ...(spec.shortcut === undefined ? {} : { 'aria-keyshortcuts': spec.shortcut }),
        }, [icon(spec.icon), el('span', { text: spec.label })]);
        item.addEventListener('click', () => void perform(host, spec.id, item));
        controls.set(spec, item);
        root.append(item);
      }
    }
  };
  const refresh = (): void => {
    const shown = actionsFor('rail').filter((spec) => offered(host, spec));
    if (shown.length !== controls.size || shown.some((spec) => !controls.has(spec))) draw();
    for (const [spec, control] of controls) reflectControl(host, spec, control);
  };
  draw();
  refresh();
  const release = host.onChange(refresh);
  return { root, refresh, dispose: release };
}

// -- The world clock (top bar) ----------------------------------------------------------------------

export interface ClockFace {
  /** `null` when this world has no clock to show (no saved society connected yet). */
  readonly minute: number | null;
  readonly mode: 'paused' | 'playing' | null;
  readonly speed: number | null;
  readonly speeds: readonly number[];
  readonly present: boolean;
}

export function buildClock(host: ActionHost, face: () => ClockFace, setSpeed: (speed: number) => void): ActionSurface {
  const minute = el('span', { class: 'x-clock-minute', role: 'status', 'aria-live': 'off' });
  const toggle = iconButton({ icon: 'play', label: 'Play', variant: 'quiet' });
  const advance = button({ label: 'Next minute', icon: 'next-minute', variant: 'quiet', size: 'sm' });
  const speed = el('select', { class: 'x-select x-clock-speed', 'aria-label': 'Speed' }) as HTMLSelectElement;
  const root = toolbar({ label: 'World clock', className: 'x-clock', items: [minute, toggle, advance, speed] });
  toggle.addEventListener('click', () => void perform(host, face().mode === 'playing' ? 'clock.pause' : 'clock.play', toggle));
  advance.addEventListener('click', () => void perform(host, 'clock.advance', advance));
  speed.addEventListener('change', () => setSpeed(Number(speed.value)));
  const refresh = (): void => {
    const now = face();
    root.hidden = !now.present;
    if (!now.present) return;
    minute.replaceChildren(stateChip(now.mode === 'playing' ? 'running' : 'queued',
      now.minute === null ? 'Clock' : `Minute ${now.minute}`));
    const playing = now.mode === 'playing';
    const playSpec = actionSpec(playing ? 'clock.pause' : 'clock.play');
    toggle.replaceChildren(icon(playing ? 'pause' : 'play'));
    toggle.setAttribute('aria-label', playSpec.label);
    reflectControl(host, playSpec, toggle);
    reflectControl(host, actionSpec('clock.advance'), advance);
    if (speed.options.length !== now.speeds.length) {
      speed.replaceChildren(...now.speeds.map((value) => el('option', { value: String(value), text: `${value}× speed` })));
    }
    if (now.speed !== null) speed.value = String(now.speed);
    speed.disabled = now.mode === null;
  };
  refresh();
  const release = host.onChange(refresh);
  return { root, refresh, dispose: release };
}

// -- The command palette ------------------------------------------------------------------------------

export interface Palette extends ActionSurface {
  open(): void;
  close(): void;
  readonly isOpen: () => boolean;
}

/**
 * Every action in one searchable list (Ctrl or Cmd K). Actions this world does not offer are listed
 * last, muted, with why; nothing is hidden from someone looking for it.
 */
export function buildPalette(host: ActionHost): Palette {
  const input = el('input', {
    type: 'search', class: 'x-input x-palette-input', placeholder: 'Search actions',
    'aria-label': 'Search actions', autocomplete: 'off', role: 'combobox', 'aria-expanded': 'true',
    'aria-controls': 'x-palette-list',
  }) as HTMLInputElement;
  const list = el('ul', { class: 'x-palette-list', id: 'x-palette-list', role: 'listbox', 'aria-label': 'Actions' });
  const root = el('section', {
    class: 'x-palette x-surface', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Actions', hidden: true,
  }, [el('div', { class: 'x-palette-search' }, [icon('search'), input]), list]);
  let restore: HTMLElement | null = null;
  let active = 0;
  let rows: { spec: ActionSpec; node: HTMLElement; ready: boolean }[] = [];

  const close = (): void => {
    if (root.hidden) return;
    root.hidden = true;
    if (restore?.isConnected === true) restore.focus({ preventScroll: true });
  };
  const choose = (spec: ActionSpec): void => {
    close();
    void perform(host, spec.id);
  };
  const render = (): void => {
    const query = input.value.trim().toLowerCase();
    const matches = ACTIONS.filter((spec) => host.binding(spec.id) !== undefined
      && host.binding(spec.id)?.offered?.() !== false
      && (query === '' || `${spec.label} ${spec.hint} ${GROUP_LABEL[spec.group]}`.toLowerCase().includes(query)));
    const ranked = matches.map((spec) => ({ spec, state: actionState(host, spec) }))
      .sort((a, b) => Number(a.state.state === 'unsupported') - Number(b.state.state === 'unsupported'));
    rows = ranked.map(({ spec, state }, index) => {
      const ready = state.state === 'available' && state.blocked === null;
      const reason = state.blocked ?? (state.words === null ? null : state.words.happened);
      const node = el('li', {
        class: 'x-palette-row', role: 'option', id: `x-palette-${index}`,
        'aria-selected': 'false', 'aria-disabled': ready ? 'false' : 'true', 'data-action': spec.id,
      }, [
        icon(spec.icon),
        el('span', { class: 'x-palette-text' }, [
          el('span', { class: 'x-palette-label', text: spec.label }),
          el('span', { class: 'x-palette-hint', text: reason ?? spec.hint }),
        ]),
        ...(ready ? [] : [stateChip(state.blocked !== null ? 'unavailable' : state.state)]),
        ...(spec.shortcut === undefined ? [] : [el('kbd', { class: 'x-shortcut', text: spec.shortcut })]),
      ]);
      // Keep focus in the search field, so pressing a row never blurs the palette closed first.
      node.addEventListener('mousedown', (event) => event.preventDefault());
      node.addEventListener('click', () => choose(spec));
      node.addEventListener('pointermove', () => select(index));
      return { spec, node, ready };
    });
    list.replaceChildren(...rows.map((row) => row.node));
    if (rows.length === 0) list.append(el('li', { class: 'x-palette-empty', text: 'No action matches that.' }));
    select(Math.min(active, Math.max(rows.length - 1, 0)));
  };
  const select = (index: number): void => {
    active = index;
    rows.forEach((row, at) => row.node.setAttribute('aria-selected', at === index ? 'true' : 'false'));
    const chosen = rows[index];
    if (chosen === undefined) input.removeAttribute('aria-activedescendant');
    else {
      input.setAttribute('aria-activedescendant', chosen.node.id);
      chosen.node.scrollIntoView({ block: 'nearest' });
    }
  };
  input.addEventListener('input', () => { active = 0; render(); });
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return; }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (rows.length > 0) select((active + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const chosen = rows[active];
      if (chosen !== undefined) choose(chosen.spec);
      return;
    }
    if (event.key === 'Tab') event.preventDefault();
  });
  root.addEventListener('focusout', (event) => {
    if (event.relatedTarget instanceof Node && root.contains(event.relatedTarget)) return;
    if (!root.hidden) window.setTimeout(() => { if (!root.contains(document.activeElement)) close(); });
  });
  const release = host.onChange(() => { if (!root.hidden) render(); });
  return {
    root,
    refresh: render,
    dispose: release,
    open() {
      restore = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      input.value = '';
      active = 0;
      root.hidden = false;
      render();
      input.focus({ preventScroll: true });
    },
    close,
    isOpen: () => !root.hidden,
  };
}

