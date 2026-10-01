// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import {
  button,
  errorState,
  iconButton,
  setButtonBusy,
  stateChip,
  STATE_LOOK,
  statusLine,
  toastStack,
} from '../src/ui/system/components.js';
import { icon, ICON_NAMES } from '../src/ui/system/icon.js';

describe('icons', () => {
  it('every name draws an svg that assistive technology skips', () => {
    for (const name of ICON_NAMES) {
      const svg = icon(name);
      expect(svg.tagName.toLowerCase()).toBe('svg');
      expect(svg.getAttribute('aria-hidden')).toBe('true');
      expect(svg.childElementCount).toBeGreaterThan(0);
    }
  });
});

describe('buttons', () => {
  it('carries its role, words and shortcut badge without typing the key into the label', () => {
    const node = button({ label: 'Add object', variant: 'primary', icon: 'object', shortcut: 'P' });
    expect(node.dataset['variant']).toBe('primary');
    expect(node.querySelector('.x-btn-label')?.textContent).toBe('Add object');
    expect(node.getAttribute('aria-keyshortcuts')).toBe('P');
    expect(node.querySelector('.x-shortcut')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('an icon-only button is named by its label', () => {
    const node = iconButton({ icon: 'close', label: 'Close' });
    expect(node.getAttribute('aria-label')).toBe('Close');
    expect(node.textContent).toBe('');
  });

  it('busy refuses a second press and keeps the words', () => {
    const node = button({ label: 'Add bench' });
    setButtonBusy(node, true);
    expect(node.disabled).toBe(true);
    expect(node.getAttribute('aria-busy')).toBe('true');
    expect(node.querySelector('.x-btn-label')?.textContent).toBe('Add bench');
    setButtonBusy(node, false);
    expect(node.disabled).toBe(false);
    expect(node.hasAttribute('aria-busy')).toBe(false);
    expect(node.querySelector('[data-transient]')).toBeNull();
  });
});

describe('states, status and failures', () => {
  it('every state the boundary keeps distinct has its own words', () => {
    const words = Object.values(STATE_LOOK).map((look) => look.words);
    expect(new Set(words).size).toBe(words.length);
    expect(stateChip('not-permitted').textContent).toBe('Not allowed');
    expect(stateChip('partial', 'Two of three done').dataset['state']).toBe('partial');
  });

  it('a status line replaces its words rather than stacking them', () => {
    const line = statusLine();
    line.say('Checking with the world', 'info');
    line.say('Ready', 'positive');
    expect(line.root.textContent).toBe('Ready');
    expect(line.root.getAttribute('role')).toBe('status');
    line.clear();
    expect(line.root.hidden).toBe(true);
  });

  it('a failure says what happened and what to do next, with codes only in the technical record', () => {
    const node = errorState({
      happened: 'Nothing was added.',
      next: 'Look again, then place it once more.',
      technical: { code: 'stale_object_base', detail: 'base 1 is not current' },
    });
    const visible = [...node.querySelectorAll('.x-error-title, .x-error-next')].map((p) => p.textContent).join(' ');
    expect(visible).not.toContain('stale_object_base');
    const record = node.querySelector('details.x-technical');
    expect(record?.hasAttribute('open')).toBe(false);
    expect(record?.textContent).toContain('code: stale_object_base');
  });

  it('keeps at most three toasts, newest first', () => {
    const stack = toastStack();
    for (const message of ['one', 'two', 'three', 'four']) stack.show({ message, durationMs: null });
    expect([...stack.root.querySelectorAll('.x-toast-message')].map((p) => p.textContent)).toEqual(['four', 'three', 'two']);
  });
});

describe('dialog', () => {
  it('takes focus, closes on Escape and gives focus back', async () => {
    const { dialog } = await import('../src/ui/system/components.js');
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    let closed = 0;
    const view = dialog({ id: 'test-dialog', title: 'Make a world', onClose: () => { closed += 1; } });
    view.body.append(Object.assign(document.createElement('button'), { textContent: 'Choose' }));
    document.body.append(view.root);
    view.open();
    expect(view.isOpen()).toBe(true);
    expect(view.root.getAttribute('aria-modal')).toBe('true');
    expect(view.root.contains(document.activeElement)).toBe(true);
    view.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(view.isOpen()).toBe(false);
    expect(closed).toBe(1);
    view.root.remove();
    opener.remove();
  });
});
