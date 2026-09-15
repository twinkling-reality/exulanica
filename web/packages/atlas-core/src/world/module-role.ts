/**
 * What a world module is for.
 *
 * Its own module because both the catalog and the form vocabulary need it, and a shared name that
 * lives inside one of two things that reference each other is how a cycle starts.
 */
export type WorldModuleRole =
  | 'navigation-field'
  | 'region-foundation'
  | 'relationship-path'
  | 'landmark'
  | 'evidence-assembly'
  | 'reconstruction-assembly'
  | 'expansion-point'
  | 'atmosphere-anchor';
