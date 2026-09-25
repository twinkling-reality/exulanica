import * as pc from 'playcanvas';
import { activityPosture, catalogBase, catalogFamily, seatPosture } from '../character/catalog.js';
import { CHARACTER_CATALOG } from '../character/catalog-data.js';
import { FAR_REGIONS, FarPerson, farAppearance, farTemplateBytes, type FarAppearance } from '../character/far.js';
import { applicationOf } from '../character/host.js';
import { inhabitantLookOf } from '../character/inhabitant.js';

/**
 * Inhabitants beyond the full-detail places, each drawn in the far form of their own look.
 *
 * A far figure is the same person as the full character they become nearer: body, height and
 * region colours come from the look that person's stable id draws (`farAppearance`), which is also
 * what their full character shows while it loads and whenever it is drawn far. It has no rig, face
 * or clothing and does not pretend to; it keeps a person's silhouette and palette, a step rhythm
 * and a lean into travel. Each costs one draw call; the sculpt is shared by everyone of a body.
 */
export interface FarFigure {
  readonly id: string;
  readonly x: number;
  readonly z: number;
  /** Facing in radians about +Y with -Z forward, as a full character faces. */
  readonly facing: number;
  /** The activity the state says this person is performing, or null. */
  readonly activity?: string | null;
  /** Height of the figure's root above the ground, metres; absent is on the ground. */
  readonly y?: number;
  /** Whether the activity is performed on a seat, which the catalog may draw in its own posture. */
  readonly seated?: boolean;
}

interface Drawn {
  readonly person: FarPerson;
  x: number;
  z: number;
}

export class FarFigures {
  readonly root: pc.Entity;
  private readonly app: pc.AppBase;
  private readonly people = new Map<string, Drawn>();
  private readonly appearances = new Map<string, FarAppearance>();
  /** Each person's family, which says how an activity is drawn. */
  private readonly families = new Map<string, string>();

  constructor(private readonly device: pc.GraphicsDevice, parent: pc.Entity) {
    const app = applicationOf(device);
    if (!app) throw new Error('Far figures need the application that owns their graphics device');
    this.app = app;
    this.root = new pc.Entity('society-far-figures', app);
    parent.addChild(this.root);
  }

  get count(): number { return this.people.size; }

  /** The shared far sculpts of this device, counted once here for the whole crowd. */
  get residentBytes(): number {
    return farTemplateBytes(this.device);
  }

  /** Each figure's 5x1 palette; figures sharing a palette share its texture. */
  get textureResidentBytes(): number {
    const palettes = new Set<string>();
    for (const { person } of this.people.values()) palettes.add(FAR_REGIONS.map((region) => person.appearance.palette[region]).join(''));
    return palettes.size * FAR_REGIONS.length * 4;
  }

  /** What this crowd's far figure draws for an inhabitant: the far form of that person's look. */
  appearanceOf(id: string): FarAppearance {
    let held = this.appearances.get(id);
    if (!held) {
      const look = inhabitantLookOf(id);
      this.appearances.set(id, (held = farAppearance(CHARACTER_CATALOG, look)));
      this.families.set(id, look.familyId);
    }
    return held;
  }

  /**
   * The posture a person's far figure is drawn in for the activity the state gives them, on a seat
   * when `seated` says the activity is performed on one.
   */
  postureOf(id: string, activity: string | null | undefined, seated = false): string | null {
    this.appearanceOf(id);
    return activityPosture(catalogFamily(CHARACTER_CATALOG, this.families.get(id)!), activity, seated);
  }

  /**
   * How fast this person's full form walks at its walk clip's own cadence, metres per second: the
   * clip's measured ground speed at the base's rest height, scaled as the body is to theirs.
   */
  walkSpeedOf(id: string): number {
    const appearance = this.appearanceOf(id);
    const base = catalogBase(catalogFamily(CHARACTER_CATALOG, this.families.get(id)!), appearance.baseId);
    return (base.clips.walk.speedMillimetresPerSecond / base.restHeightMillimetres) * appearance.heightMetres;
  }

  /** The posture a person is drawn in on a seat for an activity, or null where none is declared. */
  seatPostureOf(id: string, activity: string | null | undefined): string | null {
    this.appearanceOf(id);
    return seatPosture(catalogFamily(CHARACTER_CATALOG, this.families.get(id)!), activity);
  }

  /** Place exactly these figures this frame; everyone else in the crowd is drawn elsewhere or not at all. */
  update(figures: readonly FarFigure[], deltaSeconds = 0, reducedMotion = false): void {
    const seen = new Set<string>();
    for (const figure of figures) {
      seen.add(figure.id);
      let drawn = this.people.get(figure.id);
      if (!drawn) {
        const person = new FarPerson(this.app, this.appearanceOf(figure.id));
        this.root.addChild(person.root);
        drawn = { person, x: figure.x, z: figure.z };
        this.people.set(figure.id, drawn);
      }
      const speed = deltaSeconds > 0 ? Math.hypot(figure.x - drawn.x, figure.z - drawn.z) / deltaSeconds : 0;
      drawn.x = figure.x;
      drawn.z = figure.z;
      drawn.person.root.setLocalPosition(figure.x, figure.y ?? 0, figure.z);
      drawn.person.root.setLocalEulerAngles(0, (figure.facing * 180) / Math.PI, 0);
      drawn.person.setPosture(this.postureOf(figure.id, figure.activity, figure.seated === true));
      drawn.person.update(speed, deltaSeconds, reducedMotion);
    }
    for (const [id, drawn] of this.people) {
      if (seen.has(id)) continue;
      drawn.person.destroy();
      this.people.delete(id);
    }
  }

  destroy(): void {
    for (const { person } of this.people.values()) person.destroy();
    this.people.clear();
    this.root.destroy();
  }
}
