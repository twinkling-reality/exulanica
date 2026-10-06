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
 * renderer with a value the render look refuses.
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
): RenderLook {
  const sky = preset.sky;
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
    unavailable: TILE_LOOK_V1.unavailable,
  };
  return validateRenderLook(look);
}
