import * as pc from 'playcanvas';
import { unitRgb, type WorldArtProfile } from '@exulanica/presentation';
import type { ComposedWorld } from './composed-world.js';
import type { WorldKind } from './world-kind.js';

/*
 * THE LIGHT AND AIR A WORLD IS DRAWN IN.
 *
 * Two looks, as data: a composed world (a saved world's starter ground, or the regions of a
 * photo-built world) and a city (an owned district, a generated tile or a Google reference).
 * Each states how far the camera sees, what it clears to, the ambient light and exposure, where
 * fog starts and ends, and the sun. They are the values each kind was built with; where one was
 * measured, its comment says how. Every one of them moves pixels that the binding's GPU scenes
 * pin (`test/binding/gpu/binding-pixels.ts`). The runtime below keeps the camera's
 * clear colour, the ambient light, the fog and the sun's colour in step with the art profile and
 * the Map, and nothing outside this file sets any of them.
 */

type Rgb = readonly [number, number, number];

export interface AtmospherePreset {
  readonly name: 'composed-world' | 'city';
  /** The camera's far clip, metres: how far the world is drawn. */
  readonly farClip: number;
  /** The clear colour the world opens with, or null for the art profile's own sky. */
  readonly clearColour: Rgb | null;
  /** The ambient light the world opens with, or null for the art profile's haze. */
  readonly ambient: Rgb | null;
  readonly exposure: number;
  /** Linear fog, metres from the camera. */
  readonly fog: { readonly start: number; readonly end: number };
  readonly sun: {
    readonly intensity: number;
    readonly shadowDistance: number;
    readonly normalOffsetBias: number;
    readonly shadowBias: number;
  };
  /** A second, shadowless directional light filling from the sky, or none. */
  readonly skyFill: { readonly colour: Rgb; readonly intensity: number; readonly euler: Rgb } | null;
}

/** The share of the art profile's haze that is the ambient light. */
const HAZE_AMBIENT_SHARE = 0.58;
/** Where the sun stands, as the engine's Euler angles in degrees. */
const SUN_EULER: Rgb = [52, -38, 0];
const SUN_SHADOW_RESOLUTION = 2048;
/** The Map clears to the art profile's terrain with a share of its terrain lift. */
const MAP_CLEAR_TERRAIN_SHARE = 0.72;
const MAP_CLEAR_LIFT_SHARE = 0.28;

export const COMPOSED_WORLD_ATMOSPHERE: AtmospherePreset = Object.freeze({
  name: 'composed-world',
  farClip: 1200,
  clearColour: null,
  ambient: null,
  exposure: 1.06,
  fog: Object.freeze({ start: 46, end: 220 }),
  sun: Object.freeze({
    intensity: 1.65,
    shadowDistance: 72,
    normalOffsetBias: 0,
    // The caster pass's slope bias. The engine's receiver bias for a directional light is a
    // fixed 1e-4 of the depth range it fits to the casters in view, about a tenth of a millimetre
    // for one placed object, so at 0.05 a smooth-shaded object shadowed its own lit faces in
    // bands. 0.2 left none on a marker cube from the arrival point to 8 km (measured).
    shadowBias: 0.2,
  }),
  skyFill: null,
});

export const CITY_ATMOSPHERE: AtmospherePreset = Object.freeze({
  name: 'city',
  farClip: 15_000,
  clearColour: Object.freeze([0.79, 0.85, 0.88] as const),
  ambient: Object.freeze([0.64, 0.69, 0.74] as const),
  exposure: 1.12,
  fog: Object.freeze({ start: 110, end: 820 }),
  sun: Object.freeze({ intensity: 1.1, shadowDistance: 120, normalOffsetBias: 0.25, shadowBias: 0.2 }),
  skyFill: Object.freeze({
    colour: Object.freeze([0.7, 0.82, 1] as const),
    intensity: 0.72,
    euler: Object.freeze([28, 145, 0] as const),
  }),
});

/** A city's look at city scale, and a composed world's everywhere else. */
export function atmosphereFor(kind: WorldKind): AtmospherePreset {
  return kind.city ? CITY_ATMOSPHERE : COMPOSED_WORLD_ATMOSPHERE;
}

/*
 * FOG IN THE SPACE THE SKY IS DRAWN IN.
 *
 * The engine's lit materials end by fogging, then tone mapping, then encoding: fog is mixed in
 * linear light and the result goes through ACES with the scene's exposure. The origin sky and the
 * camera's clear colour are written raw. So fully fogged ground reached the screen as the fog
 * colour tone-mapped, which is greyer than the same colour written raw: 232 against a sky of 254
 * in the default look, measured, and a hard horizon line wherever open ground runs to the sky.
 * These replace the lit end chunk so a surface is tone-mapped and encoded first and then mixed
 * toward the fog colour exactly as authored, which is how the sky arrives on the screen. The mix
 * uses the engine's own fog factor, so start, end and blend-mode handling are unchanged.
 */
