import * as pc from 'playcanvas';
import { syntheticCharacterStyle, type CharacterPalette } from '../character-shape.js';

/**
 * Distant inhabitants as one simple standing figure each, drawn with hardware instancing.
 *
 * A far figure is the same synthetic person as its near character: its height and colours come
 * from the same identity-keyed style, and picking resolves to the same inhabitant. It has no rig,
 * face or clothing and does not pretend to; it keeps a person's silhouette and palette so a
 * street reads as populated at a distance. One mesh and one draw call per palette, whatever the
 * crowd size.
 */
export interface FarFigure {
  readonly id: string;
  readonly x: number;
  readonly z: number;
  readonly facing: number;
}

interface Group {
  readonly entity: pc.Entity;
  readonly mesh: pc.Mesh;
  readonly material: pc.StandardMaterial;
  readonly instance: pc.MeshInstance;
  buffer: pc.VertexBuffer | null;
  capacity: number;
  data: Float32Array;
}

const SEGMENTS = 8;
/** (height, radius) rings of a unit-height standing figure, feet to crown. */
const BODY: readonly (readonly [number, number])[] = [
  [0, 0.075], [0.46, 0.105], [0.6, 0.118], [0.8, 0.13], [0.84, 0.05],
];
const HEAD: readonly (readonly [number, number])[] = [
  [0.845, 0.0], [0.86, 0.045], [0.9, 0.066], [0.94, 0.064], [0.985, 0.035], [1.0, 0.0],
];

const rgb = (hex: string): readonly [number, number, number] => [
  Number.parseInt(hex.slice(1, 3), 16) / 255,
  Number.parseInt(hex.slice(3, 5), 16) / 255,
  Number.parseInt(hex.slice(5, 7), 16) / 255,
];

function lathe(
  rings: readonly (readonly [number, number])[],
  colour: (height: number) => readonly [number, number, number],
  positions: number[],
  normals: number[],
  colours: number[],
  indices: number[],
): void {
  const base = positions.length / 3;
  for (const [y, r] of rings) {
    const [cr, cg, cb] = colour(y);
    for (let s = 0; s < SEGMENTS; s += 1) {
      const angle = (s / SEGMENTS) * Math.PI * 2;
      const nx = Math.cos(angle), nz = Math.sin(angle);
      positions.push(nx * r, y, nz * r);
      normals.push(nx, 0.25, nz);
      colours.push(cr, cg, cb, 1);
    }
  }
  for (let ring = 0; ring < rings.length - 1; ring += 1) {
    for (let s = 0; s < SEGMENTS; s += 1) {
      const a = base + ring * SEGMENTS + s;
      const b = base + ring * SEGMENTS + ((s + 1) % SEGMENTS);
      const c = a + SEGMENTS, d = b + SEGMENTS;
      indices.push(a, c, b, b, c, d);
    }
  }
}

