/**
 * Distant people: one coarse, smooth silhouette per body and posture, coloured by region from a
 * five-texel palette of the person's own look. The silhouette is built to the widths the
 * preparation measured on the fitted body, and a seated one is the same sculpt bent by the abstract
 * rig along the joints of that base's baked seated clip. Geometry is shared by everyone of a body
 * and posture; a person costs one draw call and a 5x1 texture. No part asset is loaded here.
 */
import * as pc from 'playcanvas';
import { buildPlayerSculpt, type V3 } from '../player-sculpt.js';
import { shapeBone, shapePoint, type CharacterDimensions } from '../character-shape.js';
import { HUMAN_BONE_NAMES, PLAYER_BIND_BONES, deformPlayer, playerSkinWeights, type Bone } from '../player-rig.js';
import { DEFAULT_CHARACTER_BODY } from '@exulanica/atlas-core';
import { catalogBase, catalogFamily, type CharacterCatalog, type PostureJoint } from './catalog.js';
import { describeLook, type CharacterLook } from './look.js';

export const FAR_REGIONS = ['skin', 'hair', 'upper', 'lower', 'shoes'] as const;
export type FarRegion = (typeof FAR_REGIONS)[number];
export type FarPalette = Readonly<Record<FarRegion, string>>;

/** The body a far form is built to, from the catalog base the look is over. */
export interface FarForm {
  readonly restHeightMillimetres: number;
  readonly shoulderWidthMillimetres: number;
  readonly hipWidthMillimetres: number;
  /** Each posture's joints at its clip's first frame, millimetres in the asset's frame. */
  readonly postures: Readonly<Record<string, Readonly<Record<PostureJoint, readonly [number, number, number]>>>>;
}

/** What a far form draws of a person: their body, their height and their look's region colours. */
export interface FarAppearance {
  readonly baseId: string;
  readonly heightMetres: number;
  readonly palette: FarPalette;
  readonly form: FarForm;
}

/**
 * The far form of a look. Every far drawing of a person reads this and nothing else, so a person
 * keeps their colours and their build whichever far drawing shows them and whenever they cross into
 * or out of full detail. A person without hair shows skin where hair would be.
 */
export function farAppearance(catalog: CharacterCatalog, look: CharacterLook): FarAppearance {
  const description = describeLook(catalog, look, 'far');
  const base = catalogBase(catalogFamily(catalog, look.familyId), look.baseId);
  const colours = description.farColours;
  return {
    baseId: description.baseId,
    heightMetres: description.heightMillimetres / 1000,
    palette: {
      skin: colours.skin,
      hair: colours.hair ?? colours.skin,
      upper: colours.upper,
      lower: colours.lower,
      shoes: colours.shoes,
    },
    form: {
      restHeightMillimetres: base.restHeightMillimetres,
      shoulderWidthMillimetres: base.farForm.shoulderWidthMillimetres,
      hipWidthMillimetres: base.farForm.hipWidthMillimetres,
      postures: Object.fromEntries(Object.entries(base.postures).map(([key, posture]) => [key, posture.jointsMillimetres])),
    },
  };
}

const TEMPLATE_STEP = 0.045;
/** The sculpt is built at the default body's height and scaled to each person's. */
const TEMPLATE_HEIGHT_METRES = DEFAULT_CHARACTER_BODY.heightMm / 1000;
const bone = (name: (typeof HUMAN_BONE_NAMES)[number]) => HUMAN_BONE_NAMES.indexOf(name);
/**
 * Bones whose surface the widths leave out, as the preparation does on the fitted body: forearms
 * and hands hang beside the hips at rest, and at hip height the upper arms are not the hips either.
 */
const SHOULDER_EXCLUDED = new Set([bone('left-forearm'), bone('right-forearm')]);
const HIP_EXCLUDED = new Set([bone('left-forearm'), bone('right-forearm'), bone('left-upper-arm'), bone('right-upper-arm')]);
/** Half-height of the band a width is measured over, as a share of height; the preparation's own. */
const WIDTH_BAND_SHARE = 0.012;

