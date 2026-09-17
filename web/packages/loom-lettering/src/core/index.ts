/**
 * Shop-sign lettering as data: the glyph catalog reader and the layout rule, in TypeScript.
 *
 * The catalogs under `assets/catalogs/lettering/` are made once from open-licence fonts by
 * `tools/lettering`; nothing here parses a font. `exulanica.lettering` is the Python copy of these
 * two rules, and `test/lettering-cases.json` holds the two to the same answers. tess reads this
 * package's core to turn a sign into triangles.
 */
export {
  CHARACTER_SET,
  GLYPH_CATALOG_PROFILE,
  type Glyph,
  type GlyphCatalog,
  readGlyphCatalog,
} from './catalog.js';
export {
  ALIGNMENTS,
  type Alignment,
  type InkBox,
  type Placement,
  type SignLayout,
  type SignRequest,
  glyphPartsMm,
  layoutSign,
  scaleToMm,
} from './layout.js';
export {
  CATALOG_REASONS,
  type CatalogReason,
  LAYOUT_REASONS,
  type LayoutReason,
  LetteringRefusal,
} from './refusal.js';
export {
  type Part,
  type Point,
  type Ring,
  type RingSide,
  glyphsTouch,
  partsProblem,
  pointInRing,
  ringProblem,
  ringsMeet,
} from './geometry.js';
export { type CanonicalValue, canonicalBytes, canonicalJson, parseCanonical } from './canonical-json.js';
