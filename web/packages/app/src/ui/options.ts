import {
  DEFAULT_PREFERENCES,
  normalisePreferences,
  type AtlasPreferences,
  type CompanionBodyPreference,
  type CompanionColorPreference,
  type CompanionFacePreference,
  type ContrastPreference,
  type TransparencyPreference,
  type VignettePreference,
} from '../preferences.js';
import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  companionAppearanceConfiguration,
  resolveWorldStyleParameters,
  worldArtProfile,
  worldStyleControls,
} from '@exulanica/presentation';
import type { WorldStyleParameterDefinition, WorldStyleParameterValue } from '@exulanica/atlas-core';
import { commandAction, el } from './dom.js';
import { createCompanionAvatar } from './companion-avatar.js';
import { createModalFocus } from './modal-focus.js';

/*
 * What each variant is called on screen.
 *
 * These are total records over the contract's catalogs, so a silhouette, colour or expression
 * added in @exulanica/presentation cannot reach a person unnamed: the build fails until it has a
 * word. Colour labels stay plain colour words rather than the internal variant names, which is
 * what the first five already did.
 */
const BODY_LABEL: Readonly<Record<CompanionBodyPreference, string>> = Object.freeze({
  circle: 'Circle',
  pebble: 'Pebble',
  squircle: 'Squircle',
  capsule: 'Capsule',
  cloud: 'Cloud',
  droplet: 'Droplet',
  arch: 'Arch',
  bead: 'Bead',
  lozenge: 'Lozenge',
});

const COLOR_LABEL: Readonly<Record<CompanionColorPreference, string>> = Object.freeze({
  ink: 'Ink',
  rose: 'Pink',
  orange: 'Orange',
  periwinkle: 'Blue',
  mint: 'Green',
  ember: 'Red',
  iris: 'Violet',
  slate: 'Slate',
});

const FACE_LABEL: Readonly<Record<CompanionFacePreference, string>> = Object.freeze({
  neutral: 'Neutral',
  attentive: 'Attentive',
  curious: 'Curious',
  happy: 'Happy',
  sleepy: 'Sleepy',
  wide: 'Wide',
  wink: 'Wink',
  focused: 'Focused',
});

/**
 * The parts of Customize a caller can ask for by name.
 *
 * The Companion offers to redesign the world or itself, and arriving at the top of a scrolling
 * surface makes the person hunt for the thing they just asked about. These are the sections it
 * can name, and nothing else addresses them.
 */
export type AtlasInstrumentSection = 'world' | 'companion';

export interface OptionsView {
  readonly root: HTMLElement;
  /** Bring one section into view. Silent when the section is not rendered. */
  showSection(section: AtlasInstrumentSection): void;
  preferences(): AtlasPreferences;
  setPreferences(value: AtlasPreferences): void;
  setVisible(visible: boolean): void;
  reportPersistence(state: 'idle' | 'saving' | 'saved' | 'failed'): void;
  setWorldAuthority(value: WorldStyleAuthorityPresentation): void;
  reportWorldLifecycle(state: 'idle' | 'checking' | 'ready' | 'saved' | 'stale' | 'failed', detail?: string): void;
}

export interface WorldStyleAuthorityPresentation {
  readonly state: 'ready' | 'unavailable' | 'failed';
  readonly detail: string;
  readonly currentVersionId?: string;
  readonly revision?: number;
  readonly provenance?: string;
  readonly warnings?: readonly string[];
  readonly versions?: readonly {
    readonly versionId: string;
    readonly label: string;
    readonly current: boolean;
  }[];
  readonly proposal?: {
    readonly origin: string;
    readonly model: string | null;
    readonly promptVersion: string | null;
    readonly referenceCount: number;
    readonly refinesProposalId: string | null;
  };
}

