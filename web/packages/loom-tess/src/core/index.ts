/**
 * `@exulanica/loom-tess/core`: the tessellator, the container and its pure decoder.
 *
 * No DOM and no Node, by compilation: see `tsconfig.core.json`. A runtime that draws baked tiles
 * imports `decodeOwd` (layout, synchronous) and `verifyOwd` (content, with its host's SHA-256)
 * from here, and never writes a second reader.
 */
export { BAKE_PARAMETERS, bakeTile, documentOf, verifyOwd } from './bake.js';
export type { Bake, Sha256Hex } from './bake.js';
export { CanonicalJsonError, canonicalBytes, canonicalJson } from './canonical-json.js';
export { MEMBERSHIPS, readTileDocument, TILE_DOCUMENT_PROFILE, TileDocumentError } from './document.js';
export type { DeclaredSemantics, GrammarEntry, Membership, RecordPayload, TileDocument } from './document.js';
export {
  CAPSULE_RADIUS_MM,
  MATERIALISED_LOD,
  MATERIALISED_PROJECTIONS,
  NEEDS,
  PROJECTION_DEFINITIONS,
  TESSELLATOR_SOURCE_VERSION,
  TessellationError,
} from './expand.js';
export type { Need, ProjectionDefinition } from './expand.js';
export {
  absoluteSurfaceCoordinates,
  absoluteVertices,
  COORDINATES,
  decodeOwd,
  encodeOwd,
  OWD_CONTAINER,
  OWD_MAGIC,
  OWD_MEDIA_TYPE,
  OWD_PROFILE,
  OwdError,
  sectionLayout,
} from './owd.js';
export type {
  DecodedOwd,
  DecodedProjection,
  OwdGrammar,
  OwdHeader,
  OwdProjection,
  OwdRecord,
  OwdSection,
  SectionName,
} from './owd.js';
export {
  GRAMMAR_TABLES,
  MATERIAL_RECORD_KIND,
  PROJECTIONS,
  ShapeTableError,
  TILE_RECORD_KIND,
  TILE_SHAPE,
} from './record-shapes.js';
export type {
  FieldShape,
  GrammarFrame,
  GrammarTable,
  IdentityRule,
  ProjectionName,
  RecordShape,
} from './record-shapes.js';
export type { DrawnEntry, Entry, MaterialRef, Triple } from './tessellate.js';
export {
  ENTRY_STATES,
  IDENTITY_NOT_STATED,
  MATERIAL_NONE_EXISTS,
  SURFACE_ORIENTATIONS,
  TRIANGLE_DIGEST_DOMAIN,
  TRIANGLE_DIGEST_PROFILE,
  TRIANGLE_DIGEST_VERSION,
  trianglePreimage,
} from './triangle-digest.js';
export type { SurfaceOrientation } from './triangle-digest.js';
