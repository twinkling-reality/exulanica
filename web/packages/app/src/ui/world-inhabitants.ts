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

import type { AtlasBinding, OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import type { SocietyAffordance, SocietyPlaces, SocietySnapshot } from '../society-api.js';
import {
  PLAYBACK_SPEEDS,
  type SocietyPlaybackControl,
  type SocietyPlaybackSpeed,
} from '../society-control-api.js';
import { societyEngine } from '../society-engines.js';
import { inhabitantWordsFrom, type InhabitantWords } from '../society-inhabitant-words.js';
import { say } from './copy.js';
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
  a_request_is_waiting: 'Someone was just asked to go somewhere, or a model\'s decision for someone waits for '
    + 'the next simulated minute. Advance one minute first, then ask again.',
  nowhere_to_arrive: 'They cannot come back yet: there is nowhere in this world they could reach. Put something '
    + `they can rest on or visit near where you arrive, then ask again. ${say('inhabitants.whereToPlace')}`,
  stale_society_state: 'This world changed while you were deciding. Look again, then ask again.',
  engine_keeps_its_people: 'The inhabitants of this world cannot be sent away.',
};

/** A refusal of the person's request, in words. The code stays in the detail line. */
export function refusalWords(refusal: NonNullable<InhabitantsView['refusal']>): string {
  const presence = PRESENCE_WORDS[refusal.code];
  if (presence !== undefined) return presence;
  if (refusal.code === 'no_reachable_targets') {
    return 'Nobody came in: there is nowhere in this world they could reach yet. Put something they can '
      + `rest on or visit near where you arrive, then ask again. ${say('inhabitants.whereToPlace')}`;
  }
  if (refusal.status === 424) return `Inhabitants cannot come in right now. ${refusal.detail}`;
  return `Inhabitants were not brought in. ${refusal.detail}`;
}

/** How often something happens, in words: "every second", "every 4 seconds", "every 2 minutes". */
export function everyWords(ms: number): string {
  if (ms >= 60_000 && ms % 60_000 === 0) {
    const minutes = ms / 60_000;
    return minutes === 1 ? 'every minute' : `every ${minutes} minutes`;
  }
  const seconds = Math.round(ms / 100) / 10;
  return seconds === 1 ? 'every second' : `every ${seconds} seconds`;
}

/** What the People nearby panel knows about playing this world on its own. */
export interface PlaybackView {
  /** The saved control and the host's statement, or null when neither could be read. */
  readonly control: SocietyPlaybackControl | null;
  /** A change the person asked for is on its way. */
  readonly busy: boolean;
}

/**
 * Whether Play is offered, and the words beside it. Play is offered only where the host says it
 * plays this world; elsewhere the host's own sentence says why not. Pause is offered whenever the
 * saved mode is playing, so a world saved as playing on a host that does not play it can still be
 * paused and advanced by hand.
 */
export function playbackWords(control: SocietyPlaybackControl | null): {
  readonly offerPlay: boolean;
  readonly offerPause: boolean;
  readonly status: string;
  readonly why: string | null;
} {
  if (control === null) {
    return { offerPlay: false, offerPause: false, status: '', why: 'Playing on its own is not available: this world\'s playback could not be read.' };
  }
  const host = control.hostPlayback;
  const playing = control.mode === 'playing';
  if (host === null) {
    return {
      offerPlay: false, offerPause: playing, status: '',
      why: 'This server does not say whether it plays worlds on its own, so Play is not offered. Advance one minute at a time instead.',
    };
  }
  if (!host.running) {
    return {
      offerPlay: false, offerPause: playing,
      status: playing ? 'Saved as playing, but nothing moves until this host plays it.' : '',
      why: `${host.reason} Advance one minute at a time instead.`,
    };
  }
  if (!control.playEligible && !playing) {
    return { offerPlay: false, offerPause: false, status: '', why: control.playIneligibleReason ?? 'This world cannot play on its own.' };
  }
  return {
    offerPlay: !playing, offerPause: playing,
    status: playing
      ? `Playing: one simulated minute ${everyWords(host.intervalMs)}.`
      : 'Paused. Press Play to watch them live.',
    why: null,
  };
}

/** Why the crowd moved somebody without walking (`CrowdJumpReason`), read from the crowd itself. */
type MovedReason = NonNullable<AtlasBinding['authoredSociety']>['societyJumps'][number]['reason'];

/** A person the view moved without walking, as the crowd names it (`CrowdJump`). */
export interface MovedWithoutWalking {
  readonly inhabitantId: string;
  readonly reason: MovedReason;
  readonly unreadTicks: number;
}

/**
 * Why somebody was moved without walking, in words, one entry per reason the crowd names: the
 * record type makes a reason without words, or words for no reason, a type error.
 */
