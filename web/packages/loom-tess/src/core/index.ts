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
export { readTileDocument, TILE_DOCUMENT_PROFILE, TileDocumentError } from './document.js';
export type { DeclaredSemantics, GrammarEntry, RecordPayload, TileDocument } from './document.js';
export { MATERIALISED_LOD, MATERIALISED_PROJECTIONS, NEEDS, TESSELLATOR_SOURCE_VERSION, TessellationError } from './expand.js';
export type { Need } from './expand.js';
export {
  absoluteVertices,
  COORDINATES,
  decodeOwd,
  encodeOwd,
  OWD_CONTAINER,
  OWD_MAGIC,
  OWD_MEDIA_TYPE,
  OWD_PROFILE,
  OwdError,
  SECTION_LAYOUT,
} from './owd.js';
export type { DecodedOwd, DecodedProjection, OwdGrammar, OwdHeader, OwdProjection, OwdRecord, OwdSection } from './owd.js';
export { PROJECTIONS, RECORD_SHAPES, TILE_SHAPE } from './record-shapes.js';
export type { FieldShape, ProjectionName, RecordShape } from './record-shapes.js';
export type { Entry, MaterialRef, Triple } from './tessellate.js';
export {
  IDENTITY_NOT_STATED,
  MATERIAL_NOT_CARRIED,
  TRIANGLE_DIGEST_DOMAIN,
  TRIANGLE_DIGEST_PROFILE,
  TRIANGLE_DIGEST_VERSION,
  trianglePreimage,
} from './triangle-digest.js';
