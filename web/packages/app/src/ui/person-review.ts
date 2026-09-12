/** Proposals, explicit identity and account-holder decisions over server-resolved states. */
import { buildPersonRegionEditor, type PersonRegionEditorInput } from './person-region-editor.js';
import { el, replace } from './dom.js';

/** One region as the review endpoint reports it. */
export interface ReviewRegion {
  readonly regionKey: string;
  readonly action: 'detected' | 'confirmed' | 'added' | 'deleted';
  readonly shape: 'box' | 'polygon';
  readonly silhouette: { readonly kind: string; readonly points: readonly (readonly number[])[] };
  readonly detectorId: string | null;
  /** Which visible trace this is, when the detector said. Null for a region a human drew. */
  readonly part:
    | 'full_body' | 'partial_body' | 'head' | 'torso' | 'arm'
    | 'hand' | 'leg' | 'foot' | 'reflection' | 'on_screen' | null;
  readonly confidence: 'low' | 'medium' | 'high' | null;
  readonly confirmedBy: string | null;
  readonly subjectId: string | null;
  readonly state: 'unknown' | 'present' | 'shown' | 'hidden' | 'withdrawn';
  readonly masked: boolean;
  readonly namePermitted: boolean;
}

export interface PersonReviewInput {
  readonly captureId: string;
  readonly reviewState: 'unscreened' | 'screened';
  readonly regions: readonly ReviewRegion[];
  readonly editor?: PersonRegionEditorInput;
  readonly onReload?: () => void;
  readonly onConfirm?: (regionKey: string) => void;
  readonly onDelete?: (regionKey: string) => void;
  readonly onIdentify?: (regionKey: string) => void;
  readonly onUnlink?: (regionKey: string) => void;
  readonly onCorrect?: (regionKey: string) => void;
  readonly selectedRegions?: ReadonlySet<string>;
  readonly onSelectRegion?: (regionKey: string, selected: boolean) => void;
  readonly onConsent?: (
    regionKey: string,
    scope: 'presence' | 'naming' | 'likeness' | 'temporary_hide',
    decision: 'granted' | 'revoked',
  ) => void;
}

const PPM = 1_000_000;

const STATE_COPY: Record<ReviewRegion['state'], string> = {
  unknown: 'Nobody has decided about this person. They are hidden.',
  present: 'Agreed to be recorded as present. Still hidden.',
  shown: 'Agreed to their likeness being shown.',
  hidden: 'Agreed to their likeness, hidden for now.',
  withdrawn: 'Consent withdrawn. Hidden, and their geometry is rebuilt without them.',
};

/**
 * The outline alone, on a neutral field.
 *
 * Inline SVG through `createElementNS`, because `el` builds HTML elements and an SVG child
 * created as HTML renders as nothing at all.
 */