interface OptionsCallbacks {
  readonly preferences: AtlasPreferences;
  readonly onChange: (preferences: AtlasPreferences) => void;
  readonly onPreview?: (preferences: AtlasPreferences) => void;
  /**
   * Read the four `interface.*` registers out of the person's own photographs.
   *
   * Returns the control values, never a colour, and never applies them. It resolves to null when
   * the library says nothing usable, which is a real answer and not a failure.
   */
  readonly onReadSourceLight?: () => Promise<Readonly<Record<string, number>> | null>;
  readonly onWorldDiscard?: (preferences: AtlasPreferences) => void;
  readonly onWorldApply?: (preferences: AtlasPreferences) => Promise<boolean>;
  readonly onWorldRollback?: (versionId: string) => Promise<AtlasPreferences | null>;
  readonly onClose: () => void;
  readonly onShowControls: () => void;
}

function option(value: string, label: string): HTMLOptionElement {
  return el('option', { value, text: label });
}

function field(label: string, control: HTMLElement, note?: string): HTMLElement {
  const content: Node[] = [el('span', { class: 'option-label', text: label }), control];
  if (note !== undefined) content.push(el('span', { class: 'option-note', text: note }));
  return el('label', { class: 'option-field' }, content);
}

const sameWorldStyle = (left: AtlasPreferences, right: AtlasPreferences): boolean => {
  if (left.worldArtProfile !== right.worldArtProfile) return false;
  if (left.worldArtProfileVersion !== right.worldArtProfileVersion) return false;
  const keys = new Set([
    ...Object.keys(left.worldStyleParameters),
    ...Object.keys(right.worldStyleParameters),
  ]);
  return [...keys].every(
    (key) => left.worldStyleParameters[key] === right.worldStyleParameters[key],
  );
};

