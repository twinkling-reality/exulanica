/**
 * The inhabitants of a person's own saved world: whether anybody lives there, the one request that
 * brings them in, and where each of the person's objects stands for them.
 *
 * It builds elements and holds no client. The mount hands it the persisted society view and the
 * objects in the authored version, and it routes every request through handlers. Inhabitants are
 * simulated people: nothing here calls them anyone the person knows, and nothing presents what
 * they do as something that happened.
 *
 * Every statement about where inhabitants can go is read from the server's own record of the
 * input the society's current state consumed. The area they walk, its clearance and which object
 * nobody can reach are the server's numbers and verdicts, never figures kept in the browser.
 */

import type { SocietyAffordance, SocietyPlaces, SocietySnapshot } from '../society-api.js';
import { societyEngine } from '../society-engines.js';
import { el, replace } from './dom.js';
import './world-inhabitants.css';

/** What the panel reads of the persisted society view the mount holds. */
export interface InhabitantsView {
  readonly status: string;
  readonly busy: boolean;
  readonly snapshot: SocietySnapshot | null;
  readonly message: string;
  /** The server's refusal of the last request to bring inhabitants in, until the next one. */
  readonly refusal: { readonly status: number; readonly code: string; readonly detail: string } | null;
}

/** One object in the authored version, as the panel names and places it. */
export interface InhabitedObject {
  readonly objectId: string;
  readonly title: string;
  readonly xMm: number;
  readonly zMm: number;
}

export type PlaceStatus =
  | { readonly kind: 'usable'; readonly affordance: SocietyAffordance; readonly targetId: string; readonly room: number | null }
  | { readonly kind: 'unreachable'; readonly affordance: SocietyAffordance; readonly outsideArea: boolean }
  | { readonly kind: 'unusable'; readonly affordance: SocietyAffordance; readonly reason: string }
  | { readonly kind: 'not-noticed' };

/** The server's reason no inhabitant uses an object, other than being out of reach, in words. */
const UNUSABLE_WORDS: Readonly<Record<string, string>> = {
  authored_object_moves: 'Inhabitants do not use this while it moves.',
  authored_object_off_ground: 'Inhabitants cannot use this: it is not resting on the ground.',
  unsupported_active_behaviour: 'Inhabitants do not use this: they cannot tell where its movement takes it.',
};
const UNREACHABLE = 'authored_affordance_unreachable';
const ACTIVITY_WORDS: Readonly<Record<SocietyAffordance, string>> = { rest: 'rest', visit: 'visit' };

export interface PlaceRow {
  readonly object: InhabitedObject;
  /** The asset's title, numbered when two objects share one, so rows can be told apart. */
  readonly label: string;
  readonly status: PlaceStatus;
  readonly words: string;
}

const metres = (mm: number): number => Math.round(mm / 1000);

/**
 * How the area inhabitants walk is said. A ground that states its edge is walked to that edge; on
 * a ground that goes on for ever the society declared a square, and the words say the ground goes
 * on while they do not.
 */
export function areaWords(places: SocietyPlaces): string | null {
  const area = places.walkableArea;
  if (area === null) return null;
  const across = metres(2 * (area.halfWidthMm - places.clearanceMm));
  const deep = metres(2 * (area.halfDepthMm - places.clearanceMm));
  const size = across === deep
    ? `a square about ${across} metres across`
    : `an area about ${across} by ${deep} metres`;
  return area.source === 'declared'
    ? `They walk inside ${size} around where you arrive. The ground goes on; they do not.`
    : `They walk on this world's ground, ${size} just inside its edge.`;
}

function outsideArea(object: InhabitedObject, places: SocietyPlaces): boolean {
  const area = places.walkableArea;
  if (area === null) return false;
  return Math.abs(object.xMm - area.centreMm[0]) > area.halfWidthMm - places.clearanceMm
    || Math.abs(object.zMm - area.centreMm[1]) > area.halfDepthMm - places.clearanceMm;
}

