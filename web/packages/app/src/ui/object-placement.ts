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
 *
 * A motion can be given when an object is placed, and given, changed or taken away later from the
 * object's own row. Both use the same four controls, so both offer exactly the reviewed choices. A
 * later change is its own edit, which is what lets "take back the last change" undo the motion and
 * leave the object where it stands.
 */

import type { KindUse } from '@exulanica/atlas-react/playcanvas';
import type { KindActivity } from '../world-objects-api.js';
import { fill, say } from './copy.js';
import { el, replace } from './dom.js';

export type MotionAxisKey = string;

/**
 * What inhabitants do with a kind, in words, from the server's asset row alone.
 *
 * How many at a time is the number of places the kind states, what they do is the purposeful
 * routine's label, and how long they stay is its shortest and longest, one simulated minute a
 * tick. The words are copy's templates. Nothing here names a kind, an activity or a duration: a
 * kind the row gives no activity is one inhabitants do not use, and a row that states no use (an
 * asset the catalog does not state, or a row read embedded in a version) gets no sentence.
 */
export function objectUseWords(
  use: KindUse | null | undefined,
  activity: KindActivity | null | undefined,
): string | null {
  if (use === null || use === undefined || activity === undefined) return null;
  if (activity === null) return say('objectUse.unused');
  const shortest = activity.durationMinimumTicks;
  const longest = activity.durationMaximumTicks;
  const stay = shortest !== longest
    ? fill('objectUse.stay.range', { minimum: String(shortest), maximum: String(longest) })
    : shortest === 1
      ? say('objectUse.stay.oneMinute')
      : fill('objectUse.stay.minutes', { minutes: String(shortest) });
  if (use.places === null) return fill('objectUse.withoutPlaces', { activity: activity.label, stay });
  if (use.places.length === 1) return fill('objectUse.withOnePlace', { activity: activity.label, stay });
  return fill('objectUse.withPlaces', {
    count: String(use.places.length), activity: activity.label, stay,
  });
}

export type BehaviourControlKey = 'trigger' | 'stop' | 'reset';

export interface ObjectRoleOption {
  readonly key: string;
  readonly label: string;
}

export interface ObjectAssetOption {
  readonly assetKey: string;
  readonly label: string;
  /** What the object is, in the reviewed catalog's words, shown under the choice. */
  readonly summary: string;
  /**
   * What inhabitants do with it, shown under the summary: `objectUseWords` of the served row, or
   * null where the row states no use.
   */
  readonly useWords: string | null;
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

/** A bounded motion as a person chose it, in the units the wire uses. */
export interface MotionDraft {
  readonly axis: MotionAxisKey;
  readonly easing: string;
  readonly travelMm: number;
  readonly periodMilliseconds: number;
}

/** What the panel shows for one object already in the world. */
export interface PlacedObjectRow {
  readonly objectId: string;
  readonly label: string;
  /**
   * `none` means the object carries no behaviour; `unsupported` means it carries one this client
   * cannot run. The two are different facts and the panel says which.
   */
  readonly motion: 'running' | 'held' | 'at-rest' | 'none' | 'unsupported';
  /**
   * The stored motion in this panel's own controls, so a change starts from what is saved. Null
   * when the object carries none, or carries one these controls cannot show exactly.
   */
  readonly storedMotion: MotionDraft | null;
  /** A sentence the row must show, such as why a motion was refused. */
  readonly note: string | null;
}

export interface ObjectPlacementDraft extends MotionDraft {
  readonly assetKey: string;
  readonly role: string;
  readonly motion: boolean;
}

export interface ObjectPlacementHandlers {
  onPlace(draft: ObjectPlacementDraft): void;
  /** Place the arrangement this panel offers, as its objects, with the role chosen. */
  onArrange(role: string): void;
  onSelect(objectId: string): void;
  onControl(objectId: string, action: BehaviourControlKey): void;
  /** Give a placed object this motion, or replace the one it has. Confirmed before it is saved. */
  onSetMotion(objectId: string, motion: MotionDraft): void;
  /** Take a placed object's motion away. Confirmed before it is saved. */
  onClearMotion(objectId: string): void;
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
  /** Close an object's motion controls once what they proposed is saved. A refusal leaves them. */
  closeMotionEditor(): void;
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
  unsupported: 'motion this client cannot run',
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

/** The slider steps a person drags in, where a stored value allows them. */
const TRAVEL_STEP_MM = 10;
const PERIOD_STEP_MILLISECONDS = 100;

/**
 * A control a busy panel disables and an idle one must not simply re-enable.
 *
 * Start, Stop and Reset on an object with no motion are disabled for a reason of their own. When
 * the panel stops being busy, only the controls without such a reason come back.
 */
const UNAVAILABLE = 'unavailable';

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
  const placementMotion = buildMotionControls('object-placement', bounds, null);
  const placeButton = el('button', {
    type: 'button', class: 'primary object-placement-place', text: 'Place before me',
  });
  const assetSummary = el('p', { class: 'object-placement-summary' });
  const assetUse = el('p', { class: 'object-placement-use' });
  const arrangeButton = el('button', {
    type: 'button', class: 'object-placement-arrange', text: 'Place a small square before me',
  });
  /** Each offered asset's summary, by key, for the line under the choice. */
  let summaries = new Map<string, string>();
  /** Each offered asset's use in words, by key, for the line under its summary. */
  let uses = new Map<string, string | null>();
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

