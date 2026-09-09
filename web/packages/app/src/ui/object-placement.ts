/**
 * The authored-object surface: choose a reviewed asset, put it somewhere, move it, run it, undo it.
 *
 * product-direction.md's first milestone asks for one created object and one reversible
 * interaction, and this is the panel both of them are reached from. It takes handlers and returns
 * elements, and that is the entire contract: it holds no client, no session, no renderer binding
 * and no credential, so the module that mounts it can put every write through the confirmation
 * surface without this file being able to go around it.
 *
 * Three things it deliberately does NOT do.
 *
 * **It does not write, and it does not know how.** Every control calls a handler. The mount routes
 * those through the confirmation surface and the world-objects client. A panel that could reach a
 * transport would be a second write path, and the reason there is exactly one is that the
 * confirmation surface is where a person reads what they are about to change.
 *
 * **It does not describe an object as something that was there.** An authored object is created,
 * not recovered, and the note at the top of the panel says so in the panel rather than in a
 * document nobody reads while placing one. `atlas-reconstruction-inspection.md` is strict that a
 * surface must not let a made thing read as a found one, and a panel that quietly added shapes to
 * a photographed place would be the clearest possible way to break that.
 *
 * **It does not hide an asset whose bytes are missing.** An unavailable asset is listed, named,
 * and unselectable, with the reason beside it. Dropping it from the list would turn a storage
 * failure into a shorter menu, which is the one presentation of an absent asset that tells the
 * person nothing.
 *
 * The numbers the motion controls are bounded by are passed IN rather than read from the
 * behaviour registry here. The registry declares them once; a view that reached for them would be
 * a second declaration, and the two would drift the first time a range changed.
 */

import { el, replace } from './dom.js';

export type MotionAxisKey = 'x' | 'y' | 'z';

export type BehaviourControlKey = 'trigger' | 'stop' | 'reset';

export interface ObjectOriginOption {
  readonly key: string;
  readonly label: string;
}

export interface ObjectAssetOption {
  readonly assetId: string;
  readonly label: string;
  /** False when the asset's bytes are not in storage. Listed anyway, and said so. */
  readonly available: boolean;
  readonly supportsMotion: boolean;
}

export interface MotionRangeOption {
  readonly min: number;
  readonly max: number;
  readonly fallback: number;
}

export interface MotionBounds {
  readonly axes: readonly MotionAxisKey[];
  readonly amplitude: MotionRangeOption;
  readonly period: MotionRangeOption;
}

/** What the panel shows for one object already in the world. */
export interface PlacedObjectRow {
  readonly objectId: string;
  readonly label: string;
  readonly regionLabel: string;
  /**
   * `none` means the object carries no behaviour; `unsupported` means it carries one this build
   * cannot run. The two are different facts and the panel says which.
   */
  readonly motion: 'running' | 'held' | 'at-rest' | 'none' | 'unsupported';
  /** A sentence the row must show, such as why a motion was refused. */
  readonly note: string | null;
}

export interface ObjectPlacementDraft {
  readonly assetId: string;
  readonly origin: string;
  readonly motion: boolean;
  readonly axis: MotionAxisKey;
  readonly amplitude: number;
  readonly period: number;
}

export interface ObjectPlacementHandlers {
  onPlace(draft: ObjectPlacementDraft): void;
  onSelect(objectId: string): void;
  onControl(objectId: string, action: BehaviourControlKey): void;
  onRemove(objectId: string): void;
  /** Put the accumulated nudge through the confirmation surface. */
  onSaveMove(): void;
  /** Put the object back where it is saved, writing nothing. */
  onDiscardMove(): void;
  onClose(): void;
}

export interface ObjectPlacementPanel {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
  visible(): boolean;
  showAssets(assets: readonly ObjectAssetOption[], origins: readonly ObjectOriginOption[]): void;
  showObjects(rows: readonly PlacedObjectRow[], selectedId: string | null): void;
  /**
   * An uncommitted nudge, described, or null when the selected object is where it is saved.
   *
   * The keys move the object in the world immediately, because a move you cannot see is a move
   * you cannot judge, and they write nothing. This is the control that turns what you can see
   * into what is saved, and it goes through the confirmation surface like every other write.
   */
  setPendingMove(summary: string | null): void;
  /** The one line this surface speaks in. `failure` is the only kind that is coloured. */
  report(message: string, kind?: 'progress' | 'failure' | 'settled'): void;
  setBusy(busy: boolean): void;
  /** The current form values, or null when no placeable asset is chosen. */
  draft(): ObjectPlacementDraft | null;
}

const MOTION_STATE_WORDS: Readonly<Record<PlacedObjectRow['motion'], string>> = Object.freeze({
  running: 'moving',
  held: 'stopped part-way',
  'at-rest': 'still, where it was placed',
  none: 'no motion',
  unsupported: 'motion not supported here',
});