const DISPLAY_SPACE_FOG_END_GLSL = `
    gl_FragColor.rgb = combineColor(litArgs_albedo, litArgs_sheen_specularity, litArgs_clearcoat_specularity);
    gl_FragColor.rgb += litArgs_emission;
    gl_FragColor.rgb = toneMap(gl_FragColor.rgb);
    gl_FragColor.rgb = gammaCorrectOutput(gl_FragColor.rgb);
    #if (FOG != NONE)
        gl_FragColor.rgb = mix(gammaCorrectOutput(fog_color * dBlendModeFogFactor), gl_FragColor.rgb, getFogFactor());
    #endif
`;
const DISPLAY_SPACE_FOG_END_WGSL = `
    var finalRgb: vec3f = combineColor(litArgs_albedo, litArgs_sheen_specularity, litArgs_clearcoat_specularity);
    finalRgb = finalRgb + litArgs_emission;
    finalRgb = toneMap(finalRgb);
    finalRgb = gammaCorrectOutput(finalRgb);
    #if (FOG != NONE)
        finalRgb = mix(gammaCorrectOutput(uniform.fog_color * dBlendModeFogFactor), finalRgb, getFogFactor());
    #endif
    output.color = vec4f(finalRgb, output.color.a);
`;

/**
 * Make every lit material on this device fog in display space.
 *
 * THE ORDERING IS LOAD-BEARING, AT BOTH ENDS. Call it after `app.init` and before the first frame.
 * `app.init` registers the engine's default chunks over whatever the map held, so an earlier call
 * is silently undone (`display-space-fog.test.ts` shows it). And the map is read when a program is
 * built, so a program already built keeps the chunk it was built with: measured, setting this map
 * after the scene had drawn left the ground on the old order even with every material's variants
 * cleared. Between the two, nothing has compiled and every program is built with it.
 *
 * Particles and Gaussian splats have end chunks of their own and still fog before tone mapping.
 */
export function installDisplaySpaceFog(device: pc.GraphicsDevice): void {
  pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).set('endPS', DISPLAY_SPACE_FOG_END_GLSL);
  pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_WGSL).set('endPS', DISPLAY_SPACE_FOG_END_WGSL);
}

/**
 * The colour the sky shows at eye level: the composed world's own sky when it is drawing one,
 * otherwise the colour the camera clears to, which is then the whole sky.
 */
export function skyColourAtEyeLevel(
  world: Pick<ComposedWorld, 'skyHorizonColour'>,
  clear: pc.Color | undefined,
): readonly [number, number, number] {
  return world.skyHorizonColour()
    ?? (clear === undefined ? [1, 1, 1] : [clear.r, clear.g, clear.b]);
}


/**
 * Give a new world its air: the camera's reach, clear colour and tone mapping, the ambient light,
 * exposure and fog, and the sun (and a city's sky fill) under the application root. Called once,
 * right after the camera joins the scene, so the lights follow it in the scene graph.
 */
export function openAtmosphere(
  app: pc.AppBase,
  camera: pc.CameraComponent,
  preset: AtmospherePreset,
  profile: WorldArtProfile,
): void {
  camera.farClip = preset.farClip;
  const [skyR, skyG, skyB] = preset.clearColour ?? unitRgb(profile.palette.sky);
  camera.clearColor = new pc.Color(skyR, skyG, skyB, 1);
  camera.toneMapping = pc.TONEMAP_ACES;
  const [hazeR, hazeG, hazeB] = unitRgb(profile.palette.haze);
  app.scene.ambientLight = preset.ambient === null
    ? new pc.Color(hazeR * HAZE_AMBIENT_SHARE, hazeG * HAZE_AMBIENT_SHARE, hazeB * HAZE_AMBIENT_SHARE)
    : new pc.Color(...preset.ambient);
  app.scene.exposure = preset.exposure;
  app.scene.fog.type = pc.FOG_LINEAR;
  // The clear colour for now: `WorldAtmosphere.fogInDisplaySpace` aims the fog at the world's own
  // sky once it exists.
  app.scene.fog.color.set(skyR, skyG, skyB);
  app.scene.fog.start = preset.fog.start;
  app.scene.fog.end = preset.fog.end;

  const sun = new pc.Entity('atlas-directional-light');
  const [sunR, sunG, sunB] = unitRgb(profile.palette.sun);
  sun.addComponent('light', {
    type: 'directional',
    color: new pc.Color(sunR, sunG, sunB),
    intensity: preset.sun.intensity,
    castShadows: true,
    shadowDistance: preset.sun.shadowDistance,
    normalOffsetBias: preset.sun.normalOffsetBias,
    shadowBias: preset.sun.shadowBias,
    shadowResolution: SUN_SHADOW_RESOLUTION,
  });
  sun.setEulerAngles(...SUN_EULER);
  app.root.addChild(sun);
  if (preset.skyFill !== null) {
    const fill = new pc.Entity('district-sky-fill');
    fill.addComponent('light', {
      type: 'directional', color: new pc.Color(...preset.skyFill.colour), intensity: preset.skyFill.intensity,
      castShadows: false,
    });
    fill.setEulerAngles(...preset.skyFill.euler);
    app.root.addChild(fill);
  }
}

