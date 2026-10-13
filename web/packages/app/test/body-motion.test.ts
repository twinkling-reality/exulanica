import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { BODY_MOTION } from '../src/body-motion.js';

/*
 * The page reads how a drafted body moves from the catalog, never from figures of its own: each
 * value here is read from the file again, by its key.
 */
const CATALOG = JSON.parse(readFileSync(
  new URL('../../../../assets/catalogs/thing-presentation/body-motion.v2.json', import.meta.url), 'utf8',
)) as {
  entries: { key: string; value: number }[];
  posture_blend: { value: number };
  postures: { key: string; lower_share: number; head_bow_rad: number; speaks: boolean }[];
  activity_postures: { activity: string; posture: string }[];
};
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
      wingDroop: stated('wing_droop_rad'),
      wingSettle: stated('wing_settle_rad'),
      finSway: stated('fin_sway_rad'),
      spineWave: stated('spine_wave_rad'),
      spineWavelength: stated('spine_wavelength_share'),
      turnEndSpeed: stated('turn_end_speed_mm_per_second') / 1000,
      postures: {
        blendSeconds: CATALOG.posture_blend.value,
        postures: new Map(CATALOG.postures.map((one) => [one.key, { lowerShare: one.lower_share, headBow: one.head_bow_rad, speaks: one.speaks }])),
        activities: new Map(CATALOG.activity_postures.map((one) => [one.activity, one.posture])),
      },
    });
    // Every figure of the file, and the postures beside them.
    expect(Object.keys(BODY_MOTION)).toHaveLength(CATALOG.entries.length + 1);
  });

  it('draws a resting body settled and a talking one speaking, as the catalog says, and anything else standing', () => {
    const table = BODY_MOTION.postures!;
    expect(table.postures.get(table.activities.get('rest')!)!.lowerShare).toBeGreaterThan(0);
    expect(table.postures.get(table.activities.get('talk')!)!.speaks).toBe(true);
    expect(table.activities.has('idle')).toBe(false);
  });
});
