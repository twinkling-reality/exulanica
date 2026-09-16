/**
 * loom-texture: the offline texture package.
 *
 * Seeded, tiling, channel-packed texture sets, baked from integer arithmetic into a
 * self-describing container, published content-addressed under `assets/textures/`, and pinned by
 * digest in migration 0065. A set is a recipe (data, in `library/`) applied by a maker (code, with
 * a published manifest of its controls), and every recipe, manifest, library entry and bake
 * receipt is published as an object of its own. A build-time tool: nothing that ships to a
 * browser may import it. docs/texture-package.md is the full account.
 */
export {
  ACCEPTED_DECODED_ENVELOPE_BYTES,
  CORRIDOR_SET_COUNT,
  corridorDecodedBytes,
  decodedBytes,
  mipChainTexels,
} from './budget.js';
export { canonicalBytes, canonicalJson } from './canonical-json.js';
export { CATALOG, LIBRARY, definitionOf } from './catalog.js';
export {
  CONTAINER_MAGIC,
  type DecodedContainer,
  MAP_LAYOUT,
  type MapEntry,
  type MapName,
  MEDIA_TYPE,
  SET_PROFILE,
  TRUTH,
  decodeContainer,
  encodeContainer,
} from './container.js';
export type { CavitySpec, TextureSetDefinition } from './definition.js';
export { sha256Hex } from './digest.js';
export {
  type LibraryEntry,
  type LibrarySet,
  SET_ID_PATTERN,
  formatLibrarySource,
  libraryEntryProblems,
  readLibrary,
} from './library.js';
export { LICENCE_ID, LICENCE_TEXT, licenceBytes } from './licence.js';
export type { Maker } from './maker.js';
export { MAKERS, makerFor } from './makers/index.js';
export { type Fields, type Maps, bakeMaps, sampleFields } from './maps.js';
export {
  BAKE_PIPELINE,
  BAKE_RECEIPT_PROFILE,
  type BakeReceipt,
  CATALOG_FILE,
  CATALOG_PROFILE,
  type CatalogDocument,
  LIBRARY_ENTRY_PROFILE,
  type LibraryEntryObject,
  OBJECT_DIRECTORY,
} from './objects.js';
export {
  ATTRIBUTES_FILE,
  BLOB_DIRECTORY,
  MANIFEST_FILE,
  MANIFEST_PROFILE,
  type ManifestEntry,
  type Publication,
  type PublishedLibrarySet,
  type PublishedSet,
  manifestBytes,
  objectPath,
  publish,
} from './publish.js';
export {
  COMMON_CONTROLS,
  type Constraint,
  type Control,
  type Expression,
  MAKER_PROFILE,
  type MakerManifest,
  RECIPE_PROFILE,
  type Recipe,
  checkRecipe,
  defaultRecipe,
  evaluate,
  manifestProblems,
  recipeProblems,
} from './recipe.js';
export {
  MAXIMUM_DEPTH,
  STRICT_JSON_PROBLEMS,
  StrictJsonError,
  parseStrictJson,
  parseStrictJsonBytes,
} from './strict-json.js';
