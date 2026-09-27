/**
 * What a region looks like from above when something actually reconstructed it.
 *
 * `region-mass.ts` answers the same question for a region with no geometry: one standing mark per
 * anchor, because the count is the only shape such a region has. This module is the other half of
 * that answer. A region holding a point map has a real surface with a real height and a real
 * colour, and drawing it as a cluster of abstract blocks throws away the one thing it has that
 * the others do not.
 *
 * **This is not the plinth the retired `atlas-visual-language.md` 4 (revision 47f9f7d3)
 * rejects, and the difference is the whole justification.** That section removes "plinth discs"
 * and "terrain platforms" from the origin profile, and it is right to: a disc under a memory
 * asserts an edge the data does not have. The
 * same section defines a semantic object as one deriving from "graph, evidence, navigation, or
 * RECONSTRUCTION state". A height sampled out of a point map is reconstruction state. It is not a
 * platform placed under the evidence to make it look founded; it IS the evidence, seen from
 * above, at the one vantage where its vertical form is the readable content.
 *
 * **A cell with nothing in it is a hole, not a zero, and most cells are holes.** Measured on the
 * courtyard, a single-view shell covers between eleven and twenty-seven per cent of its own
 * bounding box seen from above, at every grid resolution tried. That is not a defect in the
 * sampling: a 2.5D reconstruction is a CURTAIN. Its surfaces are mostly vertical, and a wall has
 * almost no area from overhead however well it was photographed. So this draws a tile per
 * observed cell rather than a stitched terrain, which shows all of what was seen and bridges
 * none of what was not. A region will read as a ribbon until it has been reconstructed from more
 * than one viewpoint, and a ribbon is the honest shape of one photograph seen from above.
 *
 * **The sky is excluded, and by measurement rather than by a height cut.** A monocular model
 * places the background tens of metres out where adjacent samples land metres apart, and those
 * points would otherwise form a vast flat plateau behind every region. They are dropped on the
 * support channel, which already says how coarsely each point was sampled, so what survives is
 * surface the photograph resolved rather than surface a height threshold happened to spare.
 *
 * The consequence is a Map that is deliberately mixed: reconstructed regions carry relief and
 * unreconstructed ones carry anchor marks. That is the rung ladder showing through, which is what
 * `product-specification.md` 5.1 asks the interface to do rather than hide.
 */

import * as pc from 'playcanvas';
import { atlasMapPose, type AtlasScene, type IslandId } from '@exulanica/atlas-core';
import type { WorldArtProfile } from '@exulanica/presentation';
import type { PointMap } from './opm.js';

export interface RegionRelief {
  readonly entity: pc.Entity;
  /** The islands this drew a surface for. The caller suppresses their anchor marks. */
  readonly reconstructed: ReadonlySet<IslandId>;
  setMapActive(active: boolean): void;
  applyProfile(profile: WorldArtProfile): void;
  destroy(): void;
}

/**
 * Cells across the widest axis of a region's footprint.
 *
 * A resolution rather than a cell size, because a footprint is metres for a courtyard and could
 * be hundreds for a landscape, and the Map reads the same either way. Forty across is about
 * fifteen hundred cells, which a 190k-point map fills at roughly a hundred samples each: enough
 * that a cell's height is an average of real samples rather than one point's opinion.
 */
const GRID = 40;

/**
 * The least support a point may carry and still shape the ground.
 *
 * 0.25 is where the courtyard's far haze begins: measured on that map, the points below it are
 * the sky and the pavement at grazing incidence, which are surfaces the photograph did not
 * resolve well enough to stand on. Excluding them here is the same judgement the renderer already
 * makes when it fades them, made once more where it decides what the ground is.
 */
const MIN_RELIEF_SUPPORT = 0.25;

/** A cell needs more than one sample before its height means anything. */
const MIN_CELL_SAMPLES = 3;

/** Relief height at the Map vantage, as a fraction of the altitude the Map looks from. */
const RELIEF_HEIGHT_OF_ALTITUDE = 0.055;

/** Matches `region-mass`, so relief and marks open up by the same amount and stay comparable. */
const CLUSTER_SPREAD_OF_ALTITUDE = 0.14;

const VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
attribute vec4 aColor;

uniform mat4 matrix_model;
uniform mat4 matrix_viewProjection;

varying vec4 vColor;

void main(void) {
    vColor = aColor;
    gl_Position = matrix_viewProjection * matrix_model * vec4(aPosition, 1.0);
}
`;

const FRAGMENT_GLSL = /* glsl */ `
precision highp float;

