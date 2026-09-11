/**
 * The scene segments panel: the overlay switch beside the proof lens, and what it tints.
 *
 * This file builds elements and holds nothing else. Which segments exist, what they are called,
 * which colour each wears and whether a name may be proposed are all decided by
 * `composition/segments.ts` and arrive here as a model; a click, a hover or a submitted name leaves
 * as a handler call. It cannot reach the renderer or the graph, which is what
 * `ui-may-not-import-the-renderer` in `.dependency-cruiser.cjs` is protecting.
 *
 * The list is the keyboard route to everything a click in the inspector does. The world canvas is
 * `aria-hidden`, so selecting a segment there is a pointer gesture only, and every segment it could
 * select is also a row here with the same detail and the same naming form.
 *
 * Rendering is skipped when the model has not changed, and a name being typed survives the
 * re-renders that do happen: the panel is refreshed while the visitor walks, and a form that lost
 * its text every half second would be a form nobody could use.
 */

import { el, replace } from './dom.js';

export interface SceneSegmentsHandlers {
  onToggle(on: boolean): void;
  /** A row was pointed at or focused, or left. The world highlights that segment. */
  onHover(segmentId: string | null): void;
  onSelect(segmentId: string): void;
  onTravel(segmentId: string): void;
  /** Open the reconstruction inspector on this region, where a click can select a segment. */
  onInspect(): void;
  /** A name was submitted. Produces a proposal to read, never a write. */
  onName(segmentId: string, displayName: string): void;
}

export type SegmentNamingModel =
  | { readonly kind: 'named'; readonly sentence: string }
  | { readonly kind: 'offer'; readonly sentence: string }
  | { readonly kind: 'unavailable'; readonly reason: string }
  | { readonly kind: 'preview' };

export interface SegmentRowModel {
  readonly segmentId: string;
  readonly heading: string;
  /** Class, confidence and votes, in words. */
  readonly summary: string;
  /** The CSS colour the world tints this segment, or null when it is not tinted. */
  readonly swatch: string | null;
  /** Why this segment is listed and not tinted, or null. */
  readonly untinted: string | null;
  readonly selected: boolean;
  /** Shown when selected: the detector label, the entity, consent, and how it was selected. */
  readonly facts: readonly string[];
  readonly naming: SegmentNamingModel;
}

export interface SceneSegmentsModel {
  readonly on: boolean;
  readonly state: 'off' | 'nowhere' | 'loading' | 'failed' | 'ready';
  /** Which region the list is about, in words, or null. */
  readonly where: string | null;
  readonly message: string | null;
  readonly canInspect: boolean;
  readonly rows: readonly SegmentRowModel[];
  readonly notices: readonly string[];
  readonly pickSentence: string;
}

export interface SceneSegmentsPanel {
  readonly root: HTMLElement;
  render(model: SceneSegmentsModel): void;
  /** Bring the selected row into view, after a click in the world selected it. */
  revealSelected(): void;
}

const NAME_INPUT = 'segment-name';

