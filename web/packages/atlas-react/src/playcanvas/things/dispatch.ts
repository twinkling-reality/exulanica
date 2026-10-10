/**
 * One dispatch by look kind: a look document becomes the one figure that draws its kind of look.
 *
 * Every look kind the look kinds catalog states is drawn by exactly one figure here, and a look kind
 * this page does not draw is refused by name: the thing is then drawn as nothing and its reason is
 * reported, never stood in for. Nothing here reads what a thing is beyond its body (its size and the
 * plan its looks fit); no kind, look or bone is named.
 */

import * as pc from 'playcanvas';
import { inhabitantRenderable } from '../character/inhabitant.js';
import type { CharacterRenderable } from '../character/renderable.js';
import { drawnHeightMm, type KindDrawing, type LookDrawing } from './documents.js';
import { LookRoleFigure, NoFigure, PresenceFigure, StaticFigure, type PickVolume, type ThingFigure, type ThingPose } from './figures.js';
import type { BodyMotion } from './body-motion.js';
import { RigidOnBonesFigure } from './rigid-on-bones.js';
import { SkinnedFigure } from './skinned.js';
import type { BodyPlanEntry } from './skeleton.js';

export type FigureRefusal =
  | 'look_kind_not_drawn'
  | 'look_unfit'
  | 'look_incomplete'
  | 'skeleton_refused';

export class FigureRefused extends Error {
  override readonly name = 'FigureRefused';
  constructor(readonly reason: FigureRefusal, message: string) {
    super(message);
  }
}

/** A container instantiated for one figure: its entity tree and its clips by name. */
export interface InstancedContainer {
  readonly model: pc.Entity;
  readonly tracks: ReadonlyMap<string, pc.AnimTrack>;
}

export interface FigureRequest {
  readonly parent: pc.Entity;
  readonly device: pc.GraphicsDevice;
  /** The figure's root name: `thing:<id>`. */
  readonly name: string;
  /** The thing's stable id, which a catalog person is drawn from. */
  readonly thingId: string;
  readonly kind: KindDrawing;
  readonly look: LookDrawing;
  readonly plan: BodyPlanEntry | null;
  /** The look's container, instantiated, where its look kind draws one. */
  readonly container: InstancedContainer | null;
  /** The material of the engine's primitive, for a look role no pack dresses here. */
  readonly primitive: pc.Material;
  /** The table a body whose plan states its chains is posed by; none poses those chains at rest. */
  readonly motion?: BodyMotion | null;
}

/** Make the figure that draws `request.look`, or refuse it by name. */
export function makeFigure(request: FigureRequest): ThingFigure {
  const { kind, look } = request;
  if (look.bodyPlan !== kind.bodyPlan) {
    throw new FigureRefused('look_unfit', `The look ${look.look} fits ${look.bodyPlan}, and this thing's body is ${kind.bodyPlan}.`);
  }
  const needs = (what: string): never => {
    throw new FigureRefused('look_incomplete', `The look ${look.look} draws ${look.lookKind} and has no ${what}.`);
  };
  switch (look.lookKind) {
    case 'static': {
      const box = kind.boxMm ?? needs('box in its kind');
      return new StaticFigure(request.parent, (request.container ?? needs('container')).model, request.name, box);
    }
    case 'look_role': {
      const box = kind.boxMm ?? needs('box in its kind');
      return new LookRoleFigure(request.parent, request.name, box, request.primitive);
    }
    case 'light': {
      const light = look.light ?? needs('light');
      return new PresenceFigure(request.parent, request.device, request.name, light, kind.radiusMm ?? needs('radius in its kind'));
    }
    case 'rigid_on_bones': {
      const plan = request.plan ?? needs('body plan');
      const height = drawnHeightMm(kind, look) ?? needs('height');
      try {
        return new RigidOnBonesFigure(request.parent, (request.container ?? needs('container')).model, plan, request.name, look.heightMm ?? height, height, request.motion ?? null, kind.extentMm);
      } catch (error) {
        if (error instanceof FigureRefused) throw error;
        throw new FigureRefused('skeleton_refused', error instanceof Error ? error.message : String(error));
      }
    }
    case 'skinned': {
      const plan = request.plan ?? needs('body plan');
      const height = drawnHeightMm(kind, look) ?? needs('height');
      const container = request.container ?? needs('container');
      try {
        return new SkinnedFigure(request.parent, container.model, container.tracks, plan, look.rig ?? needs('rig'), request.name, look.heightMm ?? height, height, request.motion ?? null, kind.extentMm);
      } catch (error) {
        if (error instanceof FigureRefused) throw error;
        throw new FigureRefused('skeleton_refused', error instanceof Error ? error.message : String(error));
      }
    }
    case 'catalog_person':
      return new CatalogPersonFigure(request.parent, request.device, request.name, request.thingId);
    case 'none':
      return new NoFigure(request.parent, request.name, (drawnHeightMm(kind, look) ?? kind.boxMm?.height ?? 1000) / 1000);
    default:
      throw new FigureRefused('look_kind_not_drawn', `This page does not draw looks of kind ${look.lookKind}.`);
  }
}

/** A thing whose look is the people catalog's: one of the world's people, drawn from its id. */
export class CatalogPersonFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind = 'catalog_person' as const;
  readonly pickVolume: PickVolume;
  private readonly person: CharacterRenderable;
  private readonly holder: pc.Entity;

  constructor(parent: pc.Entity, device: pc.GraphicsDevice, name: string, thingId: string) {
    this.holder = new pc.Entity(name);
    parent.addChild(this.holder);
    this.person = inhabitantRenderable(device, this.holder, { societyId: 'placed', branchId: 'placed', inhabitantId: thingId }, 'near');
    // The person's own root is posed at the ground contact, so picks and marks read it.
    this.root = this.person.root;
    const w = 0.2 * this.person.standingHeight;
    this.pickVolume = { kind: 'box', min: [-w, 0, -w], max: [w, this.person.standingHeight, w] };
  }

  get standingHeight(): number {
    return this.person.standingHeight;
  }

  pose(pose: ThingPose): void {
    this.person.pose({
      position: pose.position,
      yaw: pose.facing,
      deltaSeconds: pose.deltaSeconds,
      ...(pose.reducedMotion ? { reducedMotion: true } : {}),
      ...(pose.discontinuity ? { discontinuity: true } : {}),
      activity: pose.activity ?? null,
    });
  }

  markAnchor(out: pc.Vec3): pc.Vec3 {
    return out.copy(this.root.getPosition()).add(new pc.Vec3(0, this.standingHeight + 0.25, 0));
  }

  setVisible(visible: boolean): void {
    this.person.setVisible(visible);
  }

  destroy(): void {
    this.person.destroy();
    this.holder.destroy();
  }
}
