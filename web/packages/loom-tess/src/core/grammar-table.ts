/**
 * THE SHAPE OF A GRAMMAR TABLE: what `exulanica.grammar.shapes.describe_shapes` writes, typed.
 *
 * Its own module, importing nothing, so a generated table (`city-v2.ts`) can name its type without
 * reaching the module that reads it.
 */
/** `exulanica.grammar.shapes.FIELD_KINDS`. */
export const FIELD_KINDS = [
  'integer', 'key', 'choice', 'text', 'identity', 'hex64', 'seed', 'texture_set_id', 'scalar',
  'integers', 'keys', 'choices', 'identities', 'texts', 'points', 'ring', 'rings', 'record', 'records',
] as const;
export type FieldKind = (typeof FIELD_KINDS)[number];

/** One field, exactly as `FieldShape.describe` writes it. An absent attribute is its neutral value. */
export interface FieldShape {
  readonly name: string;
  readonly kind: FieldKind;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly values?: readonly string[];
  readonly count_minimum?: number;
  readonly count_maximum?: number;
  readonly increasing?: 'strictly';
  readonly dimension?: number;
  /** The nested shape's name, for `record` and `records`. */
  readonly shape?: string;
  readonly refers_to?: readonly string[];
  readonly vocabulary?: string;
}

/** `IdentityRule.describe`: the ordinal is a field, a fixed number, or a field's fixed code. */
export interface IdentityRule {
  readonly field: string;
  readonly subject_kind: string;
  readonly owner_field: string;
  readonly ordinal:
    | string
    | number
    | { readonly field: string; readonly codes: { readonly [value: string]: number } };
}

/** `RecordShape.describe`. A top-level record kind has `kind` and `version`; a nested shape has neither. */
export interface RecordShape {
  readonly shape: string;
  readonly kind?: string;
  readonly version?: number;
  readonly fields: readonly FieldShape[];
  readonly rules: readonly string[];
  readonly identity?: IdentityRule;
  readonly extent_field?: string;
}

/** The frame a grammar version states its coordinates in, as its descriptor writes it. */
export interface GrammarFrame {
  readonly name: string;
  readonly units: string;
  readonly axes: string;
  readonly metric_class: string;
}

/**
 * The integer measures a grammar version's projection contracts state for a preserved property,
 * by projection, then property, then measure name: `capsule_clearance` for `nav_envelope` states
 * `eye_height_mm`, `height_mm` and `radius_mm`. A consumer builds to these numbers and to no
 * others; `exulanica.grammar.contract.PROPERTY_MEASURES` says which properties are measured.
 */
export interface ContractMeasures {
  readonly [projection: string]: {
    readonly [property: string]: { readonly [measure: string]: number };
  };
}

/**
 * What one record kind is to a person walking, as the descriptor's `navigation` table states it:
 * `ground` is `support`, `cover` or `none`, `cover` names the region a covering kind removes ground
 * under, and `obstruction` what a standing capsule keeps clear of. The row's reason is prose for a
 * reader and stays in the descriptor, whose digest the tile pins.
 */
export interface NavigationRow {
  readonly kind: string;
  readonly ground: string;
  readonly cover: string;
  readonly obstruction: string;
}

export interface GrammarTable {
  readonly grammar_id: string;
  readonly grammar_version: number;
  readonly frame: GrammarFrame;
  readonly measures: ContractMeasures;
  /**
   * The resolution each projection's contract states, in millimetres: the length a chord of a
   * curve may stand off the curve it stands for. A rule that turns an arc into segments reads it
   * rather than choosing a count.
   */
  readonly resolutions: { readonly [projection: string]: number };
  readonly navigation: readonly NavigationRow[];
  readonly shapes: {
    readonly nested: readonly RecordShape[];
    readonly records: readonly RecordShape[];
  };
}
