/**
 * A near, fully rigged person assembled from catalog parts.
 *
 * The base container supplies the skeleton, body, face parts and clips. Each worn part comes
 * from its own container and is bound to the base's bones by name; because every part was
 * exported with the same bind pose, the part's meshes adopt the base skin and share one skin
 * instance per person. Materials are shared by pack and tint. Nothing here moves the subject:
 * the caller supplies resolved ground positions and facing.
 */
import * as pc from 'playcanvas';
import { catalogBase, catalogFamily, catalogMaterial, type CatalogBase } from './catalog.js';
import type { CharacterHost, ContainerLease, LoadedContainer } from './host.js';
import type { CharacterRenderableDescription } from './look.js';
import { FootLock } from './foot-lock.js';

/** Motion of an already placed person: its owner positions `root`. */
export interface PersonPose {
  /** Resolved horizontal speed over the last step, metres per second. */
  readonly speed: number;
  /** Signed turn rate, radians per second. */
  readonly turnRate: number;
  readonly deltaSeconds: number;
  readonly reducedMotion: boolean;
  readonly discontinuity: boolean;
  /** A posture the family declares, or null to stand and move. */
  readonly posture: string | null;
}

const LOCOMOTION = 'Locomotion';
const SPEED = 'speed';
/** Integer parameter naming the posture held: 0 stands and moves, k + 1 the family's k-th posture. */
const POSTURE = 'posture';
/**
 * How long settling into a posture or rising from it takes. A chosen presentation time: the
 * clips cross-fade over it, so a person lowers into a seat rather than snapping into one.
 */
const POSTURE_BLEND_SECONDS = 0.8;
/** Half the distance between the feet: how far a foot travels per radian of turning in place. */
const TURN_RADIUS_METRES = 0.18;

function skinsMatch(a: pc.Skin, b: pc.Skin): boolean {
  if (a.boneNames.length !== b.boneNames.length) return false;
  for (let i = 0; i < a.boneNames.length; i++) {
    if (a.boneNames[i] !== b.boneNames[i]) return false;
    const x = a.inverseBindPose[i]!.data, y = b.inverseBindPose[i]!.data;
    for (let k = 0; k < 16; k++) if (Math.abs(x[k]! - y[k]!) > 1e-4) return false;
  }
  return true;
}

function containerMeshes(container: LoadedContainer): pc.Mesh[] {
  return container.resource.renders.flatMap((render) => (render.resource as { meshes: pc.Mesh[] }).meshes);
}

/** The slowest cadence a walk plays at, as a share of its calibrated speed; slower is a blend into standing. */
export const SLOWEST_WALK_CADENCE = 0.5;

/**
 * Where on the idle, walk and run blend a speed sits, and how fast the clips play there.
 *
 * A planted foot moves backward at the clip's speed times its cadence, so the cadence is what keeps
 * it still on the ground. Below the walk's calibrated speed the whole walk plays slower, down to
 * half cadence, rather than being mixed with standing, which shortens the step without slowing the
 * foot and makes it slide. Only below that does the walk fade into standing, still at half cadence.
 * Between walk and run the two clips blend at full cadence, and beyond the run the cadence rises.
 */
export function gaitFor(speed: number, walk: number, run: number): { readonly blend: number; readonly cadence: number } {
  if (speed <= 0) return { blend: 0, cadence: 1 };
  const slowest = walk * SLOWEST_WALK_CADENCE;
  if (speed < slowest) return { blend: walk * (speed / slowest), cadence: SLOWEST_WALK_CADENCE };
  if (speed <= walk) return { blend: walk, cadence: speed / walk };
  if (speed <= run) return { blend: speed, cadence: 1 };
  return { blend: run, cadence: speed / run };
}

/** A state's name holds no dot: `assignAnimation` reads a dot as a path into a blend tree. */
function postureState(key: string): string {
  return `Posture:${key}`;
}

export class CharacterPerson {
  readonly root: pc.Entity;
  private model: pc.Entity | null = null;
  private readonly leases: ContainerLease[] = [];
  private readonly releases: (() => void)[] = [];
  private readonly meshInstances: pc.MeshInstance[] = [];
  private footLock: FootLock | null = null;
  private disposed = false;
  private smoothedSpeed = 0;
  private walkSpeed = 1;
  private runSpeed = 2.5;
  private scale = 1;
  private visible = true;
  private postures: readonly string[] = [];
  private posture: string | null = null;
  /** Until the first update, a held posture is taken at once rather than settled into. */
  private fresh = true;

  private constructor(readonly description: CharacterRenderableDescription, app: pc.AppBase) {
    this.root = new pc.Entity(`character:${description.lookSha256.slice(0, 12)}`, app);
  }

  static async create(host: CharacterHost, description: CharacterRenderableDescription, signal: AbortSignal): Promise<CharacterPerson> {
    if (description.detail !== 'near' || !description.base) throw new TypeError('A rigged person needs a near description');
    const person = new CharacterPerson(description, host.app);
    try {
      await person.assemble(host, signal);
      return person;
    } catch (error) {
      person.destroy();
      throw error;
    }
  }