export function buildSceneSegments(handlers: SceneSegmentsHandlers): SceneSegmentsPanel {
  const root = el('section', { class: 'scene-segments', 'aria-label': 'Scene segments' });
  let rendered = '';

  const row = (model: SegmentRowModel): HTMLElement => {
    const item = el('li', { class: 'scene-segment' });
    item.dataset['segmentId'] = model.segmentId;
    if (model.selected) item.setAttribute('aria-current', 'true');
    const swatch = el('span', { class: 'scene-segment-swatch', 'aria-hidden': 'true' });
    if (model.swatch === null) swatch.dataset['untinted'] = 'true';
    else swatch.style.backgroundColor = model.swatch;
    const select = el('button', {
      type: 'button',
      class: 'scene-segment-select',
      'aria-expanded': model.selected ? 'true' : 'false',
    }, [
      swatch,
      el('span', { class: 'scene-segment-heading', text: model.heading }),
      el('span', { class: 'scene-segment-summary', text: model.summary }),
    ]);
    select.addEventListener('click', () => handlers.onSelect(model.segmentId));
    const travel = el('button', {
      type: 'button',
      class: 'scene-segment-travel',
      text: 'Travel',
      'aria-label': `Travel to ${model.heading}`,
    });
    travel.addEventListener('click', () => handlers.onTravel(model.segmentId));
    item.append(el('div', { class: 'scene-segment-row' }, [select, travel]));
    if (model.untinted !== null) {
      item.append(el('p', { class: 'scene-segment-untinted', text: model.untinted }));
    }
    if (model.selected) item.append(detail(model));
    item.addEventListener('mouseenter', () => handlers.onHover(model.segmentId));
    item.addEventListener('mouseleave', () => handlers.onHover(null));
    item.addEventListener('focusin', () => handlers.onHover(model.segmentId));
    item.addEventListener('focusout', (event) => {
      if (!(event.relatedTarget instanceof Node) || !item.contains(event.relatedTarget)) handlers.onHover(null);
    });
    return item;
  };

  const detail = (model: SegmentRowModel): HTMLElement => {
    const section = el('div', { class: 'scene-segment-detail' },
      model.facts.map((fact) => el('p', { class: 'scene-segment-fact', text: fact })));
    const naming = model.naming;
    if (naming.kind === 'offer') {
      const form = el('form', { class: 'scene-segment-name' });
      const input = el('input', {
        type: 'text',
        name: NAME_INPUT,
        maxlength: 200,
        placeholder: 'Name or describe this',
        'aria-label': `Name or describe ${model.heading}`,
      });
      form.append(
        el('p', { class: 'scene-segment-fact', text: naming.sentence }),
        input,
        el('button', { type: 'submit', class: 'primary', text: 'Propose' }),
        el('p', { class: 'name-note' }, [
          'Nothing is written yet. This produces a proposal you can read before anything changes.',
        ]),
      );
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        const value = input.value.trim();
        if (value.length > 0) handlers.onName(model.segmentId, value);
      });
      section.append(form);
    } else if (naming.kind === 'named') {
      section.append(el('p', { class: 'scene-segment-fact', text: naming.sentence }));
    } else if (naming.kind === 'unavailable') {
      section.append(el('p', { class: 'scene-segment-fact', text: naming.reason }));
    } else {
      section.append(el('p', {
        class: 'detail-note preview-read-only-note',
        text: 'Naming is unavailable in the synthetic read-only preview.',
      }));
    }
    return section;
  };

  const render = (model: SceneSegmentsModel): void => {
    const signature = JSON.stringify(model);
    if (signature === rendered) return;
    rendered = signature;
    // What the visitor was typing, and where, so a refresh while walking does not take it away.
    const typing = root.querySelector<HTMLInputElement>(`input[name="${NAME_INPUT}"]`);
    const typedFor = typing?.closest<HTMLElement>('.scene-segment')?.dataset['segmentId'];
    const typed = typing?.value ?? '';
    const hadFocus = typing !== null && typing === document.activeElement;

    root.dataset['segments'] = model.on ? 'on' : 'off';
    const toggle = el('button', {
      type: 'button',
      class: 'scene-segments-toggle',
      'aria-pressed': model.on ? 'true' : 'false',
      text: model.on ? 'Segments overlay on' : 'Segments overlay off',
    });
    toggle.addEventListener('click', () => handlers.onToggle(!model.on));
    const children: HTMLElement[] = [
      el('h2', { text: 'Scene segments' }),
      toggle,
      el('p', {
        class: 'scene-segments-copy',
        text: 'Tints what the photographs found, one colour per entity, in the region you stand in. '
          + 'Switching it changes no scene, no rung and no receipt.',
      }),
    ];
    if (model.on) {
      if (model.where !== null) children.push(el('p', { class: 'scene-segments-where', text: model.where }));
      if (model.message !== null) {
        const message = el('p', { class: 'scene-segments-message', text: model.message });
        message.dataset['state'] = model.state;
        children.push(message);
      }
      if (model.canInspect) {
        const inspect = el('button', { type: 'button', class: 'scene-segments-inspect', text: 'Inspect this region' });
        inspect.addEventListener('click', () => handlers.onInspect());
        children.push(inspect);
      }
      if (model.rows.length > 0) {
        children.push(el('ol', { class: 'scene-segments-list', 'aria-label': 'Segments in this region' },
          model.rows.map(row)));
      }
      if (model.notices.length > 0) {
        children.push(el('ul', { class: 'scene-segments-notices' },
          model.notices.map((notice) => el('li', { text: notice }))));
      }
      if (model.state === 'ready') children.push(el('p', { class: 'scene-segments-pick', text: model.pickSentence }));
    }
    replace(root, children);

    if (typedFor === undefined) return;
    const restored = root.querySelector<HTMLElement>(`.scene-segment[data-segment-id="${typedFor}"]`)
      ?.querySelector<HTMLInputElement>(`input[name="${NAME_INPUT}"]`);
    if (restored === null || restored === undefined) return;
    restored.value = typed;
    if (hadFocus) restored.focus({ preventScroll: true });
  };

  return {
    root,
    render,
    revealSelected() {
      root.querySelector<HTMLElement>('.scene-segment[aria-current="true"]')?.scrollIntoView?.({ block: 'nearest' });
    },
  };
}
