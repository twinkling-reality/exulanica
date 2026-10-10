/**
 * The things of a society of things, drawn by their own looks where the society's crowd walks them.
 *
 * A society of things (`exulanica-society/v7`) names each person's thing kind. The crowd
 * (`../society/crowd.ts`) still decides who is drawn and walks everyone along their recorded paths;
 * for a person whose look is not one of the world's people, it asks `figureFor`, and the renderable
 * made here draws that person by its look through the same figures a placed thing uses. A person
 * wears its kind's first look until a look is chosen for it; a person whose look is the people
 * catalog's is drawn as everyone is.
 *
 * A figure's look is read from the library while the crowd already walks the person: until it is
 * made nothing is drawn, and the last pose is handed over when it is. A look that cannot be made is
 * drawn as nothing, its reason kept by name (`misses`). What the person holds is the society's:
 * `setHolding` names the sockets holding something now, which the drawing of held things reads.
 */

import * as pc from 'playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { CHARACTER_RENDERABLE_TAG } from '../character/renderable.js';
import type { CrowdFigures } from '../society/crowd.js';
import type { CrowdPose, CrowdRenderable, CrowdRenderableFactory, InhabitantIdentity, SocietyInhabitantSnapshot } from '../society/types.js';
import { isMadeKind } from '../society/types.js';
import type { ThingFigureMaker } from './figure-maker.js';
import { refusalOf } from './figure-maker.js';
import type { Footprint } from './body-motion.js';
import { PresenceFigure, facingOfYaw, type ThingFigure } from './figures.js';
import type { Named } from './library.js';

/** A person's figure while its look is read: how tall to treat it before it stands. */
const PENDING_HEIGHT = 1.7;

export interface ThingFigureMiss {
  readonly subjectId: string;
  readonly reason: string;
  readonly detail: string;
}

export class ThingCrowdRenderable implements CrowdRenderable {
  readonly root: pc.Entity;
  readonly subject: CharacterSubject;
  facing = 0;
  private figureMade: ThingFigure | null = null;
  private last: (CrowdPose & { readonly yaw?: number }) | null = null;
  private holding: ReadonlySet<string> = new Set();
  private destroyed = false;

  constructor(parent: pc.Entity, identity: InhabitantIdentity, onMiss: (miss: ThingFigureMiss) => void, make: (parent: pc.Entity, stale: () => boolean) => Promise<ThingFigure | null>) {
    this.root = new pc.Entity(`thing-person:${identity.inhabitantId}`);
    // The native character runtime adopts what is not a character renderable; this draws itself.
    this.root.tags.add(CHARACTER_RENDERABLE_TAG);
    parent.addChild(this.root);
    this.subject = { kind: 'synthetic-inhabitant', ...identity };
    make(this.root, () => this.destroyed).then((figure) => {
      if (figure === null) return;
      if (this.destroyed) {
        figure.destroy();
        return;
      }
      this.figureMade = figure;
      if (this.last !== null) this.pose({ ...this.last, deltaSeconds: 0, discontinuity: true });
    }, (error: unknown) => {
      if (!this.destroyed) onMiss({ subjectId: identity.inhabitantId, reason: refusalOf(error), detail: error instanceof Error ? error.message : String(error) });
    });
  }

  /** The figure drawing this person, once made. */
  get figure(): ThingFigure | null {
    return this.figureMade;
  }

  get standingHeight(): number {
    return this.figureMade?.standingHeight ?? PENDING_HEIGHT;
  }

  /** The walking speed the figure's look declares, once the figure is made; null until then or for none. */
  get walkSpeed(): number | null {
    return this.figureMade?.walkSpeed ?? null;
  }

  /** The ground the figure's body covers, for a body whose kind states its extent; null until made or for none. */
  get footprint(): Footprint | null {
    return this.figureMade?.footprint ?? null;
  }

  /** The sockets holding something now, as the society's state says. */
  setHolding(sockets: ReadonlySet<string>): void {
    this.holding = sockets;
  }

  pose(pose: CrowdPose & { readonly yaw?: number }): void {
    if (pose.yaw !== undefined) this.facing = this.turned(pose.yaw, pose);
    this.last = pose;
    this.figureMade?.pose({
      position: pose.position,
      facing: this.facing,
      deltaSeconds: pose.deltaSeconds,
      holding: this.holding,
      activity: pose.activity ?? null,
      ...(pose.reducedMotion ? { reducedMotion: true } : {}),
      ...(pose.discontinuity ? { discontinuity: true } : {}),
    });
  }

  /**
   * The facing drawn this frame on the way to `wanted`. A body whose kind states its extent turns
   * no faster than its size lets it (`ThingFigure.turnRate`), the shorter way round; anyone else,
   * a figure not yet made and a pose that is a jump face `wanted` at once.
   */
  private turned(wanted: number, pose: CrowdPose): number {
    const rate = this.figureMade?.turnRate ?? null;
    if (rate === null || pose.discontinuity || this.last === null) return wanted;
    const turn = Math.atan2(Math.sin(wanted - this.facing), Math.cos(wanted - this.facing));
    const most = rate * Math.max(0, pose.deltaSeconds);
    return Math.abs(turn) <= most ? wanted : this.facing + Math.sign(turn) * most;
  }

