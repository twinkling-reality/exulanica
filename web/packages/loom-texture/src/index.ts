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
export { CATALOG, LIBRARY, type SetIdentity, definitionOf, recipeDefinition } from './catalog.js';
export {
  ALPHA_CUTOFF,
  type Channel,
  GLAZING_IOR_MILLIONTHS,
  MAKER_KINDS,
  type MakerKind,
  type MapDescriptor,
  MATERIAL_CLASSES,
  type MaterialClass,
  type ModelMaps,
  SET_PROFILE_V1,
  SET_PROFILE_V2,
  type SetProfile,
  V1_LAYOUT,
  allowedChannels,
  channelsOf,
  classLayout,
  classParameters,
  coveragePermille,
} from './classes.js';
export {
  CONTAINER_MAGIC,
  ContainerRefusal,
  type ContainerRefusalReason,
  type DecodedContainer,
  type FramedMap,
  MAP_LAYOUT,
  type MapEntry,
  type MapName,
  MEDIA_TYPE,
  type ReadContainer,
  SET_PROFILE,
  TRUTH,
  decodeContainer,
  encodeContainer,
  encodeContainerV2,
  frameContainer,
  readContainer,
} from './container.js';
export {
  MANIFEST_PROFILE_V1,
  MANIFEST_PROFILE_V2,
  type ManifestEntryRead,
  TextureSetRefusal,
  type TextureSetRefusalReason,
  checkTextureSet,
  readTextureManifest,
} from './manifest-reader.js';
export {
  DATASET_FILE,
  type DatasetExport,
  type DatasetRecord,
  IMAGE_DIRECTORY,
  RECORDS_FILE,
  exportDataset,
  recordSeed,
} from './dataset/export.js';
export {
  DATASET_PROFILE,
  type DatasetPlan,
  PLAN_PROFILE,
  RENDERER,
  SAMPLER,
  checkPlan,
  planProblems,
} from './dataset/plan.js';
export { type Light, type View, renderView, sampleLight, sampleView } from './dataset/render.js';
export { frameResolution, pickWide, sampleRecipe } from './dataset/sample.js';
export type { CavitySpec, TextureSetDefinition } from './definition.js';
export { sha256Hex } from './digest.js';
export {
  type LibraryEntry,
  type LibrarySet,
  SET_ID_PATTERN,
  WORKSPACE_SET_ID_PREFIX,
  formatLibrarySource,
  libraryEntryProblems,
  readLibrary,
} from './library.js';
export { LICENCE_ID, LICENCE_TEXT, licenceBytes } from './licence.js';
export type { Maker } from './maker.js';
export { MAKERS, makerFor } from './makers/index.js';
export { type Fields, type Maps, bakeClassMaps, bakeMaps, classMaps, sampleFields } from './maps.js';
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
export { repairRecipe } from './repair.js';
export {
  MAXIMUM_DEPTH,
  STRICT_JSON_PROBLEMS,
  StrictJsonError,
  parseStrictJson,
  parseStrictJsonBytes,
} from './strict-json.js';
export { RequestRefused, bakeWorkspaceRequest } from './workspace/bake.js';
export {
  WORKSPACE_LICENCE_FILE,
  WORKSPACE_LICENCE_ID,
  type WorkspaceLicence,
  workspaceLicence,
} from './workspace/licence.js';
export {
  BAKE_REQUEST_PROFILE,
  BAKE_RESULT_PROFILE,
  type BakeRequest,
  type BakeResult,
  MAXIMUM_WORKSPACE_TEXELS,
  WORKSPACE_SET_ID,
  WORKSPACE_VERSION,
  bakeRequestProblems,
} from './workspace/request.js';
export {
  SOURCE_PROFILE,
  SOURCE_ROOTS,
  type SourceFile,
  packageSourceDigest,
  sourceFiles,
} from './workspace/source.js';
