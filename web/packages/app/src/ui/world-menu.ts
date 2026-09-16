import type { AtlasCommand } from './atlas-commands.js';
import { el } from './dom.js';
import { createModalFocus } from './modal-focus.js';

export interface WorldMenu {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
}

export function buildWorldMenu(options: {
  readonly preview: boolean;
  readonly onResume: () => void;
  readonly onWorld: () => void;
  readonly onCommand: (command: AtlasCommand) => void;
}): WorldMenu {
  const root = el('section', {
    class: 'world-menu',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': 'World menu',
  });
  root.hidden = true;
  let activate = (action: () => void): void => action();

  const entry = (
    command: AtlasCommand | 'world',
    label: string,
    detail: string,
    key: string,
    className = '',
  ): HTMLButtonElement => {
    const button = el('button', {
      type: 'button',
      class: `world-menu-entry ${className}`.trim(),
      'data-command': command,
    }, [
      el('span', { class: 'world-menu-entry-label', text: label }),
      el('span', { class: 'world-menu-entry-detail', text: detail }),
      el('kbd', { text: key }),
    ]);
    button.addEventListener('click', () => activate(
      command === 'world' ? options.onWorld : () => options.onCommand(command),
    ));
    return button;
  };

  const resume = el('button', { type: 'button', class: 'world-menu-rail-action' }, [
    el('kbd', { text: 'Esc' }), el('span', { text: 'Resume' }),
  ]);
  resume.addEventListener('click', () => activate(options.onResume));

  const grid = el('div', { class: 'world-menu-grid' }, [
    entry('world', 'Place & view', 'Nearby people, creation, camera, and source context', '', 'world-menu-world'),
    entry('character', 'Character', 'Appearance and identity', 'K', 'world-menu-character'),
    entry('index', 'Library', 'People, places, and sources', 'I', 'world-menu-library'),
    entry('map', 'Map', 'Regions and orientation', 'M', 'world-menu-map'),
    entry('companion', 'Companion', 'Call the Unnamed Companion', 'X', 'world-menu-companion'),
    entry('options', 'Customize world', 'Light, material, and atmosphere', 'O', 'world-menu-customize'),
    entry('controls', 'Settings', 'Display, accessibility, movement, and controls', '?', 'world-menu-settings'),
  ]);
  const rail = el('footer', { class: 'world-menu-rail' }, [
    resume,
    el('span', { class: 'world-menu-rail-hint' }, [
      el('kbd', { text: '← ↑ ↓ →' }), 'Navigate',
    ]),
    el('span', { class: 'world-menu-rail-hint' }, [
      el('kbd', { text: 'Enter' }), 'Select',
    ]),
    el('span', {
      class: 'world-menu-session',
      text: options.preview ? 'Development preview' : 'Connected world',
    }),
  ]);
  const plane = el('div', { class: 'world-menu-plane' }, [grid, rail]);
  root.append(plane);

  root.addEventListener('keydown', (event) => {
    if (event.code === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      activate(options.onResume);
      return;
    }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.code)) return;
    const entries = [...grid.querySelectorAll<HTMLButtonElement>('.world-menu-entry')];
    const current = entries.indexOf(document.activeElement as HTMLButtonElement);
    if (current < 0) return;
    event.preventDefault();
    const columns = 4;
    const delta = event.code === 'ArrowLeft' ? -1
      : event.code === 'ArrowRight' ? 1
        : event.code === 'ArrowUp' ? -columns : columns;
    entries[(current + delta + entries.length) % entries.length]?.focus();
  });

  const firstEntry = grid.querySelector<HTMLButtonElement>('.world-menu-entry')!;
  const modalFocus = createModalFocus(root, firstEntry);
  let leaving = false;
  const reducedMotion = () =>
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  activate = (action) => {
    if (leaving) return;
    if (reducedMotion() || typeof plane.animate !== 'function') {
      action();
      return;
    }
    leaving = true;
    const animation = plane.animate([
      { opacity: 1, translate: '0 0', filter: 'brightness(1)' },
      { opacity: 0, translate: '32px 0', filter: 'brightness(1.16)' },
    ], { duration: 150, easing: 'cubic-bezier(.4,0,1,1)' });
    void animation.finished.then(action).catch(() => { leaving = false; });
  };
  return {
    root,
    setVisible(visible) {
      if (visible) {
        leaving = false;
        modalFocus.setVisible(true);
        if (!reducedMotion() && typeof plane.animate === 'function') {
          plane.animate([
            { opacity: 0, translate: '42px 0', filter: 'brightness(1.28)' },
            { opacity: 1, translate: '0 0', filter: 'brightness(1)' },
          ], { duration: 240, easing: 'cubic-bezier(.2,.8,.2,1)' });
        }
        return;
      }
      modalFocus.setVisible(false);
    },
  };
}