  private async assemble(host: CharacterHost, signal: AbortSignal): Promise<void> {
    const description = this.description;
    const family = catalogFamily(host.catalog, description.familyId);
    const base = catalogBase(family, description.baseId);
    const materialFor = (id: string, tint: string | null) => host.material(catalogMaterial(family, id), tint, signal);
    // Load everything in parallel; a failure anywhere releases what arrived.
    const baseLease = host.acquire(base.asset, signal, true);
    const partLeases = description.parts.map((part) => (part.asset ? host.acquire(part.asset, signal) : Promise.resolve(null)));
    const skin = materialFor(description.skinMaterial, null);
    const partMaterials = description.parts.map((part) => materialFor(part.materialId, part.tint));
    const settled = await Promise.allSettled([baseLease, skin, ...partLeases, ...partMaterials]);
    for (const result of settled) {
      if (result.status !== 'fulfilled' || !result.value) continue;
      const value = result.value as ContainerLease | { release(): void };
      if ('container' in value) this.leases.push(value);
      else this.releases.push(() => value.release());
    }
    const failure = settled.find((r) => r.status === 'rejected');
    if (failure) throw (failure as PromiseRejectedResult).reason;
    if (this.disposed || signal.aborted) throw new DOMException('Character request cancelled', 'AbortError');
    const baseContainer = (await baseLease).container;
    const model = baseContainer.resource.instantiateRenderEntity({ castShadows: true, receiveShadows: true });
    this.model = model;
    this.root.addChild(model);
    this.scale = description.scaleMicro / 1_000_000;
    model.setLocalScale(this.scale, this.scale, this.scale);
    // Assets face +Z; the world's forward is -Z.
    model.setLocalEulerAngles(0, 180, 0);
    model.setLocalPosition(0, (-base.idleFloorMicrometres / 1_000_000) * this.scale, 0);

    const bodyNode = model.findByName(base.bodyNode) as pc.Entity | null;
    const bodyRender = bodyNode?.render;
    const bodyInstance = bodyRender?.meshInstances[0];
    if (!bodyNode || !bodyRender || !bodyInstance?.skinInstance) throw new Error('Base container has no skinned body');
    const baseSkin = bodyInstance.mesh.skin!;
    const rootBone = bodyRender.rootBone as pc.Entity;
    const skinMaterial = (await skin).material;
    bodyInstance.material = skinMaterial;

    // Face parts live in the base: enable only the chosen ones.
    const chosenNodes = new Set(description.parts.map((p) => p.node));
    for (const part of base.parts) {
      if (part.asset) continue;
      const node = model.findByName(part.node) as pc.Entity | null;
      if (!node) throw new Error(`Base container is missing ${part.node}`);
      node.enabled = chosenNodes.has(part.node);
    }

    for (let i = 0; i < description.parts.length; i++) {
      const part = description.parts[i]!;
      const material = (await partMaterials[i]!).material;
      let node: pc.Entity | null;
      if (part.asset) {
        const lease = (await partLeases[i]!)!;
        const meshes = containerMeshes(lease.container);
        for (const mesh of meshes) {
          if (mesh.skin && mesh.skin !== baseSkin) {
            if (!skinsMatch(mesh.skin, baseSkin)) throw new Error(`${part.partId} was fitted to a different skeleton`);
            // Adopt the base skin once per container so every wearer shares one skin instance.
            mesh.skin = baseSkin;
          }
        }
        const instance = lease.container.resource.instantiateRenderEntity({ castShadows: true, receiveShadows: true });
        node = instance.findByName(part.node) as pc.Entity | null;
        if (!node?.render) {
          instance.destroy();
          throw new Error(`Part container is missing ${part.node}`);
        }
        node.render.rootBone = rootBone;
        instance.removeChild(node);
        bodyNode.parent!.addChild(node);
        instance.destroy();
      } else {
        node = model.findByName(part.node) as pc.Entity | null;
      }
      for (const mi of node?.render?.meshInstances ?? []) mi.material = material;
    }

    const variant = host.bodyVariant(baseContainer, bodyInstance.mesh, this.bodyMeshIndex(baseContainer, base), description.hideMask);
    this.releases.push(variant.release);
    bodyInstance.mesh = variant.mesh;

    this.meshInstances.push(...(model.findComponents('render') as pc.RenderComponent[]).flatMap((r) => r.meshInstances));
    for (const mi of this.meshInstances) {
      const morph = mi.morphInstance;
      if (!morph) continue;
      for (const [target, weight] of Object.entries(description.morphWeightsMilli)) {
        if (mi.mesh.morph?.targets.some((t) => t.name === target)) morph.setWeight(target, weight / 1000);
      }
    }

    this.walkSpeed = (base.clips.walk.speedMillimetresPerSecond / 1000) * this.scale;
    this.runSpeed = (base.clips.run.speedMillimetresPerSecond / 1000) * this.scale;
    this.postures = family.postures.map((posture) => posture.key);
    this.installAnimation(baseContainer, base);
    this.footLock = new FootLock(model, rootBone);
  }