export function buildOptions(callbacks: OptionsCallbacks): OptionsView {
  const root = el('section', {
    class: 'system-overlay options-view atlas-instrument held-plate',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': 'options-title',
  });
  root.hidden = true;

  const close = el('button', {
    type: 'button',
    class: 'overlay-close command-action',
    'aria-label': 'Return to Atlas',
  }, commandAction('O', 'Return'));

  const contrast = el('select', { 'aria-label': 'Contrast' }, [
    option('standard', 'Standard'),
    option('high', 'High'),
  ]);
  const transparency = el('select', { 'aria-label': 'Transparency' }, [
    option('layered', 'Layered'),
    option('reduced', 'Reduced'),
  ]);
  const fieldOfView = el('input', {
    type: 'range', min: '60', max: '90', step: '1', 'aria-label': 'Field of view',
  });
  const fieldOfViewValue = el('output', { class: 'option-value' });
  const sensitivity = el('input', {
    type: 'range', min: '0.5', max: '2', step: '0.1', 'aria-label': 'Look sensitivity',
  });
  const sensitivityValue = el('output', { class: 'option-value' });
  const persistence = el('p', {
    class: 'option-note option-persistence',
    role: 'status',
    'aria-live': 'polite',
  });
  const vignette = el('select', { 'aria-label': 'Comfort vignette' }, [
    option('off', 'Off'),
    option('subtle', 'Subtle'),
    option('strong', 'Strong'),
  ]);
  const companionBody = el('select', { 'aria-label': 'Companion shape' },
    COMPANION_BODY_VARIANTS.map((variant) => option(variant, BODY_LABEL[variant])));
  const companionColor = el('select', { 'aria-label': 'Companion color' },
    COMPANION_COLOR_VARIANTS.map((variant) => option(variant, COLOR_LABEL[variant])));
  const companionFace = el('select', { 'aria-label': 'Companion expression' },
    COMPANION_FACE_VARIANTS.map((variant) => option(variant, FACE_LABEL[variant])));

  /*
   * The preview.
   *
   * Choosing an appearance from three dropdowns of words meant reading "Lozenge" and hoping. The
   * real avatar renderer draws it here, so the choice is visible where it is made rather than
   * behind the surface that is covering the Companion. It is decorative: the selects remain the
   * controls, and records/2026-08-31-atlas-interface-plan.md asks for exactly this.
   */
  const companionPreview = createCompanionAvatar();
  const companionPreviewFrame = el('div', { class: 'companion-preview', 'aria-hidden': 'true' });
  companionPreviewFrame.append(companionPreview.root);

  const activeStyle = worldArtProfile(
    callbacks.preferences.worldArtProfile,
    callbacks.preferences.worldArtProfileVersion,
  );
  const defaultStyleParameters = resolveWorldStyleParameters(
    activeStyle.profileId,
    {},
    activeStyle.profileVersion,
  );
  const styleControls = worldStyleControls(activeStyle.profileId, activeStyle.profileVersion);
  const styleName = el('strong', { class: 'world-style-name' });
  const styleState = el('span', { class: 'world-style-state', role: 'status', 'aria-live': 'polite' });
  const worldAuthority = el('p', {
    class: 'option-note world-style-authority', role: 'status', 'aria-live': 'polite',
  });
  const worldLifecycle = el('p', {
    class: 'option-note world-style-lifecycle', role: 'status', 'aria-live': 'polite',
  });
  const worldVersion = el('p', { class: 'option-note world-style-version' });
  const worldProvenance = el('p', { class: 'option-note world-style-provenance' });
  const proposalReview = el('div', { class: 'world-style-proposal-review' });
  proposalReview.hidden = true;
  const history = el('select', { 'aria-label': 'World design history' });
  const rollbackWorld = el('button', {
    type: 'button', class: 'text-action', text: 'Restore selected version', disabled: true,
  });
  const styleSwatches = [
    ['Open air', 'sky'],
    ['Continuity field', 'terrain'],
    ['Source light', 'paper'],
    ['Confirmed relation', 'brass'],
    ['Unresolved', 'stoneShadow'],
  ].map(([label, role]) => el('span', {
    class: 'world-dna-swatch',
    title: label,
    'aria-label': label,
    'data-palette-role': role,
  }));
  const styleInputs = new Map<string, {
    readonly definition: WorldStyleParameterDefinition;
    readonly input: HTMLInputElement | HTMLSelectElement;
    readonly output?: HTMLOutputElement;
  }>();
  const styleFields = styleControls.map((definition) => {
    let input: HTMLInputElement | HTMLSelectElement;
    let output: HTMLOutputElement | undefined;
    if (definition.kind === 'range') {
      input = el('input', {
        type: 'range', min: String(definition.min), max: String(definition.max),
        step: String(definition.step), 'aria-label': definition.label,
      });
      output = el('output', { class: 'option-value' });
    } else if (definition.kind === 'choice') {
      input = el('select', { 'aria-label': definition.label },
        definition.options.map((item) => option(item.value, item.label)));
    } else {
      input = el('input', {
        type: definition.kind === 'color' ? 'color' : 'checkbox',
        'aria-label': definition.label,
      });
    }
    styleInputs.set(definition.key, { definition, input, ...(output === undefined ? {} : { output }) });
    const control = output === undefined
      ? input
      : el('span', { class: 'range-control' }, [input, output]);
    return field(definition.label, control, definition.description);
  });

  let applied = callbacks.preferences;
  let current = callbacks.preferences;
  let worldBusy = false;
  let render = (): void => {};
  const worldDirty = (): boolean => !sameWorldStyle(current, applied);
  const discardWorldPreview = (): void => {
    worldLifecycle.textContent = '';
    if (!worldDirty()) {
      callbacks.onWorldDiscard?.(applied);
      return;
    }
    current = normalisePreferences({
      ...current,
      worldArtProfile: applied.worldArtProfile,
      worldArtProfileVersion: applied.worldArtProfileVersion,
      worldStyleParameters: applied.worldStyleParameters,
    });
    render();
    callbacks.onWorldDiscard?.(applied);
  };
  close.addEventListener('click', () => {
    discardWorldPreview();
    callbacks.onClose();
  });
  const commit = (patch: Partial<AtlasPreferences>): void => {
    const draftProfile = current.worldArtProfile;
    const draftProfileVersion = current.worldArtProfileVersion;
    const draftParameters = current.worldStyleParameters;
    applied = normalisePreferences({ ...applied, ...patch });
    current = normalisePreferences({
      ...applied,
      worldArtProfile: draftProfile,
      worldArtProfileVersion: draftProfileVersion,
      worldStyleParameters: draftParameters,
    });
    render();
    callbacks.onChange(applied);
  };
  const preview = (patch: Partial<AtlasPreferences>): void => {
    current = normalisePreferences({ ...current, ...patch });
    render();
    callbacks.onPreview?.(current);
  };
  const applyWorld = el('button', {
    type: 'button', class: 'world-style-apply', text: 'Apply world design',
  });
  const undoWorld = el('button', {
    type: 'button', class: 'text-action', text: 'Undo preview',
  });
  const resetWorld = el('button', {
    type: 'button', class: 'text-action', text: 'Reset this style',
  });
  /*
   * The one action in Customize that is about this person's own library rather than about a
   * setting. It previews like every other change and it commits through the same Apply, because
   * a world that recoloured itself the moment a photograph loaded would be a style edit nobody
   * asked for.
   */
  const readSource = el('button', {
    type: 'button', class: 'text-action world-style-source', text: 'Take colour from my photographs',
  });
  const readSourceNote = el('p', { class: 'option-note world-style-source-note' });
  readSource.hidden = callbacks.onReadSourceLight === undefined;
  readSourceNote.hidden = true;
  readSource.addEventListener('click', () => {
    if (callbacks.onReadSourceLight === undefined) return;
    readSource.disabled = true;
    readSourceNote.hidden = false;
    readSourceNote.textContent = 'Reading your photographs…';
    void callbacks.onReadSourceLight().then((values) => {
      readSource.disabled = false;
      if (values === null) {
        readSourceNote.textContent =
          'Your photographs did not carry enough colour to read. Nothing was changed.';
        return;
      }
      readSourceNote.textContent =
        'Previewing the colour your photographs carry. Apply keeps it; Undo preview drops it.';
      preview({ worldStyleParameters: { ...current.worldStyleParameters, ...values } });
    });
  });

  render = (): void => {
    contrast.value = current.contrast;
    transparency.value = current.transparency;
    fieldOfView.value = String(current.fieldOfView);
    fieldOfViewValue.value = `${current.fieldOfView}°`;
    sensitivity.value = String(current.mouseSensitivity);
    sensitivityValue.value = `${current.mouseSensitivity.toFixed(1)}×`;
    vignette.value = current.vignette;
    companionBody.value = current.companionBody;
    companionColor.value = current.companionColor;
    companionFace.value = current.companionFace;
    companionPreview.setAppearance(companionAppearanceConfiguration({
      body: current.companionBody,
      color: current.companionColor,
      face: current.companionFace,
    }));
    const liveStyle = worldArtProfile(
      current.worldArtProfile,
      current.worldArtProfileVersion,
      current.worldStyleParameters,
    );
    styleName.textContent = liveStyle.displayName;
    const authored = Object.entries(defaultStyleParameters).every(
      ([key, value]) => current.worldStyleParameters[key] === value,
    );
    styleState.textContent = worldDirty()
      ? 'Previewing · not saved'
      : authored
        ? 'Authored default'
        : 'Personal variation';
    root.dataset['worldDirty'] = worldDirty() ? 'true' : 'false';
    undoWorld.toggleAttribute('disabled', !worldDirty());
    applyWorld.toggleAttribute('disabled', !worldDirty() || worldBusy);
    undoWorld.toggleAttribute('disabled', !worldDirty() || worldBusy);
    resetWorld.toggleAttribute('disabled', worldBusy);
    for (const { input } of styleInputs.values()) input.toggleAttribute('disabled', worldBusy);
    const palette = liveStyle.palette as unknown as Record<string, string>;
    for (const swatch of styleSwatches) {
      const role = swatch.dataset['paletteRole'];
      if (role !== undefined) swatch.style.backgroundColor = palette[role] ?? 'transparent';
    }
    for (const { definition, input, output } of styleInputs.values()) {
      const value = current.worldStyleParameters[definition.key] ?? definition.defaultValue;
      if (definition.kind === 'toggle') (input as HTMLInputElement).checked = value === true;
      else input.value = String(value);
      if (output !== undefined && definition.kind === 'range' && typeof value === 'number') {
        output.value = definition.capability === 'motion.tempo'
          ? `${value.toFixed(2)}×`
          : definition.min === 0 && definition.max === 1
            ? `${Math.round(value * 100)}%`
            : String(value);
      }
    }
  };

  contrast.addEventListener('change', () =>
    commit({ contrast: contrast.value as ContrastPreference }));
  transparency.addEventListener('change', () =>
    commit({ transparency: transparency.value as TransparencyPreference }));
  fieldOfView.addEventListener('input', () => preview({ fieldOfView: fieldOfView.valueAsNumber }));
  fieldOfView.addEventListener('change', () => callbacks.onChange(current));
  sensitivity.addEventListener('input', () =>
    preview({ mouseSensitivity: sensitivity.valueAsNumber }));
  sensitivity.addEventListener('change', () => callbacks.onChange(current));
  vignette.addEventListener('change', () =>
    commit({ vignette: vignette.value as VignettePreference }));
  companionBody.addEventListener('change', () =>
    commit({ companionBody: companionBody.value as CompanionBodyPreference }));
  companionColor.addEventListener('change', () =>
    commit({ companionColor: companionColor.value as CompanionColorPreference }));
  companionFace.addEventListener('change', () =>
    commit({ companionFace: companionFace.value as CompanionFacePreference }));
  for (const [key, { definition, input }] of styleInputs) {
    const stylePatch = (): Partial<AtlasPreferences> => {
      const value: WorldStyleParameterValue = definition.kind === 'range'
        ? (input as HTMLInputElement).valueAsNumber
        : definition.kind === 'toggle'
          ? (input as HTMLInputElement).checked
          : input.value;
      return { worldStyleParameters: { ...current.worldStyleParameters, [key]: value } };
    };
    if (definition.kind === 'range' || definition.kind === 'color') {
      input.addEventListener('input', () => preview(stylePatch()));
    } else {
      input.addEventListener('change', () => preview(stylePatch()));
    }
  }

  applyWorld.addEventListener('click', () => {
    if (!worldDirty()) return;
    const candidate = current;
    const commitApplied = (): void => {
      applied = normalisePreferences({
        ...applied,
        worldArtProfile: candidate.worldArtProfile,
        worldArtProfileVersion: candidate.worldArtProfileVersion,
        worldStyleParameters: candidate.worldStyleParameters,
      });
      current = applied;
      render();
      callbacks.onChange(applied);
    };
    if (callbacks.onWorldApply === undefined) {
      commitApplied();
      return;
    }
    worldBusy = true;
    render();
    void callbacks.onWorldApply(candidate).then((accepted) => {
      worldBusy = false;
      if (accepted) commitApplied();
      else render();
    }).catch(() => {
      worldBusy = false;
      render();
    });
  });
  undoWorld.addEventListener('click', discardWorldPreview);
  resetWorld.addEventListener('click', () => preview({
    worldStyleParameters: resolveWorldStyleParameters(
      current.worldArtProfile,
      {},
      current.worldArtProfileVersion,
    ),
  }));

  const controls = el('button', { type: 'button', class: 'text-action', text: 'View controls  ?' });
  controls.addEventListener('click', callbacks.onShowControls);
  const reset = el('button', { type: 'button', class: 'text-action', text: 'Restore defaults' });
  reset.addEventListener('click', () => {
    const worldWasChanged = !sameWorldStyle(applied, DEFAULT_PREFERENCES);
    applied = worldWasChanged
      ? normalisePreferences({
          ...DEFAULT_PREFERENCES,
          worldArtProfile: applied.worldArtProfile,
          worldArtProfileVersion: applied.worldArtProfileVersion,
          worldStyleParameters: applied.worldStyleParameters,
        })
      : DEFAULT_PREFERENCES;
    current = DEFAULT_PREFERENCES;
    render();
    callbacks.onChange(applied);
    if (worldWasChanged) callbacks.onPreview?.(current);
  });
  rollbackWorld.addEventListener('click', () => {
    if (callbacks.onWorldRollback === undefined || history.value.length === 0) return;
    worldBusy = true;
    render();
    void callbacks.onWorldRollback(history.value).then((restored) => {
      worldBusy = false;
      if (restored !== null) {
        applied = normalisePreferences(restored);
        current = applied;
        render();
        callbacks.onChange(applied);
      } else {
        render();
      }
    }).catch(() => {
      worldBusy = false;
      render();
    });
  });

  root.append(
    el('header', { class: 'overlay-head' }, [
      el('div', {}, [
        el('p', { class: 'overlay-kicker', text: 'Atlas system' }),
        el('h1', { id: 'options-title', text: 'Customize' }),
      ]),
      close,
    ]),
    el('div', { class: 'option-group appearance-options' }, [
      el('h2', { text: 'Display' }),
      field('Contrast', contrast, 'Strengthens edges and reading surfaces without changing evidence colors.'),
      field('Transparency', transparency, 'Reduced removes glass and grain beneath reading surfaces.'),
    ]),
    el('div', { class: 'option-group world-style-options' }, [
      el('div', { class: 'world-style-head' }, [
        el('h2', { text: 'World design' }),
        styleName,
        el('p', { class: 'option-note', text: activeStyle.description }),
        styleState,
        worldAuthority,
        worldVersion,
        worldProvenance,
        worldLifecycle,
      ]),
      el('div', {
        class: 'world-dna-strip', role: 'img',
        'aria-label': 'Colors shared by the world and its interface',
      }, styleSwatches),
      el('p', {
        class: 'world-style-explanation',
        text: 'These controls belong to this world design. Color, finish, and cadence flow into the world and its interface together.',
      }),
      ...styleFields,
      el('div', { class: 'world-style-assurance' }, [
        el('strong', { text: 'Always protected' }),
        el('span', {
          text: 'Your memories and evidence · certainty and provenance · navigation · command placement · Companion identity · readable contrast',
        }),
      ]),
      el('p', {
        class: 'world-style-future',
        text: 'Companion designs can be reviewed here when an upstream proposal service supplies bounded profile values. Atlas does not generate recipes or execute model output in the browser.',
      }),
      proposalReview,
      el('div', { class: 'world-style-source-action' }, [readSource, readSourceNote]),
      el('div', { class: 'world-style-actions' }, [undoWorld, resetWorld, applyWorld]),
      el('div', { class: 'world-style-history' }, [
        el('h3', { text: 'Version history' }),
        field('Saved version', history, 'Restoring creates a new immutable version; it never rewrites history.'),
        rollbackWorld,
      ]),
    ]),
    el('div', { class: 'option-group view-options' }, [
      el('h2', { text: 'View' }),
      field('Field of view', el('span', { class: 'range-control' }, [fieldOfView, fieldOfViewValue])),
      field('Look sensitivity', el('span', { class: 'range-control' }, [sensitivity, sensitivityValue])),
      field('Comfort vignette', vignette, 'Darkens the periphery while traversing; it does not hide evidence.'),
    ]),
    el('div', { class: 'option-group companion-options' }, [
      el('h2', { text: 'Companion' }),
      companionPreviewFrame,
      field('Shape', companionBody, 'Changes the silhouette without changing what the Companion may do.'),
      field('Color', companionColor),
      field('Expression', companionFace, 'Two slit eyes are the complete face; expression is visual only.'),
    ]),
    el('footer', { class: 'overlay-actions' }, [persistence, controls, reset]),
  );
  render();

  const modalFocus = createModalFocus(root, close);
  return {
    root,
    showSection(section) {
      const group = root.querySelector<HTMLElement>(
        section === 'world' ? '.world-style-options' : '.companion-options',
      );
      if (group === null) return;
      // The surface may still be hidden when this is called, and scrolling a hidden element does
      // nothing, so it waits for the frame in which it has been shown.
      requestAnimationFrame(() => {
        group.scrollIntoView({ block: 'start', behavior: 'auto' });
      });
    },
    preferences: () => current,
    setPreferences(value) {
      const preserveDraft = worldDirty() && sameWorldStyle(value, applied);
      const draftProfile = current.worldArtProfile;
      const draftProfileVersion = current.worldArtProfileVersion;
      const draftParameters = current.worldStyleParameters;
      applied = normalisePreferences(value);
      current = preserveDraft
        ? normalisePreferences({
            ...applied,
            worldArtProfile: draftProfile,
            worldArtProfileVersion: draftProfileVersion,
            worldStyleParameters: draftParameters,
          })
        : applied;
      render();
    },
    setVisible(visible) {
      if (!visible) discardWorldPreview();
      modalFocus.setVisible(visible);
    },
    reportPersistence(state) {
      persistence.textContent = state === 'saving'
        ? 'Saving this reviewed choice…'
        : state === 'saved'
          ? 'Saved across devices.'
          : state === 'failed'
            ? 'Applied on this device, but not saved across devices.'
            : '';
    },
    setWorldAuthority(value) {
      worldAuthority.textContent = value.detail;
      worldAuthority.dataset['state'] = value.state;
      worldVersion.textContent = value.revision === undefined || value.currentVersionId === undefined
        ? ''
        : `Current revision ${value.revision} · ${value.currentVersionId}`;
      worldProvenance.textContent = [
        value.provenance,
        ...(value.warnings ?? []),
      ].filter((item): item is string => item !== undefined && item.length > 0).join(' · ');
      history.replaceChildren(...(value.versions ?? []).map((version) => option(
        version.versionId,
        version.label,
      )));
      const selected = (value.versions ?? []).find((version) => version.current) ?? value.versions?.at(-1);
      history.value = selected?.versionId ?? '';
      const selectedIsCurrent = (value.versions ?? []).find(
        (version) => version.versionId === history.value,
      )?.current ?? true;
      rollbackWorld.toggleAttribute(
        'disabled',
        value.state !== 'ready' || callbacks.onWorldRollback === undefined || selectedIsCurrent,
      );
      history.onchange = () => {
        const chosen = (value.versions ?? []).find((version) => version.versionId === history.value);
        rollbackWorld.toggleAttribute(
          'disabled',
          value.state !== 'ready' || callbacks.onWorldRollback === undefined || chosen?.current !== false,
        );
      };
      proposalReview.hidden = value.proposal === undefined;
      if (value.proposal !== undefined) {
        const refinement = value.proposal.refinesProposalId === null
          ? 'Original proposal'
          : `Refines ${value.proposal.refinesProposalId}`;
        proposalReview.replaceChildren(
          el('strong', { text: `${value.proposal.origin} proposal ready for review` }),
          el('span', {
            text: `${value.proposal.referenceCount} provenance references · ${refinement}`,
          }),
          el('span', {
            text: value.proposal.model === null
              ? 'No model provenance'
              : `${value.proposal.model} · ${value.proposal.promptVersion ?? 'prompt version unavailable'}`,
          }),
        );
      } else {
        proposalReview.replaceChildren();
      }
    },
    reportWorldLifecycle(state, detail = '') {
      worldLifecycle.dataset['state'] = state;
      worldLifecycle.textContent = detail.length > 0
        ? detail
        : state === 'checking'
          ? 'Checking this preview against the current saved world…'
          : state === 'ready'
            ? 'Preview validated. Apply when it looks right.'
            : state === 'saved'
              ? 'World design saved as a new immutable version.'
              : state === 'stale'
                ? 'The saved world changed elsewhere. A fresh preview is ready; review it and apply again.'
                : state === 'failed'
                  ? 'The preview could not be validated or saved.'
                  : '';
    },
  };
}
