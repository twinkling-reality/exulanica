// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildCharacterStudio } from '../src/ui/character-studio.js';
import type { CharacterLook } from '../src/character-catalog.js';

const look = (lookId: string): CharacterLook => ({ lookId, label: lookId, file: `${lookId}.glb`, creator: 'Artist', license: 'CC0',
  defaultColors: { Fabric: '#704090' }, descriptor: {} as CharacterLook['descriptor'] });
function setup() {
  const handlers = { onClose: vi.fn(), onPreview: vi.fn(), onApply: vi.fn(), onRotate: vi.fn(), onZoom: vi.fn(), onMotion: vi.fn(), onGestures: vi.fn(), onRetry: vi.fn() };
  const view = buildCharacterStudio(handlers);
  const opener = document.createElement('button');
  document.body.replaceChildren(opener, view.root);
  opener.focus();
  view.setVisible(true);
  view.setCatalog([look('first'), look('second')], { lookId: 'first', appearance: {} });
  const button = (text: string) => [...view.root.querySelectorAll('button')].find(node => node.textContent === text)!;
  return { handlers, view, opener, button };
}
describe('Character studio', () => {
  it('keeps edits in the preview until Use in world and sends only the selected look and supported color', () => {
    const { view, handlers, button } = setup();
    button('Use in world').click();
    expect(handlers.onApply).not.toHaveBeenCalled();
    view.setStatus('Ready', true);
    button('second').click();
    expect(handlers.onPreview).toHaveBeenLastCalledWith({ lookId: 'second', appearance: {} });
    button('Style').click();
    const color = view.root.querySelector<HTMLInputElement>('input[type=color]')!;
    color.value = '#246880'; color.dispatchEvent(new Event('input'));
    expect(handlers.onApply).not.toHaveBeenCalled();
    button('Use in world').click();
    expect(handlers.onApply).toHaveBeenCalledWith({ lookId: 'second', appearance: { colors: { Fabric: '#246880' } } });
  });
  it('offers recovery and other looks after a load failure, but cannot apply failed bytes', () => {
    const { view, handlers, button } = setup();
    view.setFailure('Character unavailable');
    expect(button('Use in world').disabled).toBe(true);
    button('Try again').click();
    expect(handlers.onRetry).toHaveBeenCalledOnce();
    button('second').click();
    expect(handlers.onPreview).toHaveBeenCalled();
  });
  it('returns focus, contains Tab, and skips motion when reduced motion is selected', () => {
    const { view, handlers, opener, button } = setup();
    view.setStatus('Ready', true);
    const zoom = view.root.querySelector<HTMLInputElement>('[aria-label="Character zoom"]')!;
    zoom.focus(); zoom.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(button('← Return'));
    view.setReducedMotion(true);
    expect(button('Walking').disabled).toBe(true);
    button('Walking').click();
    expect(handlers.onMotion).not.toHaveBeenCalled();
    view.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(handlers.onClose).toHaveBeenCalledOnce();
    view.setVisible(false);
    expect(document.activeElement).toBe(opener);
  });
});

describe('character creation flow', () => {
  it('starts with body editing, separates premade people, and keeps color choices when a body is regenerated', () => {
    const { view, handlers, button } = setup();
    const base = { ...look('human'), familyId: 'human/v1', recipe: { heightCm: 175 } };
    view.setBodyFamily({ familyId: 'human/v1', label: 'Human', choices: [], controls: [
      { key: 'heightCm', label: 'Height', group: 'Body', min: 145, max: 205, default: 175, step: 1 },
    ] });
    view.setCatalog([base, look('Hoodie')], { lookId: 'human', appearance: {} });
    view.setStatus('Ready', true);
    expect(button('Body').getAttribute('aria-pressed')).toBe('true');
    expect(button('Hoodie').closest('details')?.open).toBe(false);
    const height = view.root.querySelector<HTMLInputElement>('[aria-label="Height"]')!;
    height.value = '192'; height.dispatchEvent(new Event('input'));
    button('Next: Face →').click();
    expect(button('Face').getAttribute('aria-pressed')).toBe('true');
    expect(view.root.textContent).toContain('cannot scan your face');
    expect(view.root.querySelector('input[type=file]')).toBeNull();
    button('Style').click();
    const color = view.root.querySelector<HTMLInputElement>('input[type=color]')!;
    color.value = '#246880'; color.dispatchEvent(new Event('input'));
    button('Reset colors').click();
    expect(view.root.querySelector<HTMLInputElement>('[aria-label="Height"]')!.value).toBe('192');
    expect(button('Use in world').disabled).toBe(true);
    const updatedColor = view.root.querySelector<HTMLInputElement>('input[type=color]')!;
    updatedColor.value = '#246880'; updatedColor.dispatchEvent(new Event('input'));
    updatedColor.focus();
    view.showGenerated({ ...base, lookId: 'new-body', recipe: { heightCm: 192 } });
    expect(document.activeElement).toBe(updatedColor);
    expect(view.root.querySelector('[aria-label="Height"]')).toBe(height);
    view.setStatus('Ready', true);
    expect(button('Style').getAttribute('aria-pressed')).toBe('true');
    button('Use in world').click();
    expect(handlers.onApply).toHaveBeenLastCalledWith({ lookId: 'new-body', appearance: { colors: { Fabric: '#246880' } } });
  });
});

it('keeps controls live during fitting, blocks stale application, and preserves draft/retry after failure', () => {
  const { view, handlers, button } = setup();
  const base = { ...look('human'), familyId: 'human/v1', recipe: { heightCm: 175 } };
  view.setBodyFamily({ familyId: 'human/v1', label: 'Human', choices: [], controls: [
    { key: 'heightCm', label: 'Height', group: 'Body', min: 145, max: 205, default: 175, step: 1 },
  ] });
  view.setCatalog([base], { lookId: 'human', appearance: {} });
  view.setStatus('Ready', true);
  const height = view.root.querySelector<HTMLInputElement>('[aria-label="Height"]')!;
  height.value = '190'; height.dispatchEvent(new Event('input'));
  view.setBodyUpdating();
  expect(view.root.querySelector<HTMLFieldSetElement>('.character-editor')!.disabled).toBe(false);
  expect(view.root.querySelector('.character-fitting')?.textContent).toContain('Refitting your character');
  expect(view.root.querySelector('.character-fitting')?.hasAttribute('hidden')).toBe(false);
  expect(view.canvas.getAttribute('aria-busy')).toBe('true');
  expect(view.root.dataset['fitting']).toBe('true');
  expect(button('Use in world').disabled).toBe(true);
  height.value = '180'; height.dispatchEvent(new Event('input'));
  view.setFailure('Fitting unavailable');
  expect(view.root.querySelector('.character-fitting')?.hasAttribute('hidden')).toBe(true);
  expect(view.canvas.getAttribute('aria-busy')).toBe('false');
  button('Style').click();
  const color = view.root.querySelector<HTMLInputElement>('input[type=color]')!;
  color.value = '#246880'; color.dispatchEvent(new Event('input'));
  view.setStatus('Color updated', true);
  expect(button('Try again').hidden).toBe(false);
  expect(button('Use in world').disabled).toBe(true);
  expect(view.root.querySelector<HTMLInputElement>('[aria-label="Height"]')!.value).toBe('180');
  button('Try again').click(); expect(handlers.onRetry).toHaveBeenCalled();
  view.setCatalog([base], { lookId: 'human', appearance: {} });
  view.setStatus('Reopened applied character', true);
  expect(view.root.querySelector('.character-fitting')?.hasAttribute('hidden')).toBe(true);
  expect(button('Use in world').disabled).toBe(false);
});
