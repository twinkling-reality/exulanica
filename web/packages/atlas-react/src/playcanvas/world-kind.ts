import {
  RECOVERY_MARGIN_AU,
  buildNavigationWorld,
  navigationRegionForIsland,
  ownedDistrictNavigation,
  type AtlasScene,
  type DistrictInterpretation,
  type IslandId,
  type NavigationSurface,
  type NavigationWorld,
  type OwnedDistrict,
} from '@exulanica/atlas-core';
import type { GeneratedTileMount } from './generated-tile/binding-contract.js';
import type { GoogleTilesConfig } from './google-tiles-config.js';
import type { AuthoredGroundSupport, EndlessAuthoredGroundSupport } from './world-field.js';

/*
 * WHAT KIND OF WORLD THE BINDING IS DRAWING, DECIDED ONCE.
 *
 * The options the app hands `AtlasBinding.create` name at most one ground (an authored starter
 * region, an owned district or a generated tile; none means the regions of a photo-built world)
 * and possibly a Google reference over it. Every decision that follows from which one it is
 * (city scale, where fog is mixed, how the session opens, what is drawn at first, where a person
 * can walk) is read from the one description `describeWorldKind` returns, which also carries the
 * ground's own data, so the binding never asks the options what kind of world it is.
 */

/** Admitted geographic ground, as the app hands it over. */
export interface OwnedDistrictGround {
  readonly document: OwnedDistrict;
  readonly residentBytes: number;
  readonly interpretation?: DistrictInterpretation;
}

/** The ground a world stands on, with what it is drawn from. */
export type WorldGround =
  | { readonly form: 'authored-endless'; readonly region: AuthoredRegion }
  | { readonly form: 'authored-flat'; readonly region: AuthoredRegion }
  | { readonly form: 'scene-regions' }
  | { readonly form: 'owned-district'; readonly district: OwnedDistrictGround }
  | { readonly form: 'generated-tile'; readonly tile: GeneratedTileMount };

export interface WorldKind {
  readonly ground: WorldGround;
  /** The Google photorealistic reference drawn over the world, for looking only, or null. */
  readonly google: GoogleTilesConfig | null;
  /** City scale: a geographic ground or a Google reference, lit and paced as a street is. */
  readonly city: boolean;
  /**
   * Lit materials fog in display space, toward the sky's own colour. Every kind but a generated
   * tile, whose sky is a skybox the engine tone-maps along with its fog.
   */
  readonly displaySpaceFog: boolean;
  /**
   * The session opens from above, at the overview (`camera-views.ts`), rather than standing on the
   * ground. Only where the ground states no arrival of its own and a Google reference is drawn:
   * regions under a reference. A starter's spawn and a district's clear spawn are where they open.
   */
  readonly aerialStart: boolean;
  /** The binding's own ground field is drawn. A district or a tile draws its own ground. */
  readonly fieldVisible: boolean;
  /** The memory layer (the render root) starts shown. Off wherever another ground is drawn. */
  readonly memoryLayerVisible: boolean;
}

/** The options the kind is decided from: which ground, and whether a Google reference is on. */
export interface WorldKindOptions {
  readonly authoredRegion?: AuthoredRegion;
  readonly ownedDistrict?: OwnedDistrictGround;
  readonly generatedTile?: GeneratedTileMount;
  readonly googleTiles?: GoogleTilesConfig;
}

/**
 * Describe the world these options ask for, or refuse a combination no world can be.
 *
 * An authored region WITH a Google reference is accepted, and is exactly what the rules below
 * make it: authored navigation and the authored spawn, stood on the ground, the Google reference
 * drawn at city scale, and the memory layer (with the authored ground in it) hidden. That is what
 * the binding did before this description existed; refusing it would be a change of behaviour and
 * is not made here.
 */
export function describeWorldKind(options: WorldKindOptions): WorldKind {
  if (options.ownedDistrict !== undefined && options.generatedTile !== undefined) {
    throw new TypeError('A generated tile replaces the owned district; pass one or the other');
  }
  if (options.authoredRegion !== undefined &&
      (options.ownedDistrict !== undefined || options.generatedTile !== undefined)) {
    throw new TypeError('An authored starter region cannot replace geographic ground');
  }
  const google = options.googleTiles?.enabled === true && options.googleTiles.apiKey.length > 0
    ? options.googleTiles
    : null;
  const ground: WorldGround = options.generatedTile !== undefined
    ? { form: 'generated-tile', tile: options.generatedTile }
    : options.ownedDistrict !== undefined
      ? { form: 'owned-district', district: options.ownedDistrict }
      : options.authoredRegion === undefined
        ? { form: 'scene-regions' }
        : options.authoredRegion.ground.kind === 'endless'
          ? { form: 'authored-endless', region: options.authoredRegion }
          : { form: 'authored-flat', region: options.authoredRegion };
  const geographic = ground.form === 'owned-district' || ground.form === 'generated-tile';
  return Object.freeze({
    ground: Object.freeze(ground),
    google,
    city: geographic || google !== null,
    displaySpaceFog: ground.form !== 'generated-tile',
    aerialStart: ground.form === 'scene-regions' && google !== null,
    fieldVisible: !geographic,
    memoryLayerVisible: !geographic && google === null,
  });
}

