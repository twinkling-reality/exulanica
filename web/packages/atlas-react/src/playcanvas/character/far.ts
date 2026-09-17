/**
 * Distant people: one coarse, smooth silhouette per body type, coloured by region from a
 * five-texel palette of the person's own look. Geometry is shared by everyone of a body type;
 * a person costs one draw call and a 5x1 texture. No part asset is loaded at this detail.
 */
import * as pc from 'playcanvas';
import { buildPlayerSculpt, type V3 } from '../player-sculpt.js';
import { shapePoint, type CharacterDimensions } from '../character-shape.js';
import { DEFAULT_CHARACTER_BODY } from '@exulanica/atlas-core';

export const FAR_REGIONS = ['skin', 'hair', 'upper', 'lower', 'shoes'] as const;
export type FarRegion = (typeof FAR_REGIONS)[number];
export type FarPalette = Readonly<Record<FarRegion, string>>;

const TEMPLATE_STEP = 0.045;
const TEMPLATE_HEIGHT_METRES = 1.82;

/** Body proportions per base family; choices, never measurements. */
const PROPORTIONS: Readonly<Record<string, Partial<CharacterDimensions>>> = {
  feminine: { shoulderWidthMm: 370, hipWidthMm: 300 },
  masculine: { shoulderWidthMm: 425, hipWidthMm: 275 },
};

function region(p: V3): FarRegion {
  const [x, y, z] = p;
  if (y < 0.13) return 'shoes';
  if (y > 1.6 && (z > -0.035 || y > 1.72)) return 'hair';
  if (y > 1.43) return 'skin';
  if (Math.abs(x) > 0.25 && y < 1.02) return 'skin';
  if (y > 0.9) return 'upper';
  return 'lower';
}

class Template {
  readonly mesh: pc.Mesh;
  constructor(device: pc.GraphicsDevice, baseId: string) {
    const sculpt = buildPlayerSculpt(TEMPLATE_STEP);
    const body = { ...DEFAULT_CHARACTER_BODY, ...(PROPORTIONS[baseId] ?? {}) };
    const positions = new Float32Array(sculpt.positions.length);
    const uvs = new Float32Array((sculpt.positions.length / 3) * 2);
    for (let i = 0; i < sculpt.positions.length / 3; i++) {
      const p: V3 = [sculpt.positions[i * 3]!, sculpt.positions[i * 3 + 1]!, sculpt.positions[i * 3 + 2]!];
      positions.set(shapePoint(p, body), i * 3);
      uvs[i * 2] = (FAR_REGIONS.indexOf(region(p)) + 0.5) / FAR_REGIONS.length;
      uvs[i * 2 + 1] = 0.5;
    }
    this.mesh = new pc.Mesh(device);
    this.mesh.setPositions(positions);
    this.mesh.setNormals(sculpt.normals);
    this.mesh.setUvs(0, uvs);
    this.mesh.setIndices(sculpt.indices);
    this.mesh.update(pc.PRIMITIVE_TRIANGLES);
    this.mesh.incRefCount();
  }
  get triangles(): number {
    return this.mesh.primitive[0]!.count / 3;
  }
}

const templates = new WeakMap<pc.GraphicsDevice, Map<string, Template>>();
const palettes = new WeakMap<pc.GraphicsDevice, Map<string, { material: pc.StandardMaterial; texture: pc.Texture; references: number }>>();

function template(device: pc.GraphicsDevice, baseId: string): Template {
  let byBase = templates.get(device);
  if (!byBase) templates.set(device, (byBase = new Map()));
  let held = byBase.get(baseId);
  if (!held) byBase.set(baseId, (held = new Template(device, baseId)));
  return held;
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
  private readonly palette: { material: pc.StandardMaterial; release(): void };
  private phase = 0;
  private disposed = false;

  constructor(app: pc.AppBase, baseId: string, heightMetres: number, palette: FarPalette) {
    const device = app.graphicsDevice;
    const shared = template(device, baseId);
    this.palette = acquirePalette(device, palette);
    this.root = new pc.Entity('character-far', app);
    this.body = new pc.Entity('character-far-body', app);
    this.root.addChild(this.body);
    const scale = heightMetres / TEMPLATE_HEIGHT_METRES;
    this.body.setLocalScale(scale, scale, scale);
    const instance = new pc.MeshInstance(shared.mesh, this.palette.material, this.body);
    this.body.addComponent('render', { meshInstances: [instance], castShadows: false, receiveShadows: true });
  }

  static templateTriangles(device: pc.GraphicsDevice, baseId: string): number {
    return template(device, baseId).triangles;
  }

  /** The owner places the root; this only animates the step rhythm. */
  update(speed: number, deltaSeconds: number, reducedMotion: boolean): void {
    if (this.disposed) return;
    // A step rhythm at distance: a small rise and fall at walking cadence, nothing when still.
    const moving = !reducedMotion && speed > 0.05;
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