/** Each object's standing for inhabitants, as the consumed input states it. */
export function placeRows(objects: readonly InhabitedObject[], places: SocietyPlaces): readonly PlaceRow[] {
  const seen = new Map<string, number>();
  const shared = new Map<string, number>();
  for (const object of objects) shared.set(object.title, (shared.get(object.title) ?? 0) + 1);
  return objects.map((object) => {
    const ordinal = (seen.get(object.title) ?? 0) + 1;
    seen.set(object.title, ordinal);
    const label = (shared.get(object.title) ?? 0) > 1 ? `${object.title} ${ordinal}` : object.title;
    const target = places.targets.find((held) => held.objectId === object.objectId && held.enabled);
    const unreachable = places.unreachable.find((held) => held.objectId === object.objectId);
    let status: PlaceStatus;
    let words: string;
    if (target !== undefined) {
      // Where the input states places, only that many use it at once and each has room.
      const room = target.placeNodeIds.length === 0 ? null : target.placeNodeIds.length;
      status = { kind: 'usable', affordance: target.affordance, targetId: target.targetId, room };
      const activity = ACTIVITY_WORDS[target.affordance];
      words = room === null
        ? `Inhabitants can ${activity} here.`
        : `Inhabitants can ${activity} here, ${room === 1 ? 'one' : room} at a time.`;
    } else if (unreachable !== undefined && unreachable.reason !== UNREACHABLE) {
      status = { kind: 'unusable', affordance: unreachable.affordance, reason: unreachable.reason };
      words = UNUSABLE_WORDS[unreachable.reason] ?? 'Inhabitants cannot use this.';
    } else if (unreachable !== undefined) {
      const outside = outsideArea(object, places);
      status = { kind: 'unreachable', affordance: unreachable.affordance, outsideArea: outside };
      words = outside
        ? 'Inhabitants cannot get close enough to use this: it is outside the area they walk in.'
        : 'Inhabitants cannot get close enough to use this.';
    } else {
      status = { kind: 'not-noticed' };
      words = 'Inhabitants notice this after the next simulated minute.';
    }
    return { object, label, status, words };
  });
}

/** Why the server would not send everyone away or bring them back, by the name it gave. */
const PRESENCE_WORDS: Readonly<Record<string, string>> = {
  nobody_to_send_away: 'Nobody is here to send away.',
  already_here: 'They are already here.',
  a_request_is_waiting: 'Someone was just asked to go somewhere. Advance one minute first, then ask again.',
  nowhere_to_arrive: 'They cannot come back yet: there is nowhere in this world they could reach. Put a Marker '
    + 'plate for them to rest on, or a Marker cube or pillar to visit, near where you arrive, then ask again.',
  stale_society_state: 'This world changed while you were deciding. Look again, then ask again.',
  engine_keeps_its_people: 'The inhabitants of this world cannot be sent away.',
};

/** A refusal of the person's request, in words. The code stays in the detail line. */
export function refusalWords(refusal: NonNullable<InhabitantsView['refusal']>): string {
  const presence = PRESENCE_WORDS[refusal.code];
  if (presence !== undefined) return presence;
  if (/reachable targets/.test(refusal.detail)) {
    return 'Nobody came in: there is nowhere in this world they could reach yet. Put a Marker plate '
      + 'for them to rest on, or a Marker cube or pillar to visit, near where you arrive, then ask again.';
  }
  if (refusal.status === 424) return `Inhabitants cannot come in right now. ${refusal.detail}`;
  return `Inhabitants were not brought in. ${refusal.detail}`;
}

export interface WorldInhabitantsPanel {
  readonly root: HTMLElement;
  readonly bringIn: HTMLButtonElement;
  readonly advance: HTMLButtonElement;
  /** Shown while people live here: the person's request to send everyone away. */
  readonly sendAway: HTMLButtonElement;
  /** Shown while they are away: the person's request to bring the same people back. */
  readonly bringBack: HTMLButtonElement;
  /** Say what is true now: nobody yet, a refusal, or who lives here and where they can go. */
  render(state: {
    readonly society: InhabitantsView;
    readonly objects: readonly InhabitedObject[] | null;
    /** Inhabitants whose recorded path moved them in the last simulated minute. */
    readonly walked: number;
    /** Why advancing is not possible now, or null when it is. */
    readonly advanceBlocked: string | null;
  }): void;
  /** Say that nothing can be shown here, and why. */
  unavailable(reason: string): void;
}