  const motionFields = placementMotion.root;
  motionFields.classList.add('object-placement-motion-fields');

  const reflectMotion = (): void => {
    motionFields.hidden = !motionToggle.checked;
  };
  const reflectAsset = (): void => {
    const chosen = assetSelect.selectedOptions[0];
    placeButton.disabled = chosen === undefined || chosen.disabled;
    assetSummary.textContent = chosen === undefined ? '' : summaries.get(chosen.value) ?? '';
    const use = chosen === undefined ? null : uses.get(chosen.value) ?? null;
    assetUse.textContent = use ?? '';
    assetUse.hidden = use === null;
  };

  motionToggle.addEventListener('change', reflectMotion);
  assetSelect.addEventListener('change', reflectAsset);
  close.addEventListener('click', () => handlers.onClose());

  const currentDraft = (): ObjectPlacementDraft | null => {
    const chosen = assetSelect.selectedOptions[0];
    if (chosen === undefined || chosen.disabled || chosen.value.length === 0) return null;
    return Object.freeze({
      assetKey: chosen.value,
      role: roleSelect.value,
      motion: motionToggle.checked,
      ...placementMotion.read(),
    });
  };
  placeButton.addEventListener('click', () => {
    const draft = currentDraft();
    if (draft !== null) handlers.onPlace(draft);
  });
  arrangeButton.addEventListener('click', () => handlers.onArrange(roleSelect.value));

