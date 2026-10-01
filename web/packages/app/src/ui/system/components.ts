/**
 * The component layer: plain DOM factories over tokens.css and components.css.
 *
 * A surface asks for a role (a primary button, a status line, a state chip) and gets the one look
 * that role has everywhere. Nothing here knows a route, a code or a world; words are passed in.
 */
import { el } from '../dom.js';
import { createModalFocus } from '../modal-focus.js';
import { icon, type IconName, type IconSize } from './icon.js';

// -- Button ---------------------------------------------------------------------------------------

/**
 * `primary` is the one main action in view, `secondary` the others, `quiet` a text-weight action,
 * `danger` an action that cannot be taken back.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonOptions {
  readonly label: string;
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
  readonly icon?: IconName;
  /** The key that also runs it, shown as its own badge, never typed into the label. */
  readonly shortcut?: string;
  readonly type?: 'button' | 'submit';
  readonly block?: boolean;
  readonly className?: string;
  readonly onClick?: (event: MouseEvent) => void;
}

export function button(options: ButtonOptions): HTMLButtonElement {
  const node = el('button', {
    type: options.type ?? 'button',
    class: ['x-btn', options.className].filter(Boolean).join(' '),
    'data-variant': options.variant ?? 'secondary',
    'data-size': options.size ?? 'md',
    'data-block': options.block === true,
  });
  if (options.icon !== undefined) node.append(iconSlot(options.icon, options.size));
  node.append(el('span', { class: 'x-btn-label', text: options.label }));
  if (options.shortcut !== undefined) {
    node.append(el('kbd', { class: 'x-shortcut', 'aria-hidden': 'true', text: options.shortcut }));
    node.setAttribute('aria-keyshortcuts', options.shortcut);
  }
  if (options.onClick !== undefined) node.addEventListener('click', options.onClick);
  return node;
}

export interface IconButtonOptions extends Omit<ButtonOptions, 'icon' | 'block'> {
  readonly icon: IconName;
}

/** An icon-only button. Its label is its accessible name and its tooltip. */
export function iconButton(options: IconButtonOptions): HTMLButtonElement {
  const node = el('button', {
    type: options.type ?? 'button',
    class: ['x-btn', 'x-icon-btn', options.className].filter(Boolean).join(' '),
    'data-variant': options.variant ?? 'quiet',
    'data-size': options.size ?? 'md',
    'aria-label': options.label,
    title: options.shortcut === undefined ? options.label : `${options.label} (${options.shortcut})`,
  });
  node.append(iconSlot(options.icon, options.size));
  if (options.shortcut !== undefined) node.setAttribute('aria-keyshortcuts', options.shortcut);
  if (options.onClick !== undefined) node.addEventListener('click', options.onClick);
  return node;
}

/** Change a button's words without rebuilding it (the icon and badge stay). */
export function setButtonLabel(node: HTMLButtonElement, label: string): void {
  const slot = node.querySelector('.x-btn-label');
  if (slot !== null) slot.textContent = label;
  else node.setAttribute('aria-label', label);
}

/**
 * Busy: the button keeps its words, shows a turning icon and refuses a second press. Nothing is
 * said to have happened while it is busy; the caller says so from the receipt.
 */
export function setButtonBusy(node: HTMLButtonElement, busy: boolean): void {
  if (busy) node.setAttribute('aria-busy', 'true');
  else node.removeAttribute('aria-busy');
  node.disabled = busy;
  const existing = node.querySelector<SVGElement>('.x-btn-icon');
  if (busy && existing === null) {
    node.prepend(iconSlot('busy', (node.dataset['size'] as ButtonSize | undefined) ?? 'md', true));
  } else if (!busy && existing?.dataset['transient'] === 'busy') {
    existing.remove();
  }
}

function iconSlot(name: IconName, size: ButtonSize | undefined, transient = false): SVGElement {
  const glyph = icon(name, iconSizeFor(size));
  glyph.classList.add('x-btn-icon');
  if (transient) glyph.dataset['transient'] = 'busy';
  return glyph;
}

function iconSizeFor(size: ButtonSize | undefined): IconSize {
  return size === 'lg' ? 'md' : 'sm';
}