export function buildWorldInhabitants(handlers: {
  readonly onBringIn: () => void;
  readonly onAdvance: () => void;
  readonly onSendAway: () => void;
  readonly onBringBack: () => void;
}): WorldInhabitantsPanel {
  const heading = el('h3', { text: 'Inhabitants' });
  const summary = el('p', { class: 'world-inhabitants-summary', role: 'status', 'aria-live': 'polite' });
  const about = el('p', {
    class: 'world-help',
    text: 'Inhabitants are simulated people. They are invented, not anyone you know, and what '
      + 'they do is simulation, never a memory.',
  });
  const need = el('p', {
    class: 'world-help',
    text: 'They need somewhere to go: a Marker plate to rest on, or a Marker cube or pillar to '
      + 'visit. Nothing comes in until you ask.',
  });
  const refusal = el('p', { class: 'world-inhabitants-refusal', role: 'alert', hidden: true });
  const refusalCode = el('code');
  const refusalDetails = el('details', { hidden: true }, [el('summary', { text: 'Details' }), refusalCode]);
  const bringIn = el('button', { type: 'button', text: 'Bring in inhabitants' }) as HTMLButtonElement;
  const advance = el('button', { type: 'button', text: 'Advance one minute' }) as HTMLButtonElement;
  const sendAway = el('button', { type: 'button', text: 'Send everyone away' }) as HTMLButtonElement;
  const bringBack = el('button', { type: 'button', text: 'Bring them back' }) as HTMLButtonElement;
  const presenceHelp = el('p', { class: 'world-help', hidden: true });
  const advanceWhy = el('p', { class: 'world-help', hidden: true });
  const area = el('p', { class: 'world-help', hidden: true });
  const placesHeading = el('h4', { text: 'Where they can go', hidden: true });
  const placesList = el('ul', { class: 'world-inhabitants-places', hidden: true });
  const select = el('p', {
    class: 'world-help',
    hidden: true,
    text: 'Choose someone below, or aim at them and press E, to see what they are doing and ask '
      + 'them to rest or visit somewhere.',
  });
  bringIn.addEventListener('click', () => handlers.onBringIn());
  advance.addEventListener('click', () => handlers.onAdvance());
  sendAway.addEventListener('click', () => handlers.onSendAway());
  bringBack.addEventListener('click', () => handlers.onBringBack());
  const root = el('section', { class: 'world-inhabitants', 'aria-label': 'Inhabitants' }, [
    heading, summary, about, need, refusal, refusalDetails, bringIn, bringBack, advance, advanceWhy,
    sendAway, presenceHelp, area, placesHeading, placesList, select,
  ]);
  root.dataset['state'] = 'idle';

  const render: WorldInhabitantsPanel['render'] = ({ society, objects, walked, advanceBlocked }) => {
    const snapshot = society.snapshot;
    const present = snapshot !== null;
    root.dataset['state'] = present ? 'present' : society.status;
    refusal.hidden = society.refusal === null;
    refusalDetails.hidden = society.refusal === null;
    if (society.refusal !== null) {
      refusal.textContent = refusalWords(society.refusal);
      refusalCode.textContent = `${society.refusal.code}: ${society.refusal.detail}`;
    }
    // Sent away, the world still has its society and its history, and nobody in it. Whether its
    // people can be sent away at all is the engine table's to say.
    const away = present && snapshot.presence.status === 'away';
    const here = present && !away;
    const movable = present && societyEngine(snapshot.state.profile).presence;
    need.hidden = present;
    bringIn.hidden = present;
    bringIn.disabled = society.busy || society.status === 'unauthorized';
    bringIn.textContent = society.busy && !present ? 'Bringing them in…' : 'Bring in inhabitants';
    advance.hidden = !here;
    advance.disabled = society.busy || advanceBlocked !== null;
    advanceWhy.hidden = !here || advanceBlocked === null;
    advanceWhy.textContent = advanceBlocked ?? '';
    sendAway.hidden = !here || !movable;
    sendAway.disabled = society.busy;
    bringBack.hidden = !away;
    bringBack.disabled = society.busy;
    presenceHelp.hidden = !movable;
    presenceHelp.textContent = away
      ? 'Bringing them back is a new arrival: the same people come in at spread starting places in '
        + 'the world as it is when you ask, with nothing in hand. Their time here before they left '
        + 'stays in the history.'
      : 'Sending everyone away is kept in this world\'s history. You can bring the same people back later.';
    select.hidden = !here;
    if (!present) {
      summary.textContent = society.status === 'absent' || society.status === 'idle'
        ? 'Nobody lives here yet.'
        : society.message;
      area.hidden = true;
      placesHeading.hidden = true;
      placesList.hidden = true;
      replace(placesList, []);
      return;
    }
    const people = snapshot.populationSize;
    summary.textContent = away
      ? `Nobody lives here now: you sent everyone away at simulated minute ${snapshot.presence.sinceTick}.`
      : `${people} inhabitants live here. ${walked} walked in the last minute. `
        + `Simulated minute ${snapshot.currentTick}.`;
    const places = snapshot.places;
    const words = places === null ? null : areaWords(places);
    area.hidden = words === null;
    area.textContent = words ?? '';
    const rows = places === null || objects === null ? [] : placeRows(objects, places);
    placesHeading.hidden = rows.length === 0;
    placesList.hidden = rows.length === 0;
    replace(placesList, rows.map((row) => {
      const item = el('li', {}, [el('strong', { text: row.label }), document.createTextNode(` ${row.words}`)]);
      item.dataset['objectId'] = row.object.objectId;
      item.dataset['status'] = row.status.kind;
      if (row.status.kind === 'unusable') item.dataset['reason'] = row.status.reason;
      return item;
    }));
  };

  return {
    root,
    bringIn,
    advance,
    sendAway,
    bringBack,
    render,
    unavailable(reason) {
      root.dataset['state'] = 'unavailable';
      summary.textContent = reason;
      for (const node of [need, refusal, refusalDetails, bringIn, bringBack, advance, advanceWhy, sendAway, presenceHelp, area, placesHeading, placesList, select]) {
        node.hidden = true;
      }
    },
  };
}