uniform vec3 uGround;
uniform float uMix;

varying vec4 vColor;

void main(void) {
    // The photograph's own colour, eased toward the field so a region reads as part of the Atlas
    // rather than as a photograph pasted onto it. The alpha carries the cell's mean support, so a
    // thinly sampled shelf sits closer to the ground colour exactly as it does in the world view.
    vec3 rgb = mix(vColor.rgb, uGround, uMix + (1.0 - vColor.a) * 0.30);
    gl_FragColor = vec4(rgb, 1.0);
}
`;

export interface ReliefCell {
  height: number;
  r: number;
  g: number;
  b: number;
  support: number;
  samples: number;
}

/**
 * Bin one point map into a height and a colour per cell, over the extent it actually occupies.
 *
 * The grid is laid over the map's own BOUNDS and not over a disc of its footprint radius. A
 * monocular reconstruction is not centred on its origin: the camera stands at the origin looking
 * down -Z, so every point has negative z and the surface sits entirely in front. A grid centred
 * on the origin puts the whole region in a quarter of its cells and leaves three quarters empty,
 * which renders as a small smudge in the corner of a region-sized area of nothing.
 */
export function sampleRelief(map: PointMap): { cells: (ReliefCell | null)[]; ok: boolean; grid: number } {
  const cells: (ReliefCell | null)[] = new Array(GRID * GRID).fill(null);
  const { min, max } = map.header.bounds;
  const spanX = max[0] - min[0];
  const spanZ = max[2] - min[2];
  if (!(spanX > 0) || !(spanZ > 0)) return { cells, ok: false, grid: GRID };

  const { position, color } = map;
  const count = map.header.pointCount;
  for (let i = 0; i < count; i += 1) {
    const support = (color[i * 4 + 3] ?? 0) / 255;
    if (support < MIN_RELIEF_SUPPORT) continue;
    const x = position[i * 3] ?? 0;
    const y = position[i * 3 + 1] ?? 0;
    const z = position[i * 3 + 2] ?? 0;
    const cx = Math.floor(((x - min[0]) / spanX) * GRID);
    const cz = Math.floor(((z - min[2]) / spanZ) * GRID);
    if (cx < 0 || cx >= GRID || cz < 0 || cz >= GRID) continue;
    const index = cz * GRID + cx;
    const cell = cells[index];
    if (cell === undefined || cell === null) {
      cells[index] = {
        height: y,
        r: color[i * 4] ?? 0,
        g: color[i * 4 + 1] ?? 0,
        b: color[i * 4 + 2] ?? 0,
        support,
        samples: 1,
      };
      continue;
    }
    cell.height += y;
    cell.r += color[i * 4] ?? 0;
    cell.g += color[i * 4 + 1] ?? 0;
    cell.b += color[i * 4 + 2] ?? 0;
    cell.support += support;
    cell.samples += 1;
  }

  for (let i = 0; i < cells.length; i += 1) {
    const cell = cells[i];
    if (cell === undefined || cell === null) continue;
    if (cell.samples < MIN_CELL_SAMPLES) {
      cells[i] = null;
      continue;
    }
    cell.height /= cell.samples;
    cell.r /= cell.samples;
    cell.g /= cell.samples;
    cell.b /= cell.samples;
    cell.support /= cell.samples;
  }
  return { cells, ok: true, grid: GRID };
}

export function createRegionRelief(
  device: pc.GraphicsDevice,
  scene: AtlasScene,
  pointMaps: ReadonlyMap<IslandId, PointMap>,
  profile: WorldArtProfile,
): RegionRelief {
  const altitude = atlasMapPose(scene).position.y;
  const entity = new pc.Entity('atlas-region-relief');
  const instances: pc.MeshInstance[] = [];
  const meshes: pc.Mesh[] = [];
  const reconstructed = new Set<IslandId>();

  const material = new pc.ShaderMaterial({
    uniqueName: 'exulanica-region-relief',
    attributes: { aPosition: pc.SEMANTIC_POSITION, aColor: pc.SEMANTIC_COLOR },
    vertexGLSL: VERTEX_GLSL,
    fragmentGLSL: FRAGMENT_GLSL,
  } as ConstructorParameters<typeof pc.ShaderMaterial>[0]);
  material.cull = pc.CULLFACE_NONE;
  material.blendType = pc.BLEND_NONE;
  material.depthWrite = true;
  material.depthTest = true;

  for (const island of scene.islands) {
    const map = pointMaps.get(island.islandId);
    if (map === undefined) continue;

    const { cells, ok } = sampleRelief(map);
    if (!ok) continue;
    const heights = cells.filter((c): c is ReliefCell => c !== null).map((c) => c.height);
    if (heights.length < 4) continue;

    // The OCCUPIED extent, not the bounds rectangle. A monocular map fills a camera frustum, so
    // the wedge it actually covers is a fraction of its own bounding box, and normalising to the
    // box would draw the region at a fraction of the area the Map gives it while the unfilled
    // corners sat there as nothing. A region should read at the size of what it holds.
    let minCx = GRID;
    let maxCx = -1;
    let minCz = GRID;
    let maxCz = -1;
    for (let i = 0; i < cells.length; i += 1) {
      if (cells[i] === null) continue;
      const cx = i % GRID;
      const cz = Math.floor(i / GRID);
      if (cx < minCx) minCx = cx;
      if (cx > maxCx) maxCx = cx;
      if (cz < minCz) minCz = cz;
      if (cz > maxCz) maxCz = cz;
    }
    const usedX = Math.max(1, maxCx - minCx);
    const usedZ = Math.max(1, maxCz - minCz);

    const low = Math.min(...heights);
    const high = Math.max(...heights);
    const range = high - low;
    const reliefHeight = altitude * RELIEF_HEIGHT_OF_ALTITUDE;
    // The cluster spread `region-mass` uses, so a relief region and a mark region occupy the same
    // area of the Map and one cannot appear to dwarf the other for a reason that is not real.
    const half = altitude * CLUSTER_SPREAD_OF_ALTITUDE;
    const centre = island.placement.position;

    const positions: number[] = [];
    const colours: number[] = [];
    const indices: number[] = [];

    const stepX = (half * 2) / usedX;
    const stepZ = (half * 2) / usedZ;
    for (let i = 0; i < cells.length; i += 1) {
      const cell = cells[i];
      if (cell === null || cell === undefined) continue;
      const cx = i % GRID;
      const cz = Math.floor(i / GRID);
      const x = centre.x + ((cx - minCx) / usedX - 0.5) * half * 2;
      const z = centre.z + ((cz - minCz) / usedZ - 0.5) * half * 2;
      const y = range > 0 ? ((cell.height - low) / range) * reliefHeight : 0;
      const base = positions.length / 3;
      // Four corners of this cell alone. Tiles rather than a stitched surface, and that is a
      // finding rather than a shortcut: measured on the courtyard, a single-view shell covers
      // only 11 to 27 per cent of its own bounding box from above at every grid resolution
      // tried, because a 2.5D reconstruction is a curtain and a vertical wall has almost no
      // area seen from overhead. Stitching quads across that leaves a handful of fragments and
      // spans ground nobody photographed. A tile per observed cell shows all of what was seen
      // and bridges none of what was not, which is the same rule the point map already follows.
      positions.push(
        x, y, z,
        x + stepX, y, z,
        x, y, z + stepZ,
        x + stepX, y, z + stepZ,
      );
      const r = Math.round(cell.r);
      const g = Math.round(cell.g);
      const b = Math.round(cell.b);
      const a = Math.round(Math.min(1, cell.support) * 255);
      for (let corner = 0; corner < 4; corner += 1) colours.push(r, g, b, a);
      indices.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
    }
    if (indices.length === 0) continue;

    const mesh = new pc.Mesh(device);
    mesh.setPositions(positions);
    mesh.setColors32(colours);
    mesh.setIndices(indices);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    meshes.push(mesh);

    const node = new pc.Entity(`region-relief:${island.islandId}`);
    const instance = new pc.MeshInstance(mesh, material, node);
    instance.castShadow = false;
    instance.receiveShadow = false;
    instance.visible = false;
    node.addComponent('render', { meshInstances: [instance] });
    entity.addChild(node);
    instances.push(instance);
    reconstructed.add(island.islandId);
  }

  const applyProfile = (next: WorldArtProfile): void => {
    const ground = new pc.Color();
    ground.fromString(next.ui.colors.ground ?? '#ffffff');
    material.setParameter('uGround', [ground.r, ground.g, ground.b]);
    // A constant lift toward the field. The Map is a diagram and a full-strength photograph on it
    // reads as a picture lying on the ground rather than as the ground having a shape.
    material.setParameter('uMix', 0.1);
    material.update();
  };
  applyProfile(profile);

  return {
    entity,
    reconstructed,
    setMapActive(active) {
      for (const instance of instances) instance.visible = active;
    },
    applyProfile,
    destroy() {
      for (const mesh of meshes) mesh.destroy();
      material.destroy();
      entity.destroy();
    },
  };
}
