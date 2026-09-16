/**
 * loom-texture: the offline texture package.
 *
 * Seeded, tiling, channel-packed texture sets, baked from integer arithmetic into a
 * self-describing container, published content-addressed under `assets/textures/`, and pinned by
 * digest in migration 0065. A build-time tool: nothing that ships to a browser may import it.
 * docs/texture-package.md is the full account.
 */
export {
  ACCEPTED_DECODED_ENVELOPE_BYTES,
  CORRIDOR_SET_COUNT,
  corridorDecodedBytes,
  decodedBytes,
  mipChainTexels,
} from './budget.js';
export { canonicalBytes, canonicalJson } from './canonical-json.js';
export { CATALOG } from './catalog.js';
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
export { LICENCE_ID, LICENCE_TEXT, licenceBytes } from './licence.js';
export { type Fields, type Maps, bakeMaps, sampleFields } from './maps.js';
export {
  ATTRIBUTES_FILE,
  BLOB_DIRECTORY,
  MANIFEST_FILE,
  MANIFEST_PROFILE,
  type ManifestEntry,
  type Publication,
  type PublishedSet,
  SET_ID_PATTERN,
  manifestBytes,
  publish,
  sha256Hex,
} from './publish.js';