function figureMesh(device: pc.GraphicsDevice, palette: CharacterPalette): pc.Mesh {
  const positions: number[] = [], normals: number[] = [], colours: number[] = [], indices: number[] = [];
  const torso = rgb(palette.torso), limbs = rgb(palette.limbs), head = rgb(palette.head);
  lathe(BODY, (y) => (y < 0.46 ? limbs : torso), positions, normals, colours, indices);
  lathe(HEAD, () => head, positions, normals, colours, indices);
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setColors(colours);
  mesh.setIndices(indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}

export class FarFigures {
  readonly root: pc.Entity;
  private readonly groups = new Map<string, Group>();
  private readonly styles = new Map<string, { key: string; palette: CharacterPalette; height: number; width: number }>();
  private readonly transform = new pc.Mat4();
  private readonly rotation = new pc.Quat();
  private readonly position = new pc.Vec3();
  private readonly scale = new pc.Vec3();
  private drawn = 0;

  constructor(private readonly device: pc.GraphicsDevice, parent: pc.Entity) {
    this.root = new pc.Entity('society-far-figures');
    parent.addChild(this.root);
  }

  get count(): number { return this.drawn; }

  get residentBytes(): number {
    let bytes = 0;
    for (const group of this.groups.values()) {
      bytes += (group.mesh.vertexBuffer?.numBytes ?? 0) + (group.buffer?.numBytes ?? 0);
      bytes += group.mesh.indexBuffer.reduce((sum, b) => sum + (b?.numBytes ?? 0), 0);
    }
    return bytes;
  }

  private style(id: string) {
    let held = this.styles.get(id);
    if (!held) {
      const style = syntheticCharacterStyle(id);
      held = {
        key: `${style.palette.head}${style.palette.torso}${style.palette.limbs}`,
        palette: style.palette,
        height: style.body.heightMm / 1000,
        width: style.body.shoulderWidthMm / 400,
      };
      this.styles.set(id, held);
    }
    return held;
  }

  private group(key: string, palette: CharacterPalette): Group {
    let group = this.groups.get(key);
    if (!group) {
      const mesh = figureMesh(this.device, palette);
      const material = new pc.StandardMaterial();
      material.diffuse = new pc.Color(1, 1, 1);
      material.diffuseVertexColor = true;
      material.useMetalness = true;
      material.metalness = 0.02;
      material.gloss = 0.3;
      material.update();
      const entity = new pc.Entity(`society-far-figures:${this.groups.size}`);
      this.root.addChild(entity);
      const instance = new pc.MeshInstance(mesh, material, entity);
      instance.cull = false;
      entity.addComponent('render', { meshInstances: [instance], castShadows: false, receiveShadows: true });
      group = { entity, mesh, material, instance, buffer: null, capacity: 0, data: new Float32Array(0) };
      this.groups.set(key, group);
    }
    return group;
  }

  /** Place exactly these figures this frame; everyone else in the crowd is drawn elsewhere or not at all. */
  update(figures: readonly FarFigure[]): void {
    const byGroup = new Map<string, FarFigure[]>();
    for (const figure of figures) {
      const style = this.style(figure.id);
      this.group(style.key, style.palette);
      const list = byGroup.get(style.key) ?? [];
      list.push(figure);
      byGroup.set(style.key, list);
    }
    this.drawn = figures.length;
    for (const [key, group] of this.groups) {
      const list = byGroup.get(key) ?? [];
      if (list.length > group.capacity) {
        group.buffer?.destroy();
        group.capacity = Math.max(16, 2 ** Math.ceil(Math.log2(list.length)));
        group.data = new Float32Array(group.capacity * 16);
        group.buffer = new pc.VertexBuffer(
          this.device,
          pc.VertexFormat.getDefaultInstancingFormat(this.device),
          group.capacity,
          { usage: pc.BUFFER_DYNAMIC },
        );
        group.instance.setInstancing(group.buffer);
      }
      list.forEach((figure, index) => {
        const style = this.style(figure.id);
        this.position.set(figure.x, 0, figure.z);
        this.rotation.setFromEulerAngles(0, (figure.facing * 180) / Math.PI, 0);
        this.scale.set(style.height * style.width, style.height, style.height * style.width);
        this.transform.setTRS(this.position, this.rotation, this.scale);
        group.data.set(this.transform.data, index * 16);
      });
      if (group.buffer && list.length) {
        const target = new Float32Array(group.buffer.lock());
        target.set(group.data.subarray(0, list.length * 16));
        group.buffer.unlock();
      }
      group.instance.instancingCount = list.length;
      group.instance.visible = list.length > 0;
    }
  }

  destroy(): void {
    for (const group of this.groups.values()) {
      group.instance.setInstancing(null);
      group.entity.destroy();
      group.buffer?.destroy();
      group.mesh.destroy();
      group.material.destroy();
    }
    this.groups.clear();
    this.root.destroy();
  }
}