function region(p: V3): FarRegion {
  const [x, y, z] = p;
  if (y < 0.13) return 'shoes';
  if (y > 1.6 && (z > -0.035 || y > 1.72)) return 'hair';
  if (y > 1.43) return 'skin';
  if (Math.abs(x) > 0.25 && y < 1.02) return 'skin';
  if (y > 0.9) return 'upper';
  return 'lower';
}

type Skin = ReturnType<typeof playerSkinWeights>;

/** Width of the sculpt's surface across a band at `height`, leaving out the given bones. */
function sculptWidth(positions: Float32Array, skin: Skin, height: number, excluded: ReadonlySet<number>): number {
  const band = WIDTH_BAND_SHARE * TEMPLATE_HEIGHT_METRES;
  let low = Infinity, high = -Infinity;
  for (let i = 0; i < positions.length / 3; i++) {
    if (Math.abs(positions[i * 3 + 1]! - height) > band || excluded.has(skin.indices[i * 3]!)) continue;
    low = Math.min(low, positions[i * 3]!);
    high = Math.max(high, positions[i * 3]!);
  }
  return high - low;
}

/**
 * The template's dimensions, with the fitted body's measured widths. The sculpt is measured the way
 * the preparation measures the body, so the proportion that scales it is like for like.
 */
function formDimensions(form: FarForm, positions: Float32Array, skin: Skin): CharacterDimensions {
  const toTemplate = TEMPLATE_HEIGHT_METRES / (form.restHeightMillimetres / 1000);
  const shoulderAt = PLAYER_BIND_BONES[bone('left-upper-arm')]!.a[1];
  const hipAt = PLAYER_BIND_BONES[bone('left-thigh')]!.a[1];
  const shoulder = sculptWidth(positions, skin, shoulderAt, SHOULDER_EXCLUDED);
  const hip = sculptWidth(positions, skin, hipAt, HIP_EXCLUDED);
  return {
    ...DEFAULT_CHARACTER_BODY,
    shoulderWidthMm: DEFAULT_CHARACTER_BODY.shoulderWidthMm * ((form.shoulderWidthMillimetres / 1000) * toTemplate) / shoulder,
    hipWidthMm: DEFAULT_CHARACTER_BODY.hipWidthMm * ((form.hipWidthMillimetres / 1000) * toTemplate) / hip,
  };
}

/**
 * The abstract rig's bones laid along a posture's measured joints, each keeping its own length so
 * the sculpt bends without stretching. Joints turn from the asset's frame (facing +Z) into the
 * sculpt's (facing -Z) and scale to the template height.
 */
function postureBones(form: FarForm, joints: FarForm['postures'][string], bind: readonly Bone[]): Bone[] {
  const scale = TEMPLATE_HEIGHT_METRES / form.restHeightMillimetres;
  const at = (name: PostureJoint): V3 => {
    const [x, y, z] = joints[name];
    return [-x * scale, y * scale, -z * scale];
  };
  const along = (start: V3, from: PostureJoint, to: PostureJoint, index: number): Bone => {
    const a = at(from), b = at(to);
    const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const length = Math.hypot(...d);
    const own = bind[index]!;
    const reach = Math.hypot(own.b[0] - own.a[0], own.b[1] - own.a[1], own.b[2] - own.a[2]);
    return { a: start, b: [start[0] + (d[0]! / length) * reach, start[1] + (d[1]! / length) * reach, start[2] + (d[2]! / length) * reach] };
  };
  const bones: Bone[] = [];
  bones[bone('pelvis')] = along(at('pelvis'), 'pelvis', 'chest', bone('pelvis'));
  bones[bone('spine')] = along(bones[bone('pelvis')]!.b, 'chest', 'neck', bone('spine'));
  bones[bone('head')] = along(bones[bone('spine')]!.b, 'neck', 'head', bone('head'));
  for (const side of ['left', 'right'] as const) {
    const thigh = along(at(`${side}Hip`), `${side}Hip`, `${side}Knee`, bone(`${side}-thigh`));
    const shin = along(thigh.b, `${side}Knee`, `${side}Ankle`, bone(`${side}-shin`));
    const upper = along(at(`${side}Shoulder`), `${side}Shoulder`, `${side}Elbow`, bone(`${side}-upper-arm`));
    bones[bone(`${side}-thigh`)] = thigh;
    bones[bone(`${side}-shin`)] = shin;
    bones[bone(`${side}-foot`)] = along(shin.b, `${side}Ankle`, `${side}Toe`, bone(`${side}-foot`));
    bones[bone(`${side}-upper-arm`)] = upper;
    bones[bone(`${side}-forearm`)] = along(upper.b, `${side}Elbow`, `${side}Wrist`, bone(`${side}-forearm`));
  }
  return bones;
}