// -- Toolbar --------------------------------------------------------------------------------------

/**
 * A group of controls that is one tab stop: arrow keys move between its items, Home and End jump.
 */
export function toolbar(options: {
  readonly label: string;
  readonly orientation?: 'horizontal' | 'vertical';
  readonly className?: string;
  readonly items?: readonly HTMLElement[];
}): HTMLElement {
  const orientation = options.orientation ?? 'horizontal';
  const root = el('div', {
    class: ['x-toolbar', options.className].filter(Boolean).join(' '),
    role: 'toolbar',
    'aria-label': options.label,
    'aria-orientation': orientation,
  }, [...(options.items ?? [])]);
  const items = (): HTMLElement[] => [...root.querySelectorAll<HTMLElement>('button, select, input')]
    .filter((item) => !(item as HTMLButtonElement).disabled && item.getClientRects().length > 0);
  const roam = (): void => {
    const all = items();
    const current = all.find((item) => item.tabIndex === 0) ?? all[0];
    for (const item of all) item.tabIndex = item === current ? 0 : -1;
  };
  root.addEventListener('focusin', (event) => {
    if (!(event.target instanceof HTMLElement)) return;
    for (const item of items()) item.tabIndex = item === event.target ? 0 : -1;
  });
  root.addEventListener('keydown', (event) => {
    const forward = orientation === 'horizontal' ? 'ArrowRight' : 'ArrowDown';
    const back = orientation === 'horizontal' ? 'ArrowLeft' : 'ArrowUp';
    if (![forward, back, 'Home', 'End'].includes(event.key)) return;
    if (event.target instanceof HTMLSelectElement || event.target instanceof HTMLInputElement) return;
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (at < 0 || all.length === 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? all.length - 1
        : (at + (event.key === forward ? 1 : -1) + all.length) % all.length;
    all[next]!.focus();
  });
  queueMicrotask(roam);
  return root;
}

export function toolbarSeparator(): HTMLElement {
  return el('span', { class: 'x-toolbar-separator', role: 'separator' });
}

// -- Panel ----------------------------------------------------------------------------------------

export interface Panel {
  readonly root: HTMLElement;
  readonly header: HTMLElement;
  readonly title: HTMLHeadingElement;
  readonly body: HTMLElement;
  readonly footer: HTMLElement;
  readonly close: HTMLButtonElement;
}

/**
 * A panel: header with icon, title and close; a body that scrolls; a footer for its actions. It
 * does not position itself: the layout puts it in a region (ui/system/layout.ts).
 */
export function panel(options: {
  readonly id: string;
  readonly title: string;
  readonly icon?: IconName;
  readonly closeLabel?: string;
  readonly onClose?: () => void;
  readonly className?: string;
  readonly role?: 'region' | 'dialog';
}): Panel {
  const titleId = `${options.id}-title`;
  const title = el('h2', { class: 'x-panel-title', id: titleId, text: options.title });
  const close = iconButton({
    icon: 'close', label: options.closeLabel ?? 'Close', size: 'sm', className: 'x-panel-close',
  });
  if (options.onClose !== undefined) close.addEventListener('click', options.onClose);
  const header = el('header', { class: 'x-panel-header' }, [
    ...(options.icon === undefined ? [] : [icon(options.icon)]),
    title,
    close,
  ]);
  const body = el('div', { class: 'x-panel-body' });
  const footer = el('footer', { class: 'x-panel-footer', hidden: true });
  const root = el('section', {
    class: ['x-surface', 'x-panel', options.className].filter(Boolean).join(' '),
    id: options.id,
    role: options.role ?? 'region',
    'aria-labelledby': titleId,
  }, [header, body, footer]);
  return { root, header, title, body, footer, close };
}

// -- Dialog -------------------------------------------------------------------------------------

export interface Dialog extends Panel {
  open(): void;
  dismiss(): void;
  readonly isOpen: () => boolean;
}

/**
 * A modal panel: focus moves in and is kept there (modal-focus.ts), Escape closes it, and focus
 * returns to what opened it. Where it sits is the layout's choice, like any panel.
 */
export function dialog(options: {
  readonly id: string;
  readonly title: string;
  readonly icon?: IconName;
  readonly closeLabel?: string;
  readonly onClose?: () => void;
  readonly className?: string;
}): Dialog {
  const parts = panel({ ...options, role: 'dialog', onClose: () => dismiss() });
  parts.root.setAttribute('aria-modal', 'true');
  parts.root.hidden = true;
  const focus = createModalFocus(parts.root, parts.close);
  const dismiss = (): void => {
    if (parts.root.hidden) return;
    focus.setVisible(false);
    options.onClose?.();
  };
  parts.root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    dismiss();
  });
  return {
    ...parts,
    open() {
      focus.setVisible(true);
      const first = parts.body.querySelector<HTMLElement>('button, select, input, textarea, [tabindex="0"]');
      first?.focus({ preventScroll: true });
    },
    dismiss,
    isOpen: () => !parts.root.hidden,
  };
}