function outline(region: ReviewRegion): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${PPM} ${PPM}`);
  svg.setAttribute('class', 'person-review-outline');
  svg.setAttribute('role', 'img');
  svg.setAttribute(
    'aria-label',
    `Outline of a person in this photograph, ${region.masked ? 'hidden' : 'shown'}.`,
  );
  const shape = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  shape.setAttribute('points', region.silhouette.points.map((p) => `${p[0]},${p[1]}`).join(' '));
  // Opaque, never translucent. A see-through silhouette over a photograph is still drawing the
  // photograph, which is the thing this must not do.
  shape.setAttribute('class', region.masked ? 'person-outline-hidden' : 'person-outline-shown');
  svg.append(shape);
  return svg;
}

const PART_COPY: Record<string, string> = {
  full_body: 'A whole person.',
  partial_body: 'Part of a person.',
  head: "Somebody's head.",
  torso: "Somebody's torso.",
  arm: "Somebody's arm.",
  hand: "Somebody's hand.",
  leg: "Somebody's leg.",
  foot: "Somebody's foot.",
  reflection: 'Somebody reflected in a surface.',
  on_screen: 'Somebody on a screen inside the photograph.',
};

/**
 * What kind of trace this is, in words.
 *
 * A reviewer is looking at an outline on a neutral field with no photograph behind it, so without
 * this a hand at the edge of a frame and a coat on a chair are the same grey shape. The partial
 * traces are the ones the old detector missed entirely, and they are the ones hardest to judge.
 */
function partSentence(region: ReviewRegion): string {
  if (region.part === null) return 'Drawn by a person reviewing this photograph.';
  return PART_COPY[region.part] ?? 'A trace of a person.';
}

function provenance(region: ReviewRegion): string {
  if (region.detectorId === null) return 'Added by a person reviewing this photograph.';
  const band = region.confidence === null ? 'no stated confidence' : `${region.confidence} confidence`;
  return `Proposed by ${region.detectorId} at ${band}. A proposal, not a decision.`;
}

export function buildPersonReview(input: PersonReviewInput): HTMLElement {
  const panel = el('section', { class: 'person-review' });
  panel.dataset.captureId = input.captureId;
  const body: (Node | string)[] = [el('h2', { text: 'People in this photograph' })];

  if (input.editor) body.push(buildPersonRegionEditor(input.editor));
  if (input.onReload) body.push(button('Reload review', input.onReload));

  if (input.reviewState === 'unscreened') {
    // Said as its own state rather than as an empty list. "Nobody has looked" and "somebody
    // looked and found nobody" are opposite answers that render identically if this is skipped.
    body.push(
      el('p', {
        class: 'person-review-unscreened',
        text:
          'No person regions are recorded yet. Detection may be pending or unavailable. ' +
          'An empty inventory is not a human no-person attestation.',
      }),
    );
    replace(panel, body);
    return panel;
  }

  if (input.regions.length === 0) {
    body.push(
      el('p', {
        class: 'person-review-empty',
        text: 'No active person regions remain. This does not establish a human no-person attestation.',
      }),
    );
    replace(panel, body);
    return panel;
  }

  body.push(
    el('p', {
      class: 'person-review-authority',
      text:
        'Every decision recorded here is yours as the account holder, not the decision of the ' +
        'person in the photograph. They have no way to answer for themselves yet.',
    }),
  );

  for (const region of input.regions) {
    const item = el('article', { class: 'person-review-region' });
    item.dataset.regionKey = region.regionKey;
    item.dataset.state = region.state;
    const controls = el('div', { class: 'person-review-controls' });

    if (input.onSelectRegion) {
      const select = el('input', { type: 'checkbox', 'aria-label': 'Select region for same-person linking' });
      select.checked = input.selectedRegions?.has(region.regionKey) ?? false;
      select.addEventListener('change', () => input.onSelectRegion?.(region.regionKey, select.checked));
      controls.append(el('label', {}, [select, 'Same person across photographs']));
    }
    if (region.action === 'detected') {
      controls.append(button('This is a person', () => input.onConfirm?.(region.regionKey)));
    }
    controls.append(button('Not a person', () => input.onDelete?.(region.regionKey)));
    if (input.onCorrect) controls.append(button('Correct outline', () => input.onCorrect?.(region.regionKey)));
    if (region.subjectId === null) {
      controls.append(el('p', { text: 'Identity not linked. Select matching regions or identify this person separately.' }));
      if (input.onIdentify) controls.append(button('Identify as a separate person', () => input.onIdentify?.(region.regionKey)));
    } else {
      controls.append(el('p', { text: `Person ${region.subjectId}` }));
      if (input.onUnlink) controls.append(button('Unlink incorrect identity', () => input.onUnlink?.(region.regionKey)));
      const choice = el('select', { 'aria-label': 'Account-holder decision for this region' });
      choice.append(el('option', { value: '', text: 'Choose the actual decision' }));
      const decisions = [
        ['presence', 'granted', 'Record presence consent'], ['presence', 'revoked', 'Withdraw presence'],
        ['naming', 'granted', 'Record naming consent'], ['naming', 'revoked', 'Withdraw naming'],
        ['likeness', 'granted', 'Record likeness consent'], ['likeness', 'revoked', 'Withdraw likeness'],
        ['temporary_hide', 'granted', 'Hide this person here'],
        ['temporary_hide', 'revoked', 'Show here if likeness is permitted'],
      ] as const;
      decisions.forEach(([, , label], i) => choice.append(el('option', { value: String(i), text: label })));
      const save = button('Record selected decision', () => {
        if (choice.value === '') return;
        const selected = decisions[Number(choice.value)];
        if (selected) input.onConsent?.(region.regionKey, selected[0], selected[1]);
      });
      save.disabled = true;
      choice.addEventListener('change', () => { save.disabled = choice.value === ''; });
      controls.append(choice, save);
    }

    item.append(
      outline(region),
      el('p', { class: 'person-review-part', text: partSentence(region) }),
      el('p', { class: 'person-review-state', text: STATE_COPY[region.state] }),
      el('p', { class: 'person-review-provenance', text: provenance(region) }),
      controls,
    );
    body.push(item);
  }

  replace(panel, body);
  return panel;
}

function button(label: string, onClick: () => void): HTMLButtonElement {
  const node = el('button', { type: 'button', class: 'person-review-action', text: label });
  node.addEventListener('click', onClick);
  return node;
}