/** The authored starter region a world stands on, or null when it stands on anything else. */
export function authoredRegionOf(kind: WorldKind): AuthoredRegion | null {
  return kind.ground.form === 'authored-endless' || kind.ground.form === 'authored-flat'
    ? kind.ground.region
    : null;
}

/**
 * The camera views a person can ask this kind of world for, besides turning the view and
 * walking, which every world carries out.
 *
 * Asking a world for a view it does not carry out changes nothing on the screen, so the app
 * offers each view only where this says the world has it. `test/binding/world-views.test.ts`
 * holds both halves against the binding for every kind: an offered view moves the camera, and a
 * withheld one leaves it where it was.
 */
export interface WorldViews {
  /**
   * An overview from above and a stance at street level. A district frames both on its own
   * buildings and a Google reference on its fixed city viewpoints; a world with neither has
   * nothing to frame them on.
   */
  readonly cityViews: boolean;
  /**
   * A camera behind the person's drawn figure, at a chosen distance. The follow camera keeps out of
   * what the binding knows is solid: the ground under the person, and a district's buildings
   * (`player-camera.ts`). So it is offered on every ground where that is all there is to keep out
   * of: a starter, the regions of a photo-built world and a district. Not on a generated tile,
   * whose buildings are drawn with no collision the camera could read, so a boom behind the person
   * would pass through their facades; and not under a Google reference, whose photographed ground
   * the binding has no surface for, so the drawn figure would stand on a plane the picture does not
   * show. There the view stays first person, where a distance has nothing to set.
   */
  readonly thirdPerson: boolean;
}

/** The views this kind of world carries out, read from its ground and its reference only. */
export function worldViews(kind: WorldKind): WorldViews {
  const district = kind.ground.form === 'owned-district';
  return Object.freeze({
    cityViews: district || kind.google !== null,
    thirdPerson: kind.google === null && kind.ground.form !== 'generated-tile',
  });
}

/** The layers a person can switch on and off in this kind of world. */
export interface WorldLayers {
  /**
   * A switch for the memory layer: the render root, holding the regions and their motes, the
   * binding's own ground field and the composed world with its sky. Offered only where another
   * ground is drawn outside it, a district, a tile or a Google reference, which is what `city`
   * names. In any other world the memory layer holds the ground itself, so switching it off leaves
   * nothing drawn. `test/binding/world-layers.test.ts` holds both halves for every kind.
   */
  readonly memoryLayer: boolean;
}

/** The layers this kind of world lets a person switch. */
export function worldLayers(kind: WorldKind): WorldLayers {
  return Object.freeze({ memoryLayer: kind.city });
}

/**
 * How far this renderer carries a person across a ground that states no extent.
 *
 * Its reason is what has been measured end to end. The world's own movement resolver walks from
 * the origin to the soft band at 8096 m one frame at a time without a recovery
 * (`test/endless-authored-ground.test.ts`), and on a release build a sprint to 8 km keeps the sky,
 * a placed cube and the rest of the frame as they are at arrival (the render at distance record,
 * `docs/evaluation/2026-09-23-render-at-distance.json`). The 144 m from the last measured picture
 * to the recovery radius at 8144 m are not measured on their own.
 *
 * The float32 step permits the radius and does not set it. A position reaches the GPU as a 32-bit
 * float, and the render origin only moves when the active neighborhood changes, which in a world
 * whose scene holds no regions never happens, so the walk is drawn at its true distance from the
 * world origin. The float32 step there is 0.12 mm at 2 km, 0.49 mm from 4096 to 8192 m and
 * 0.98 mm from 8192 m up to 16384 m: a drawn position resolves the millimetre, the unit every
 * stored coordinate in this product is written in, to twice this radius.
 *
 * It is a property of this renderer and not of the world. A descriptor states that its ground has
 * no edge; this states how much of that ground the current pipeline can honestly draw, and it
 * moves when the pipeline does, with no stored world changing and nothing to migrate.
 */
export const AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M = 8192;

