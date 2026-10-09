/**
 * The things an open saved world's version places, drawn by their looks, and the two events the
 * drawing shares with a thing's card: the one a pick of a drawn thing raises, and the one a look
 * chosen for a thing raises.
 *
 * The layer (`@exulanica/atlas-react/things`) stands each placed thing where the version puts it, in
 * the frame its region is drawn in, wearing its kind's look as the host's thing library serves it.
 * A pick (aiming and pressing E, through the saved world's interact handler) becomes one event on the
 * shell, `exulanica:thing-pick`, whose detail names the thing by every id the drawing knows and how
 * it was picked; the thing's card opens from that event. Dispatching the same event with a null
 * detail takes the ring away, as a card does when it closes.
 *
 * A look chosen for a thing on the page (its look route answered) is told by one event on the shell,
 * `exulanica:thing-look-chosen`, whose detail names the thing by its id in the society; the world
 * page then reads the looks chosen at once and draws what the read lists, not what was sent.
 */
import {
  ThingCrowdFigures,
  ThingLayer,
  type PlacedThingRecord,
  type SocietyPoint,
  type ThingLayerOptions,
  type ThingLibrary,
  type ThingMiss,
  type ThingPick,
} from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import type { Credentials } from '../config.js';
import { openThingLibrary } from '../things-library.js';
import { tokenBlock } from '../ui/system/token-values.js';
import type { ThingLookChoice } from '../thing-looks-api.js';
import type { PlacedThing } from '../world-objects-api.js';

export const THING_PICK_EVENT = 'exulanica:thing-pick';

export type ThingPickVia = 'aim' | 'pointer' | 'mark';

/** The event's detail: what was picked, and how; null when nothing is picked any more. */
export type ThingPickDetail = (ThingPick & { readonly via: ThingPickVia }) | null;

/**
 * Raised on the shell, bubbling, once a look chosen for a thing is recorded (its look route
 * answered 200): the world page reads the looks chosen at once, outside the minute's read.
 */
export const THING_LOOK_CHOSEN_EVENT = 'exulanica:thing-look-chosen';

/** The look chosen event's detail: the thing whose look was chosen, by its id in the society. */
export interface ThingLookChosenDetail {
  readonly thingId: string;
}

export interface ThingsDependencies {
  readonly app: ThingLayerOptions['app'];
  readonly camera: ThingLayerOptions['camera'];
  readonly shell: HTMLElement;
  readonly credentials: Credentials;
  /** The entity a region's things stand in, or null where this world does not draw that region. */
  readonly regionRoot: ThingLayerOptions['regionRoot'];
  readonly invalidate: () => void;
  readonly reducedMotion: () => boolean;
  /** The library to read from; the host's, read with the credentials, when left out. */
  readonly library?: () => Promise<ThingLibrary>;
  /**
   * Whether a person's drawn walk for the latest state has ended (the society's crowd), which a
   * thing changing hands waits for; everyone's has, when left out.
   */
  readonly walkEnded?: (subjectId: string) => boolean;
  /** The society drawn now (its crowd's root and where each person's feet are), for Play this one's rings. */
  readonly society?: ThingLayerOptions['society'];
  /**
   * Whether a visitor the state has gone from is still drawn walking back into its gate (the
   * society's crowd), whose carried-out things stay in its hand until then; nobody is, when left out.
   */
  readonly leaving?: (subjectId: string) => boolean;
}

export interface MountedThings {
  /** Stand the version's placed things; resolves when every one is drawn or named a miss. */
  setPlaced(things: readonly PlacedThing[]): Promise<void>;
  /** The nearest drawn thing a world ray meets, and how far along it. */
  pick(origin: readonly [number, number, number], direction: readonly [number, number, number]): { readonly pick: ThingPick; readonly distance: number } | null;
  /** Raise the pick event for `pick`, or for nothing with null. */
  raise(pick: ThingPick | null, via: ThingPickVia): void;
  /**
   * What the world's society says about its things, or null when no society is shown: its beings
   * are drawn by the crowd through `crowdFigures`, its objects stand or are held as it says.
   */
  setSociety(state: OwnedSocietyState | null): void;
  /** How the society's crowd draws its things by their looks (`AuthoredRegionSociety.setFigures`). */
  readonly crowdFigures: ThingCrowdFigures;
  /**
   * The looks chosen for the society's things, by thing id (`GET .../thing-looks`): a person of a
   * kind wears its chosen look in the crowd, a placed thing in the layer; a thing with none wears its
   * kind's first look. The crowd is asked again by its caller (`refreshFigures`).
   */
  setLooks(choices: ReadonlyMap<string, ThingLookChoice>): void;
  /** Placed things drawn as nothing, and why. */
  readonly misses: readonly ThingMiss[];
  /** Play this one: ring the being the viewer plays at its feet, or none with null. */
  setPlayed(subjectId: string | null): void;
  /** Play this one: ring the ground where the played being's next walk goes (the society's own frame), or none with null. */
  setDestination(point: SocietyPoint | null): void;
  readonly layer: ThingLayer;
  destroy(): void;
}

/**
 * The ring's colour: the design tokens' signal colour, as tokens.css states it for the world's own
 * light (the ring stands in the world, whose light does not follow the interface's scheme).
 */
