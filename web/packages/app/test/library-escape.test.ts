// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ALL_FACETS } from '@exulanica/world-index';
import { mountInputModes, type InputModeDependencies } from '../src/composition/input-modes.js';
import { buildWorldIndex } from '../src/ui/world-index.js';

const pressEscape = (): void => {
  (document.activeElement ?? window).dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }),
  );
};

afterEach(() => {
  document.body.replaceChildren();
});

describe('Escape from the Library', () => {
  it('closes the Library in one press, but first leaves a search the person opened', () => {
    Object.defineProperty(document, 'pointerLockElement', { configurable: true, value: null });
    const worldIndex = buildWorldIndex({
      onEntity: vi.fn(), onOccurrence: vi.fn(), onSearch: vi.fn(),
    });
    document.body.append(worldIndex.root);
    const dispatchShell = vi.fn();
    const state = { mountListeners: null, indexFacets: ALL_FACETS, selected: null };
    const binding = {
      controls: { mode: 'converse' }, mapOverlay: null,
      releaseFocusedAnchor: vi.fn(),
    };
    const mounted = mountInputModes({
      env: { canvas: document.createElement('canvas'), systemAppearance: new EventTarget() },
      state,
      snapshot: { occurrences: [] },
      atlas: { binding },
      companion: { panel: { state: () => 'enter', setState: vi.fn() } },
      status: { inspectorRoot: { hidden: true } },
      chrome: { setMode: vi.fn() },
      worldIndex,
      firstUse: { prompt: () => null, observeMode: vi.fn() },
      shellState: () => ({ primary: 'index', camera: 'ground', detailId: null }),
      dispatchShell,
      setInputMode: vi.fn(), reflectFirstUse: vi.fn(),
    } as unknown as InputModeDependencies);

    pressEscape();
    expect(dispatchShell).toHaveBeenCalledOnce();
    expect(dispatchShell).toHaveBeenCalledWith({ type: 'step-back' });

    dispatchShell.mockClear();
    worldIndex.focusSearch();
    expect(document.activeElement).toBe(worldIndex.root.querySelector('input[type=search]'));
    pressEscape();
    expect(dispatchShell).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(worldIndex.root.querySelector('.index-close'));
    pressEscape();
    expect(dispatchShell).toHaveBeenCalledOnce();
    expect(dispatchShell).toHaveBeenCalledWith({ type: 'step-back' });
    mounted.dispose();
  });
});
