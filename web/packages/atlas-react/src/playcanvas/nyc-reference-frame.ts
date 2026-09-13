/**
 * Independently chosen public render frame for the owned Flatiron district.
 *
 * Both visualization providers and semantic sources transform into this frame from their own
 * coordinates. Sharing these numbers prevents co-rendered layers from drifting; it does not
 * derive identity, geometry, bounds, or alignment from either provider's content.
 */
export const NYC_REFERENCE_FRAME = Object.freeze({
  longitude: -73.99,
  latitude: 40.742,
  // The first owned slice explicitly authors a flat ground datum. It is not surveyed elevation.
  altitude: 0,
});