// -- State chip -----------------------------------------------------------------------------------

/**
 * The states the interface keeps distinct (ui-backend-boundary.md). Each has one look and one
 * default word; a surface may pass more precise words, never a raw code.
 */
export type InterfaceState =
  | 'available' | 'unavailable' | 'unsupported' | 'not-permitted' | 'unknown'
  | 'queued' | 'running' | 'ready' | 'failed' | 'stale' | 'cancelled' | 'partial';

type Tone = 'neutral' | 'accent' | 'positive' | 'caution' | 'danger' | 'info';

export const STATE_LOOK: Readonly<Record<InterfaceState, { tone: Tone; icon: IconName | null; words: string }>> = {
  available: { tone: 'positive', icon: 'ready', words: 'Available' },
  unavailable: { tone: 'caution', icon: 'warning', words: 'Unavailable' },
  unsupported: { tone: 'neutral', icon: null, words: 'Not in this world' },
  'not-permitted': { tone: 'neutral', icon: 'locked', words: 'Not allowed' },
  unknown: { tone: 'neutral', icon: null, words: 'Can’t tell yet' },
  queued: { tone: 'info', icon: 'waiting', words: 'Waiting' },
  running: { tone: 'info', icon: 'busy', words: 'Working' },
  ready: { tone: 'positive', icon: 'ready', words: 'Ready' },
  failed: { tone: 'danger', icon: 'failed', words: 'Failed' },
  stale: { tone: 'caution', icon: 'warning', words: 'Out of date' },
  cancelled: { tone: 'neutral', icon: 'cancelled', words: 'Cancelled' },
  partial: { tone: 'caution', icon: 'warning', words: 'Partly done' },
};

export function stateChip(state: InterfaceState, words?: string): HTMLElement {
  const look = STATE_LOOK[state];
  return el('span', { class: 'x-chip', 'data-tone': look.tone, 'data-state': state }, [
    ...(look.icon === null ? [] : [icon(look.icon, 'sm')]),
    words ?? look.words,
  ]);
}

// -- Status line ----------------------------------------------------------------------------------

export type StatusTone = 'neutral' | 'positive' | 'caution' | 'danger' | 'info';

const TONE_ICON: Readonly<Record<StatusTone, IconName | null>> = {
  neutral: null, positive: 'ready', caution: 'warning', danger: 'failed', info: 'info',
};

export interface StatusLine {
  readonly root: HTMLElement;
  say(message: string, tone?: StatusTone): void;
  clear(): void;
}

/** One status line per surface: a polite live region whose words replace, never stack. */
export function statusLine(className?: string): StatusLine {
  const root = el('p', {
    class: ['x-status', className].filter(Boolean).join(' '),
    role: 'status',
    'aria-live': 'polite',
    hidden: true,
  });
  return {
    root,
    say(message, tone = 'neutral') {
      // The same words again are not news: leave the region alone so it is not announced twice.
      if (root.dataset['tone'] === tone && root.textContent === message && root.hidden === (message.length === 0)) return;
      const glyph = TONE_ICON[tone];
      root.replaceChildren(...(glyph === null ? [] : [icon(glyph, 'sm')]), el('span', { text: message }));
      root.dataset['tone'] = tone;
      root.hidden = message.length === 0;
    },
    clear() {
      root.replaceChildren();
      root.hidden = true;
    },
  };
}

// -- Toast ----------------------------------------------------------------------------------------