const AXIS_WORDS: Readonly<Record<MotionAxisKey, string>> = Object.freeze({
  x: 'Side to side',
  y: 'Up and down',
  z: 'Forward and back',
});

export function buildObjectPlacement(
  handlers: ObjectPlacementHandlers,
  bounds: MotionBounds,
): ObjectPlacementPanel {
  const root = el('aside', {
    class: 'object-placement',
    'aria-labelledby': 'object-placement-title',
    hidden: '',
  });

  const assetSelect = el('select', { class: 'object-placement-asset', id: 'object-placement-asset' });
  const originSelect = el('select', { class: 'object-placement-origin', id: 'object-placement-origin' });
  const motionToggle = el('input', { type: 'checkbox', id: 'object-placement-motion' });
  const axisSelect = el('select', { id: 'object-placement-axis' });
  const amplitude = el('input', {
    type: 'range', id: 'object-placement-amplitude',
    min: bounds.amplitude.min, max: bounds.amplitude.max, step: 0.05,
    value: bounds.amplitude.fallback,
  });
  const period = el('input', {
    type: 'range', id: 'object-placement-period',
    min: bounds.period.min, max: bounds.period.max, step: 0.5,
    value: bounds.period.fallback,
  });
  const amplitudeValue = el('output', { text: bounds.amplitude.fallback.toFixed(2) });
  const periodValue = el('output', { text: `${bounds.period.fallback.toFixed(1)}s` });
  const placeButton = el('button', {
    type: 'button', class: 'primary object-placement-place', text: 'Place before me',
  });
  const objectList = el('ul', { class: 'object-placement-list' });
  const status = el('p', { class: 'object-placement-status', role: 'status', 'aria-live': 'polite' });
  const close = el('button', { type: 'button', class: 'ghost', text: 'Close' });

  const pendingText = el('span', { class: 'object-placement-pending-text' });
  const saveMove = el('button', { type: 'button', class: 'primary', text: 'Save this position' });
  const discardMove = el('button', { type: 'button', class: 'ghost', text: 'Put it back' });
  saveMove.addEventListener('click', () => handlers.onSaveMove());
  discardMove.addEventListener('click', () => handlers.onDiscardMove());
  const pending = el('div', { class: 'object-placement-pending' }, [
    pendingText,
    el('div', { class: 'object-placement-controls' }, [saveMove, discardMove]),
  ]);
  pending.hidden = true;

  for (const axis of bounds.axes) {
    axisSelect.append(el('option', { value: axis, text: AXIS_WORDS[axis] }));
  }
  // The registry declares its axes in coordinate order, which is not a preference order. An
  // object placed standing on the ground bobs, so vertical is the default when it is offered.
  if (bounds.axes.includes('y')) axisSelect.value = 'y';

  const motionFields = el('div', { class: 'object-placement-motion-fields' }, [
    field('object-placement-axis', 'Direction', axisSelect),
    field('object-placement-amplitude', 'How far', amplitude, amplitudeValue),
    field('object-placement-period', 'How long one cycle takes', period, periodValue),
  ]);

  const reflectMotion = (): void => {
    motionFields.hidden = !motionToggle.checked;
  };
  const reflectValues = (): void => {
    amplitudeValue.textContent = Number(amplitude.value).toFixed(2);
    periodValue.textContent = `${Number(period.value).toFixed(1)}s`;
  };
  const reflectAssetMotion = (): void => {
    const chosen = assetSelect.selectedOptions[0];
    const supports = chosen?.dataset['motion'] === 'yes';
    motionToggle.disabled = !supports;
    if (!supports) motionToggle.checked = false;
    placeButton.disabled = chosen === undefined || chosen.disabled;
    reflectMotion();
  };

  motionToggle.addEventListener('change', reflectMotion);
  amplitude.addEventListener('input', reflectValues);
  period.addEventListener('input', reflectValues);
  assetSelect.addEventListener('change', reflectAssetMotion);
  close.addEventListener('click', () => handlers.onClose());

  const currentDraft = (): ObjectPlacementDraft | null => {
    const chosen = assetSelect.selectedOptions[0];
    if (chosen === undefined || chosen.disabled || chosen.value.length === 0) return null;
    return Object.freeze({
      assetId: chosen.value,
      origin: originSelect.value,
      motion: motionToggle.checked,
      axis: (axisSelect.value === '' ? 'y' : axisSelect.value) as MotionAxisKey,
      amplitude: Number(amplitude.value),
      period: Number(period.value),
    });
  };
  placeButton.addEventListener('click', () => {
    const draft = currentDraft();
    if (draft !== null) handlers.onPlace(draft);
  });

  replace(root, [
    el('h2', { id: 'object-placement-title', text: 'Objects you have added' }),
    el('p', { class: 'object-placement-note' }, [
      'Anything you add here is something you made. It is not part of what the photographs '
        + 'recorded, and adding it changes nothing about what this place was.',
    ]),
    el('div', { class: 'object-placement-form' }, [
      field('object-placement-asset', 'Object', assetSelect),
      field('object-placement-origin', 'What this is to you', originSelect),
      el('label', { class: 'object-placement-check', for: 'object-placement-motion' }, [
        motionToggle,
        el('span', { text: 'Give it a bounded motion' }),
      ]),
      motionFields,
      placeButton,
    ]),
    el('p', { class: 'object-placement-hint' }, [
      'Placed objects stand on the ground of the region you are in. With one selected, the arrow '
        + 'keys move it, Page Up and Page Down raise and lower it, and the bracket keys turn it. '
        + 'Each move is confirmed before it is saved.',
    ]),
    objectList,
    pending,
    status,
    el('div', { class: 'object-placement-actions' }, [close]),
  ]);

  reflectValues();
  reflectMotion();

  return {
    root,

    setVisible(visible) {
      root.hidden = !visible;
    },

    visible() {
      return !root.hidden;
    },

    showAssets(assets, origins) {
      replace(assetSelect, assets.map((asset) => {
        const option = el('option', {
          value: asset.assetId,
          text: asset.available
            ? asset.label
            : `${asset.label} (its file is not in storage)`,
        });
        option.disabled = !asset.available;
        option.dataset['motion'] = asset.supportsMotion ? 'yes' : 'no';
        return option;
      }));
      if (assets.length === 0) {
        const empty = el('option', { value: '', text: 'No reviewed objects are available' });
        empty.disabled = true;
        assetSelect.append(empty);
      }
      const first = assets.findIndex((asset) => asset.available);
      assetSelect.selectedIndex = first === -1 ? 0 : first;
      replace(originSelect, origins.map((origin) =>
        el('option', { value: origin.key, text: origin.label })));
      reflectAssetMotion();
    },

    showObjects(rows, selectedId) {
      replace(objectList, rows.map((row) => {
        const selected = row.objectId === selectedId;
        const item = el('li', { class: 'object-placement-item' });
        item.dataset['selected'] = selected ? 'yes' : 'no';

        const choose = el('button', {
          type: 'button',
          class: 'object-placement-choose',
          'aria-pressed': selected ? 'true' : 'false',
        }, [
          el('strong', { text: row.label }),
          el('span', { class: 'object-placement-where', text: row.regionLabel }),
          el('span', { class: 'object-placement-motion', text: MOTION_STATE_WORDS[row.motion] }),
        ]);
        choose.addEventListener('click', () => handlers.onSelect(row.objectId));

        const controls = el('div', { class: 'object-placement-controls' });
        const runnable = row.motion === 'running' || row.motion === 'held' || row.motion === 'at-rest';
        for (const [action, label] of [
          ['trigger', 'Start'], ['stop', 'Stop'], ['reset', 'Reset'],
        ] as const) {
          const button = el('button', { type: 'button', class: 'ghost', text: label });
          button.disabled = !runnable;
          button.addEventListener('click', () => handlers.onControl(row.objectId, action));
          controls.append(button);
        }
        const remove = el('button', { type: 'button', class: 'ghost object-placement-remove', text: 'Remove' });
        remove.addEventListener('click', () => handlers.onRemove(row.objectId));
        controls.append(remove);

        const children: HTMLElement[] = [choose, controls];
        if (row.note !== null) {
          children.splice(1, 0, el('p', { class: 'object-placement-item-note', text: row.note }));
        }
        replace(item, children);
        return item;
      }));
      if (rows.length === 0) {
        objectList.append(el('li', {
          class: 'object-placement-empty',
          text: 'You have not added anything to this world yet.',
        }));
      }
    },

    setPendingMove(summary) {
      pending.hidden = summary === null;
      pendingText.textContent = summary ?? '';
    },

    report(message, kind = 'progress') {
      status.textContent = message;
      status.dataset['kind'] = kind;
    },

    setBusy(busy) {
      root.dataset['busy'] = busy ? 'yes' : 'no';
      placeButton.disabled = busy || currentDraft() === null;
      for (const button of objectList.querySelectorAll('button')) button.disabled = busy;
      saveMove.disabled = busy;
      discardMove.disabled = busy;
    },

    draft: currentDraft,
  };
}

/**
 * A labelled control, once.
 *
 * `options.ts` builds one of these locally rather than exporting one, and this follows it: a
 * shared field helper would have to accept every surface's layout, and two of them agreeing on
 * three lines of markup is cheaper than one of them growing options.
 */
function field(id: string, label: string, control: HTMLElement, suffix?: HTMLElement): HTMLElement {
  return el('div', { class: 'object-placement-field' }, [
    el('label', { for: id, text: label }),
    suffix === undefined
      ? control
      : el('div', { class: 'object-placement-field-row' }, [control, suffix]),
  ]);
}
