import {
  DEFAULT_PREFERENCES,
  normalisePreferences,
  type AtlasPreferences,
  type ContrastPreference,
  type TransitionPreference,
  type TransparencyPreference,
  type VignettePreference,
} from '../preferences.js';
import { commandAction, el } from './dom.js';
import { createModalFocus } from './modal-focus.js';

type SettingsSection = 'display' | 'movement' | 'controls';

export interface ControlsGuide {
  readonly root: HTMLElement;
  section(): SettingsSection;
  showSection(section: SettingsSection): void;
  setPreferences(value: AtlasPreferences): void;
  setVisible(visible: boolean): void;
}

interface ControlsGuideOptions {
  readonly preferences: AtlasPreferences;
  readonly onChange: (preferences: AtlasPreferences) => void;
  readonly onClose: () => void;
  readonly onShowCustomize: () => void;
}

const controlRows: readonly (readonly [string, string])[] = [
  ['W A S D', 'Move and turn your character toward travel'],
  ['Mouse', 'Orbit the view independently'],
  ['Shift', 'Move faster'],
  ['E · Space · Enter', 'Interact with what is centred'],
  ['X · Right click', 'Call the Companion'],
  ['H', 'Open the World hub'],
  ['I', 'Open Index'],
  ['M', 'Tap for the Map, hold to look and drop back'],
  ['O', 'Open Customize'],
  ['?', 'Open Settings'],
  ['Escape', 'Release the mouse, dismiss, or step back'],
];

function option(value: string, label: string): HTMLOptionElement {
  return el('option', { value, text: label });
}

function settingRow(label: string, control: HTMLElement, note?: string): HTMLElement {
  return el('label', { class: 'setting-row' }, [
    el('span', { class: 'setting-copy' }, [
      el('strong', { text: label }),
      ...(note === undefined ? [] : [el('span', { class: 'setting-note', text: note })]),
    ]),
    control,
  ]);
}

