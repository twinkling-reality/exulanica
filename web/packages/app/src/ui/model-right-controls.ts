/**
 * The model rights a person may give over their own photos, drawn from what the server states.
 *
 * Every word a right is shown with comes from `GET /personal-admission`, in `model_right_offers`:
 * the tick's label, the notice, the name of the per-photo state and the words that stop it. This
 * module holds no wording of its own for any right and no list of roles, so a right the server
 * offers is drawn and one it stops offering is not. The notice goes back unchanged with the grant,
 * and the server compares it for exact equality and refuses anything else, which is what makes the
 * words a person read the words the receipt records.
 *
 * **Nothing is granted without the person's own tick.** Every box starts unticked, and the caller
 * takes every tick back whenever the photos it speaks about change.
 *
 * **A role is allowed only when every model it can reach is.** A role's chain can hold a primary
 * and a fallback, each with its own right, and a request to the role can reach either, so the
 * server refuses the role unless every model of the chain is covered. The state drawn here asks
 * the same question, and stopping a role ends every current right it holds over the photo.
 */

import { el, replace } from './dom.js';
import type { ModelRightOffer, ModelRightState } from '../personal-admission-api.js';

export interface ModelRightGrants {
  readonly root: HTMLElement;
  /** The line under the ticks that says how long a right would last. Filled by the caller. */
  readonly term: HTMLElement;
  /** Draw one unticked control per offer, in the server's order. Earlier ticks are taken back. */
  show(offers: readonly ModelRightOffer[]): void;
  /** The offers ticked now, each carrying the server's own notice. */
  chosen(): readonly ModelRightOffer[];
  /** Take every tick back. */
  reset(): void;
  /** Called after a tick changes. */
  onChange(handler: () => void): void;
}

export function buildModelRightGrants(groupLabel: string): ModelRightGrants {
  const list = el('div', { class: 'model-right-offers' });
  const term = el('p', { class: 'model-right-term' });
  const root = el('fieldset', { class: 'model-right-grants', 'aria-label': groupLabel }, [list, term]);
  root.style.minWidth = '0';
  let ticks: { offer: ModelRightOffer; input: HTMLInputElement }[] = [];
  const handlers: (() => void)[] = [];
  return {
    root,
    term,
    show(offers) {
      ticks = offers.map((offer) => {
        const input = el('input', { type: 'checkbox', 'aria-label': offer.label }) as HTMLInputElement;
        input.checked = false;
        input.addEventListener('change', () => { for (const handler of handlers) handler(); });
        return { offer, input };
      });
      replace(list, ticks.map(({ offer, input }) => el('div', {
        class: 'model-right-offer', 'data-role': offer.role,
      }, [
        el('label', { class: 'model-right-choice' }, [input, ` ${offer.label}`]),
        el('p', { class: 'model-right-notice', text: offer.notice }),
      ])));
      root.hidden = ticks.length === 0;
    },
    chosen() {
      return ticks.filter(({ input }) => input.checked).map(({ offer }) => offer);
    },
    reset() {
      for (const { input } of ticks) input.checked = false;
    },
    onChange(handler) {
      handlers.push(handler);
    },
  };
}

/** What one role's rights over one photo come to, as the server last reported them. */
export type ModelRightStanding = 'none' | 'current' | 'partial' | 'ended';

export interface RoleStanding {
  readonly offer: ModelRightOffer;
  readonly standing: ModelRightStanding;
  /** Every current right of this role over the photo. Stopping the role ends each of them. */
  readonly current: readonly ModelRightState[];
  /** A current right was granted against other words than the offer's, or against none. */
  readonly withoutTheseWords: boolean;
  /**
   * While the role is allowed, the end of its term as the server recorded it: the earliest, over
   * the chain's models, of the latest term among the current rights covering that model. The role
   * is allowed only while every model is, so the first model whose rights run out ends it.
   */
  readonly until: string | null;
  /** Every right of the role ended because the person stopped it, rather than by its term. */
  readonly stopped: boolean;
}

const isCurrent = (right: ModelRightState): boolean =>
  (right.state ?? (right.withdrawn ? 'ended' : 'current')) === 'current';

const sameModel = (a: ModelRightState['model'], b: ModelRightState['model']): boolean =>
  a.provider === b.provider && a.role === b.role && a.model_id === b.model_id &&
  (a.revision ?? null) === (b.revision ?? null);

const instant = (value: string): number => Date.parse(value);