/**
 * Keeps the air in step with the art profile and the Map once the world is built.
 *
 * A profile change sets the sky and Map clear colours, the ambient light (from the profile's haze,
 * in every kind of world) and the sun's colour, and re-aims the fog. The Map clears to its own
 * colour and re-aims the fog at whatever sky is then drawn.
 */
export class WorldAtmosphere {
  readonly #skyClear = new pc.Color();
  readonly #mapClear = new pc.Color();
  #displaySpaceFog = false;

  /** Whether lit materials fog in display space toward the sky. */
  get displaySpaceFog(): boolean {
    return this.#displaySpaceFog;
  }

  constructor(
    private readonly app: pc.AppBase,
    private readonly camera: pc.CameraComponent,
    private readonly world: Pick<ComposedWorld, 'skyHorizonColour'>,
    profile: WorldArtProfile,
  ) {
    this.#setClearColours(profile);
  }

  /**
   * Mix fog in display space toward the sky, from now on, and aim it now. Called once the render
   * roots are on or off, because whether the world's own sky is drawn depends on them: the city
   * and the tile switch the composed world off, and their sky is the clear colour.
   */
  fogInDisplaySpace(displaySpaceFog: boolean): void {
    this.#displaySpaceFog = displaySpaceFog;
    if (displaySpaceFog) this.#syncFogToSky();
  }

  setProfile(profile: WorldArtProfile, mapActive: boolean): void {
    this.#setClearColours(profile);
    this.camera.clearColor.copy(mapActive ? this.#mapClear : this.#skyClear);
    const [hazeR, hazeG, hazeB] = unitRgb(profile.palette.haze);
    this.app.scene.ambientLight.set(hazeR * HAZE_AMBIENT_SHARE, hazeG * HAZE_AMBIENT_SHARE, hazeB * HAZE_AMBIENT_SHARE);
    if (this.#displaySpaceFog) this.#syncFogToSky();
    else this.app.scene.fog.color.set(hazeR, hazeG, hazeB);
    const [sunR, sunG, sunB] = unitRgb(profile.palette.sun);
    const sun = (this.app.root.findByName('atlas-directional-light') as pc.Entity | null)?.light;
    if (sun !== undefined && sun !== null) sun.color.set(sunR, sunG, sunB);
  }

  setMapActive(active: boolean): void {
    this.camera.clearColor.copy(active ? this.#mapClear : this.#skyClear);
    if (this.#displaySpaceFog) this.#syncFogToSky();
  }

  #setClearColours(profile: WorldArtProfile): void {
    const [skyR, skyG, skyB] = unitRgb(profile.palette.sky);
    this.#skyClear.set(skyR, skyG, skyB, 1);
    const [groundR, groundG, groundB] = unitRgb(profile.palette.terrain);
    const [surfaceR, surfaceG, surfaceB] = unitRgb(profile.palette.terrainLift);
    this.#mapClear.set(
      groundR * MAP_CLEAR_TERRAIN_SHARE + surfaceR * MAP_CLEAR_LIFT_SHARE,
      groundG * MAP_CLEAR_TERRAIN_SHARE + surfaceG * MAP_CLEAR_LIFT_SHARE,
      groundB * MAP_CLEAR_TERRAIN_SHARE + surfaceB * MAP_CLEAR_LIFT_SHARE,
      1,
    );
  }

  /**
   * Aim the fog at the colour the sky shows at eye level: the composed world's own sky when it is
   * drawing one, otherwise the colour the camera clears to. With fog mixed in display space, far
   * ground then arrives on the screen as exactly the sky beside it.
   */
  #syncFogToSky(): void {
    const [r, g, b] = skyColourAtEyeLevel(this.world, this.camera.clearColor);
    this.app.scene.fog.color.set(r, g, b);
  }
}
