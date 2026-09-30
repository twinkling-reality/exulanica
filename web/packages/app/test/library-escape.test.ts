// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ALL_FACETS } from '@exulanica/world-index';
import { mountInputModes, type InputModeDependencies } from '../src/composition/input-modes.js';
import { buildWorldIndex } from '../src/ui/world-index.js';
import { FirstPersonControls } from '../../atlas-react/src/playcanvas/controls.js';

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

describe('pointer dismissal of the Companion', () => {
  it('lets a world tap close the current conversation layer', () => {
    const canvas = document.createElement('canvas');
    const requestPointerLock = vi.fn();
    canvas.requestPointerLock = requestPointerLock;
    const controls = new FirstPersonControls(canvas, { x: 0, y: 2, z: 0, yaw: 0, pitch: 0 });
    controls.setEnabled(false);
    const dismiss = vi.fn(() => controls.setEnabled(true));
    const closeEvidence = vi.fn().mockReturnValueOnce(true).mockReturnValue(false);
    const resolveEvidenceAt = vi.fn();
    const state = { mountListeners: null, indexFacets: ALL_FACETS, selected: null };
    const mounted = mountInputModes({
      env: { canvas, systemAppearance: new EventTarget() },
      state,
      snapshot: { occurrences: [] },
      atlas: { binding: { controls: { mode: 'converse' }, mapOverlay: null, releaseFocusedAnchor: vi.fn() } },
      companion: { panel: { state: () => 'open', closeEvidence }, dismiss },
      status: { inspectorRoot: { hidden: false }, resolveEvidenceAt },
      chrome: { setMode: vi.fn() },
      worldIndex: buildWorldIndex({ onEntity: vi.fn(), onOccurrence: vi.fn(), onSearch: vi.fn() }),
      firstUse: { prompt: () => null, observeMode: vi.fn() },
      shellState: () => ({ primary: 'world', camera: 'ground', detailId: null }),
      dispatchShell: vi.fn(), setInputMode: vi.fn(), reflectFirstUse: vi.fn(),
    } as unknown as InputModeDependencies);
    const tap = () => {
      canvas.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true }));
      canvas.dispatchEvent(new PointerEvent('pointerup', { button: 0, bubbles: true }));
      canvas.dispatchEvent(new MouseEvent('click', { button: 0, bubbles: true }));
    };
    tap();
    expect(closeEvidence).toHaveBeenCalledOnce();
    expect(dismiss).not.toHaveBeenCalled();
    tap();
    expect(dismiss).toHaveBeenCalledOnce();
    expect(resolveEvidenceAt).not.toHaveBeenCalled();
    expect(requestPointerLock).not.toHaveBeenCalled();
    mounted.dispose();
    controls.destroy();
  });
});