export function buildControlsGuide(options: ControlsGuideOptions): ControlsGuide {
  const root = el('section', {
    class: 'system-overlay controls-view settings-view held-plate',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': 'settings-title',
  });
  root.hidden = true;

  const close = el('button', {
    type: 'button', class: 'overlay-close command-action', 'aria-label': 'Return to your world',
  }, commandAction('?', 'Dismiss'));
  close.addEventListener('click', options.onClose);
  const customize = el(
    'button',
    { type: 'button', class: 'text-action command-action', 'aria-label': 'Open Customize' },
    commandAction('O', 'Customize'),
  );
  customize.addEventListener('click', options.onShowCustomize);

  const contrast = el('select', { 'aria-label': 'Contrast' }, [
    option('standard', 'Standard'), option('high', 'High'),
  ]);
  const transparency = el('select', { 'aria-label': 'Transparency' }, [
    option('layered', 'Layered'), option('reduced', 'Reduced'),
  ]);
  const transition = el('select', { 'aria-label': 'Interface motion' }, [
    option('system', 'Follow system'), option('motion', 'Full motion'), option('fade', 'Fade only'),
  ]);
  const fieldOfView = el('input', {
    type: 'range', min: '60', max: '90', step: '1', 'aria-label': 'Field of view',
  });
  const fieldOfViewValue = el('output', { class: 'setting-value' });
  const sensitivity = el('input', {
    type: 'range', min: '0.5', max: '2', step: '0.1', 'aria-label': 'Look sensitivity',
  });
  const sensitivityValue = el('output', { class: 'setting-value' });
  const vignette = el('select', { 'aria-label': 'Comfort vignette' }, [
    option('off', 'Off'), option('subtle', 'Subtle'), option('strong', 'Strong'),
  ]);
  const regionMinimap = el('select', { 'aria-label': 'Region minimap' }, [
    option('off', 'Off'), option('on', 'Shown'),
  ]);

  let current = normalisePreferences(options.preferences);
  let activeSection: SettingsSection = 'display';
  const pages = new Map<SettingsSection, HTMLElement>();
  const navButtons = new Map<SettingsSection, HTMLButtonElement>();

  const nav = el('nav', { class: 'settings-categories', 'aria-label': 'Settings categories' });
  const addCategory = (section: SettingsSection, label: string): void => {
    const button = el('button', {
      type: 'button', class: 'settings-category', 'data-section': section, text: label,
    });
    button.addEventListener('click', () => showSection(section));
    navButtons.set(section, button);
    nav.append(button);
  };
  addCategory('display', 'Display & accessibility');
  addCategory('movement', 'Movement');
  addCategory('controls', 'Controls');

  const page = (section: SettingsSection, title: string, children: readonly Node[]): HTMLElement => {
    const pageRoot = el('section', {
      class: `settings-page settings-page-${section}`,
      'aria-labelledby': `settings-${section}-title`,
    }, [
      el('header', { class: 'settings-page-head' }, [
        el('p', { class: 'overlay-kicker', text: 'Settings' }),
        el('h2', { id: `settings-${section}-title`, text: title }),
      ]),
      ...children,
    ]);
    pages.set(section, pageRoot);
    return pageRoot;
  };

  const displayPage = page('display', 'Display & accessibility', [
    el('p', { class: 'settings-page-intro', text: 'Reading overrides take priority over every world design.' }),
    el('div', { class: 'settings-rows' }, [
      settingRow('Contrast', contrast, 'Strengthens edges and reading surfaces.'),
      settingRow('Transparency', transparency, 'Removes blur and world motion beneath text.'),
      settingRow('Interface motion', transition, 'Controls navigation and direct-travel transitions.'),
    ]),
  ]);
  const movementPage = page('movement', 'Movement', [
    el('p', { class: 'settings-page-intro', text: 'View changes never alter memory positions or evidence.' }),
    el('div', { class: 'settings-rows' }, [
      settingRow('Field of view', el('span', { class: 'setting-range' }, [fieldOfView, fieldOfViewValue])),
      settingRow('Look sensitivity', el('span', { class: 'setting-range' }, [sensitivity, sensitivityValue])),
      settingRow('Comfort vignette', vignette, 'Darkens only the periphery while traversing.'),
      settingRow(
        'Region minimap',
        regionMinimap,
        'A plan of the regions in the corner while traversing. The world is meant to orient you '
          + 'on its own, so this stays off until you want it.',
      ),
    ]),
  ]);
  const controlsPage = page('controls', 'Controls', [
    el('p', { class: 'settings-page-intro', text: 'The same commands remain available everywhere in your world.' }),
    el('dl', { class: 'settings-control-list' }, controlRows.flatMap(([key, meaning]) => [
      el('dt', {}, [el('kbd', { text: key })]),
      el('dd', { text: meaning }),
    ])),
  ]);

  const reset = el('button', { type: 'button', class: 'text-action settings-reset', text: 'Reset category' });

  const render = (): void => {
    contrast.value = current.contrast;
    transparency.value = current.transparency;
    transition.value = current.transition;
    fieldOfView.value = String(current.fieldOfView);
    fieldOfViewValue.value = `${current.fieldOfView}°`;
    sensitivity.value = String(current.mouseSensitivity);
    sensitivityValue.value = `${current.mouseSensitivity.toFixed(1)}×`;
    vignette.value = current.vignette;
    regionMinimap.value = current.regionMinimap ? 'on' : 'off';
    const atDefaults = activeSection === 'display'
      ? current.contrast === DEFAULT_PREFERENCES.contrast &&
        current.transparency === DEFAULT_PREFERENCES.transparency &&
        current.transition === DEFAULT_PREFERENCES.transition
      : activeSection === 'movement'
        ? current.fieldOfView === DEFAULT_PREFERENCES.fieldOfView &&
          current.mouseSensitivity === DEFAULT_PREFERENCES.mouseSensitivity &&
          current.vignette === DEFAULT_PREFERENCES.vignette
        : true;
    reset.disabled = atDefaults;
    reset.hidden = activeSection === 'controls';
  };

  const commit = (patch: Partial<AtlasPreferences>): void => {
    current = normalisePreferences({ ...current, ...patch });
    render();
    options.onChange(current);
  };

  function showSection(section: SettingsSection): void {
    activeSection = section;
    root.dataset['section'] = section;
    for (const [key, pageRoot] of pages) pageRoot.hidden = key !== section;
    for (const [key, button] of navButtons) {
      if (key === section) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    render();
  }

  contrast.addEventListener('change', () => commit({ contrast: contrast.value as ContrastPreference }));
  transparency.addEventListener('change', () =>
    commit({ transparency: transparency.value as TransparencyPreference }));
  transition.addEventListener('change', () =>
    commit({ transition: transition.value as TransitionPreference }));
  fieldOfView.addEventListener('input', () => commit({ fieldOfView: fieldOfView.valueAsNumber }));
  sensitivity.addEventListener('input', () =>
    commit({ mouseSensitivity: sensitivity.valueAsNumber }));
  vignette.addEventListener('change', () => commit({ vignette: vignette.value as VignettePreference }));
  regionMinimap.addEventListener('change', () => commit({ regionMinimap: regionMinimap.value === 'on' }));
  reset.addEventListener('click', () => {
    if (activeSection === 'display') {
      commit({
        contrast: DEFAULT_PREFERENCES.contrast,
        transparency: DEFAULT_PREFERENCES.transparency,
        transition: DEFAULT_PREFERENCES.transition,
      });
      return;
    }
    if (activeSection === 'movement') {
      commit({
        fieldOfView: DEFAULT_PREFERENCES.fieldOfView,
        mouseSensitivity: DEFAULT_PREFERENCES.mouseSensitivity,
        vignette: DEFAULT_PREFERENCES.vignette,
        regionMinimap: DEFAULT_PREFERENCES.regionMinimap,
      });
    }
  });

  root.append(
    el('header', { class: 'overlay-head settings-head' }, [
      el('div', {}, [
        el('p', { class: 'overlay-kicker', text: 'System' }),
        el('h1', { id: 'settings-title', text: 'Settings' }),
      ]),
    ]),
    nav,
    el('main', { class: 'settings-pages' }, [displayPage, movementPage, controlsPage]),
    el('footer', { class: 'settings-actions' }, [reset, customize, close]),
  );

  showSection('display');
  const modalFocus = createModalFocus(root, close);
  return {
    root,
    section: () => activeSection,
    showSection,
    setPreferences(value) {
      current = normalisePreferences(value);
      render();
    },
    setVisible(visible) {
      modalFocus.setVisible(visible);
    },
  };
}