export function signalColour(): string {
  const value = tokenBlock(':root').get('--color-signal');
  if (value === undefined || !/^#[0-9a-f]{6}$/iu.test(value)) throw new Error('tokens.css :root --color-signal is not a colour');
  return value.toLowerCase();
}

/**
 * Play this one's rings: the world-mark person colour, the "You" pill's own, as tokens.css states it
 * (fixed in every scheme: it stands in the world).
 */
export function worldMarkPersonColour(): string {
  const value = tokenBlock(':root').get('--color-world-mark-person');
  if (value === undefined || !/^#[0-9a-f]{6}$/iu.test(value)) throw new Error('tokens.css :root --color-world-mark-person is not a colour');
  return value.toLowerCase();
}

/**
 * The dark edge Play this one's rings stand on: the world-mark person ink, the "You" pill's own words
 * colour, as tokens.css states it (fixed in every scheme), so the yellow ring reads on pale ground.
 */
export function worldMarkPersonInk(): string {
  const value = tokenBlock(':root').get('--color-world-mark-person-ink');
  if (value === undefined || !/^#[0-9a-f]{6}$/iu.test(value)) throw new Error('tokens.css :root --color-world-mark-person-ink is not a colour');
  return value.toLowerCase();
}

/**
 * How often the looks chosen for a society's things are read while one is drawn: one private read a
 * minute per open world page, which brings a choice made elsewhere (an owner's, in another browser)
 * and drops one the store no longer lists (a withdrawn look's).
 */
export const LOOKS_READ_INTERVAL_MS = 60_000;

/**
 * Whether the looks chosen for a society's things are to be read now: once a minute while a society
 * of things is drawn, the first time at once, and never within `LOOKS_READ_INTERVAL_MS` of the last
 * ask. A visitor's look is recorded in the minute that brings it in, so it is read within a minute.
 */
export function looksReadDue(askedAt: number, now: number): boolean {
  return now - askedAt >= LOOKS_READ_INTERVAL_MS;
}

export function placedThingRecord(thing: PlacedThing): PlacedThingRecord {
  return {
    thingId: thing.thingId,
    kind: thing.kind,
    regionId: thing.regionId,
    transform: {
      xMm: thing.transform.xMm,
      yMm: thing.transform.yMm,
      zMm: thing.transform.zMm,
      yawMicroradians: thing.transform.yawMicroradians,
      scaleMilli: thing.transform.scaleMilli,
    },
    removed: thing.removed,
  };
}

export async function mountThings(deps: ThingsDependencies): Promise<MountedThings> {
  const library = await (deps.library ?? (() => openThingLibrary(deps.credentials)))();
  const layer = new ThingLayer({
    app: deps.app,
    camera: deps.camera,
    library,
    regionRoot: deps.regionRoot,
    ringColour: signalColour(),
    personColour: worldMarkPersonColour(),
    personEdge: worldMarkPersonInk(),
    invalidate: deps.invalidate,
    reducedMotion: deps.reducedMotion,
    ...(deps.society ? { society: deps.society } : {}),
  });
  // The ring follows the event, whoever raises it: a pick here, a card closing, a mark.
  const onPick = (event: Event) => {
    const detail = (event as CustomEvent<ThingPickDetail>).detail;
    layer.setPicked(detail === null ? null : { placedId: detail.placedId, thingId: detail.thingId, subjectId: detail.subjectId });
  };
  deps.shell.addEventListener(THING_PICK_EVENT, onPick);
  let chosen: ReadonlyMap<string, ThingLookChoice> = new Map();
  /** The placed things a choice was last given to, so a choice withdrawn returns them to their first look. */
  let chosenPlaced = new Set<string>();
  /** Each placed thing's authored yaw, by its placed id, so a placed being stands as it was placed. */
  let placedYaw: ReadonlyMap<string, number> = new Map();
  const crowdFigures = new ThingCrowdFigures({
    maker: layer.maker,
    lookOf: (person) => chosen.get(person.id)?.look ?? null,
    placedYawOf: (placedId) => placedYaw.get(placedId) ?? null,
  });
  let destroyed = false;
  /** The being the viewer plays, as last handed to the layer. */
  let played: string | null = null;
  return {
    async setPlaced(things) {
      if (destroyed) return;
      placedYaw = new Map(things.map((thing) => [thing.thingId, thing.transform.yawMicroradians]));
      await layer.setPlaced(things.map(placedThingRecord));
    },
    setSociety(state) {
      if (!destroyed) layer.setSociety(state, state === null ? null : crowdFigures, deps.walkEnded ?? (() => true), deps.leaving ?? (() => false));
    },
    crowdFigures,
    setLooks(choices) {
      if (destroyed) return;
      chosen = choices;
      const placed = new Set<string>();
      for (const choice of choices.values()) {
        if (choice.placedId === null) continue;
        placed.add(choice.placedId);
        void layer.setLook(choice.placedId, choice.look);
      }
      for (const placedId of chosenPlaced) if (!placed.has(placedId)) void layer.setLook(placedId, null);
      chosenPlaced = placed;
    },
    pick: (origin, direction) => layer.pick(origin, direction),
    raise(pick, via) {
      const detail: ThingPickDetail = pick === null ? null : Object.freeze({ ...pick, via });
      deps.shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, { bubbles: true, detail }));
    },
    get misses() {
      return layer.misses;
    },
    setPlayed(subjectId) {
      // Every refresh of the marks says whom the viewer plays; the layer hears only a change.
      if (destroyed || subjectId === played) return;
      played = subjectId;
      layer.setPlayed(subjectId);
    },
    setDestination(point) {
      if (!destroyed) layer.setDestination(point);
    },
    layer,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      deps.shell.removeEventListener(THING_PICK_EVENT, onPick);
      layer.destroy();
    },
  };
}
