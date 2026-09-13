/**
 * Independently chosen public render frame for the East Village/Lower East Side slice.
 *
 * Both visualization providers and semantic sources transform into this frame from their own
 * coordinates. Sharing these numbers prevents co-rendered layers from drifting; it does not
 * derive identity, geometry, bounds, or alignment from either provider's content.
 */
export const NYC_REFERENCE_FRAME = Object.freeze({
  longitude: -73.9885,
  latitude: 40.722,
  altitude: 0,
});
