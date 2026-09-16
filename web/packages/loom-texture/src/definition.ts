import type { Pattern } from './sample.js';

/**
 * One texture set, as the catalog states it before anything is baked.
 *
 * A set is named by the SURFACE it draws (brick, ashlar, asphalt), never by an era, a typology or
 * a height class. Deciding which building gets which surface is the grammar's material stage, and
 * the dependency-cruiser fence around this package exists so that vocabulary cannot be rebuilt
 * here by accident.
 *
 * Every number is an integer in a stated unit, because every number here reaches the container
 * header and the header is a digest input. `extentU` and `extentV` are the load-bearing pair: they
 * are the physical size one tile covers, which is what lets a surface carry a UV scale derived
 * from a real dimension (surface width / extentU repeats) instead of one somebody guessed.
 */
export interface TextureSetDefinition {
  /** Stable name, `<licence>.<surface>`, matching ^[a-z][a-z0-9.-]*$. Never a version or digest. */
  readonly setId: string;
  /** Bake input, bumped whenever the bytes change. A pinned version never names new bytes. */
  readonly version: number;
  /** The hash seed, recorded in the header. */
  readonly seed: number;
  /** The surface family, for a reader; the id is what anything resolves. */
  readonly family: string;
  readonly title: string;
  readonly summary: string;
  /** Texels. */
  readonly width: number;
  readonly height: number;
  /** Millimetres of surface one tile covers along u (columns) and v (rows). */
  readonly extentU: number;
  readonly extentV: number;
  /**
   * How the tile lies. `vertical`: u runs horizontally along a wall and v runs downward, so world
   * up is toward row 0. `horizontal`: u runs along the carriageway, footway or kerb and v across it.
   */
  readonly surface: 'vertical' | 'horizontal';
  /** Millimetres between height 0 and height 255. */
  readonly heightRangeMm: number;
  /** How the bake measures occlusion from the height field. */
  readonly cavity: CavitySpec;
  /** What the recipe reads, stated in the header so a reader can see the module it was built on. */
  readonly parameters: Readonly<Record<string, number | string>>;
  /** Build the pattern. Called once per bake, so a pattern may hold scratch state. */
  readonly pattern: () => Pattern;
}

export interface CavitySpec {
  /** Radius of the neighbourhood a texel is compared against, mm. */
  readonly radiusMm: number;
  /** Depth below that neighbourhood at which occlusion reaches its maximum, mm. */
  readonly depthMm: number;
  /** The maximum occlusion, in thousandths. */
  readonly strengthPermille: number;
}