/** One role's standing over one photo, from every right the photo's owner granted. */
export function standingOf(offer: ModelRightOffer, rights: readonly ModelRightState[]): RoleStanding {
  const mine = rights.filter((right) => right.model.role === offer.role);
  const current = mine.filter(isCurrent);
  // For each model of the chain, the current rights that cover it at the offer's destination.
  const covering = offer.models.map((model) => current.filter(
    (right) => right.destination === offer.destination && sameModel(right.model, model)));
  const covered = covering.length > 0 && covering.every((each) => each.length > 0);
  const standing: ModelRightStanding = mine.length === 0 ? 'none'
    : covered ? 'current'
    : current.length > 0 ? 'partial'
    : 'ended';
  const ends = covering.map((each) => each.reduce(
    (latest, right) => (instant(right.valid_until) > instant(latest) ? right.valid_until : latest),
    each[0]?.valid_until ?? ''));
  return {
    offer,
    standing,
    current,
    withoutTheseWords: standing === 'current' && current.some((right) => right.notice_current === false),
    until: covered ? ends.reduce((earliest, end) => (instant(end) < instant(earliest) ? end : earliest)) : null,
    stopped: standing === 'ended' && mine.every((right) => right.withdrawn),
  };
}

/** A server instant as the person's clock reads it, or as the server spelled it if unreadable. */
function shown(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** The state in a sentence fragment, named with the server's own short name for the right. */
export function standingText(standing: RoleStanding): string {
  const name = standing.offer.short;
  switch (standing.standing) {
    case 'none': return `${name}: not allowed`;
    case 'current': {
      const allowed = standing.until === null ? `${name}: allowed` : `${name}: allowed until ${shown(standing.until)}`;
      return standing.withoutTheseWords ? `${allowed}, without the wording shown here` : allowed;
    }
    case 'partial': return `${name}: not allowed for every model named here`;
    case 'ended': return standing.stopped ? `${name}: stopped` : `${name}: no longer allowed`;
  }
}

export interface StopHandlers {
  /** True while this role's stop is waiting for confirmation on this photo. */
  readonly confirming: boolean;
  /** True while another request is running or the page may not write. */
  readonly locked: boolean;
  readonly onAsk: () => void;
  readonly onStop: () => void;
  readonly onKeep: () => void;
}

/** The state line and, while any right of the role is current, the control that ends them. */
export function standingControls(standing: RoleStanding, handlers: StopHandlers): HTMLElement[] {
  const children: HTMLElement[] = [
    el('span', {
      class: 'photo-right-state', 'data-role': standing.offer.role, text: standingText(standing),
    }),
  ];
  if (standing.current.length === 0) return children;
  const offer = standing.offer;
  if (handlers.confirming) {
    const stop = el('button', { type: 'button', class: 'photo-right-stop-confirm', text: offer.stop_confirm });
    const keep = el('button', { type: 'button', text: 'Keep allowing them' });
    stop.disabled = handlers.locked;
    stop.onclick = () => { handlers.onStop(); };
    keep.onclick = () => { handlers.onKeep(); };
    children.push(el('div', {
      class: 'photo-right-confirm', role: 'group', 'aria-label': `Confirm: ${offer.stop_action}`,
    }, [
      el('p', { text: offer.stop }),
      el('div', { class: 'photo-reference-actions' }, [stop, keep]),
    ]));
    return children;
  }
  const ask = el('button', { type: 'button', class: 'photo-right-stop', text: offer.stop_action });
  ask.disabled = handlers.locked;
  ask.onclick = () => { handlers.onAsk(); };
  children.push(el('div', { class: 'photo-reference-actions' }, [ask]));
  return children;
}

/** Keep only offers whose words and terms are all present, so nothing is drawn from a half read. */
export function readOffers(value: unknown): readonly ModelRightOffer[] {
  if (!Array.isArray(value)) return [];
  const text = (field: unknown): field is string => typeof field === 'string' && field.trim() !== '';
  return value.filter((offer: Partial<ModelRightOffer> | null): offer is ModelRightOffer =>
    offer !== null && typeof offer === 'object'
    && text(offer.role) && text(offer.label) && text(offer.short) && text(offer.notice)
    && text(offer.stop) && text(offer.stop_action) && text(offer.stop_confirm)
    && text(offer.destination) && (offer.offered_with === 'detect' || offer.offered_with === 'review')
    && Array.isArray(offer.models) && offer.models.length > 0);
}
