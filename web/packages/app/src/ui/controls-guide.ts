import {
  DEFAULT_PREFERENCES,
  normalisePreferences,
  type AtlasPreferences,
  type ContrastPreference,
  type TransparencyPreference,
} from '../preferences.js';
import {
  PREFERENCE_BINDINGS,
  preferenceValue,
  type InteractionCapability,
  type InteractionValue,
} from '../interaction-settings.js';
import { commandAction, el } from './dom.js';
import { createModalFocus } from './modal-focus.js';
import { DEVICE_SETTING_WORDS, deviceSelect, drawSetting, type DrawnSetting, type SettingHost } from './setting-controls.js';

type SettingsSection = 'display' | 'movement' | 'controls';

export interface ControlsGuide {
  readonly root: HTMLElement;
  section(): SettingsSection;
  showSection(section: SettingsSection): void;
  setPreferences(value: AtlasPreferences): void;
  setVisible(visible: boolean): void;
  /**
   * Draw the movement settings from the capabilities the server serves
   * (`GET /world/interactions/catalog`), as Customize does: one control for each the registry says
   * the settings page offers, and none for any other.
   */
  showSettings(capabilities: readonly InteractionCapability[]): void;
  /** Say the served settings could not be read, in place of controls drawn from a guess. */
  settingsUnavailable(detail: string): void;
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

function settingRow(label: string, control: HTMLElement, note?: string): HTMLElement {
  return el('label', { class: 'setting-row' }, [
    el('span', { class: 'setting-copy' }, [
      el('strong', { text: label }),
      ...(note === undefined ? [] : [el('span', { class: 'setting-note', text: note })]),
    ]),
    control,
  ]);
}

/** A served setting laid out as this overlay lays out its own: a range in its framed well. */
function servedRow(label: string, control: HTMLElement, note?: string): HTMLElement {
  if (control.classList.contains('range-control')) {
    control.classList.add('setting-range');
    control.querySelector('output')?.classList.add('setting-value');
  }
  return settingRow(label, control, note);
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

  const contrast = deviceSelect('contrast');
  const transparency = deviceSelect('transparency');
  const regionMinimap = deviceSelect('regionMinimap');
  // The movement settings are drawn from the served catalog when it arrives (`showSettings`).
  const servedSettings = el('div', { class: 'settings-rows' }, [
    el('p', { class: 'setting-note', text: 'Reading the settings this world offers.' }),
  ]);
  let drawn: readonly { readonly capability: InteractionCapability; readonly control: DrawnSetting }[] = [];

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
      settingRow(DEVICE_SETTING_WORDS.contrast.label, contrast, DEVICE_SETTING_WORDS.contrast.note),
      settingRow(DEVICE_SETTING_WORDS.transparency.label, transparency, DEVICE_SETTING_WORDS.transparency.note),
    ]),
  ]);
  const movementPage = page('movement', 'Movement', [
    el('p', { class: 'settings-page-intro', text: 'View changes never alter memory positions or evidence.' }),
    servedSettings,
    el('div', { class: 'settings-rows' }, [
      settingRow(DEVICE_SETTING_WORDS.regionMinimap.label, regionMinimap, DEVICE_SETTING_WORDS.regionMinimap.note),
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

  /** What resetting a category writes: each of its settings at its default. */
  const defaults = (section: SettingsSection): Partial<AtlasPreferences> => {
    if (section === 'display') {
      return { contrast: DEFAULT_PREFERENCES.contrast, transparency: DEFAULT_PREFERENCES.transparency };
    }
    if (section !== 'movement') return {};
    const patch: Record<string, InteractionValue> = { regionMinimap: DEFAULT_PREFERENCES.regionMinimap };
    for (const { capability } of drawn) {
      const field = PREFERENCE_BINDINGS[capability.key]?.field;
      const value = preferenceValue(capability.key, capability.default);
      if (field !== undefined && value !== undefined) patch[field] = value;
    }
    return patch as Partial<AtlasPreferences>;
  };

  const render = (): void => {
    contrast.value = current.contrast;
    transparency.value = current.transparency;
    regionMinimap.value = current.regionMinimap ? 'on' : 'off';
    for (const { control } of drawn) control.refresh();
    const held = current as unknown as Readonly<Record<string, unknown>>;
    reset.disabled = Object.entries(defaults(activeSection)).every(([key, value]) => held[key] === value);
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

  // A setting here applies as it is changed, a range while it is dragged.
  const host: SettingHost = {
    value: (key) => (current as unknown as Readonly<Record<string, unknown>>)[key] as InteractionValue,
    preview: commit,
    commit,
    settle: () => undefined,
  };

  contrast.addEventListener('change', () => commit({ contrast: contrast.value as ContrastPreference }));
  transparency.addEventListener('change', () =>
    commit({ transparency: transparency.value as TransparencyPreference }));
  regionMinimap.addEventListener('change', () => commit({ regionMinimap: regionMinimap.value === 'on' }));
  reset.addEventListener('click', () => {
    const patch = defaults(activeSection);
    if (Object.keys(patch).length > 0) commit(patch);
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
    showSettings(capabilities) {
      drawn = capabilities
        .filter((capability) => capability.shownInSettings)
        .flatMap((capability) => {
          const control = drawSetting(capability, host, servedRow);
          return control === null ? [] : [{ capability, control }];
        });
      servedSettings.replaceChildren(...drawn.map(({ control }) => control.element));
      render();
    },
    settingsUnavailable(detail) {
      drawn = [];
      servedSettings.replaceChildren(
        el('p', { class: 'setting-note', text: `The settings this world offers could not be read: ${detail}` }),
      );
      render();
    },
  };
}