export interface ToastOptions {
  readonly message: string;
  readonly tone?: StatusTone;
  /** One follow-up, such as Undo, run from the toast itself. */
  readonly action?: { readonly label: string; readonly run: () => void };
  /** Milliseconds; failures default to staying until dismissed or replaced. */
  readonly durationMs?: number | null;
}

export interface ToastStack {
  readonly root: HTMLElement;
  show(options: ToastOptions): HTMLElement;
  clear(): void;
}

const TOAST_LIMIT = 3;
const TOAST_DURATION_MS = 4000;

/** The one place short notices and receipts appear. Newest first, at most three. */
export function toastStack(): ToastStack {
  const root = el('div', { class: 'x-toast-stack', role: 'status', 'aria-live': 'polite' });
  const dismiss = (toast: HTMLElement): void => { toast.remove(); };
  return {
    root,
    show(options) {
      const tone = options.tone ?? 'neutral';
      const glyph = TONE_ICON[tone] ?? 'info';
      const toast = el('div', { class: 'x-toast x-surface', 'data-tone': tone }, [
        icon(glyph),
        el('p', { class: 'x-toast-message', text: options.message }),
      ]);
      if (options.action !== undefined) {
        const { label, run } = options.action;
        toast.append(button({ label, variant: 'quiet', size: 'sm', onClick: () => { dismiss(toast); run(); } }));
      }
      toast.append(iconButton({ icon: 'close', label: 'Dismiss', size: 'sm', onClick: () => dismiss(toast) }));
      root.prepend(toast);
      while (root.children.length > TOAST_LIMIT) root.lastElementChild?.remove();
      const duration = options.durationMs === undefined
        ? (tone === 'danger' ? null : TOAST_DURATION_MS)
        : options.durationMs;
      if (duration !== null) window.setTimeout(() => dismiss(toast), duration);
      return toast;
    },
    clear() { root.replaceChildren(); },
  };
}

// -- Tabs -----------------------------------------------------------------------------------------

export interface Tabs {
  readonly root: HTMLElement;
  select(id: string): void;
  readonly selected: () => string;
}

export function tabs(options: {
  readonly label: string;
  readonly items: readonly { readonly id: string; readonly label: string; readonly panel: HTMLElement }[];
  readonly onSelect?: (id: string) => void;
}): Tabs {
  const list = el('div', { class: 'x-tabs', role: 'tablist', 'aria-label': options.label });
  let current = options.items[0]?.id ?? '';
  const buttons = new Map<string, HTMLButtonElement>();
  for (const item of options.items) {
    const tab = el('button', {
      type: 'button', class: 'x-tab', role: 'tab', id: `${item.id}-tab`,
      'aria-controls': item.id, text: item.label,
    });
    item.panel.id = item.id;
    item.panel.setAttribute('role', 'tabpanel');
    item.panel.setAttribute('aria-labelledby', `${item.id}-tab`);
    tab.addEventListener('click', () => select(item.id));
    buttons.set(item.id, tab);
    list.append(tab);
  }
  list.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const ids = options.items.map((item) => item.id);
    const at = ids.indexOf(current);
    const next = ids[(at + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length]!;
    event.preventDefault();
    select(next);
    buttons.get(next)?.focus();
  });
  const select = (id: string): void => {
    current = id;
    for (const item of options.items) {
      const on = item.id === id;
      const tab = buttons.get(item.id)!;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      item.panel.hidden = !on;
    }
    options.onSelect?.(id);
  };
  select(current);
  return { root: list, select, selected: () => current };
}

// -- Tooltip --------------------------------------------------------------------------------------

/**
 * A tooltip on hover and focus. It repeats words that are also the control's accessible name; it
 * is never the only place a word lives.
 */
