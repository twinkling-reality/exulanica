import type { TextureSetDefinition } from '../definition.js';
import { stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp } from '../integer.js';
import { band, fbm, valueNoise } from '../noise.js';
import { type Recipe, heightOfLength, jitter, permille, setColour, shade } from '../sample.js';
import { type Srgb, decode } from '../srgb.js';

/**
 * Brushed, clear-anodised aluminium, the finish of most storefront framing and cladding.
 *
 * The brushing runs along u. Real hairline brushing is finer than a 1 mm texel, so it is carried
 * mostly by roughness and base colour, with a 2.5 mm streak field the texels can actually hold.
 * The base colour is the metal's reflectance at normal incidence, as glTF expects of a metal, and
 * metalness is full except under smudges, which are a thin dielectric film.
 */
const EXTENT = 1000;
const RANGE_MM = 1;
const SURFACE_MM_1024THS = 512;

/** Clear-anodised aluminium reflectance, a little below bare aluminium's. sRGB. */
const ALUMINIUM: Srgb = [228, 230, 232];

function recipe(seed: number): Recipe {
  const aluminium = decode(ALUMINIUM);
  const brushSeed = stream(seed, 1);
  const hairSeed = stream(seed, 2);
  const waveSeed = stream(seed, 3);
  const smudgeSeed = stream(seed, 4);
  const toneSeed = stream(seed, 5);

  return (x, y, out) => {
    // Streaks 250 mm long and 2.5 mm across, and a finer layer at twice the frequency.
    const brush = fbm(x, y, 4, 400, brushSeed, 2);
    const hair = valueNoise(x, y, 16, 512, hairSeed);
    const wave = fbm(x, y, 3, 3, waveSeed, 2);
    out.height = heightOfLength(
      SURFACE_MM_1024THS
        + floorDiv((brush - 32768) * 40, 32768)
        + floorDiv((hair - 32768) * 20, 32768)
        + floorDiv((wave - 32768) * 120, 32768),
      RANGE_MM,
    );

    // Handling marks: small and faint. A strong broad smudge would repeat down the whole street.
    const smudge = band(fbm(x, y, 16, 16, smudgeSeed, 3), 47500, 52500);
    setColour(out, aluminium);
    shade(out, jitter(fbm(x, y, 5, 5, toneSeed, 2), 900));
    shade(out, jitter(brush, 1300));
    shade(out, jitter(hair, 700));
    shade(out, ONE - floorDiv(smudge * 3, 100));

    out.roughness = clamp(
      permille(320)
        + floorDiv((brush - 32768) * 4000, 32768)
        + floorDiv((hair - 32768) * 1800, 32768)
        + floorDiv(smudge * 3300, ONE),
      0,
      FULL,
    );
    out.metalness = lerp(FULL, permille(950), smudge);
    out.occlusion = ONE;
  };
}

export const metal = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.storefront-metal',
  version,
  seed,
  family: 'metal',
  title: 'Storefront metal',
  summary: 'Brushed clear-anodised aluminium with the brushing along u and light smudging.',
  width: 1024,
  height: 1024,
  extentU: EXTENT,
  extentV: EXTENT,
  surface: 'vertical',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 3, depthMm: 1, strengthPermille: 150 },
  parameters: {
    finish: 'brushed along u, clear anodised',
    brush_streak_length_mm: EXTENT / 4,
    brush_streak_width_mm_1024ths: floorDiv(EXTENT * 1024, 400),
    surface_height_mm_1024ths: SURFACE_MM_1024THS,
  },
  recipe: () => recipe(seed),
});
