import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { VEHICLE_LOOKS } from '../src/playcanvas/traffic/traffic-layer.js';

describe('the vehicle looks', () => {
  it('state a look for every body family and colour the traffic catalog names, and no other', () => {
    const catalog = JSON.parse(
      readFileSync(new URL('../../../../assets/catalogs/traffic/vehicle-class.v1.json', import.meta.url), 'utf8'),
    ) as { entries: { body_families: string[]; colours: string[] }[] };
    const families = new Set(catalog.entries.flatMap((entry) => entry.body_families));
    const colours = new Set(catalog.entries.flatMap((entry) => entry.colours));
    expect(new Set(Object.keys(VEHICLE_LOOKS.body_families))).toEqual(families);
    expect(new Set(Object.keys(VEHICLE_LOOKS.colours))).toEqual(colours);
  });

  it('give every box a role the looks colour, inside the body it is proportioned to', () => {
    for (const [family, { boxes }] of Object.entries(VEHICLE_LOOKS.body_families)) {
      expect(boxes.length, family).toBeGreaterThan(0);
      for (const box of boxes) {
        expect(VEHICLE_LOOKS.roles[box.role], `${family} ${box.role}`).toBeDefined();
        const [a0, a1] = box.along_permille;
        const [u0, u1] = box.up_permille;
        expect(0 <= a0 && a0 < a1 && a1 <= 1000 && 0 <= u0 && u0 < u1 && u1 <= 1000, family).toBe(true);
      }
    }
  });
});
