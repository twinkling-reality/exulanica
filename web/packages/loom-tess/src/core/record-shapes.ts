/**
 * THE RECORD SHAPES THIS TESSELLATOR READS, TRANSCRIBED FROM THE GRAMMAR AND HELD TO IT.
 *
 * Every field name, bound and closed value below is the grammar's own, from
 * `exulanica/grammar/grammars/city/*.py`, `exulanica/grammar/records.py` and
 * `exulanica/grammar/contract.py`. Nothing here is chosen by this package. The table is data, not
 * a generator: it says what a well formed record is, never what a record should contain.
 *
 * It is the only file in `src/core` allowed to carry grammar numbers and closed values, and that
 * exemption is earned rather than asserted: `tests/test_bake_determinism.py` prints this table
 * through the CLI (`exulanica-tess shapes`) and compares it with the grammar's dataclasses and
 * module constants, field by field. A bound edited on one side and not the other fails there.
 * `test/vocabulary-emptiness.test.ts` exempts this file from its literal rules for that reason
 * and for no other.
 *
 * Adding a record kind is a new entry here, a new expander in `expand.ts`, and a bump of
 * `TESSELLATOR_SOURCE_VERSION`, which the bake stage's parameters carry.
 */

/** Integers a JavaScript reader holds exactly. `exulanica.grammar.records.MAX_SAFE_INTEGER`. */
export const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;

/** `exulanica.grammar.records.KEY_PATTERN`. */
export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;
/** `exulanica.grammar.records._IDENTITY`: a canonical lowercase UUID string. */
export const IDENTITY_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** `exulanica.grammar.records._HEX64` and `exulanica.grammar.seed._SEED`. */
export const HEX64_PATTERN = /^[0-9a-f]{64}$/;
/** `exulanica.grammar.textures.TEXTURE_SET_ID`. */
export const TEXTURE_SET_ID_PATTERN = /^[a-z][a-z0-9.-]*$/;

/** `exulanica.grammar.contract.PLANE`. The one plane a grammar may declare. */
export const PLANE = 'invented';

/**
 * `exulanica.grammar.contract.ADMISSIBLE_USES`, in the grammar's order. These are the named
 * projections of the target architecture; a grammar's declared semantics list the ones its output
 * is admitted to, and this tessellator emits a projection for a record only when they do.
 */
export const PROJECTIONS = [
  'render_batch',
  'collision_proxy',
  'nav_envelope',
  'pick_geometry',
  'export_gltf',
] as const;
export type ProjectionName = (typeof PROJECTIONS)[number];

export type FieldShape =
  | { readonly type: 'int'; readonly min?: number; readonly max?: number }
  | { readonly type: 'key' }
  | { readonly type: 'identity' }
  | { readonly type: 'hex64' }
  | { readonly type: 'seed' }
  | { readonly type: 'texture_set_id' }
  | { readonly type: 'enum'; readonly values: readonly string[] }
  | { readonly type: 'ints'; readonly min?: number }
  | { readonly type: 'increasing_ints'; readonly min: number }
  | { readonly type: 'int_pairs'; readonly min_count: number }
  | { readonly type: 'ring'; readonly min_count: number }
  | { readonly type: 'setbacks' }
  | { readonly type: 'parameters' }
  | { readonly type: 'grammar_versions' }
  | { readonly type: 'semantics' };

/**
 * A rule that spans fields, named so a refusal says which one. Each is one sentence of the
 * grammar validator it mirrors, and the parity test lists them by name.
 */
export type CrossRule =
  | 'grid_sample_count'
  | 'distinct_segment_nodes'
  | 'curb_edge_not_self'
  | 'ring_not_closed'
  | 'setback_storeys_below_top';

export interface RecordShape {
  readonly kind: string;
  readonly version: number;
  readonly fields: Readonly<Record<string, FieldShape>>;
  readonly rules: readonly CrossRule[];
  /** The field that states the record's subject identity, when the record states one. */
  readonly identity_field?: string;
}

const int = (min?: number, max?: number): FieldShape => {
  if (min === undefined) return max === undefined ? { type: 'int' } : { type: 'int', max };
  return max === undefined ? { type: 'int', min } : { type: 'int', min, max };
};

/** The record kind a drawn range's material reference must name. */
export const MATERIAL_RECORD_KIND = 'city.surface_material';

/** `exulanica.grammar.grammars.city.streets.CURB_SIDES`. */
const CURB_SIDES = ['left', 'right'] as const;
/** `exulanica.grammar.grammars.city.parcels.LOT_CLASSES`. */
const LOT_CLASSES = ['building', 'memory_precinct'] as const;

/** `exulanica.grammar.grammars.city.tile`: the tile record, which heads a tile document. */
export const TILE_SHAPE: RecordShape = {
  kind: 'city.tile',
  version: 1,
  fields: {
    city_seed: { type: 'seed' },
    grammar_versions: { type: 'grammar_versions' },
    catalog_digest: { type: 'hex64' },
    tile_x: int(),
    tile_y: int(),
    lod: int(0),
    // TILE_SIZE_MM and HALO_RADIUS_MM: version 1 of the tile stage declares both exactly.
    tile_size_mm: int(128_000, 128_000),
    halo_radius_mm: int(64_000, 64_000),
    edit_delta_digest: { type: 'hex64' },
  },
  rules: [],
};

