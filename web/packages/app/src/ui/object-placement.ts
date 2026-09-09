/**
 * The authored-object surface: choose a reviewed asset, put it somewhere, move it, run it, undo it.
 *
 * product-direction.md's first milestone asks for one created object and one reversible
 * interaction, and this is the panel both are reached from. It takes handlers and returns
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
 * and unselectable, with the recorded state beside it. Dropping it from the list would turn a
 * storage failure into a shorter menu, which is the one presentation of an absent asset that tells
 * the person nothing.
 *
 * The bounds the motion controls obey are passed IN rather than read from the behaviour registry
 * here, and they are the reviewed server registry's own: `travel_mm` and `period_milliseconds` are
 * integers in the units the wire uses, so the sliders move in whole millimetres and whole
 * milliseconds and no value is ever converted twice. A view that reached for the registry would be
 * a second declaration of a bound the server already owns.
 */

import { el, replace } from './dom.js';

export type MotionAxisKey = string;

export type BehaviourControlKey = 'trigger' | 'stop' | 'reset';

export interface ObjectRoleOption {
  readonly key: string;
  readonly label: string;
}

export interface ObjectAssetOption {
  readonly assetKey: string;
  readonly label: string;
  /** False when the reviewed bytes are not in storage. Listed anyway, and said so. */
  readonly available: boolean;
  /** The recorded state, when it is not `available`. Shown rather than smoothed over. */
  readonly unavailableReason: string | null;
  readonly licenceId: string;
}

export interface IntegerBound {
  readonly min: number;
  readonly max: number;
  readonly fallback: number;
}

export interface MotionBounds {
  readonly axes: readonly MotionAxisKey[];
  readonly axisFallback: MotionAxisKey;
  readonly easings: readonly string[];
  readonly easingFallback: string;
  readonly travelMm: IntegerBound;
  readonly periodMilliseconds: IntegerBound;
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
  readonly assetKey: string;
  readonly role: string;
  readonly motion: boolean;
  readonly axis: MotionAxisKey;
  readonly easing: string;
  readonly travelMm: number;
  readonly periodMilliseconds: number;
}

export interface ObjectPlacementHandlers {
  onPlace(draft: ObjectPlacementDraft): void;
  onSelect(objectId: string): void;
  onControl(objectId: string, action: BehaviourControlKey): void;
  onRemove(objectId: string): void;
  /** Take back the newest change to this world. The authority decides which one that is. */
  onUndo(): void;
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
  showAssets(assets: readonly ObjectAssetOption[], roles: readonly ObjectRoleOption[]): void;
  showObjects(rows: readonly PlacedObjectRow[], selectedId: string | null): void;
  /** Whether this world has an edit left to take back. */
  setUndoable(undoable: boolean): void;
  /**
   * An uncommitted nudge, described, or null when the selected object is where it is saved.
   *
   * The keys move the object in the world immediately, because a move you cannot see is a move you
   * cannot judge, and they write nothing. This is the control that turns what you can see into
   * what is saved, and it goes through the confirmation surface like every other write.
   */
  setPendingMove(summary: string | null): void;
  /** The one line this surface speaks in. `failure` is the only kind that is coloured. */
  report(message: string, kind?: 'progress' | 'failure' | 'settled'): void;
  setBusy(busy: boolean): void;
  /** The current form values, or null when no placeable asset is chosen. */
  draft(): ObjectPlacementDraft | null;
}

const MOTION_STATE_WORDS: Readonly<Record<PlacedObjectRow['motion'], string>> = Object.freeze({
  running: 'travelling',
  held: 'stopped part-way',
  'at-rest': 'still, where it was placed',
  none: 'no motion',
  unsupported: 'motion this build cannot run',
});

const AXIS_WORDS: Readonly<Record<string, string>> = Object.freeze({
  x: 'Side to side',
  y: 'Up and down',
  z: 'Forward and back',
});

