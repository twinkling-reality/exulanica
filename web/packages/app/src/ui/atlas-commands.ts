import { el } from './dom.js';

export type AtlasCommand = 'index' | 'map' | 'options' | 'controls' | 'companion' | 'character';

export interface AtlasCommands {
  readonly root: HTMLElement;
  reflect(primary: string, camera: string): void;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function commandIcon(command: AtlasCommand): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'atlas-command-icon');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '1.8');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('d', {
    character: 'M12 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM6 21v-4a6 6 0 0 1 12 0v4M9 16v5m6-5v5',
    companion: 'M4 5h16v11H10l-5 4v-4H4V5Zm4 5h8',
    index: 'M5 4.5h9.25A2.75 2.75 0 0 1 17 7.25V20H7.75A2.75 2.75 0 0 1 5 17.25V4.5Zm3 4h6m-6 4h6m-6 4h3.5',
    map: 'm3.5 6 5-2.5 7 2.5 5-2.5v14l-5 2.5-7-2.5-5 2.5V6Zm5-2.5v14m7-11.5v14',
    options: 'M5 7h8m4 0h2M5 12h2m4 0h8M5 17h6m4 0h4M13 5v4M7 10v4m4 1v4',
    controls: 'M12 8.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2Zm0-5.2 1.1 2.05 2.3.55 1.85-1.45 2.4 2.4-1.45 1.85.55 2.3L20.8 12l-2.05 1.1-.55 2.3 1.45 1.85-2.4 2.4-1.85-1.45-2.3.55L12 20.8l-1.1-2.05-2.3-.55-1.85 1.45-2.4-2.4L5.8 15.4l-.55-2.3L3.2 12l2.05-1.1.55-2.3-1.45-1.85 2.4-2.4L8.6 5.8l2.3-.55L12 3.2Z',
  }[command]);
  svg.append(path);
  return svg;
}

export function buildAtlasCommands(onCommand: (command: AtlasCommand) => void): AtlasCommands {
  const entries: readonly (readonly [AtlasCommand, string, string])[] = [
    ['character', 'Character', 'K'],
    ['index', 'Library', 'I'],
    ['companion', 'Companion', 'X'],
    ['map', 'Map', 'M'],
    ['options', 'Customize', 'O'],
    ['controls', 'Settings', '?'],
  ];
  const buttons = new Map<AtlasCommand, HTMLButtonElement>();
  const root = el('nav', { class: 'atlas-commands', 'aria-label': 'Atlas commands' });
  for (const [command, label, key] of entries) {
    const button = el('button', {
      type: 'button',
      'data-command': command,
      'data-label': label,
      'aria-label': `${label} (${key})`,
    }, [
      commandIcon(command),
      el('span', { class: 'atlas-command-label', text: label }),
      el('span', { class: 'atlas-command-tooltip' }, [
        el('span', { text: label }),
        el('kbd', { text: key }),
      ]),
    ]);
    button.addEventListener('click', () => onCommand(command));
    buttons.set(command, button);
    root.append(button);
  }
  return {
    root,
    reflect(primary, camera) {
      for (const [command, button] of buttons) {
        const current =
          (command === 'character' && primary === 'character') ||
          (command === 'index' && primary === 'index') ||
          (command === 'map' && camera === 'map') ||
          (command === 'options' && primary === 'options') ||
          (command === 'controls' && primary === 'controls');
        if (current) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      }
    },
  };
}