class Template {
  readonly mesh: pc.Mesh;
  constructor(device: pc.GraphicsDevice, form: FarForm, posture: string | null) {
    const sculpt = buildPlayerSculpt(TEMPLATE_STEP);
    const skin = playerSkinWeights(sculpt.positions);
    const body = formDimensions(form, sculpt.positions, skin);
    const positions = new Float32Array(sculpt.positions.length);
    const uvs = new Float32Array((sculpt.positions.length / 3) * 2);
    for (let i = 0; i < sculpt.positions.length / 3; i++) {
      const p: V3 = [sculpt.positions[i * 3]!, sculpt.positions[i * 3 + 1]!, sculpt.positions[i * 3 + 2]!];
      positions.set(shapePoint(p, body), i * 3);
      uvs[i * 2] = (FAR_REGIONS.indexOf(region(p)) + 0.5) / FAR_REGIONS.length;
      uvs[i * 2 + 1] = 0.5;
    }
    let normals = sculpt.normals;
    if (posture !== null) {
      const joints = form.postures[posture];
      if (!joints) throw new TypeError(`No far form for posture ${posture}`);
      const bind = PLAYER_BIND_BONES.map((b) => shapeBone(b, body));
      const bent = new Float32Array(positions.length);
      normals = new Float32Array(sculpt.normals.length);
      deformPlayer(positions, sculpt.normals, skin, postureBones(form, joints, bind), bent, normals, bind);
      positions.set(bent);
    }
    this.mesh = new pc.Mesh(device);
    this.mesh.setPositions(positions);
    this.mesh.setNormals(normals);
    this.mesh.setUvs(0, uvs);
    this.mesh.setIndices(sculpt.indices);
    this.mesh.update(pc.PRIMITIVE_TRIANGLES);
    this.mesh.incRefCount();
  }
}

const templates = new WeakMap<pc.GraphicsDevice, Map<string, Template>>();
const palettes = new WeakMap<pc.GraphicsDevice, Map<string, { material: pc.StandardMaterial; texture: pc.Texture; references: number }>>();

function template(device: pc.GraphicsDevice, form: FarForm, posture: string | null): Template {
  let byKey = templates.get(device);
  if (!byKey) templates.set(device, (byKey = new Map()));
  const key = JSON.stringify([form.restHeightMillimetres, form.shoulderWidthMillimetres, form.hipWidthMillimetres, posture, posture && form.postures[posture]]);
  let held = byKey.get(key);
  if (!held) byKey.set(key, (held = new Template(device, form, posture)));
  return held;
}