const EASING_WORDS: Readonly<Record<string, string>> = Object.freeze({
  linear: 'An even pace',
  smooth: 'Easing in and out',
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
  const roleSelect = el('select', { class: 'object-placement-role', id: 'object-placement-role' });
  const motionToggle = el('input', { type: 'checkbox', id: 'object-placement-motion' });
  const axisSelect = el('select', { id: 'object-placement-axis' });
  const easingSelect = el('select', { id: 'object-placement-easing' });
  const travel = el('input', {
    type: 'range', id: 'object-placement-travel',
    min: bounds.travelMm.min, max: bounds.travelMm.max, step: 10,
    value: bounds.travelMm.fallback,
  });
  const period = el('input', {
    type: 'range', id: 'object-placement-period',
    min: bounds.periodMilliseconds.min, max: bounds.periodMilliseconds.max, step: 100,
    value: bounds.periodMilliseconds.fallback,
  });
  const travelValue = el('output');
  const periodValue = el('output');
  const placeButton = el('button', {
    type: 'button', class: 'primary object-placement-place', text: 'Place before me',
  });
  const objectList = el('ul', { class: 'object-placement-list' });
  const status = el('p', { class: 'object-placement-status', role: 'status', 'aria-live': 'polite' });
  const undoButton = el('button', { type: 'button', class: 'ghost', text: 'Take back the last change' });
  const close = el('button', { type: 'button', class: 'ghost', text: 'Close' });
  undoButton.addEventListener('click', () => handlers.onUndo());

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
    axisSelect.append(el('option', { value: axis, text: AXIS_WORDS[axis] ?? axis }));
  }
  // The registry declares its axes in coordinate order, which is not a preference order, and it
  // carries its own default. That default is the reviewed one, so the view uses it rather than
  // whichever option happens to be first.
  if (bounds.axes.includes(bounds.axisFallback)) axisSelect.value = bounds.axisFallback;
  for (const easing of bounds.easings) {
    easingSelect.append(el('option', { value: easing, text: EASING_WORDS[easing] ?? easing }));
  }
  if (bounds.easings.includes(bounds.easingFallback)) easingSelect.value = bounds.easingFallback;

  const motionFields = el('div', { class: 'object-placement-motion-fields' }, [
    field('object-placement-axis', 'Direction', axisSelect),
    field('object-placement-easing', 'How it moves', easingSelect),
    field('object-placement-travel', 'How far it travels', travel, travelValue),
    field('object-placement-period', 'How long one journey takes', period, periodValue),
  ]);

  const reflectMotion = (): void => {
    motionFields.hidden = !motionToggle.checked;
  };
  const reflectValues = (): void => {
    // Shown in the units a person thinks in, sent in the units the wire uses. The slider itself
    // is the wire's unit, so what is sent is exactly what was chosen.
    travelValue.textContent = `${(Number(travel.value) / 1000).toFixed(2)} m`;
    periodValue.textContent = `${(Number(period.value) / 1000).toFixed(1)} s`;
  };
  const reflectAsset = (): void => {
    const chosen = assetSelect.selectedOptions[0];
    placeButton.disabled = chosen === undefined || chosen.disabled;
  };

  motionToggle.addEventListener('change', reflectMotion);
  travel.addEventListener('input', reflectValues);
  period.addEventListener('input', reflectValues);
  assetSelect.addEventListener('change', reflectAsset);
  close.addEventListener('click', () => handlers.onClose());

  const currentDraft = (): ObjectPlacementDraft | null => {
    const chosen = assetSelect.selectedOptions[0];
    if (chosen === undefined || chosen.disabled || chosen.value.length === 0) return null;
    return Object.freeze({
      assetKey: chosen.value,
      role: roleSelect.value,
      motion: motionToggle.checked,
      axis: axisSelect.value === '' ? bounds.axisFallback : axisSelect.value,
      easing: easingSelect.value === '' ? bounds.easingFallback : easingSelect.value,
      travelMm: Math.round(Number(travel.value)),
      periodMilliseconds: Math.round(Number(period.value)),
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
      field('object-placement-role', 'What this is to you', roleSelect),
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
    el('div', { class: 'object-placement-actions' }, [undoButton, close]),
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

    showAssets(assets, roles) {
      replace(assetSelect, assets.map((asset) => {
        const option = el('option', {
          value: asset.assetKey,
          text: asset.available
            ? asset.label
            : `${asset.label} (${asset.unavailableReason ?? 'not in storage'})`,
        });
        option.disabled = !asset.available;
        return option;
      }));
      if (assets.length === 0) {
        const empty = el('option', { value: '', text: 'No reviewed objects are available' });
        empty.disabled = true;
        assetSelect.append(empty);
      }
      const first = assets.findIndex((asset) => asset.available);
      assetSelect.selectedIndex = first === -1 ? 0 : first;
      replace(roleSelect, roles.map((role) =>
        el('option', { value: role.key, text: role.label })));
      reflectAsset();
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

    setUndoable(undoable) {
      undoButton.disabled = !undoable;
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
