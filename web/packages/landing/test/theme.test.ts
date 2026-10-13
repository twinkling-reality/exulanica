// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { createPublicTheme, PUBLIC_THEME_KEY } from '../src/theme.js';
import { buildChrome } from '../src/ui/chrome.js';

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); document.body.replaceChildren(); });

it('keeps the header preference through navigation and a new page session', () => {
  const theme = createPublicTheme();
  const chrome = buildChrome({ onToggleTheme: () => theme.toggle() });
  theme.subscribe(chrome.setTheme);
  document.body.append(chrome.root);
  const toggle = chrome.root.querySelector<HTMLButtonElement>('.theme-toggle')!;
  toggle.focus();
  toggle.click();
  chrome.setSurface('docs');
  expect(document.documentElement.dataset.theme).toBe('landing-dark');
  expect(toggle.getAttribute('aria-label')).toBe('Switch to light theme');
  expect(document.activeElement).toBe(toggle);
  expect(localStorage.getItem(PUBLIC_THEME_KEY)).toBe('dark');
  theme.dispose();
  const reopened = createPublicTheme();
  expect(document.documentElement.dataset.theme).toBe('landing-dark');
  reopened.toggle();
  expect(document.documentElement.dataset.theme).toBe('landing-light');
  reopened.dispose();
});

it('still changes theme when preference storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  const theme = createPublicTheme();
  theme.toggle();
  expect(document.documentElement.dataset.theme).toBe('landing-dark');
  theme.toggle();
  expect(document.documentElement.dataset.theme).toBe('landing-light');
  theme.dispose();
});

it('reflects a preference change from another tab without writing it back', () => {
  const theme = createPublicTheme();
  const write = vi.spyOn(Storage.prototype, 'setItem');
  window.dispatchEvent(new StorageEvent('storage', { key: PUBLIC_THEME_KEY, newValue: 'dark' }));
  expect(document.documentElement.dataset.theme).toBe('landing-dark');
  expect(write).not.toHaveBeenCalled();
  theme.dispose();
});
