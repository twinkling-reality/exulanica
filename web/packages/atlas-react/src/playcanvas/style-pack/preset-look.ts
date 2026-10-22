import type { Srgb8, StylePackLightPreset, StylePackManifest } from '@exulanica/atlas-core';
import { RENDER_LOOK_ID, TILE_LOOK_V1, validateRenderLook, type RenderLook, type Rgb } from '../generated-tile/look.js';

/**
 * A pack's light preset as the render look the renderer draws with.
 *
 * A pack states whole numbers in stated units and sRGB bytes; the render look states linear light
 * and metres. This is the one conversion between them: per mille and millionths divided out,
 * millimetres to metres, millidegrees to degrees, and each sRGB byte through the IEC 61966-2-1
 * transfer function (the sun's colour too, since a light's colour is linear). What a pack does not
 * choose stays the engine's: shadow maps of 4096 texels in four cascades to 140 m, a 512-texel probe
 * prefiltered from 64-texel faces, sixteen occlusion samples, and the tile look's surface and
 * unavailable rules. The result is validated like any render look, so a pack can never reach the
 * renderer with a value the render look refuses. `waterLight`, the share of its look's own light a
 * world's setting gives (`world-look.ts`), is carried on the water when it is below 1.
 */

const linear = (byte: number): number => {
  const v = byte / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
export const linearRgb = ([r, g, b]: Srgb8): Rgb => [linear(r), linear(g), linear(b)];

export const PACK_ENGINE = Object.freeze({
  shadowResolution: 4096,
  shadowDistanceM: 140,
  cascades: 4,
  cascadeDistribution: 0.6,
  bias: 0.12,
  normalOffsetBias: 0.08,
  atlasSize: 512,
  sourceSize: 64,
  occlusionSamples: 16,
});

export function renderLookOfPreset(
  preset: StylePackLightPreset,
  shading: NonNullable<StylePackManifest['shading']>,
  edge: StylePackManifest['edge'],
  version = 1,
  water?: StylePackManifest['water'],
  fallingWater?: StylePackManifest['falling_water'],
  waterLight = 1,
): RenderLook {
  const sky = preset.sky;
  const haze = preset.haze;
  const wind = preset.wind;
  const post = preset.post;
  const look: RenderLook = {
    id: RENDER_LOOK_ID,
    version,
    exposure: preset.exposure_permille / 1000,
    toneMapping: preset.tone_mapping,
    sky: {
      zenith: linearRgb(sky.zenith),
      horizon: linearRgb(sky.horizon),
      ground: linearRgb(sky.ground),
      bounceGround: linearRgb(sky.bounce_ground),
      intensity: sky.intensity_permille / 1000,
      sunGlow: sky.sun_glow_permille / 1000,
      sunDisc: sky.sun_disc_permille / 1000,
      clouds: sky.clouds === null ? null : {
        cover: sky.clouds.cover_permille / 1000,
        colour: linearRgb(sky.clouds.colour),
        shade: linearRgb(sky.clouds.shade),
        scale: sky.clouds.scale_permille / 1000,
        seed: sky.clouds.seed,
      },
      faceTexels: sky.face_texels,
      ...(sky.model === undefined || sky.model === null ? {} : {
        model: {
          kind: sky.model.kind,
          turbidity: sky.model.turbidity_permille / 1000,
          rayleigh: sky.model.rayleigh_permille / 1000,
          mie: sky.model.mie_micro / 1_000_000,
          mieDirection: sky.model.mie_direction_permille / 1000,
        },
      }),
      ...(sky.stars === undefined ? {} : {
        stars: { density: sky.stars.density_permille / 1000, intensity: sky.stars.intensity_permille / 1000, seed: sky.stars.seed },
      }),
      ...(sky.moon === undefined ? {} : { moon: { maria: sky.moon.maria_permille / 1000, seed: sky.moon.seed } }),
    },
    fog: preset.fog.kind === 'linear'
      ? { kind: 'linear', startM: preset.fog.start_mm / 1000, endM: preset.fog.end_mm / 1000, colour: linearRgb(preset.fog.colour) }
      : { kind: 'exp2', density: preset.fog.density_micro / 1_000_000, colour: linearRgb(preset.fog.colour) },
    sun: {
      elevationDeg: preset.sun.elevation_mdeg / 1000,
      azimuthDeg: preset.sun.azimuth_mdeg / 1000,
      colour: linearRgb(preset.sun.colour),
      intensity: preset.sun.intensity_permille / 1000,
      shadow: {
        resolution: PACK_ENGINE.shadowResolution,
        distanceM: PACK_ENGINE.shadowDistanceM,
        cascades: PACK_ENGINE.cascades,
        cascadeDistribution: PACK_ENGINE.cascadeDistribution,
        bias: PACK_ENGINE.bias,
        normalOffsetBias: PACK_ENGINE.normalOffsetBias,
        filter: preset.sun.shadow.filter,
        penumbra: 0,
      },
    },
    environment: { intensity: preset.environment.intensity_permille / 1000, atlasSize: PACK_ENGINE.atlasSize, sourceSize: PACK_ENGINE.sourceSize },
    contactShadow: {
      ...TILE_LOOK_V1.contactShadow,
      mode: preset.contact_shadow.mode,
      radiusM: preset.contact_shadow.radius_mm / 1000,
      intensity: preset.contact_shadow.intensity_permille / 1000,
      samples: PACK_ENGINE.occlusionSamples,
    },
    surface: TILE_LOOK_V1.surface,
    post: {
      bloom: post.bloom === null ? null : { intensity: post.bloom.intensity_permille / 1000, blurLevel: post.bloom.blur_level },
      grading: {
        brightness: post.grading.brightness_permille / 1000,
        contrast: post.grading.contrast_permille / 1000,
        saturation: post.grading.saturation_permille / 1000,
        tint: linearRgb(post.grading.tint),
      },
      enhance: {
        shadows: post.enhance.shadows_permille / 1000,
        highlights: post.enhance.highlights_permille / 1000,
        midtones: post.enhance.midtones_permille / 1000,
        vibrance: post.enhance.vibrance_permille / 1000,
        dehaze: post.enhance.dehaze_permille / 1000,
      },
      vignette: post.vignette === null ? null : {
        intensity: post.vignette.intensity_permille / 1000,
        inner: post.vignette.inner_permille / 1000,
        outer: post.vignette.outer_permille / 1000,
        curvature: post.vignette.curvature_permille / 1000,
        colour: linearRgb(post.vignette.colour),
      },
      taa: post.taa,
      ...(post.sharpness_permille === undefined ? {} : { sharpness: post.sharpness_permille / 1000 }),
    },
    shading: {
      model: shading.model,
      toon: shading.toon === null ? null : {
        shadowEdge: shading.toon.shadow_edge_permille / 1000,
        lightEdge: shading.toon.light_edge_permille / 1000,
        bandShare: shading.toon.band_share_permille / 1000,
        softness: shading.toon.softness_permille / 1000,
      },
      ink: shading.ink === null ? null : linearRgb(shading.ink),
    },
    edge: edge === null ? null : { ground: linearRgb(edge.ground), dropM: edge.drop_mm / 1000, reachM: edge.reach_mm / 1000 },
    ...(wind === undefined ? {} : {
      wind: {
        direction: (wind.direction_mdeg / 1000) * (Math.PI / 180),
        swayM: wind.sway_mm / 1000,
        pace: wind.pace_millirad_per_s / 1000,
        gustScaleM: wind.gust_scale_mm / 1000,
        gustShare: wind.gust_share_permille / 1000,
        flutterM: wind.flutter_mm / 1000,
        swayFamilies: [...wind.sway_families],
      },
    }),
    ...(preset.lit_windows_permille === undefined ? {} : { litWindows: preset.lit_windows_permille / 1000 }),
    ...(haze === undefined ? {} : {
      haze: {
        density: haze.density_micro / 1_000_000,
        falloff: haze.falloff_micro / 1_000_000,
        baseM: haze.base_mm / 1000,
        maxDepth: haze.max_depth_permille / 1000,
        colour: haze.colour === null ? null : linearRgb(haze.colour),
      },
    }),
    ...(water === undefined ? {} : {
      water: {
        shallow: linearRgb(water.shallow),
        deep: linearRgb(water.deep),
        absorption: [water.absorption_per_km[0] / 1000, water.absorption_per_km[1] / 1000, water.absorption_per_km[2] / 1000] as const,
        depthScaleM: water.depth_scale_mm / 1000,
        foamWidthM: water.foam_width_mm / 1000,
        reflection: water.reflection_permille / 1000,
        ...(water.ripples === undefined ? {} : {
          ripples: {
            octaves: water.ripples.octaves.map((octave) => ({
              angle: (octave.angle_mdeg / 1000) * (Math.PI / 180),
              cellM: octave.cell_mm / 1000,
              tilt: octave.tilt_permille / 1000,
              drift: [octave.drift_mm_per_s[0] / 1000, octave.drift_mm_per_s[1] / 1000] as const,
            })),
            fadeFrom: water.ripples.fade_from_millicells_per_px / 1000,
            fadeTo: water.ripples.fade_to_millicells_per_px / 1000,
          },
        }),
        ...(water.caustics === undefined ? {} : {
          caustics: {
            strength: water.caustics.strength_permille / 1000,
            cellM: water.caustics.cell_mm / 1000,
            pace: water.caustics.pace_millirad_per_s / 1000,
            reachM: water.caustics.reach_mm / 1000,
          },
        }),
        ...(water.contact === undefined ? {} : {
          contact: {
            wetKeep: water.contact.wet_keep_permille / 1000,
            lightDown: water.contact.light_down_permille / 1000,
            shallowFacing: water.contact.shallow_facing_permille / 1000,
            foamReachM: Object.fromEntries(Object.entries(water.contact.foam_reach_mm).map(([role, mm]) => [role, mm / 1000])),
          },
        }),
        ...(waterLight >= 1 ? {} : { light: waterLight }),
      },
    }),
    ...(fallingWater === undefined ? {} : {
      fallingWater: {
        streakSpeedMps: fallingWater.streak_speed_mm_per_s / 1000,
        streakWidthM: fallingWater.streak_width_mm / 1000,
        streakLengthM: fallingWater.streak_length_mm / 1000,
        streakContrast: fallingWater.streak_contrast_permille / 1000,
        aeration: fallingWater.aeration_permille / 1000,
        foamHeightM: fallingWater.foam_height_mm / 1000,
        foam: linearRgb(fallingWater.foam),
      },
    }),
    unavailable: TILE_LOOK_V1.unavailable,
  };
  return validateRenderLook(look);
}
