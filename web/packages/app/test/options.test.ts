// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildOptions } from '../src/ui/options.js';

describe('Options', () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it('shows only settings that emit a live preference change', () => {
    const onChange = vi.fn();
    const onPreview = vi.fn();
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange,
      onPreview,
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);

    const contrast = view.root.querySelector<HTMLSelectElement>('[aria-label="Contrast"]')!;
    contrast.value = 'high';
    contrast.dispatchEvent(new Event('change'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ contrast: 'high' }));

    expect(view.root.querySelector('[aria-label="World form"]')).toBeNull();
    expect(view.root.textContent).not.toContain('Blue Hour');

    const vitality = view.root.querySelector<HTMLInputElement>('[aria-label="Color vitality"]')!;
    expect(vitality).not.toBeNull();
    vitality.value = '0.4';
    vitality.dispatchEvent(new Event('input'));
    expect(onPreview).toHaveBeenLastCalledWith(expect.objectContaining({
      worldStyleParameters: expect.objectContaining({ vitality: 0.4 }),
    }));
    expect(view.root.textContent).toContain('Previewing · not saved');
    expect(view.root.textContent).toContain('Always protected');
    expect(view.root.textContent).toContain('upstream proposal service');
    expect(view.root.textContent).toContain('does not generate recipes');
    expect(view.root.querySelector('[aria-label="Surface finish"]')).not.toBeNull();
    [...view.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Apply world design')!
      .click();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      worldStyleParameters: expect.objectContaining({ vitality: 0.4 }),
    }));
    expect(view.root.textContent).toContain('Personal variation');

    const fieldOfView = view.root.querySelector<HTMLInputElement>('[aria-label="Field of view"]')!;
    fieldOfView.value = '82';
    fieldOfView.dispatchEvent(new Event('input'));
    expect(onPreview).toHaveBeenLastCalledWith(expect.objectContaining({ fieldOfView: 82 }));
    expect(onChange).not.toHaveBeenLastCalledWith(expect.objectContaining({ fieldOfView: 82 }));
    fieldOfView.dispatchEvent(new Event('change'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ fieldOfView: 82 }));

    const shape = view.root.querySelector<HTMLSelectElement>('[aria-label="Companion shape"]')!;
    shape.value = 'cloud';
    shape.dispatchEvent(new Event('change'));
    const color = view.root.querySelector<HTMLSelectElement>('[aria-label="Companion color"]')!;
    color.value = 'periwinkle';
    color.dispatchEvent(new Event('change'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      companionBody: 'cloud',
      companionColor: 'periwinkle',
    }));
  });

  it('keeps world edits as a reversible preview until explicitly applied', () => {
    const onPreview = vi.fn();
    const onWorldDiscard = vi.fn();
    const onChange = vi.fn();
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange,
      onPreview,
      onWorldDiscard,
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);

    const finish = view.root.querySelector<HTMLSelectElement>('[aria-label="Surface finish"]')!;
    finish.value = 'clear-lens';
    finish.dispatchEvent(new Event('change'));
    expect(onPreview).toHaveBeenLastCalledWith(expect.objectContaining({
      worldStyleParameters: expect.objectContaining({ 'surface-finish': 'clear-lens' }),
    }));
    expect(onChange).not.toHaveBeenCalled();

    [...view.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Undo preview')!
      .click();
    expect(onWorldDiscard).toHaveBeenCalledWith(DEFAULT_PREFERENCES);
    expect(view.preferences().worldStyleParameters['surface-finish']).toBe('source-paper');
    expect(view.root.textContent).toContain('Authored default');
  });

  it('reports whether a reviewed choice is durable without hiding the live device result', () => {
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    view.reportPersistence('saving');
    expect(view.root.textContent).toContain('Saving this reviewed choice');
    view.reportPersistence('failed');
    expect(view.root.textContent).toContain('Applied on this device, but not saved');
  });

  it('does not mark a world preview saved until backend authority accepts it', async () => {
    const onChange = vi.fn();
    const onWorldApply = vi.fn(async () => false);
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange,
      onWorldApply,
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    const vitality = view.root.querySelector<HTMLInputElement>('[aria-label="Color vitality"]')!;
    vitality.value = '0.4';
    vitality.dispatchEvent(new Event('input'));
    [...view.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Apply world design')!
      .click();
    await vi.waitFor(() => expect(onWorldApply).toHaveBeenCalledOnce());
    expect(onChange).not.toHaveBeenCalled();
    expect(view.root.textContent).toContain('Previewing · not saved');
  });

  it('renders immutable history, proposal provenance, and rollback as explicit actions', async () => {
    const onWorldRollback = vi.fn(async () => ({
      ...DEFAULT_PREFERENCES,
      worldStyleParameters: { ...DEFAULT_PREFERENCES.worldStyleParameters, vitality: 0.3 },
    }));
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onWorldRollback,
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    view.setWorldAuthority({
      state: 'ready',
      detail: 'Connected to immutable world style history.',
      currentVersionId: 'v1',
      revision: 1,
      provenance: 'settings by actor-1 · appearance-panel',
      warnings: ['Stored parameters were resolved through the reviewed fallback.'],
      versions: [
        { versionId: 'v0', label: 'Revision 0 · authored', current: false },
        { versionId: 'v1', label: 'Revision 1 · settings', current: true },
      ],
      proposal: {
        origin: 'companion',
        model: 'reviewed-personalizer-v1',
        promptVersion: 'world-style-v1',
        referenceCount: 2,
        refinesProposalId: 'proposal-0',
      },
    });
    expect(view.root.querySelector('.world-style-version')?.textContent)
      .toBe('Current revision 1');
    expect(view.root.textContent).toContain('settings by actor-1');
    expect(view.root.textContent).toContain('companion proposal ready for review');
    expect(view.root.textContent).toContain('2 provenance references');
    expect(view.root.textContent).toContain('Refines an earlier proposal');
    expect(view.root.querySelector('.world-style-proposal-review')?.textContent)
      .not.toContain('proposal-0');

    const history = view.root.querySelector<HTMLSelectElement>('[aria-label="World design history"]')!;
    history.value = 'v0';
    history.dispatchEvent(new Event('change'));
    [...view.root.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === 'Restore selected version')!
      .click();
    await vi.waitFor(() => expect(onWorldRollback).toHaveBeenCalledWith('v0'));
  });

  it('moves focus into the dialog and restores it on return', () => {
    const prior = document.createElement('button');
    document.body.append(prior);
    prior.focus();
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    view.setVisible(true);
    expect(view.root.hidden).toBe(false);
    expect(document.activeElement).toBe(view.root.querySelector('.overlay-close'));
    view.setVisible(false);
    expect(document.activeElement).toBe(prior);
  });

  it('restores focus after the shell releases an inert command surface', async () => {
    const commandSurface = document.createElement('nav');
    const prior = document.createElement('button');
    commandSurface.append(prior);
    document.body.append(commandSurface);
    prior.focus();
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    view.setVisible(true);

    const focus = prior.focus.bind(prior);
    let inert = true;
    vi.spyOn(prior, 'focus').mockImplementation(() => {
      if (!inert) focus();
    });
    view.setVisible(false);
    (document.activeElement as HTMLElement).blur();
    inert = false;
    await Promise.resolve();

    expect(document.activeElement).toBe(prior);
  });

  it('clears a failed lifecycle message when its preview is discarded', () => {
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    const vitality = view.root.querySelector<HTMLInputElement>('[aria-label="Color vitality"]')!;
    vitality.value = '0.4';
    vitality.dispatchEvent(new Event('input'));
    view.reportWorldLifecycle('failed', 'No durable change was made.');
    expect(view.root.textContent).toContain('No durable change was made.');

    [...view.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Undo preview')!
      .click();
    expect(view.root.textContent).not.toContain('No durable change was made.');
  });

  it('keeps Tab inside the modal without taking Escape', () => {
    const view = buildOptions({
      preferences: DEFAULT_PREFERENCES,
      onChange: vi.fn(),
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    view.setVisible(true);
    const focusable = [...view.root.querySelectorAll<HTMLElement>('button, input, select')];
    const first = focusable[0]!;
    const last = focusable.at(-1)!;
    last.focus();
    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    expect(document.activeElement).toBe(first);

    first.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Tab', shiftKey: true, bubbles: true,
    }));
    expect(document.activeElement).toBe(last);

    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(view.root.hidden).toBe(false);
  });

  it('restores the authored defaults as one preference object', () => {
    const onChange = vi.fn();
    const view = buildOptions({
      preferences: { ...DEFAULT_PREFERENCES, appearance: 'dawn', fieldOfView: 88 },
      onChange,
      onClose: vi.fn(),
      onShowControls: vi.fn(),
    });
    document.body.append(view.root);
    [...view.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Restore defaults')!
      .click();
    expect(onChange).toHaveBeenLastCalledWith(DEFAULT_PREFERENCES);
  });
});