const MOVED_WORDS: Readonly<Record<MovedReason, (unread: number) => string>> = {
  'minutes-not-read': (unread) => `this page missed ${unread === 1 ? 'a simulated minute' : `${unread} simulated minutes`}, so they are shown where they are now.`,
  'path-starts-elsewhere': () => 'they started this minute somewhere new.',
  'too-far-behind': () => 'this page fell behind them, so they are shown further along their way.',
  'no-recorded-path': () => 'this world does not record how they got there.',
  'not-newer': () => 'this page was shown an older minute, so they are shown where it says.',
};

/** One line for everyone the latest minute moved without walking, or null when nobody. */
export function movedWords(moved: readonly MovedWithoutWalking[]): string | null {
  if (moved.length === 0) return null;
  const first = moved[0]!;
  const words = MOVED_WORDS[first.reason];
  const because = words === undefined ? `of a reason this page has no words for (${first.reason}).` : words(first.unreadTicks);
  const who = moved.length === 1 ? 'Someone moved' : `${moved.length} people moved`;
  const others = moved.some((held) => held.reason !== first.reason) ? ' Others moved for other reasons.' : '';
  return `${who} without walking: ${because}${others}`;
}

/** An object placed or moved while people were here, and whether they have noticed it yet. */
export interface Noticing {
  readonly label: string;
  /** The simulated minute that notices it: the one after the minute the edit was made in. */
  readonly minute: number;
  readonly noticed: boolean;
}

export function noticeWords(noticing: Noticing): string {
  return noticing.noticed
    ? `They noticed ${noticing.label} at simulated minute ${noticing.minute}.`
    : `They notice ${noticing.label} at simulated minute ${noticing.minute}, the next one.`;
}

type Inhabitant = OwnedSocietyState['inhabitants'][number];

export { REASON_WORDS, type InhabitantWords } from '../society-inhabitant-words.js';

/**
 * Who a simulated person is and what they are doing, in words. Places are named by the titles of
 * the person's own objects (`placeRows`); a place the rows do not name is said to be gone rather
 * than guessed at. Somebody talking is named with the other person, by the display name `people`
 * gives them; talking has no content, so nothing here says what about. The words and the choice
 * among them are `inhabitantWordsFrom`, which the server's Companion follows too.
 */
export function inhabitantWords(
  person: Inhabitant,
  rows: readonly PlaceRow[],
  people: readonly Inhabitant[] = [],
): InhabitantWords {
  const named = new Map<string, string>();
  for (const row of rows) if (row.status.kind === 'usable') named.set(row.status.targetId, row.label);
  return inhabitantWordsFrom(
    person,
    (targetId) => named.get(targetId) ?? null,
    (id) => people.find((other) => other.id === id)?.display_name ?? null,
  );
}

export interface WorldInhabitantsPanel {
  readonly root: HTMLElement;
  readonly bringIn: HTMLButtonElement;
  readonly advance: HTMLButtonElement;
  /** Shown while people live here: the person's request to send everyone away. */
  readonly sendAway: HTMLButtonElement;
  /** Shown while they are away: the person's request to bring the same people back. */
  readonly bringBack: HTMLButtonElement;
  /** Play or Pause: offered where the host plays this world, or to pause one saved as playing. */
  readonly play: HTMLButtonElement;
  /** How fast a simulated minute passes while playing. */
  readonly pace: HTMLSelectElement;
  /** Say what is true now: nobody yet, a refusal, or who lives here and where they can go. */
  render(state: {
    readonly society: InhabitantsView;
    readonly objects: readonly InhabitedObject[] | null;
    /** Inhabitants whose recorded path moved them in the last simulated minute. */
    readonly walked: number;
    /** Why advancing is not possible now, or null when it is. */
    readonly advanceBlocked: string | null;
    /** Playing on its own; absent where this panel offers no playback. */
    readonly playback?: PlaybackView | null;
    /** Everyone the latest minute moved without walking. */
    readonly moved?: readonly MovedWithoutWalking[];
    /** The object last placed or moved while people were here. */
    readonly noticing?: Noticing | null;
  }): void;
  /** Say that nothing can be shown here, and why. */
  unavailable(reason: string): void;
}

