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

  it('give every part a role the looks colour, inside the body it is proportioned to', () => {
    for (const [family, { boxes, rider }] of Object.entries(VEHICLE_LOOKS.body_families)) {
      expect(boxes.length, family).toBeGreaterThan(0);
      for (const box of [...boxes, ...(rider?.boxes ?? [])]) {
        expect(VEHICLE_LOOKS.roles[box.role], `${family} ${box.role}`).toBeDefined();
        const [a0, a1] = box.along_permille;
        const [u0, u1] = box.up_permille;
        const inside = [a0, a1, u0, u1].every((v) => 0 <= v && v <= 1000);
        // A rod runs between its two points, either way; a box or a disc states its extent, the lower first.
        const ordered = box.shape === 'rod' ? a0 !== a1 || u0 !== u1 : a0 < a1 && u0 < u1;
        const offset = Math.abs(box.across_offset_permille ?? 0) + box.across_permille / 2;
        expect(inside && ordered && offset <= 1000, `${family} ${box.role}`).toBe(true);
      }
    }
  });

  it('draw a bicycle as two wheels, a frame of rods, a saddle and a handlebar, nothing above a metre', () => {
    const catalog = JSON.parse(
      readFileSync(new URL('../../../../assets/catalogs/traffic/vehicle-class.v1.json', import.meta.url), 'utf8'),
    ) as { entries: { key: string; length_mm: number; height_mm: number }[] };
    const bicycle = catalog.entries.find((entry) => entry.key === 'bicycle')!;
    const { boxes } = VEHICLE_LOOKS.body_families['upright_bicycle']!;
    const wheels = boxes.filter((box) => box.role === 'wheel');
    expect(wheels.map((box) => box.shape)).toEqual(['disc', 'disc']);
    for (const wheel of wheels) {
      // Round: as long along as it is high, about 660 mm across.
      const along = ((wheel.along_permille[1] - wheel.along_permille[0]) / 1000) * bicycle.length_mm;
      const up = ((wheel.up_permille[1] - wheel.up_permille[0]) / 1000) * bicycle.height_mm;
      expect(Math.abs(along - up)).toBeLessThan(5);
      expect(Math.abs(along - 660)).toBeLessThan(10);
    }
    expect(boxes.filter((box) => box.role === 'frame' && box.shape === 'rod').length).toBeGreaterThanOrEqual(5);
    expect(boxes.some((box) => box.role === 'seat') && boxes.some((box) => box.role === 'handlebar')).toBe(true);
    // The record's height is a rider's eye envelope; no rider is drawn, so nothing stands above a metre.
    const top = Math.max(...boxes.map((box) => Math.max(...box.up_permille))) / 1000 * bicycle.height_mm;
    expect(top).toBeLessThanOrEqual(1000);
  });

  it('keep every other family in boxes, as version 1 drew it, with no rider', () => {
    for (const [family, { boxes, rider }] of Object.entries(VEHICLE_LOOKS.body_families)) {
      if (family === 'upright_bicycle') continue;
      expect(boxes.every((box) => box.shape === undefined && box.across_offset_permille === undefined), family).toBe(true);
      expect(rider, family).toBeUndefined();
    }
  });

  it('seat a riding bicycle\'s rider with the head at the class\'s envelope, in no frame colour', () => {
    const catalog = JSON.parse(
      readFileSync(new URL('../../../../assets/catalogs/traffic/vehicle-class.v1.json', import.meta.url), 'utf8'),
    ) as { entries: { key: string; height_mm: number }[] };
    const height = catalog.entries.find((entry) => entry.key === 'bicycle')!.height_mm;
    const rider = VEHICLE_LOOKS.body_families['upright_bicycle']!.rider!;
    const head = rider.boxes.filter((box) => box.role === 'rider_head');
    expect(head).toHaveLength(1);
    expect((head[0]!.up_permille[1] / 1000) * height).toBe(1500);
    // Two arms and two legs, one either side of the frame.
    const sides = rider.boxes.filter((box) => box.shape === 'rod' && box.across_offset_permille !== undefined).map((box) => Math.sign(box.across_offset_permille!));
    expect(sides.filter((side) => side > 0).length).toBe(3);
    expect(sides.filter((side) => side < 0).length).toBe(3);
    const clothing = VEHICLE_LOOKS.roles['rider']!.colour;
    expect(Object.values(VEHICLE_LOOKS.colours)).not.toContain(clothing);
  });
});