/**
 * The ground an authored region states.
 *
 * `flat` describes a surface whose perimeter is a real edge, such as a place rebuilt from
 * photographs. `endless` states there is no perimeter, so it carries no extent to read.
 */
export type AuthoredGround =
  | {
      readonly kind: 'flat';
      readonly halfWidthMm: number;
      readonly halfDepthMm: number;
      readonly elevationMm: number;
    }
  | {
      readonly kind: 'endless';
      readonly elevationMm: number;
    };

export interface AuthoredRegion {
  readonly regionId: IslandId;
  readonly module: {
    readonly key: 'region.authored-ground';
    readonly version: 1 | 2;
  };
  readonly ground: AuthoredGround;
  /** Ground-contact pose in the authored region frame, in fixed-point wire units. */
  readonly spawn: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
  };
}

/** Where an authored ground has a walking surface, in metres, for the navigation contract. */
export function authoredGroundSurface(ground: AuthoredGround): NavigationSurface {
  const elevation = ground.elevationMm / 1000;
  const sample = Object.freeze({
    height: elevation,
    normal: Object.freeze({ x: 0, y: 1, z: 0 }),
  });
  if (ground.kind === 'endless') {
    const radius = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M;
    return Object.freeze({
      sample: (x: number, z: number) => (Math.hypot(x, z) <= radius ? sample : null),
    });
  }
  const halfWidth = ground.halfWidthMm / 1000;
  const halfDepth = ground.halfDepthMm / 1000;
  return Object.freeze({
    sample: (x: number, z: number) =>
      Math.abs(x) <= halfWidth && Math.abs(z) <= halfDepth ? sample : null,
  });
}

/**
 * The walkable field an endless authored ground admits.
 *
 * `buildNavigationWorld` sizes its field from the scene's regions, and a starter world has none,
 * so it lands on its 90 metre floor. That floor was the second wall standing behind the first: a
 * sampler with no rectangle still leaves a person compressed at 90 metres and returned at 138.
 *
 * Both radii sit INSIDE the distance the surface answers for, by the same margin the resident
 * field already puts between its soft band and its hard envelope. A walk is therefore returned
 * while there is still described ground underneath it, which is what makes the refusal honest:
 * the field this renderer can carry ran out, not the ground. Every position movement can reach,
 * including the compressed overshoot, is a position the surface answers.
 */
export function endlessAuthoredNavigation(world: NavigationWorld): NavigationWorld {
  const recoveryRadius = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M - RECOVERY_MARGIN_AU;
  return Object.freeze({
    ...world,
    fieldRadius: recoveryRadius - RECOVERY_MARGIN_AU,
    recoveryRadius,
  });
}

/** Where a person can walk in this kind of world. */
export function worldNavigation(kind: WorldKind, scene: AtlasScene): NavigationWorld {
  const ground = kind.ground;
  switch (ground.form) {
    case 'generated-tile':
      return ground.tile.navigationWorld;
    // The district owns the ground and the blockers; the scene owns where the memories are. Both
    // are already drawn in the same coordinate space, so withholding the regions from the
    // navigation world did not keep them apart, it only made them unreachable.
    case 'owned-district':
      return ownedDistrictNavigation(ground.district.document, scene.islands.map(navigationRegionForIsland));
    case 'authored-endless':
      return endlessAuthoredNavigation(buildNavigationWorld(scene, authoredGroundSurface(ground.region.ground)));
    case 'authored-flat':
      return buildNavigationWorld(scene, authoredGroundSurface(ground.region.ground));
    case 'scene-regions':
      return buildNavigationWorld(scene, undefined);
  }
  throw new TypeError(`No navigation for a world standing on ${(ground as { form: string }).form}`);
}

/**
 * The support the binding's ground field draws for an authored region, or none for any other
 * ground. An endless ground is still an authored starter, so the field is told so rather than
 * given nothing: given nothing, it drew the photo-world landscape, whose shader never samples a
 * shadow map, and objects placed on it cast no shadow. It is given an elevation and no extent,
 * because it has none, and how far the camera sees, which is how far its face is drawn.
 */
export function authoredFieldSupport(
  region: AuthoredRegion | null,
  reach: number,
): AuthoredGroundSupport | EndlessAuthoredGroundSupport | undefined {
  if (region === null) return undefined;
  const elevation = region.ground.elevationMm / 1000;
  return region.ground.kind === 'endless'
    ? Object.freeze({ kind: 'endless' as const, elevation, reach })
    : Object.freeze({
      halfWidth: region.ground.halfWidthMm / 1000,
      halfDepth: region.ground.halfDepthMm / 1000,
      elevation,
    });
}
