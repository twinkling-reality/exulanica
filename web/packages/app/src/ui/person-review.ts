/**
 * The screen a reviewer uses to say who is in a photograph and what they agreed to.
 *
 * This replaces one checkbox. The old gate asked a person to attest that a photograph contained
 * nobody, and the only way to keep a usable collection was to answer yes; the retained bowl
 * review did exactly that over 51 frames containing diners' arms. So this panel is built around
 * the answers that were missing: this is a person, this is not, I missed one, and separately,
 * here is what each of them agreed to.
 *
 * Three things it deliberately does NOT do.
 *
 * It never renders the photograph behind the outlines. A review screen that showed the pixels
 * would be a place where an unconsented person is displayed, and drawing the very body the
 * feature exists to hide, in the tool built to hide it, would be a strange thing to ship. The
 * outlines are drawn on a neutral field with the frame's aspect, which is enough to tell one
 * person from another and to see a false positive.
 *
 * It does not offer a "consent on their behalf" control that pretends to be the subject's own
 * decision. Every consent recorded here is the account holder's, the API records `owner`, and
 * this panel says so in words next to the buttons rather than in a tooltip.
 *
 * It does not let a reviewer confirm everything at once. Bulk-confirm is the affordance that
 * turned the old gate into a formality, and a screen whose fastest path is "agree to all of it"
 * collects the same worthless answer in a new shape.
 */

import { el, replace } from './dom.js';

/** One region as the review endpoint reports it. */
export interface ReviewRegion {
  readonly regionKey: string;
  readonly action: 'detected' | 'confirmed' | 'added' | 'deleted';
  readonly shape: 'box' | 'polygon';
  readonly silhouette: { readonly kind: string; readonly points: readonly (readonly number[])[] };
  readonly detectorId: string | null;
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
  readonly onConfirm?: (regionKey: string) => void;
  readonly onDelete?: (regionKey: string) => void;
  readonly onConsent?: (
    regionKey: string,
    scope: 'presence' | 'naming' | 'likeness',
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

function provenance(region: ReviewRegion): string {
  if (region.detectorId === null) return 'Added by a person reviewing this photograph.';
  const band = region.confidence === null ? 'no stated confidence' : `${region.confidence} confidence`;
  return `Proposed by ${region.detectorId} at ${band}. A proposal, not a decision.`;
}

export function buildPersonReview(input: PersonReviewInput): HTMLElement {
  const panel = el('section', { class: 'person-review' });
  panel.dataset.captureId = input.captureId;
  const body: (Node | string)[] = [el('h2', { text: 'People in this photograph' })];

  if (input.reviewState === 'unscreened') {
    // Said as its own state rather than as an empty list. "Nobody has looked" and "somebody
    // looked and found nobody" are opposite answers that render identically if this is skipped.
    body.push(
      el('p', {
        class: 'person-review-unscreened',
        text:
          'Nobody has looked at this photograph for people yet, so it is not shown anywhere. ' +
          'That is different from a photograph somebody checked and found empty.',
      }),
    );
    replace(panel, body);
    return panel;
  }

  if (input.regions.length === 0) {
    body.push(
      el('p', {
        class: 'person-review-empty',
        text: 'Screened, and nobody was found in this photograph.',
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

    if (region.action === 'detected') {
      controls.append(
        button('This is a person', () => input.onConfirm?.(region.regionKey)),
        button('Not a person', () => input.onDelete?.(region.regionKey)),
      );
    } else {
      for (const scope of ['presence', 'naming', 'likeness'] as const) {
        const granted = scope === 'likeness' ? !region.masked : undefined;
        controls.append(
          button(
            granted === true ? `Withdraw ${scope}` : `Record ${scope} consent`,
            () =>
              input.onConsent?.(
                region.regionKey,
                scope,
                granted === true ? 'revoked' : 'granted',
              ),
          ),
        );
      }
    }

    item.append(
      outline(region),
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