/** Bytes of the far sculpts built for this device so far, shared by every far person on it. */
export function farTemplateBytes(device: pc.GraphicsDevice): number {
  let bytes = 0;
  for (const held of templates.get(device)?.values() ?? []) {
    const mesh = held.mesh;
    bytes += (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((sum, b) => sum + (b?.numBytes ?? 0), 0);
  }
  return bytes;
}

function paletteKey(palette: FarPalette): string {
  return FAR_REGIONS.map((r) => palette[r]).join('');
}

function acquirePalette(device: pc.GraphicsDevice, palette: FarPalette): { material: pc.StandardMaterial; release(): void } {
  let byKey = palettes.get(device);
  if (!byKey) palettes.set(device, (byKey = new Map()));
  const key = paletteKey(palette);
  let entry = byKey.get(key);
  if (!entry) {
    const texture = new pc.Texture(device, {
      name: `far-palette:${key}`,
      width: FAR_REGIONS.length,
      height: 1,
      format: pc.PIXELFORMAT_SRGBA8,
      mipmaps: false,
      minFilter: pc.FILTER_NEAREST,
      magFilter: pc.FILTER_NEAREST,
      addressU: pc.ADDRESS_CLAMP_TO_EDGE,
      addressV: pc.ADDRESS_CLAMP_TO_EDGE,
    });
    const pixels = texture.lock() as Uint8Array;
    FAR_REGIONS.forEach((r, i) => {
      const colour = palette[r];
      for (let c = 0; c < 3; c++) pixels[i * 4 + c] = Number.parseInt(colour.slice(1 + c * 2, 3 + c * 2), 16);
      pixels[i * 4 + 3] = 255;
    });
    texture.unlock();
    const material = new pc.StandardMaterial();
    material.name = `far-person:${key}`;
    material.diffuseMap = texture;
    material.useMetalness = true;
    material.metalness = 0;
    material.gloss = 0.25;
    material.update();
    entry = { material, texture, references: 0 };
    byKey.set(key, entry);
  }
  const held = entry;
  held.references += 1;
  let released = false;
  return {
    material: held.material,
    release: () => {
      if (released) return;
      released = true;
      held.references -= 1;
      if (held.references > 0) return;
      byKey!.delete(key);
      held.material.destroy();
      held.texture.destroy();
    },
  };
}

export class FarPerson {
  readonly root: pc.Entity;
  private readonly body: pc.Entity;
  private readonly instance: pc.MeshInstance;
  private readonly palette: { material: pc.StandardMaterial; release(): void };
  private phase = 0;
  private posture: string | null = null;
  private disposed = false;

  constructor(private readonly app: pc.AppBase, readonly appearance: FarAppearance) {
    const device = app.graphicsDevice;
    const shared = template(device, appearance.form, null);
    this.palette = acquirePalette(device, appearance.palette);
    this.root = new pc.Entity('character-far', app);
    this.body = new pc.Entity('character-far-body', app);
    this.root.addChild(this.body);
    const scale = appearance.heightMetres / TEMPLATE_HEIGHT_METRES;
    this.body.setLocalScale(scale, scale, scale);
    this.instance = new pc.MeshInstance(shared.mesh, this.palette.material, this.body);
    this.body.addComponent('render', { meshInstances: [this.instance], castShadows: false, receiveShadows: true });
  }

  /** The posture drawn now: null for standing and moving. */
  get drawnPosture(): string | null {
    return this.posture;
  }

  /** Draw a posture the far form has joints for, or stand for null. */
  setPosture(posture: string | null): void {
    if (this.disposed || posture === this.posture) return;
    this.instance.mesh = template(this.app.graphicsDevice, this.appearance.form, posture).mesh;
    this.posture = posture;
  }

  /** The owner places the root; this only animates the step rhythm of someone standing. */
  update(speed: number, deltaSeconds: number, reducedMotion: boolean): void {
    if (this.disposed) return;
    // A step rhythm at distance: a small rise and fall at walking cadence, nothing when still.
    const moving = !reducedMotion && this.posture === null && speed > 0.05;
    this.phase = moving ? (this.phase + deltaSeconds * Math.min(3.2, 1.2 + speed * 0.9) * Math.PI * 2) % (Math.PI * 2) : 0;
    const bob = moving ? Math.abs(Math.sin(this.phase)) * 0.025 : 0;
    this.body.setLocalPosition(0, bob, 0);
    // Lean into travel: forward is -Z, so the lean is a negative pitch.
    this.body.setLocalEulerAngles(moving ? -Math.min(6, speed * 2.5) : 0, 0, 0);
  }

  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.root.destroy();
    this.palette.release();
  }
}
