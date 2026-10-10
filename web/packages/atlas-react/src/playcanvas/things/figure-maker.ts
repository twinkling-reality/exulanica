/**
 * Making a thing's figure from the library: its kind, the look it wears, the look's body plan and
 * container, then the one figure its look kind draws (`./dispatch.ts`).
 *
 * One maker serves every figure of a page (a version's placed things and a society's things), so a
 * container is fetched, held to its digest and read by the engine once a digest, and each figure is
 * an instance of it. A thing with no look (its kind lists none) is drawn as nothing and keeps its
 * place. A kind its workspace keeps (named by digest alone) is drawn on the drafted body plan its
 * document names, read from the workspace by that plan's digest. Anything that cannot be made is
 * refused by name, for the caller to report.
 */

import * as pc from 'playcanvas';
import { createObjectContainerAsset } from '../scene-objects.js';
import type { BodyMotion } from './body-motion.js';
import type { KindDrawing, LookDrawing } from './documents.js';
import { makeFigure, type InstancedContainer } from './dispatch.js';
import type { ThingFigure } from './figures.js';
import type { Named, ThingLibrary, WorkspaceNamed } from './library.js';

export interface FigureMade {
  readonly figure: ThingFigure;
  readonly kind: KindDrawing;
  /** The look drawn, `look/vN`, or `none`. */
  readonly look: string;
}

export interface FigureMakerOptions {
  readonly app: pc.AppBase;
  readonly library: ThingLibrary;
  /** Make one figure's instance of a look's container; the engine's reader of the library's bytes when left out. */
  readonly instantiate?: (look: LookDrawing) => Promise<InstancedContainer>;
  /** The table a drafted body's stated chains are posed by (`./body-motion.ts`); at rest when left out. */
  readonly bodyMotion?: BodyMotion;
}

/** The look a thing with none is drawn in: nothing, at its place. */
const NO_LOOK = (kind: KindDrawing): LookDrawing => ({
  look: 'none', version: 1, label: 'no look', bodyPlan: kind.bodyPlan, lookKind: 'none',
  container: null, rig: null, heightMm: null, sampling: 'linear', light: null, role: null,
});

export class ThingFigureMaker {
  private readonly assets = new Map<string, Promise<pc.Asset>>();
  private readonly primitive: pc.StandardMaterial;
  private destroyed = false;

  constructor(readonly options: FigureMakerOptions) {
    this.primitive = new pc.StandardMaterial();
    this.primitive.name = 'thing:look-role-primitive';
    this.primitive.diffuse = new pc.Color(0.62, 0.6, 0.56);
    this.primitive.useMetalness = true;
    this.primitive.metalness = 0;
    this.primitive.gloss = 0.2;
    this.primitive.update();
  }

  get library(): ThingLibrary {
    return this.options.library;
  }

  /**
   * Make the figure of a thing of `kind` in `look` (its kind's first look with null) under `parent`.
   * `stale` is asked before anything is put in the scene: a figure asked for and no longer wanted
   * is never made.
   */
  async make(
    parent: pc.Entity,
    request: { readonly name: string; readonly thingId: string; readonly kind: Named | WorkspaceNamed; readonly look: Named | null },
    stale: () => boolean = () => false,
  ): Promise<FigureMade | null> {
    const library = this.options.library;
    const kind = await library.kind(request.kind);
    const chosen = request.look ?? kind.looks[0] ?? null;
    const look = chosen === null ? null : await library.look(chosen);
    const plan = look === null
      ? null
      : (await library.bodyPlans()).get(look.bodyPlan)
        ?? (kind.bodyPlanSha256 === null ? null : await library.heldPlan(kind.bodyPlanSha256, look.bodyPlan));
    const container = look?.container == null ? null : await (this.options.instantiate ?? ((one: LookDrawing) => this.instance(one)))(look);
    if (stale() || this.destroyed) {
      container?.model.destroy();
      return null;
    }
    const figure = makeFigure({
      parent,
      device: this.options.app.graphicsDevice,
      name: request.name,
      thingId: request.thingId,
      kind,
      look: look ?? NO_LOOK(kind),
      plan,
      container,
      primitive: this.primitive,
      motion: this.options.bodyMotion ?? null,
    });
    return { figure, kind, look: look === null ? 'none' : `${look.look}/v${look.version}` };
  }

  /** The look's container, loaded once a digest, instantiated for one figure. */
  private async instance(look: LookDrawing): Promise<InstancedContainer> {
    const reference = look.container!;
    let held = this.assets.get(reference.sha256);
    if (held === undefined) {
      held = this.options.library.container(reference).then(async (bytes) => {
        const asset = await createObjectContainerAsset(this.options.app, `thing-look:${reference.sha256.slice(0, 16)}`, bytes);
        if (look.sampling === 'nearest') nearestSampling(asset);
        return asset;
      });
      held.catch(() => this.assets.delete(reference.sha256));
      this.assets.set(reference.sha256, held);
    }
    const asset = await held;
    const resource = asset.resource as pc.ContainerResource & { animations?: pc.Asset[] };
    const model = resource.instantiateRenderEntity({});
    const tracks = new Map<string, pc.AnimTrack>();
    for (const clip of resource.animations ?? []) {
      const track = clip.resource as pc.AnimTrack;
      tracks.set(track.name, track);
    }
    return { model, tracks };
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.primitive.destroy();
    for (const held of this.assets.values()) {
      void held.then((asset) => {
        asset.unload();
        this.options.app.assets.remove(asset);
      }, () => undefined);
    }
    this.assets.clear();
  }
}

/** The reason a thing could not be made, by name: the refusal's own, or `look_unreadable`. */
export function refusalOf(error: unknown): string {
  if (error instanceof Error && 'reason' in error && typeof (error as { reason: unknown }).reason === 'string') {
    return (error as { reason: string }).reason;
  }
  return 'look_unreadable';
}

/** Draw a pixel-art look's textures as their pixels: nearest filtering, no blur between texels. */
function nearestSampling(asset: pc.Asset): void {
  const resource = asset.resource as pc.ContainerResource & { textures?: pc.Asset[] };
  for (const texture of resource.textures ?? []) {
    const t = texture.resource as pc.Texture | undefined;
    if (t === undefined) continue;
    t.minFilter = pc.FILTER_NEAREST;
    t.magFilter = pc.FILTER_NEAREST;
  }
}