  private bodyMeshIndex(container: LoadedContainer, base: CatalogBase): number {
    const index = container.document?.meshes.findIndex((m) => m.name === base.bodyNode) ?? -1;
    if (index < 0) throw new Error('Base document has no body mesh');
    return index;
  }

  private installAnimation(container: LoadedContainer, base: CatalogBase): void {
    const model = this.model!;
    model.addComponent('anim', { activate: true });
    const anim = model.anim!;
    const held = (index: number) => [{ parameterName: POSTURE, predicate: pc.ANIM_EQUAL_TO, value: index }];
    anim.loadStateGraph({
      layers: [{
        name: 'Base',
        states: [
          { name: 'START' },
          {
            name: LOCOMOTION,
            loop: true,
            speed: 1,
            blendTree: {
              type: pc.ANIM_BLEND_1D,
              parameter: SPEED,
              syncAnimations: true,
              children: [
                { name: 'idle', point: 0 },
                { name: 'walk', point: this.walkSpeed },
                { name: 'run', point: this.runSpeed },
              ],
            },
          },
          ...this.postures.map((key) => ({ name: postureState(key), loop: true, speed: 1 })),
        ],
        transitions: [
          { from: 'START', to: LOCOMOTION },
          ...this.postures.flatMap((key, index) => [
            { from: LOCOMOTION, to: postureState(key), time: POSTURE_BLEND_SECONDS, conditions: held(index + 1) },
            { from: postureState(key), to: LOCOMOTION, time: POSTURE_BLEND_SECONDS, conditions: held(0) },
          ]),
        ],
      }],
      parameters: {
        [SPEED]: { name: SPEED, type: pc.ANIM_PARAMETER_FLOAT, value: 0 },
        [POSTURE]: { name: POSTURE, type: pc.ANIM_PARAMETER_INTEGER, value: 0 },
      },
    });
    const tracks = new Map(container.resource.animations.map((asset) => [(asset.resource as pc.AnimTrack).name, asset.resource as pc.AnimTrack]));
    const track = (name: string) => {
      const found = tracks.get(name);
      if (!found) throw new Error(`Base container is missing ${name}`);
      return found;
    };
    for (const kind of ['idle', 'walk', 'run'] as const) anim.assignAnimation(`${LOCOMOTION}.${kind}`, track(base.clips[kind].name));
    for (const key of this.postures) {
      const posture = base.postures[key];
      if (!posture) throw new Error(`Base ${base.baseId} has no ${key} posture`);
      anim.assignAnimation(postureState(key), track(posture.clip.name));
    }
  }

  get meshes(): readonly pc.MeshInstance[] {
    return this.meshInstances;
  }

  get standingHeight(): number {
    return this.description.heightMillimetres / 1000;
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    this.root.enabled = visible;
    if (!visible) this.footLock?.reset();
  }

  /** The posture held now, or null for standing and moving. */
  get heldPosture(): string | null {
    return this.posture;
  }

  /** Advance the gait from resolved motion. Called after the animation update. */
  update(pose: PersonPose): void {
    if (this.disposed || !this.model?.anim || !this.visible) return;
    const anim = this.model.anim;
    if (pose.posture !== this.posture) {
      const index = pose.posture === null ? 0 : this.postures.indexOf(pose.posture) + 1;
      if (index === 0 && pose.posture !== null) throw new TypeError(`Unknown posture ${pose.posture}`);
      anim.setInteger(POSTURE, index);
      // Someone first drawn, or moved without travelling, is shown as they are, not getting there.
      if (this.fresh || pose.discontinuity) anim.baseLayer?.transition(pose.posture === null ? LOCOMOTION : postureState(pose.posture), 0);
      this.posture = pose.posture;
      this.footLock?.reset();
    }
    this.fresh = false;
    if (this.posture !== null) {
      // A held posture plays its own clip; the gait and the contact lock rest until it ends.
      this.smoothedSpeed = 0;
      anim.setFloat(SPEED, 0);
      anim.speed = pose.reducedMotion ? 0 : 1;
      return;
    }
    const target = pose.reducedMotion || pose.discontinuity
      ? 0
      : Math.hypot(pose.speed, pose.turnRate * TURN_RADIUS_METRES * this.scale);
    const dt = Math.max(0, Math.min(0.1, pose.deltaSeconds));
    // Acceleration and braking read as weight transfer rather than a snap between gaits.
    this.smoothedSpeed = pose.discontinuity ? 0 : this.smoothedSpeed + (target - this.smoothedSpeed) * (1 - Math.exp(-dt / 0.12));
    const speed = this.smoothedSpeed < 0.02 ? 0 : this.smoothedSpeed;
    const gait = gaitFor(speed, this.walkSpeed, this.runSpeed);
    anim.setFloat(SPEED, gait.blend);
    anim.speed = pose.reducedMotion ? 0 : gait.cadence;
    if (pose.discontinuity) this.footLock?.reset();
    else this.footLock?.apply(dt, speed);
  }

  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.footLock = null;
    this.root.destroy();
    this.model = null;
    for (const release of this.releases.splice(0)) release();
    for (const lease of this.leases.splice(0)) lease.release();
  }
}
