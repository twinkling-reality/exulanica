import { commandIcon, type AtlasCommand } from './atlas-commands.js';
import { say } from './copy.js';
import { el } from './dom.js';
import { createModalFocus } from './modal-focus.js';

export interface WorldMenu {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
}

type MenuArrow = 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown';

/** Follow the tiles as drawn, including tiles that span more than one mosaic cell. */
function nextMenuEntry(
  entries: readonly HTMLButtonElement[], current: number, arrow: MenuArrow,
): HTMLButtonElement | undefined {
  const here = entries[current];
  if (here === undefined) return undefined;
  const boxes = entries.map((entry) => entry.getBoundingClientRect());
  if (boxes.some((box) => box.width <= 0 || box.height <= 0)) {
    const step = arrow === 'ArrowLeft' || arrow === 'ArrowUp' ? -1 : 1;
    return entries[(current + step + entries.length) % entries.length];
  }
  const vertical = arrow === 'ArrowUp' || arrow === 'ArrowDown';
  const positive = arrow === 'ArrowRight' || arrow === 'ArrowDown';
  const position = (box: DOMRect, main: boolean) => main
    ? (vertical ? (box.top + box.bottom) / 2 : (box.left + box.right) / 2)
    : (vertical ? (box.left + box.right) / 2 : (box.top + box.bottom) / 2);
  const near = (box: DOMRect, main: boolean) => main
    ? (vertical ? box.top : box.left)
    : (vertical ? box.left : box.top);
  const far = (box: DOMRect, main: boolean) => main
    ? (vertical ? box.bottom : box.right)
    : (vertical ? box.right : box.bottom);
  const origin = boxes[current]!;
  const candidates = boxes.map((box, index) => ({ box, index }))
    .filter(({ index }) => index !== current);
  const inDirection = candidates.filter(({ box }) => positive
    ? position(box, true) > position(origin, true)
    : position(box, true) < position(origin, true));
  if (inDirection.length === 0) {
    const edge = Math[positive ? 'min' : 'max'](
      ...candidates.map(({ box }) => position(box, true)),
    );
    const wrapped = candidates.filter(({ box }) => position(box, true) === edge)
      .sort((left, right) =>
        Math.abs(position(left.box, false) - position(origin, false))
        - Math.abs(position(right.box, false) - position(origin, false)));
    return entries[wrapped[0]?.index ?? current];
  }
  inDirection.sort((left, right) => {
    const rank = (box: DOMRect): readonly number[] => [
      Math.max(0, near(box, false) - far(origin, false), near(origin, false) - far(box, false)),
      positive ? Math.max(0, near(box, true) - far(origin, true))
        : Math.max(0, near(origin, true) - far(box, true)),
      Math.abs(position(box, false) - position(origin, false)),
    ];
    const a = rank(left.box);
    const b = rank(right.box);
    return (a[0]! - b[0]!) || (a[1]! - b[1]!) || (a[2]! - b[2]!);
  });
  return entries[inDirection[0]!.index];
}

export function buildWorldMenu(options: {
  readonly preview: boolean;
  readonly onResume: () => void;
  readonly onWorld: () => void;
  /** Opens the comparisons of the models that ran this world's people; absent with no world. */
  readonly onCompare?: () => void;
  /** Offers the recipes a new world can be generated from; absent where no worlds are saved. */
  readonly onMakeWorld?: () => void;
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
    command: AtlasCommand | 'world' | 'compare' | 'make',
    label: string,
    detail: string,
    key: string,
    className = '',
    accessibleName?: string,
  ): HTMLButtonElement => {
    const icon = command === 'world' || command === 'compare'
      || command === 'make' ? [] : [commandIcon(command)];
    const button = el('button', {
      type: 'button',
      class: `world-menu-entry ${className}`.trim(),
      'data-command': command,
      'aria-label': accessibleName,
    }, [
      ...icon,
      el('span', { class: 'world-menu-entry-label', text: label }),
      el('span', { class: 'world-menu-entry-detail', text: detail }),
      el('kbd', { text: key }),
    ]);
    button.addEventListener('click', () => activate(command === 'world'
      ? options.onWorld
      : command === 'compare'
          ? options.onCompare!
          : command === 'make'
            ? options.onMakeWorld!
            : () => options.onCommand(command)));
    return button;
  };

  const resume = el('button', { type: 'button', class: 'world-menu-rail-action' }, [
    el('kbd', { text: 'Esc' }), el('span', { text: 'Resume' }),
  ]);
  resume.addEventListener('click', () => activate(options.onResume));

  const grid = el('div', { class: 'world-menu-grid' }, [
    entry('world', 'World', 'Explore and build', '', 'world-menu-world'),
    entry('character', 'Character', 'Appearance and identity', 'K', 'world-menu-character'),
    entry('index', 'Library', 'People and sources', 'I', 'world-menu-library'),
    entry('map', 'Map', 'Regions and orientation', 'M', 'world-menu-map'),
    ...(options.onCompare === undefined ? [] : [
      entry('compare', 'Compare', 'See what each model chose', '', 'world-menu-compare', 'Compare models'),
    ]),
    entry('companion', 'Companion', 'Ask and act', 'X', 'world-menu-companion'),
    ...(options.onMakeWorld === undefined ? [] : [
      entry('make', say('worldMenu.make'), say('worldMenu.make.detail'), '', 'world-menu-make', say('worldMenu.make')),
    ]),
    entry('options', 'Design', 'Light and material', 'O', 'world-menu-customize', 'Customize world'),
    entry('controls', 'Settings', 'Display and controls', '?', 'world-menu-settings'),
  ]);
  const rail = el('footer', { class: 'world-menu-rail' }, [
    resume,
    el('span', { class: 'world-menu-rail-hint' }, [
      el('kbd', { text: 'Arrows' }), 'Move',
    ]),
    el('span', { class: 'world-menu-rail-hint' }, [
      el('kbd', { text: 'Enter' }), 'Open',
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
    nextMenuEntry(entries, current, event.code as MenuArrow)?.focus();
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
    // The choice never waits on the animation: a page whose frames are throttled (a background
    // tab, a busy machine) may not finish it, and the menu would ignore every key after.
    let done = false;
    const finish = (): void => {
      if (done) return;
      done = true;
      action();
    };
    const fallback = window.setTimeout(finish, 300);
    void animation.finished.then(() => {
      window.clearTimeout(fallback);
      finish();
    }).catch(() => {
      window.clearTimeout(fallback);
      leaving = false;
    });
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
