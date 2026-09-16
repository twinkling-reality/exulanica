// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildCharacterBody, type BodyFamily } from '../src/ui/character-body.js';
const family: BodyFamily = { familyId: 'test/v1', label: 'Human', controls: [
  { key: 'heightCm', label: 'Height', group: 'Body', min: 145, max: 205, default: 175, step: 1, unit: 'cm' },
], choices: [{ key: 'hair', label: 'Hair', default: 'none', options: [{ value: 'none', label: 'No hair' }] }] };
describe('editable body controls', () => {
  it('requests a full updated recipe as soon as a control changes', () => {
    const generate = vi.fn(), dirty = vi.fn();
    const view = buildCharacterBody(generate, dirty);
    view.setFamily(family);
    const slider = view.root.querySelector('input')!;
    slider.value = '192'; slider.dispatchEvent(new Event('input'));
    expect(dirty).toHaveBeenCalledOnce();
    expect(generate).toHaveBeenCalledWith({ heightCm: 192, hair: 'none' });
    view.setRecipe({ heightCm: 160, hair: 'none' });
    expect(view.root.querySelector('input')!.value).toBe('160');
  });
  it('does not offer a non-working build when the adapter is unavailable', () => {
    const generate = vi.fn();
    const view = buildCharacterBody(generate, vi.fn());
    view.setFamily(family); view.setUnavailable();
    const slider = view.root.querySelector('input')!;
    slider.value = '190'; slider.dispatchEvent(new Event('input'));
    expect(generate).not.toHaveBeenCalled();
    expect(view.root.textContent).toContain('unavailable');
  });
});

describe('one character across creation steps', () => {
  it('changes starting shape without replacing measurements, face or clothing and retains edits across steps', () => {
    const generate = vi.fn();
    const view = buildCharacterBody(generate, vi.fn());
    view.setFamily({ ...family, presets: [{ label: 'Female', recipe: { gender: 0 } }, { label: 'Male', recipe: { gender: 1 } }],
      controls: [...family.controls,
        { key: 'gender', label: 'Body shape', group: 'Body', min: 0, max: 1, default: .5, step: .05 },
        { key: 'nose', label: 'Nose width', group: 'Face', min: -.5, max: .5, default: 0, step: .05 }],
    });
    view.setRecipe({ heightCm: 192, gender: .5, nose: .2, hair: 'none' });
    [...view.root.querySelectorAll('button')].find(b => b.textContent === 'Female')!.click();
    view.setStep('face');
    expect(view.sections.body.hidden).toBe(true);
    expect(view.sections.face.hidden).toBe(false);
    expect(view.root.querySelector<HTMLInputElement>('[aria-label="Nose width"]')!.value).toBe('0.2');
    view.setStep('style');
    expect(view.sections.style.hidden).toBe(false);
    view.setStep('body');
    expect(view.root.querySelector('button')?.textContent).not.toBe('Update character');
    expect(generate).toHaveBeenCalledWith({ heightCm: 192, gender: 0, nose: .2, hair: 'none' });
  });
});