export function tooltip(target: HTMLElement, text: string): () => void {
  let tip: HTMLElement | null = null;
  const show = (): void => {
    if (tip !== null) return;
    tip = el('div', { class: 'x-tooltip', role: 'tooltip', text });
    document.body.append(tip);
    const box = target.getBoundingClientRect();
    const own = tip.getBoundingClientRect();
    const left = Math.min(Math.max(8, box.left + box.width / 2 - own.width / 2), window.innerWidth - own.width - 8);
    const above = box.top - own.height - 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${above >= 8 ? above : box.bottom + 8}px`;
  };
  const hide = (): void => { tip?.remove(); tip = null; };
  const listeners = new AbortController();
  for (const [type, run] of [['pointerenter', show], ['focus', show], ['pointerleave', hide], ['blur', hide]] as const) {
    target.addEventListener(type, run, { signal: listeners.signal });
  }
  return () => { hide(); listeners.abort(); };
}

// -- Field ----------------------------------------------------------------------------------------

let fieldCount = 0;

export interface Field {
  readonly root: HTMLElement;
  setError(message: string | null): void;
}

/** A labelled control with an optional hint and an error line; the label is always visible. */
export function field(options: {
  readonly label: string;
  readonly control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
  readonly hint?: string;
}): Field {
  fieldCount += 1;
  const id = options.control.id || `x-field-${fieldCount}`;
  options.control.id = id;
  if (options.control instanceof HTMLSelectElement) options.control.classList.add('x-select');
  else options.control.classList.add('x-input');
  const hint = options.hint === undefined
    ? null
    : el('span', { class: 'x-field-hint', id: `${id}-hint`, text: options.hint });
  const error = el('span', { class: 'x-field-error', id: `${id}-error`, role: 'alert', hidden: true });
  const describedBy = [hint?.id, error.id].filter(Boolean).join(' ');
  options.control.setAttribute('aria-describedby', describedBy);
  const root = el('div', { class: 'x-field' }, [
    el('label', { class: 'x-field-label', for: id, text: options.label }),
    options.control,
    ...(hint === null ? [] : [hint]),
    error,
  ]);
  return {
    root,
    setError(message) {
      error.textContent = message ?? '';
      error.hidden = message === null;
      options.control.toggleAttribute('aria-invalid', message !== null);
    },
  };
}

/** A checkbox with its words beside it. */
export function checkbox(options: { readonly label: string; readonly checked?: boolean }): {
  readonly root: HTMLLabelElement;
  readonly input: HTMLInputElement;
} {
  const input = el('input', { type: 'checkbox' }) as HTMLInputElement;
  input.checked = options.checked === true;
  return { root: el('label', { class: 'x-check' }, [input, el('span', { text: options.label })]), input };
}

// -- Empty and error states -----------------------------------------------------------------------

export function emptyState(options: {
  readonly title: string;
  readonly body?: string;
  readonly icon?: IconName;
  readonly action?: HTMLElement;
}): HTMLElement {
  return el('div', { class: 'x-empty' }, [
    ...(options.icon === undefined ? [] : [icon(options.icon, 'lg')]),
    el('p', { class: 'x-empty-title', text: options.title }),
    ...(options.body === undefined ? [] : [el('p', { class: 'x-empty-body', text: options.body })]),
    ...(options.action === undefined ? [] : [options.action]),
  ]);
}

/** The technical record of a refusal: codes and server detail, closed by default and copyable. */
export interface TechnicalRecord {
  readonly code?: string | null;
  readonly detail?: string | null;
  readonly [key: string]: string | number | null | undefined;
}

/**
 * A failure as a person reads it: what happened, then what to do next. A raw code or server detail
 * goes only into the technical record; the two sentences never contain it.
 */
export function errorState(options: {
  readonly happened: string;
  readonly next?: string;
  readonly action?: HTMLElement;
  readonly technical?: TechnicalRecord;
}): HTMLElement {
  const root = el('div', { class: 'x-error', role: 'alert' }, [
    icon('failed', 'lg'),
    el('p', { class: 'x-error-title', text: options.happened }),
    ...(options.next === undefined ? [] : [el('p', { class: 'x-error-next', text: options.next })]),
    ...(options.action === undefined ? [] : [options.action]),
  ]);
  if (options.technical !== undefined) root.append(technicalRecord(options.technical));
  return root;
}

export function technicalRecord(record: TechnicalRecord): HTMLElement {
  const lines = Object.entries(record)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}: ${String(value)}`);
  return el('details', { class: 'x-technical' }, [
    el('summary', { text: 'Technical details' }),
    el('pre', { text: lines.join('\n') }),
  ]);
}
