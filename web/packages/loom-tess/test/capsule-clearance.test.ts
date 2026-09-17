/**
 * The capsule radius the nav_envelope carve keeps clear is the city grammar's own: the integer
 * measures its descriptor's nav_envelope contract states for capsule_clearance, carried into the
 * generated grammar table. Nothing in core restates the number.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CITY_V2 } from '../src/core/city-v2.js';
import { CITY_DESCRIPTOR_PATH } from './grammar-table-sources.js';

describe('the capsule clearance the nav_envelope carve keeps', () => {
  it('is the measure the city descriptor states for nav_envelope', () => {
    const descriptor = JSON.parse(readFileSync(CITY_DESCRIPTOR_PATH, 'utf8')) as {
      projections: { projection: string; preserved: { property: string; measures?: Record<string, number> }[] }[];
    };
    const nav = descriptor.projections.find((projection) => projection.projection === 'nav_envelope')!;
    const clearance = nav.preserved.find((row) => row.property === 'capsule_clearance')!;
    expect(clearance.measures).toBeDefined();
    expect(CITY_V2.measures.nav_envelope?.capsule_clearance).toEqual(clearance.measures);
    expect(CITY_V2.measures.nav_envelope?.capsule_clearance?.radius_mm).toBeGreaterThan(0);
  });
});
