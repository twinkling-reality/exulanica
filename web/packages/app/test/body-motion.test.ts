import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { BODY_MOTION } from '../src/body-motion.js';

/*
 * The page reads how a drafted body moves from the catalog, never from figures of its own: each
 * value here is read from the file again, by its key.
 */
const CATALOG = JSON.parse(readFileSync(
  new URL('../../../../assets/catalogs/thing-presentation/body-motion.v1.json', import.meta.url), 'utf8',
)) as { entries: { key: string; value: number }[] };
const stated = (key: string) => CATALOG.entries.find((entry) => entry.key === key)!.value;

describe('the body motion table the page hands its figures', () => {
  it('is the catalog\'s, figure for figure', () => {
    expect(BODY_MOTION).toEqual({
      fullWalkCadence: stated('full_walk_strides_per_second'),
      lookAbout: stated('look_about_rad'),
      lookAboutPeriod: stated('look_about_period_seconds'),
      nod: stated('nod_rad'),
      speechBeats: stated('speech_beats_per_second'),
      jawOpen: stated('jaw_open_rad'),
      wave: stated('wave_rad'),
      wavePeriod: stated('wave_period_seconds'),
      waveLag: stated('wave_lag_cycles'),
      wingFold: stated('wing_fold_share'),
      wingSettle: stated('wing_settle_rad'),
      finSway: stated('fin_sway_rad'),
      spineWave: stated('spine_wave_rad'),
      spineWavelength: stated('spine_wavelength_share'),
      turnEndSpeed: stated('turn_end_speed_mm_per_second') / 1000,
    });
    expect(Object.keys(BODY_MOTION)).toHaveLength(CATALOG.entries.length);
  });
});