  setVisible(visible: boolean): void {
    this.root.enabled = visible;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.figureMade?.destroy();
    this.figureMade = null;
    this.root.destroy();
  }
}

export interface ThingCrowdFiguresOptions {
  readonly maker: ThingFigureMaker;
  /** The look chosen for a person, or null for its kind's first look. */
  readonly lookOf?: (person: SocietyInhabitantSnapshot) => Named | null;
  /** A placed thing's authored yaw by its placed id, or null for one not placed (`facingOfYaw`). */
  readonly placedYawOf?: (placedId: string) => number | null;
}

/**
 * The crowd's figures for a society of things: a factory for each person whose kind's look (or
 * chosen look) is not the people catalog's, keyed by that look so a changed look makes it again.
 */
export class ThingCrowdFigures implements CrowdFigures {
  private readonly made = new Map<string, ThingCrowdRenderable>();
  private readonly missed = new Map<string, ThingFigureMiss>();
  /** Looks by `key/version/sha256` that draw as one of the world's people. */
  private readonly catalogLooks: ReadonlySet<string>;

  constructor(private readonly options: ThingCrowdFiguresOptions) {
    const library = options.maker.library;
    this.catalogLooks = new Set(library.list.looks.filter((look) => look.lookKind === 'catalog_person').map((look) => `${look.look}/${look.version}/${look.sha256}`));
  }

  figureFor(person: SocietyInhabitantSnapshot): { readonly key: string; readonly factory: CrowdRenderableFactory } | null {
    const kind = person.kind;
    if (kind === undefined) return null;
    const library = this.options.maker.library;
    // A kind its workspace keeps is named by its digest alone: the maker asks the workspace for
    // it, and with no look chosen draws its kind's first look, its sketch.
    const made = isMadeKind(kind);
    const listed = made ? undefined : library.list.kinds.find((one) => one.kind === kind.kind && one.version === kind.version && one.sha256 === kind.sha256);
    const look = this.options.lookOf?.(person) ?? (listed === undefined ? null : listed.looks[0] ?? null);
    const lookKey = look === null ? 'none' : `${look.key}/${look.version}/${look.sha256}`;
    // A person whose look is the people catalog's is one of the world's people, drawn as today.
    if (this.catalogLooks.has(lookKey)) return null;
    const key = `${made ? 'workspace' : `${kind.kind}/${kind.version}`}/${kind.sha256}|${lookKey}`;
    const factory: CrowdRenderableFactory = (_device, parent, identity) => {
      const renderable = new ThingCrowdRenderable(parent, identity, (miss) => this.missed.set(miss.subjectId, miss), async (root, stale) => {
        const figure = await this.options.maker.make(root, {
          name: `thing:${identity.inhabitantId}`,
          thingId: identity.inhabitantId,
          kind: isMadeKind(kind) ? { source: 'workspace', sha256: kind.sha256 } : { key: kind.kind, version: kind.version, sha256: kind.sha256 },
          look,
        }, stale);
        if (figure !== null) this.missed.delete(identity.inhabitantId);
        return figure?.figure ?? null;
      });
      this.made.set(identity.inhabitantId, renderable);
      return renderable;
    };
    return { key, factory };
  }

  /**
   * A placed being stands at its placed yaw until it first walks, as the layer draws it before a
   * society holds it: one rule for both (`facingOfYaw`). Anyone else, or a placement not read, null.
   */
  standingFacingOf(person: SocietyInhabitantSnapshot): number | null {
    const placedId = person.placed_id ?? null;
    if (placedId === null) return null;
    const yaw = this.options.placedYawOf?.(placedId) ?? null;
    return yaw === null ? null : facingOfYaw(yaw);
  }

  /** The figure drawing a person now, or null while it is not drawn in full or not yet made. */
  figureOf(subjectId: string): ThingFigure | null {
    const renderable = this.made.get(subjectId);
    if (renderable === undefined || !renderable.root.parent) {
      this.made.delete(subjectId);
      return null;
    }
    return renderable.figure;
  }

  /** The renderable drawing a person now, or null. */
  renderableOf(subjectId: string): ThingCrowdRenderable | null {
    const renderable = this.made.get(subjectId);
    return renderable !== undefined && renderable.root.parent ? renderable : null;
  }

  /** Every person whose look could not be made, and why. */
  get misses(): readonly ThingFigureMiss[] {
    return [...this.missed.values()];
  }

  /** Once a frame, after the engine's animation step: rigged arms over clips, glows to the camera. */
  afterAnimation(camera: pc.Vec3): void {
    for (const [id, renderable] of this.made) {
      if (!renderable.root.parent) {
        this.made.delete(id);
        continue;
      }
      const figure: ThingFigure | null = renderable.figure;
      if (figure instanceof PresenceFigure) figure.face(camera);
      else figure?.afterAnimation?.();
    }
  }
}
