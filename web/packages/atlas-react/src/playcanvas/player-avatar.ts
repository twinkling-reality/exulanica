import * as pc from 'playcanvas';
import type { ResolvedCharacterRepresentation } from '@exulanica/atlas-core';
import type { CameraState } from './controls.js';
import { buildPlayerSculpt } from './player-sculpt.js';
import { deformPlayer, playerSkinWeights } from './player-rig.js';
import { CharacterMotion } from './character-motion.js';
import {
  BASE_DIMENSIONS,
  BASE_PALETTE,
  abstractCharacter,
  shapePoint,
  type CharacterDimensions,
} from './character-shape.js';

const skinCache = new Map<number, ReturnType<typeof playerSkinWeights>>();
const rgb = (hex: string) =>
  [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255);
/** Shared continuous abstract representation. Its caller owns subject identity and canonical position. */
export class PlayerAvatar {
  readonly root: pc.Entity;
  readonly body: CharacterDimensions;
  readonly representation: ResolvedCharacterRepresentation;
  private readonly sculpt: ReturnType<typeof buildPlayerSculpt>;
  private readonly skin: ReturnType<typeof playerSkinWeights>;
  private readonly bindPositions: Float32Array;
  private readonly positions: Float32Array;
  private readonly normals: Float32Array;
  private readonly motion: CharacterMotion;
  private readonly mesh: pc.Mesh;
  private readonly material = new pc.StandardMaterial();
  private wasVisible = false;
  private lastFacing = 0;
  private readonly contactMesh: pc.Mesh;
  private readonly grain: pc.Texture;
  private readonly contactMaterial = new pc.StandardMaterial();
  constructor(
    device: pc.GraphicsDevice,
    parent: pc.Entity,
    options: {
      name?: string;
      representation?: ResolvedCharacterRepresentation;
      detail?: 'near' | 'mid';
    } = {},
  ) {
    this.root = new pc.Entity(options.name ?? 'local-player-representation');
    parent.addChild(this.root);
    this.representation =
      options.representation ??
      abstractCharacter({ kind: 'player', playerId: 'local-viewer' }, 'near');
    this.body = this.representation.body ?? BASE_DIMENSIONS;
    const step = options.detail === 'mid' ? 0.035 : 0.018;
    this.sculpt = buildPlayerSculpt(step);
    this.skin = skinCache.get(step) ?? playerSkinWeights(this.sculpt.positions);
    skinCache.set(step, this.skin);
    this.bindPositions = new Float32Array(this.sculpt.positions.length);
    for (let i = 0; i < this.bindPositions.length; i += 3)
      this.bindPositions.set(
        shapePoint(
          [
            this.sculpt.positions[i]!,
            this.sculpt.positions[i + 1]!,
            this.sculpt.positions[i + 2]!,
          ],
          this.body,
        ),
        i,
      );
    this.positions = new Float32Array(this.bindPositions);
    this.normals = new Float32Array(this.sculpt.normals);
    this.motion = new CharacterMotion(this.body);
    const appearance = this.representation.appearance;
    const palette =
        appearance?.kind === 'abstract' ? appearance.palette : BASE_PALETTE,
      head = rgb(palette.head),
      body = rgb(palette.torso),
      limbs = rgb(palette.limbs),
      colors = new Float32Array(this.sculpt.colors.length);
    for (let i = 0; i < this.sculpt.positions.length / 3; i++) {
      const y = this.sculpt.positions[i * 3 + 1]!,
        x = this.sculpt.positions[i * 3]!;
      let t = Math.max(0, Math.min(1, (y - 1.48) / 0.17));
      t = t * t * (3 - 2 * t);
      const base = y < 0.9 || Math.abs(x) > 0.22 ? limbs : body;
      for (let j = 0; j < 3; j++)
        colors[i * 4 + j] = base[j]! * (1 - t) + head[j]! * t;
      colors[i * 4 + 3] = 1;
    }
    this.grain = new pc.Texture(device, {
      name: 'abstract-human-fine-satin',
      width: 128,
      height: 128,
      format: pc.PIXELFORMAT_RGBA8,
      mipmaps: true,
    });
    const grain = this.grain.lock() as Uint8Array;
    let random = 9467;
    for (let i = 0; i < 128 * 128; i++) {
      random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
      const weave = Math.sin((i % 128) * Math.PI) * 2;
      const value = 238 + (random % 14) + weave;
      grain.set([value, value, value, 255], i * 4);
    }
    this.grain.unlock();
    this.grain.addressU = pc.ADDRESS_REPEAT;
    this.grain.addressV = pc.ADDRESS_REPEAT;
    this.material.diffuseMap = this.grain;
    this.material.diffuseMapTiling = new pc.Vec2(5, 5);
    this.material.diffuse = new pc.Color(1, 1, 1);
    this.material.diffuseVertexColor = true;
    this.material.emissive = new pc.Color(0.025, 0.025, 0.025);
    this.material.emissiveVertexColor = true;
    this.material.useMetalness = true;
    this.material.metalness = 0.03;
    this.material.gloss = 0.38;
    this.material.update();
    this.mesh = new pc.Mesh(device);
    this.mesh.setPositions(this.positions);
    this.mesh.setNormals(this.normals);
    this.mesh.setColors(colors);
    const uvs: number[] = [];
    for (let i = 0; i < this.sculpt.positions.length; i += 3)
      uvs.push(
        this.sculpt.positions[i]! * 0.8,
        this.sculpt.positions[i + 1]! * 0.8,
      );
    this.mesh.setUvs(0, uvs);
    this.mesh.setIndices(this.sculpt.indices);
    this.mesh.update(pc.PRIMITIVE_TRIANGLES);
    this.root.addComponent('render', {
      meshInstances: [new pc.MeshInstance(this.mesh, this.material, this.root)],
      castShadows: false,
      receiveShadows: true,
    });
    this.root.enabled = false;
    this.contactMaterial.diffuse = new pc.Color(0, 0, 0);
    this.contactMaterial.useLighting = false;
    this.contactMaterial.opacityVertexColor = true;
    this.contactMaterial.opacityVertexColorChannel = 'a';
    this.contactMaterial.blendType = pc.BLEND_NORMAL;
    this.contactMaterial.depthWrite = false;
    this.contactMaterial.update();
    this.contactMesh = new pc.Mesh(device);
    this.contactMesh.setPositions([0, 0, 0, 0, 0, 0, 0, 0, 0]);
    this.contactMesh.setColors([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
    this.contactMesh.setIndices([0, 1, 2]);
    this.contactMesh.update(pc.PRIMITIVE_TRIANGLES);
    const shadow = new pc.Entity('foot-contact-occlusion');
    this.root.addChild(shadow);
    shadow.addComponent('render', {
      meshInstances: [
        new pc.MeshInstance(this.contactMesh, this.contactMaterial, shadow),
      ],
      castShadows: false,
      receiveShadows: false,
    });
  }
  get textureResidentBytes(): number {
    return this.grain.gpuSize;
  }
  get residentBytes(): number {
    return [this.mesh, this.contactMesh].reduce(
      (bytes, mesh) =>
        bytes +
        (mesh.vertexBuffer?.numBytes ?? 0) +
        mesh.indexBuffer.reduce((sum, b) => sum + (b?.numBytes ?? 0), 0),
      0,
    );
  }
  /**
   * Facing in radians, as the motion solver resolved it.
   *
   * Read this instead of the entity's Euler angles. `getLocalEulerAngles()` decomposes the
   * rotation quaternion, and for any |yaw| over 90 degrees it returns the equivalent
   * (180, 180 - yaw, 180) triple, so its `y` stops being the yaw and a character heading away
   * from -Z is drawn mirrored, up to a full reversal at 180 degrees.
   */
  get facing(): number {
    return this.lastFacing;
  }

  update(
    player: CameraState,
    dx: number,
    dz: number,
    dt: number,
    visible: boolean,
    reduced: boolean,
    groundY = player.y - (this.body.heightMm / 1000) * 0.89,
    headingYaw: number | null = null,
  ): void {
    visible = visible && this.representation.availability !== 'hidden';
    this.root.enabled = visible;
    if (!visible) {
      this.wasVisible = false;
      return;
    }
    if (!this.wasVisible) this.motion.reset();
    const pose = this.motion.update({
      x: player.x,
      z: player.z,
      yaw: player.yaw,
      dx,
      dz,
      headingYaw,
      dt,
      reduced,
    });
    // Native replacements still use this stable root and facing, without uploading hidden fallback vertices.
    this.lastFacing = pose.facing;
    this.root.setLocalPosition(player.x, groundY, player.z);
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    if (this.root.render?.enabled === false) { this.wasVisible = true; return; }
    deformPlayer(
      this.bindPositions,
      this.sculpt.normals,
      this.skin,
      pose.bones,
      this.positions,
      this.normals,
      this.motion.bindBones,
    );
    this.mesh.setPositions(this.positions);
    this.mesh.setNormals(this.normals);
    this.mesh.update(pc.PRIMITIVE_TRIANGLES);
    const contactPositions: number[] = [],
      contactColors: number[] = [],
      contactIndices: number[] = [];
    for (let side = 0; side < 2; side++) {
      const foot = pose.bones[5 + side * 5]!.a,
        start = contactPositions.length / 3,
        fade = Math.max(0, 1 - (foot[1] - 0.105) / 0.2) * 0.3;
      contactPositions.push(foot[0], 0.032, foot[2] - 0.035);
      contactColors.push(0, 0, 0, fade);
      for (let k = 0; k <= 20; k++) {
        const angle = (k / 20) * Math.PI * 2;
        contactPositions.push(
          foot[0] + Math.cos(angle) * 0.14,
          0.032,
          foot[2] - 0.035 + Math.sin(angle) * 0.22,
        );
        contactColors.push(0, 0, 0, 0);
        if (k < 20) contactIndices.push(start, start + k + 2, start + k + 1);
      }
    }
    this.contactMesh.setPositions(contactPositions);
    this.contactMesh.setColors(contactColors);
    this.contactMesh.setIndices(contactIndices);
    this.contactMesh.update(pc.PRIMITIVE_TRIANGLES);
    this.root.setLocalPosition(
      player.x,
      groundY,
      player.z,
    );
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    this.wasVisible = true;
  }
  destroy(): void {
    this.root.destroy();
    this.mesh.destroy();
    this.material.destroy();
    this.contactMesh.destroy();
    this.contactMaterial.destroy();
    this.grain.destroy();
  }
}
