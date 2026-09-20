/**
 * The Atlas shell state, separate from DOM and renderer concerns.
 *
 * Pointer lock still owns the input mode. This state only answers which product surface is
 * occupying the live world and which camera presentation is active. Keeping those answers in one
 * reducer prevents Index, Options, Map and an orphaned detail pane from independently claiming the
 * same pixels.
 */

export type PrimarySurface =
  | 'world' | 'menu' | 'index' | 'options' | 'controls' | 'character' | 'experiment' | 'photos';
export type CameraPresentation = 'ground' | 'map';

export interface WorldSurfaceContext {
  readonly primary: PrimarySurface;
  readonly camera: CameraPresentation;
  /** A detail belongs to the Index. It is illegal on every other primary surface. */
  readonly detailId: string | null;
}

export interface WorldShellState extends WorldSurfaceContext {
  /** Temporary major surfaces unwind in order, preserving the exact prior product context. */
  readonly returnStack: readonly WorldSurfaceContext[];
}

export type WorldShellEvent =
  | { readonly type: 'toggle-menu' }
  | { readonly type: 'toggle-character' }
  | { readonly type: 'toggle-index' }
  | { readonly type: 'toggle-map' }
  | { readonly type: 'toggle-options' }
  | { readonly type: 'toggle-controls' }
  | { readonly type: 'toggle-experiment' }
  | { readonly type: 'toggle-photos' }
  | { readonly type: 'show-index' }
  | { readonly type: 'show-world' }
  | { readonly type: 'show-detail'; readonly id: string }
  | { readonly type: 'close-detail' }
  | { readonly type: 'step-back' };

export type WorldCommand =
  | 'toggle-menu'
  | 'toggle-character'
  | 'toggle-index'
  | 'toggle-map'
  | 'toggle-options'
  | 'toggle-controls'
  | 'selection-back';

export interface CommandKeystroke {
  readonly code: string;
  readonly key: string;
  readonly modified: boolean;
  readonly typing: boolean;
}

export function initialWorldShell(): WorldShellState {
  return Object.freeze({
    primary: 'world',
    camera: 'ground',
    detailId: null,
    returnStack: Object.freeze([]),
  });
}

/** One transition function is the collision policy. */
export function updateWorldShell(
  state: WorldShellState,
  event: WorldShellEvent,
): WorldShellState {
  switch (event.type) {
    case 'toggle-menu':
      return state.primary === 'menu'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'menu', camera: 'ground', detailId: null });
    case 'toggle-character':
      return state.primary === 'character'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'character', camera: 'ground', detailId: null });
    case 'toggle-index':
      return state.primary === 'index'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'index', camera: 'ground', detailId: null });
    case 'toggle-map':
      return state.camera === 'map'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'world', camera: 'map', detailId: null });
    case 'toggle-options':
      if (state.primary === 'options') return restoreSurface(state);
      if (state.primary === 'controls') return Object.freeze({ ...state, primary: 'options' });
      return openTemporarySurface(state, { primary: 'options', camera: 'ground', detailId: null });
    case 'toggle-controls':
      if (state.primary === 'controls') return restoreSurface(state);
      if (state.primary === 'options') return Object.freeze({ ...state, primary: 'controls' });
      return openTemporarySurface(state, { primary: 'controls', camera: 'ground', detailId: null });
    case 'toggle-experiment':
      return state.primary === 'experiment'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'experiment', camera: 'ground', detailId: null });
    case 'toggle-photos':
      return state.primary === 'photos'
        ? restoreSurface(state)
        : openTemporarySurface(state, { primary: 'photos', camera: 'ground', detailId: null });
    case 'show-world':
      return initialWorldShell();
    case 'show-index':
      return Object.freeze({
        primary: 'index', camera: 'ground', detailId: null, returnTo: null,
        returnStack: Object.freeze([]),
      });
    case 'show-detail':
      return state.primary === 'index'
        ? Object.freeze({ ...state, detailId: event.id })
        : state;
    case 'close-detail':
      return state.detailId === null ? state : Object.freeze({ ...state, detailId: null });
    case 'step-back':
      return restoreSurface(state);
  }
}

function openTemporarySurface(
  state: WorldShellState,
  next: WorldSurfaceContext,
): WorldShellState {
  const current: WorldSurfaceContext = Object.freeze({
    primary: state.primary,
    camera: state.camera,
    detailId: state.detailId,
  });
  return Object.freeze({
    ...next,
    returnStack: Object.freeze([...state.returnStack, current]),
  });
}

function restoreSurface(state: WorldShellState): WorldShellState {
  const prior = state.returnStack.at(-1);
  return prior === undefined
    ? initialWorldShell()
    : Object.freeze({
        ...prior,
        returnStack: Object.freeze(state.returnStack.slice(0, -1)),
      });
}

/**
 * Resolve only shell-owned keys. World verbs stay in the renderer controls and dialogue number
 * keys stay in the Companion surface. Modified shortcuts and editable controls always keep their
 * native/browser meaning.
 */
export function commandForKeystroke(stroke: CommandKeystroke): WorldCommand | null {
  if (stroke.modified || stroke.typing) return null;
  switch (stroke.code) {
    case 'KeyH':
      return 'toggle-menu';
    case 'KeyK':
      return 'toggle-character';
    case 'KeyI':
      return 'toggle-index';
    case 'KeyM':
      return 'toggle-map';
    case 'KeyO':
      return 'toggle-options';
    case 'Backspace':
      return 'selection-back';
    default:
      return stroke.key === '?' ? 'toggle-controls' : null;
  }
}
