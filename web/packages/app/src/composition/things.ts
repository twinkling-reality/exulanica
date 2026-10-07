/**
 * The things an open saved world's version places, drawn by their looks, and the one event a pick
 * of a drawn thing raises.
 *
 * The layer (`@exulanica/atlas-react/things`) stands each placed thing where the version puts it, in
 * the frame its region is drawn in, wearing its kind's look as the host's thing library serves it.
 * A pick (aiming and pressing E, through the saved world's interact handler) becomes one event on the
 * shell, `exulanica:thing-pick`, whose detail names the thing by every id the drawing knows and how
 * it was picked; the thing's card opens from that event. Dispatching the same event with a null
 * detail takes the ring away, as a card does when it closes.
 */
import {
  ThingCrowdFigures,
  ThingLayer,
  type PlacedThingRecord,
  type ThingLayerOptions,
  type ThingLibrary,
  type ThingMiss,
  type ThingPick,
} from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import type { Credentials } from '../config.js';
import { openThingLibrary } from '../things-library.js';
import { tokenBlock } from '../ui/system/token-values.js';
import type { PlacedThing } from '../world-objects-api.js';

export const THING_PICK_EVENT = 'exulanica:thing-pick';

export type ThingPickVia = 'aim' | 'pointer' | 'mark';

/** The event's detail: what was picked, and how; null when nothing is picked any more. */
export type ThingPickDetail = (ThingPick & { readonly via: ThingPickVia }) | null;

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
  /** Placed things drawn as nothing, and why. */
  readonly misses: readonly ThingMiss[];
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
    invalidate: deps.invalidate,
    reducedMotion: deps.reducedMotion,
  });
  // The ring follows the event, whoever raises it: a pick here, a card closing, a mark.
  const onPick = (event: Event) => {
    const detail = (event as CustomEvent<ThingPickDetail>).detail;
    layer.setPicked(detail === null ? null : { placedId: detail.placedId, thingId: detail.thingId, subjectId: detail.subjectId });
  };
  deps.shell.addEventListener(THING_PICK_EVENT, onPick);
  const crowdFigures = new ThingCrowdFigures({ maker: layer.maker });
  let destroyed = false;
  return {
    async setPlaced(things) {
      if (destroyed) return;
      await layer.setPlaced(things.map(placedThingRecord));
    },
    setSociety(state) {
      if (!destroyed) layer.setSociety(state, state === null ? null : crowdFigures);
    },
    crowdFigures,
    pick: (origin, direction) => layer.pick(origin, direction),
    raise(pick, via) {
      const detail: ThingPickDetail = pick === null ? null : Object.freeze({ ...pick, via });
      deps.shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, { bubbles: true, detail }));
    },
    get misses() {
      return layer.misses;
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
