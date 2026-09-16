import type { TextureSetDefinition } from '../definition.js';
import { pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import {
  type Recipe,
  heightOfLength,
  jitter,
  mixColour,
  permille,
  setColour,
  shade,
} from '../sample.js';
import { type Srgb, decode } from '../srgb.js';
import { MM } from '../tile.js';

/**
 * Painted render (stucco) with a dashed finish.
 *
 * No joints and no module, so the tile's 2000 mm extent is a statement about how large the
 * finish's features are rather than about any unit: the dash is laid on a 6.7 mm cell and the
 * trowel relief on a 50 mm one. Paint has flaked from a few of the raised dashes, which is where a
 * wall is rubbed and weathered first. Anything broader than a few hundred millimetres is kept
 * faint, because a strong broad stain in a tiling texture is a stain the whole street repeats.
 */
const EXTENT = 2000;
const RANGE_MM = 4;
const BASE_MM_1024THS = 1536;
const RELIEF_MM_1024THS = 760;
const DASH_MM_1024THS = 1180;

const PAINT: Srgb = [210, 198, 172];
const RENDER: Srgb = [156, 152, 144];
const GRIME: Srgb = [120, 112, 98];

function recipe(seed: number): Recipe {
  const paint = decode(PAINT);
  const render = decode(RENDER);
  const grime = decode(GRIME);
  const reliefSeed = stream(seed, 1);
  const dashSeed = stream(seed, 2);
  const sandSeed = stream(seed, 3);
  const wearSeed = stream(seed, 4);
  const hueSeed = stream(seed, 5);
  const dirtSeed = stream(seed, 6);
  const dash: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    const relief = fbm(x, y, 40, 40, reliefSeed, 4);
    cells(x, y, 300, 300, dashSeed, ONE, dash);
    const size = 30000 + pick(dash.id, 0, 12000);
    const blob = dash.nearest < size ? smoothstep(0, size, size - dash.nearest) : 0;
    const sand = valueNoise(x, y, 1000, 1000, sandSeed);
    const length = BASE_MM_1024THS
      + floorDiv((relief - 32768) * RELIEF_MM_1024THS, 32768)
      + floorDiv(blob * DASH_MM_1024THS, ONE)
      + floorDiv((sand - 32768) * 90, 32768);
    out.height = heightOfLength(length, RANGE_MM);

    setColour(out, paint);
    shade(out, jitter(fbm(x, y, 9, 9, hueSeed, 2), 1300));
    shade(out, jitter(sand, 900));
    // Dashes catch a little more light-coloured paint on their crowns.
    shade(out, ONE + floorDiv(blob * 3, 100));

    // Flaking: small, and only on raised dashes where the flaking field also runs high.
    const raised = clamp(length - BASE_MM_1024THS, 0, MM);
    const wearField = fbm(x, y, 24, 24, wearSeed, 3) + floorDiv(raised * 9000, MM);
    const worn = band(wearField, 56000, 59000);
    mixColour(out, render, floorDiv(worn * 80, 100));

    const dirt = band(fbm(x, y, 12, 12, dirtSeed, 3), 26000, 46000);
    mixColour(out, grime, floorDiv(dirt * 9, 100));

    out.roughness = clamp(
      lerp(permille(720), permille(900), worn) + floorDiv(dirt * 6, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const render = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.painted-render',
  version,
  seed,
  family: 'render',
  title: 'Painted render',
  summary: 'Warm off-white paint over a dashed render finish, flaking on a few raised dashes.',
  width: 1024,
  height: 1024,
  extentU: EXTENT,
  extentV: EXTENT,
  surface: 'vertical',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 6, depthMm: 1, strengthPermille: 300 },
  parameters: {
    finish: 'dashed render, painted',
    dash_cell_mm_1024ths: floorDiv(EXTENT * MM, 300),
    relief_cell_mm: EXTENT / 40,
    base_height_mm_1024ths: BASE_MM_1024THS,
    relief_amplitude_mm_1024ths: RELIEF_MM_1024THS,
    dash_height_max_mm_1024ths: DASH_MM_1024THS,
  },
  recipe: () => recipe(seed),
});