export function buildWorldInhabitants(handlers: {
  readonly onBringIn: () => void;
  readonly onAdvance: () => void;
  readonly onSendAway: () => void;
  readonly onBringBack: () => void;
  readonly onPlay?: () => void;
  readonly onPause?: () => void;
  readonly onPace?: (speed: SocietyPlaybackSpeed) => void;
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
    text: 'They need somewhere to go: something to rest on or visit. '
      + `${say('inhabitants.whereToPlace')} Nothing comes in until you ask.`,
  });
  const refusal = el('p', { class: 'world-inhabitants-refusal', role: 'alert', hidden: true });
  const refusalCode = el('code');
  const refusalDetails = el('details', { hidden: true }, [el('summary', { text: 'Details' }), refusalCode]);
  const bringIn = el('button', { type: 'button', text: 'Bring in inhabitants' }) as HTMLButtonElement;
  const advance = el('button', { type: 'button', text: 'Advance one minute' }) as HTMLButtonElement;
  const sendAway = el('button', { type: 'button', text: 'Send everyone away' }) as HTMLButtonElement;
  const bringBack = el('button', { type: 'button', text: 'Bring them back' }) as HTMLButtonElement;
  const play = el('button', { type: 'button', text: 'Play', hidden: true }) as HTMLButtonElement;
  const pace = el('select', { 'aria-label': 'Pace' }) as HTMLSelectElement;
  for (const speed of PLAYBACK_SPEEDS) pace.append(el('option', { value: String(speed), text: `${speed}×` }));
  const paceLabel = el('label', { class: 'world-inhabitants-pace', hidden: true }, [document.createTextNode('Pace '), pace]);
  const playbackStatus = el('p', { class: 'world-inhabitants-playback', role: 'status', hidden: true });
  const playbackWhy = el('p', { class: 'world-help', hidden: true });
  const movedLine = el('p', { class: 'world-help world-inhabitants-moved', hidden: true });
  const noticeLine = el('p', { class: 'world-inhabitants-notice', role: 'status', hidden: true });
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
  play.addEventListener('click', () => (play.dataset['action'] === 'pause' ? handlers.onPause?.() : handlers.onPlay?.()));
  pace.addEventListener('change', () => handlers.onPace?.(Number(pace.value) as SocietyPlaybackSpeed));
  const root = el('section', { class: 'world-inhabitants', 'aria-label': 'Inhabitants' }, [
    heading, summary, about, need, refusal, refusalDetails, bringIn, bringBack, play, paceLabel,
    playbackStatus, playbackWhy, advance, advanceWhy, movedLine, noticeLine,
    sendAway, presenceHelp, area, placesHeading, placesList, select,
  ]);
  root.dataset['state'] = 'idle';

  /** Play, Pause and pace, while people are here; nothing about playing while nobody is. */
  const renderPlayback = (here: boolean, playback: PlaybackView | null | undefined): boolean => {
    const offered = here && playback !== null && playback !== undefined;
    const words = offered ? playbackWords(playback.control) : null;
    const playing = words?.offerPause === true;
    play.hidden = !(words?.offerPlay || words?.offerPause);
    play.textContent = playing ? 'Pause' : 'Play';
    play.dataset['action'] = playing ? 'pause' : 'play';
    play.disabled = playback?.busy === true;
    paceLabel.hidden = play.hidden;
    pace.disabled = playback?.busy === true;
    const control = playback?.control ?? null;
    if (control !== null) {
      pace.value = String(control.speed);
      // The host's base interval is its effective one times the speed it was read at.
      const host = control.hostPlayback;
      for (const option of pace.options) {
        const speed = Number(option.value);
        option.textContent = host === null
          ? `${speed}×`
          : `${speed}× · a minute ${everyWords(host.intervalMs * control.speed / speed)}`;
      }
    }
    playbackStatus.hidden = !words?.status;
    playbackStatus.textContent = words?.status ?? '';
    playbackWhy.hidden = !words?.why;
    playbackWhy.textContent = words?.why ?? '';
    return playing;
  };

  const render: WorldInhabitantsPanel['render'] = ({ society, objects, walked, advanceBlocked, playback, moved, noticing }) => {
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
    // While the world plays on its own, advancing by hand is not offered at all.
    const playing = renderPlayback(here, playback);
    advance.hidden = !here || playing;
    advance.disabled = society.busy || advanceBlocked !== null;
    advanceWhy.hidden = !here || playing || advanceBlocked === null;
    const movedText = here ? movedWords(moved ?? []) : null;
    movedLine.hidden = movedText === null;
    movedLine.textContent = movedText ?? '';
    noticeLine.hidden = !here || noticing === null || noticing === undefined;
    noticeLine.textContent = here && noticing ? noticeWords(noticing) : '';
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
    play,
    pace,
    render,
    unavailable(reason) {
      root.dataset['state'] = 'unavailable';
      summary.textContent = reason;
      for (const node of [need, refusal, refusalDetails, bringIn, bringBack, play, paceLabel, playbackStatus, playbackWhy,
        advance, advanceWhy, movedLine, noticeLine, sendAway, presenceHelp, area, placesHeading, placesList, select]) {
        node.hidden = true;
      }
    },
  };
}