  replace(root, [
    el('h2', { id: 'object-placement-title', text: 'Objects you have added' }),
    el('p', { class: 'object-placement-note' }, [
      'Anything you add here is something you made. It is not part of what the photographs '
        + 'recorded, and adding it changes nothing about what this place was.',
    ]),
    el('div', { class: 'object-placement-form' }, [
      field('object-placement-asset', 'Object', assetSelect),
      assetSummary,
      assetUse,
      field('object-placement-role', 'What this is to you', roleSelect),
      el('label', { class: 'object-placement-check', for: 'object-placement-motion' }, [
        motionToggle,
        el('span', { text: 'Give it a bounded motion' }),
      ]),
      motionFields,
      placeButton,
    ]),
    el('div', { class: 'object-placement-arrangement' }, [
      el('p', { class: 'object-placement-hint' }, [
        'Or place a small square: several objects together in front of you, facing you, each its '
          + 'own change, so “Take back the last change” removes them one at a time. It brings '
          + 'nobody in.',
      ]),
      arrangeButton,
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

  reflectMotion();

  /**
   * The one object whose motion controls are open, and what has been chosen in them so far.
   *
   * Held here rather than in the row, because a refresh rebuilds every row: the chosen values
   * have to survive the redraw a Start press or a selection causes, or a half-made choice would
   * reset under the person's hand.
   */
  let editing: { readonly objectId: string; values: MotionDraft } | null = null;
  let rendered: { rows: readonly PlacedObjectRow[]; selectedId: string | null } = {
    rows: [], selectedId: null,
  };
  let busy = false;

  const motionEditor = (row: PlacedObjectRow, values: MotionDraft): HTMLElement => {
    const controls = buildMotionControls('object-motion', bounds, values, (draft) => {
      if (editing?.objectId === row.objectId) editing.values = draft;
    });
    controls.root.classList.add('object-placement-motion-fields');
    const save = el('button', { type: 'button', class: 'primary', text: 'Save this motion' });
    save.addEventListener('click', () => handlers.onSetMotion(row.objectId, controls.read()));
    const keep = el('button', { type: 'button', class: 'ghost', text: 'Keep it as it is' });
    keep.addEventListener('click', () => {
      editing = null;
      showObjects(rendered.rows, rendered.selectedId);
    });
    const buttons: HTMLElement[] = [save];
    if (row.motion !== 'none') {
      const takeAway = el('button', { type: 'button', class: 'ghost', text: 'Take its motion away' });
      takeAway.addEventListener('click', () => handlers.onClearMotion(row.objectId));
      buttons.push(takeAway);
    }
    buttons.push(keep);
    return el('div', {
      class: 'object-placement-motion-editor',
      role: 'group',
      'aria-label': `Motion for ${row.label}`,
    }, [
      el('p', {
        class: 'object-placement-motion-editor-note',
        text: row.motion === 'unsupported'
          ? 'Saving replaces the motion this client cannot run with the one chosen here.'
          : 'Saved as its own change, so it can be taken back without moving the object.',
      }),
      controls.root,
      el('div', { class: 'object-placement-controls' }, buttons),
    ]);
  };

  function showObjects(rows: readonly PlacedObjectRow[], selectedId: string | null): void {
    rendered = { rows, selectedId };
    if (editing !== null && !rows.some((row) => row.objectId === editing!.objectId)) editing = null;
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
        el('span', { class: 'object-placement-motion', text: MOTION_STATE_WORDS[row.motion] }),
      ]);
      choose.addEventListener('click', () => handlers.onSelect(row.objectId));

      const controls = el('div', { class: 'object-placement-controls' });
      const runnable = row.motion === 'running' || row.motion === 'held' || row.motion === 'at-rest';
      for (const [action, label] of [
        ['trigger', 'Start'], ['stop', 'Stop'], ['reset', 'Reset'],
      ] as const) {
        const button = el('button', { type: 'button', class: 'ghost', text: label });
        if (!runnable) button.dataset[UNAVAILABLE] = 'yes';
        button.disabled = busy || !runnable;
        button.addEventListener('click', () => handlers.onControl(row.objectId, action));
        controls.append(button);
      }
      const open = editing?.objectId === row.objectId;
      const motion = el('button', {
        type: 'button',
        class: 'ghost object-placement-motion-edit',
        'aria-expanded': open ? 'true' : 'false',
        text: row.motion === 'none' ? 'Give it motion' : 'Change its motion',
      });
      motion.disabled = busy;
      motion.addEventListener('click', () => {
        editing = editing?.objectId === row.objectId
          ? null
          : { objectId: row.objectId, values: row.storedMotion ?? placementMotion.fallback() };
        showObjects(rendered.rows, rendered.selectedId);
      });
      controls.append(motion);
      const remove = el('button', { type: 'button', class: 'ghost object-placement-remove', text: 'Remove' });
      remove.disabled = busy;
      remove.addEventListener('click', () => handlers.onRemove(row.objectId));
      controls.append(remove);

      const children: HTMLElement[] = [choose, controls];
      if (row.note !== null) {
        children.splice(1, 0, el('p', { class: 'object-placement-item-note', text: row.note }));
      }
      if (open) {
        children.push(motionEditor(row, editing!.values));
        for (const button of children[children.length - 1]!.querySelectorAll('button')) {
          button.disabled = busy;
        }
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
  }

  let restoreFocus: HTMLElement | null = null;
  return {
    root,

    setVisible(visible) {
      if (visible === !root.hidden) return;
      if (visible) restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      root.hidden = !visible;
      if (visible) close.focus({ preventScroll: true });
      else if (restoreFocus?.isConnected && restoreFocus.getClientRects().length) restoreFocus.focus({ preventScroll: true });
    },

    visible() {
      return !root.hidden;
    },

    showAssets(assets, roles) {
      summaries = new Map(assets.map((asset) => [asset.assetKey, asset.summary]));
      uses = new Map(assets.map((asset) => [asset.assetKey, asset.useWords]));
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
      // No role starts chosen, and a refresh keeps the one the person picked: a preselected
      // option would send an answer nobody gave.
      const chosenRole = roleSelect.value;
      const unchosen = el('option', { value: '', text: 'Choose one' });
      unchosen.disabled = true;
      replace(roleSelect, [unchosen, ...roles.map((role) =>
        el('option', { value: role.key, text: role.label }))]);
      const kept = roles.findIndex((role) => role.key === chosenRole);
      roleSelect.selectedIndex = kept === -1 ? 0 : kept + 1;
      reflectAsset();
    },

    showObjects,

    closeMotionEditor() {
      if (editing === null) return;
      editing = null;
      showObjects(rendered.rows, rendered.selectedId);
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

    setBusy(next) {
      busy = next;
      root.dataset['busy'] = next ? 'yes' : 'no';
      placeButton.disabled = next || currentDraft() === null;
      arrangeButton.disabled = next;
      for (const button of objectList.querySelectorAll<HTMLButtonElement>('button')) {
        button.disabled = next || button.dataset[UNAVAILABLE] === 'yes';
      }
      saveMove.disabled = next;
      discardMove.disabled = next;
    },

    draft: currentDraft,
  };
}

interface MotionControls {
  readonly root: HTMLElement;
  read(): MotionDraft;
  /** The reviewed defaults, which is what a motion starts from when none is stored. */
  fallback(): MotionDraft;
}

/**
 * Direction, pace, distance and duration, as four labelled controls.
 *
 * The same four serve placing an object with a motion and changing the motion of one already
 * placed, so both offer exactly the reviewed choices and bounds. `prefix` keeps their ids apart,
 * because the two can be on screen together.
 *
 * A slider moves in steps that are comfortable to drag. A stored value between two steps would be
 * snapped to one of them by the browser and then saved as a change nobody made, so a slider
 * starting from such a value moves in whole units instead.
 */
function buildMotionControls(
  prefix: string,
  bounds: MotionBounds,
  initial: MotionDraft | null,
  onInput: (draft: MotionDraft) => void = () => undefined,
): MotionControls {
  const fallback = (): MotionDraft => Object.freeze({
    axis: bounds.axisFallback,
    easing: bounds.easingFallback,
    travelMm: bounds.travelMm.fallback,
    periodMilliseconds: bounds.periodMilliseconds.fallback,
  });
  const start = initial ?? fallback();
  const stepFor = (value: number, min: number, step: number): number =>
    (value - min) % step === 0 ? step : 1;

  const axisSelect = el('select', { id: `${prefix}-axis` });
  const easingSelect = el('select', { id: `${prefix}-easing` });
  const travel = el('input', {
    type: 'range', id: `${prefix}-travel`,
    min: bounds.travelMm.min, max: bounds.travelMm.max,
    step: stepFor(start.travelMm, bounds.travelMm.min, TRAVEL_STEP_MM),
    value: start.travelMm,
  });
  const period = el('input', {
    type: 'range', id: `${prefix}-period`,
    min: bounds.periodMilliseconds.min, max: bounds.periodMilliseconds.max,
    step: stepFor(start.periodMilliseconds, bounds.periodMilliseconds.min, PERIOD_STEP_MILLISECONDS),
    value: start.periodMilliseconds,
  });
  const travelValue = el('output');
  const periodValue = el('output');

  for (const axis of bounds.axes) {
    axisSelect.append(el('option', { value: axis, text: AXIS_WORDS[axis] ?? axis }));
  }
  // The registry declares its axes in coordinate order, which is not a preference order, and it
  // carries its own default. That default is the reviewed one, so the view uses it rather than
  // whichever option happens to be first.
  if (bounds.axes.includes(start.axis)) axisSelect.value = start.axis;
  else if (bounds.axes.includes(bounds.axisFallback)) axisSelect.value = bounds.axisFallback;
  for (const easing of bounds.easings) {
    easingSelect.append(el('option', { value: easing, text: EASING_WORDS[easing] ?? easing }));
  }
  if (bounds.easings.includes(start.easing)) easingSelect.value = start.easing;
  else if (bounds.easings.includes(bounds.easingFallback)) easingSelect.value = bounds.easingFallback;

  const read = (): MotionDraft => Object.freeze({
    axis: axisSelect.value === '' ? bounds.axisFallback : axisSelect.value,
    easing: easingSelect.value === '' ? bounds.easingFallback : easingSelect.value,
    travelMm: Math.round(Number(travel.value)),
    periodMilliseconds: Math.round(Number(period.value)),
  });
  const reflect = (): void => {
    // Shown in the units a person thinks in, sent in the units the wire uses. The slider itself
    // is the wire's unit, so what is sent is exactly what was chosen.
    travelValue.textContent = `${(Number(travel.value) / 1000).toFixed(2)} m`;
    periodValue.textContent = `${(Number(period.value) / 1000).toFixed(1)} s`;
  };
  for (const control of [axisSelect, easingSelect, travel, period]) {
    control.addEventListener('input', () => { reflect(); onInput(read()); });
    control.addEventListener('change', () => { reflect(); onInput(read()); });
  }
  reflect();

  return {
    root: el('div', {}, [
      field(`${prefix}-axis`, 'Direction', axisSelect),
      field(`${prefix}-easing`, 'How it moves', easingSelect),
      field(`${prefix}-travel`, 'How far it travels', travel, travelValue),
      field(`${prefix}-period`, 'How long one journey takes', period, periodValue),
    ]),
    read,
    fallback,
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
