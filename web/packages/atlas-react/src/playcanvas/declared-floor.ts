import * as pc from 'playcanvas';
import type { IslandId } from '@exulanica/atlas-core';

/**
 * The floor every region of a world made from photographs has, drawn as a floor.
 *
 * Such a world states no ground: its photographs are cards nobody stands on. The server declares a
 * floor in each region instead (the society ground catalog's `floor: declared`, served on the saved
 * world's entry as `declared_floor`): a square of a stated half extent about the region origin, at
 * a stated height in the region's frame. Objects are placed on it and the region's people walk on
 * it, so a person is shown what they stand on, as a surface of its own, and never a photograph
 * standing in for ground. It is hung from each drawn region's own root, so it turns and moves with
 * the region, as the region's objects and people do.
 */

export interface DeclaredFloorSpec {
  readonly halfExtentMm: number;
  readonly elevationMm: number;
}

/**
 * What the floors are drawn under: the device and the root of every region the binding draws,
 * whether or not anything in it was reconstructed (a region drawn only as photographs has a root
 * and no point map).
 */
export interface FloorRegions {
  readonly device: pc.GraphicsDevice;
  readonly regionRoots: ReadonlyMap<IslandId, pc.Entity>;
}

export interface DrawnDeclaredFloors {
  readonly islandIds: readonly IslandId[];
  destroy(): void;
}

const MM_PER_METRE = 1000;
/** One tile of the floor's pattern, a metre: a unit, so the floor's size reads at a glance. */
const TILE_MM = 1000;
/** Texels on a side of the tile's pattern; the line is one texel, so it stays thin up close. */
const TILE_TEXELS = 32;
/** The floor's tone and its tile lines: a pale stone apart from the landscape and the prints. */
const FLOOR_RGB = [198, 192, 180] as const;
const LINE_RGB = [160, 153, 140] as const;
/** The edge that says where the declared floor ends, in metres wide, and its tone. */
const EDGE_WIDTH_M = 0.08;
const EDGE_RGB = [0.42, 0.39, 0.35] as const;
/** How far the edge stands above the floor, in metres, so the two never fight for a pixel. */
const EDGE_LIFT_M = 0.002;

function tileTexels(): Uint8Array {
  const out = new Uint8Array(TILE_TEXELS * TILE_TEXELS * 4);
  for (let y = 0; y < TILE_TEXELS; y += 1) {
    for (let x = 0; x < TILE_TEXELS; x += 1) {
      const rgb = x === 0 || y === 0 ? LINE_RGB : FLOOR_RGB;
      out.set([rgb[0], rgb[1], rgb[2], 255], (y * TILE_TEXELS + x) * 4);
    }
  }
  return out;
}

/** Draw the declared floor under every region the binding draws; `destroy` takes them all away. */
export function drawDeclaredFloors(binding: FloorRegions, floor: DeclaredFloorSpec): DrawnDeclaredFloors {
  if (!(floor.halfExtentMm > 0)) throw new Error('A declared floor has a positive half extent');
  const side = (2 * floor.halfExtentMm) / MM_PER_METRE;
  const height = floor.elevationMm / MM_PER_METRE;
  const texture = new pc.Texture(binding.device, {
    name: 'declared-floor-tile',
    width: TILE_TEXELS,
    height: TILE_TEXELS,
    format: pc.PIXELFORMAT_SRGBA8,
    mipmaps: true,
    addressU: pc.ADDRESS_REPEAT,
    addressV: pc.ADDRESS_REPEAT,
    minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
    magFilter: pc.FILTER_LINEAR,
    levels: [tileTexels()],
  });
  const surface = new pc.StandardMaterial();
  surface.name = 'declared-floor';
  surface.diffuseMap = texture;
  const tiles = (2 * floor.halfExtentMm) / TILE_MM;
  surface.diffuseMapTiling = new pc.Vec2(tiles, tiles);
  surface.update();
  const edge = new pc.StandardMaterial();
  edge.name = 'declared-floor-edge';
  edge.diffuse = new pc.Color(EDGE_RGB[0], EDGE_RGB[1], EDGE_RGB[2]);
  edge.update();
  const entities: pc.Entity[] = [];
  for (const [islandId, region] of binding.regionRoots) {
    const root = new pc.Entity(`declared-floor:${islandId}`);
    root.setLocalPosition(0, height, 0);
    const plane = new pc.Entity('declared-floor-surface');
    plane.addComponent('render', { type: 'plane', material: surface, castShadows: false });
    plane.setLocalScale(side, 1, side);
    root.addChild(plane);
    // Four strips along the edges, so where people and objects may stand ends where it is seen.
    for (const [x, z, sx, sz] of [
      [0, -side / 2, side, EDGE_WIDTH_M], [0, side / 2, side, EDGE_WIDTH_M],
      [-side / 2, 0, EDGE_WIDTH_M, side], [side / 2, 0, EDGE_WIDTH_M, side],
    ] as const) {
      const strip = new pc.Entity('declared-floor-edge');
      strip.addComponent('render', { type: 'plane', material: edge, castShadows: false });
      strip.setLocalPosition(x, EDGE_LIFT_M, z);
      strip.setLocalScale(sx, 1, sz);
      root.addChild(strip);
    }
    region.addChild(root);
    entities.push(root);
  }
  let destroyed = false;
  return {
    islandIds: [...binding.regionRoots.keys()],
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      for (const entity of entities) entity.destroy();
      surface.destroy();
      edge.destroy();
      texture.destroy();
    },
  };
}