/** Every record kind a tile document may carry, sorted by kind. */
export const RECORD_SHAPES: readonly RecordShape[] = [
  {
    kind: 'city.curb_edge',
    version: 1,
    fields: {
      curb_ordinal: int(0),
      segment_ordinal: int(0),
      side: { type: 'enum', values: CURB_SIDES },
      next_curb_ordinal: int(0),
    },
    rules: ['curb_edge_not_self'],
  },
  {
    kind: 'city.facade',
    version: 1,
    fields: {
      building_identity: { type: 'identity' },
      grammar_version: int(1),
      parameters: { type: 'parameters' },
      seed: { type: 'seed' },
      output_digest: { type: 'hex64' },
      declared_semantics: { type: 'semantics' },
      edge_ordinal: int(0),
    },
    rules: [],
    identity_field: 'building_identity',
  },
  {
    kind: 'city.massing',
    version: 1,
    fields: {
      building_identity: { type: 'identity' },
      parcel_ordinal: int(0),
      typology: { type: 'key' },
      era: { type: 'key' },
      storeys: int(1),
      ground_storey_height_mm: int(1),
      upper_storey_height_mm: int(1),
      setbacks: { type: 'setbacks' },
      party_wall_edges: { type: 'increasing_ints', min: 0 },
      light_well_count: int(0),
      roof_family: { type: 'key' },
      parapet_height_mm: int(0),
      rooftop_plant_count: int(0),
      rooftop_tank_count: int(0),
    },
    rules: ['setback_storeys_below_top'],
    identity_field: 'building_identity',
  },
  {
    kind: 'city.parcel',
    version: 1,
    fields: {
      parcel_ordinal: int(0),
      block_ordinal: int(0),
      lot_class: { type: 'enum', values: LOT_CLASSES },
      boundary_mm: { type: 'ring', min_count: 3 },
      frontage_segment_ordinal: int(0),
      frontage_mm: int(1),
      address_number: int(1),
      threshold_offset_mm: int(0),
    },
    rules: ['ring_not_closed'],
  },
  {
    kind: 'city.premises',
    version: 1,
    fields: {
      building_identity: { type: 'identity' },
      unit_ordinal: int(0),
      use_class: { type: 'key' },
      sign: { type: 'key' },
    },
    rules: [],
    identity_field: 'building_identity',
  },
  {
    kind: 'city.street_furniture',
    version: 1,
    fields: {
      item_ordinal: int(0),
      item_class: { type: 'key' },
      segment_ordinal: int(0),
      side: { type: 'enum', values: CURB_SIDES },
      along_mm: int(0),
      kerb_offset_mm: int(0),
      x_mm: int(),
      y_mm: int(),
    },
    rules: [],
  },
  {
    kind: 'city.street_node',
    version: 1,
    fields: {
      node_ordinal: int(0),
      x_mm: int(),
      y_mm: int(),
    },
    rules: [],
  },
  {
    kind: 'city.street_segment',
    version: 1,
    fields: {
      segment_ordinal: int(0),
      start_node: int(0),
      end_node: int(0),
      centreline_mm: { type: 'int_pairs', min_count: 2 },
      hierarchy: { type: 'key' },
      carriageway_width_mm: int(1),
      // KERB_HEIGHT_MINIMUM_MM and KERB_HEIGHT_MAXIMUM_MM.
      kerb_height_mm: int(100, 180),
      gutter_width_mm: int(0),
      footway_width_mm: int(1),
      corner_radius_mm: int(0),
      crossing_offsets_mm: { type: 'increasing_ints', min: 0 },
    },
    rules: ['distinct_segment_nodes'],
  },
  {
    kind: 'city.surface_material',
    version: 1,
    fields: {
      building_identity: { type: 'identity' },
      edge_ordinal: int(0),
      material: { type: 'key' },
      texture_set_id: { type: 'texture_set_id' },
      uv_scale_millionths: int(1),
      // MAXIMUM_ROTATION_URAD.
      uv_rotation_urad: int(0, 6_283_185),
      course_module_mm: int(0),
      mortar_module_mm: int(0),
      // MILLIONTHS.
      soiling_gradient_millionths: int(0, 1_000_000),
      base_weathering_millionths: int(0, 1_000_000),
      reveal_darkening_millionths: int(0, 1_000_000),
    },
    rules: [],
    identity_field: 'building_identity',
  },
  {
    kind: 'city.terrain',
    version: 1,
    fields: {
      origin_x_mm: int(),
      origin_y_mm: int(),
      cell_mm: int(1),
      columns: int(1),
      rows: int(1),
      height_mm: { type: 'ints' },
      slope_millionths: { type: 'ints', min: 0 },
    },
    rules: ['grid_sample_count'],
  },
  {
    kind: 'city.vitrine',
    version: 1,
    fields: {
      building_identity: { type: 'identity' },
      edge_ordinal: int(0),
      bay_ordinal: int(0),
      // VITRINE_DEPTH_MINIMUM_MM and VITRINE_DEPTH_MAXIMUM_MM.
      depth_mm: int(600, 1500),
      fitout: { type: 'key' },
    },
    rules: [],
    identity_field: 'building_identity',
  },
];

/** `DeclaredSemantics` has no record kind; its fields are read as a plain object. */
export const SEMANTICS_FIELDS = ['admissible_uses', 'plane', 'subject_kind'] as const;
