import { localVec3 } from '../coords.js';
import type { WorldModuleDefinition } from './module-registry.js';
import { WorldModuleRegistry } from './module-registry.js';
import type { WorldRecipeDefinition, WorldRecipeSlot } from './recipe-registry.js';
import { WorldRecipeRegistry } from './recipe-registry.js';

const NO_COLLISION = Object.freeze({ kind: 'none' as const });
const DECORATIVE_NAVIGATION = Object.freeze({
  surface: 'none' as const,
  maxSlopeDegrees: 0,
  minimumClearance: 0,
  requiredDestination: false,
});
const COMMON_CUSTOMIZATION = Object.freeze([
  'geometry-variant' as const,
  'material-family' as const,
  'regional-accent' as const,
  'detail-density' as const,
]);

const moduleDefinitions: readonly WorldModuleDefinition[] = Object.freeze([
  {
    key: 'field.memory-ground',
    version: 1,
    role: 'navigation-field',
    allowedRungs: 'any',
    bounds: { radius: 1, height: 0 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: {
      surface: 'walkable',
      maxSlopeDegrees: 12,
      minimumClearance: 0.68,
      requiredDestination: false,
    },
    lod: { stub: 'field-index', proxy: 'field-flat', coarse: 'field-directional', full: 'field-directional' },
    accessibility: { interactive: false, labelKey: null, colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: ['material-family', 'atmosphere'],
  },
  {
    key: 'region.soft-footprint',
    version: 1,
    role: 'region-foundation',
    allowedRungs: 'any',
    bounds: { radius: 1, height: 0.1 },
    sockets: [
      {
        key: 'content',
        local: localVec3(0, 0, 0),
        yaw: 0,
        accepts: ['evidence-assembly', 'reconstruction-assembly'],
        clearanceRadius: 0.12,
      },
      {
        key: 'landmark',
        local: localVec3(-0.52, 0, 0.34),
        yaw: -0.25,
        accepts: ['landmark'],
        clearanceRadius: 0.1,
      },
      {
        key: 'growth',
        local: localVec3(0.56, 0, -0.42),
        yaw: 0.35,
        accepts: ['expansion-point'],
        clearanceRadius: 0.08,
      },
    ],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'region-sigil', proxy: 'region-haze', coarse: 'region-soft', full: 'region-soft' },
    accessibility: { interactive: false, labelKey: null, colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: ['material-family', 'regional-accent', 'detail-density'],
  },
  {
    key: 'region.source-register',
    version: 1,
    role: 'evidence-assembly',
    allowedRungs: 'any',
    bounds: { radius: 1.75, height: 2.55 },
    sockets: [],
    collision: { kind: 'box', halfWidth: 1.75, halfDepth: 0.5, source: 'authored-proxy' },
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'source-sigil', proxy: 'source-card', coarse: 'source-register', full: 'source-register' },
    accessibility: { interactive: true, labelKey: 'world.source-evidence', colorIsSoleCarrier: false },
    evidence: 'source-evidence',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'region.reconstruction-volume',
    version: 1,
    role: 'reconstruction-assembly',
    allowedRungs: [1],
    bounds: { radius: 0.72, height: 0.9 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: {
      surface: 'constrained',
      maxSlopeDegrees: 12,
      minimumClearance: 0.68,
      requiredDestination: true,
    },
    lod: { stub: 'volume-sigil', proxy: 'volume-silhouette', coarse: 'volume-coarse', full: 'volume-measured' },
    accessibility: { interactive: true, labelKey: 'world.reconstruction-volume', colorIsSoleCarrier: false },
    evidence: 'reconstruction-asset',
    fallbackKey: 'region.source-register',
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'region.reconstruction-corridor',
    version: 1,
    role: 'reconstruction-assembly',
    allowedRungs: [2],
    bounds: { radius: 0.68, height: 0.82 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: {
      surface: 'constrained',
      maxSlopeDegrees: 8,
      minimumClearance: 0.68,
      requiredDestination: true,
    },
    lod: { stub: 'corridor-sigil', proxy: 'corridor-line', coarse: 'corridor-shell', full: 'corridor-measured' },
    accessibility: { interactive: true, labelKey: 'world.reconstruction-corridor', colorIsSoleCarrier: false },
    evidence: 'reconstruction-asset',
    fallbackKey: 'region.source-register',
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'region.photographic-panels',
    version: 1,
    role: 'reconstruction-assembly',
    allowedRungs: [3],
    bounds: { radius: 0.6, height: 0.78 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: {
      surface: 'constrained',
      maxSlopeDegrees: 8,
      minimumClearance: 0.68,
      requiredDestination: true,
    },
    lod: { stub: 'panel-sigil', proxy: 'panel-silhouette', coarse: 'panel-depth', full: 'panel-measured' },
    accessibility: { interactive: true, labelKey: 'world.photographic-panels', colorIsSoleCarrier: false },
    evidence: 'reconstruction-asset',
    fallbackKey: 'region.source-register',
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'region.evidence-cards',
    version: 1,
    role: 'evidence-assembly',
    allowedRungs: [4],
    bounds: { radius: 1.75, height: 2.55 },
    sockets: [],
    collision: { kind: 'box', halfWidth: 1.75, halfDepth: 0.5, source: 'authored-proxy' },
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'card-sigil', proxy: 'card-triplet', coarse: 'card-grove', full: 'card-grove' },
    accessibility: { interactive: true, labelKey: 'world.evidence-cards', colorIsSoleCarrier: false },
    evidence: 'source-evidence',
    fallbackKey: 'region.source-register',
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'landmark.orientation-register',
    version: 1,
    role: 'landmark',
    allowedRungs: 'any',
    bounds: { radius: 0.08, height: 0.7 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'landmark-dot', proxy: 'landmark-spine', coarse: 'landmark-register', full: 'landmark-register' },
    accessibility: { interactive: false, labelKey: null, colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'growth.open-register',
    version: 1,
    role: 'expansion-point',
    allowedRungs: 'any',
    bounds: { radius: 0.08, height: 0.24 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'growth-dot', proxy: 'growth-mark', coarse: 'growth-register', full: 'growth-register' },
    accessibility: { interactive: false, labelKey: 'world.expansion-point', colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: COMMON_CUSTOMIZATION,
  },
  {
    key: 'relationship.confirmed-trace',
    version: 1,
    role: 'relationship-path',
    allowedRungs: 'any',
    bounds: { radius: 0, height: 0 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'trace-index', proxy: 'trace-faint', coarse: 'trace-field', full: 'trace-field' },
    accessibility: { interactive: false, labelKey: 'world.confirmed-relationship', colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: null,
    variantOf: null,
    form: null,
    customization: ['material-family', 'regional-accent', 'detail-density'],
  },
  /*
   * Footprint arrangements.
   *
   * A region's foundation decides where its orientation register stands and where its growth
   * register sits, so substituting the footprint rearranges the region without inventing geometry
   * or touching the renderer, which places both from the socket it is given. These carry the same
   * role, evidence requirement, rungs and socket contract as `region.soft-footprint`; the registry
   * refuses them otherwise. Adding a fourth arrangement is this edit and nothing else.
   */
  {
    key: 'region.terraced-footprint',
    version: 1,
    role: 'region-foundation',
    allowedRungs: 'any',
    bounds: { radius: 1, height: 0.1 },
    sockets: [
      {
        key: 'content',
        local: localVec3(0, 0, 0),
        yaw: 0,
        accepts: ['evidence-assembly', 'reconstruction-assembly'],
        clearanceRadius: 0.12,
      },
      {
        key: 'landmark',
        local: localVec3(0.48, 0, 0.46),
        yaw: 0.62,
        accepts: ['landmark'],
        clearanceRadius: 0.1,
      },
      {
        key: 'growth',
        local: localVec3(-0.44, 0, -0.5),
        yaw: -0.58,
        accepts: ['expansion-point'],
        clearanceRadius: 0.08,
      },
    ],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'region-sigil', proxy: 'region-haze', coarse: 'region-terraced', full: 'region-terraced' },
    accessibility: { interactive: false, labelKey: null, colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: 'region.soft-footprint',
    variantOf: 'region.soft-footprint',
    form: null,
    customization: ['material-family', 'regional-accent', 'detail-density'],
  },
  {
    key: 'region.sheltered-footprint',
    version: 1,
    role: 'region-foundation',
    allowedRungs: 'any',
    bounds: { radius: 1, height: 0.1 },
    sockets: [
      {
        key: 'content',
        local: localVec3(0, 0, 0),
        yaw: 0,
        accepts: ['evidence-assembly', 'reconstruction-assembly'],
        clearanceRadius: 0.12,
      },
      {
        key: 'landmark',
        local: localVec3(-0.06, 0, -0.62),
        yaw: 2.9,
        accepts: ['landmark'],
        clearanceRadius: 0.1,
      },
      {
        key: 'growth',
        local: localVec3(0.62, 0, 0.18),
        yaw: 1.28,
        accepts: ['expansion-point'],
        clearanceRadius: 0.08,
      },
    ],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'region-sigil', proxy: 'region-haze', coarse: 'region-sheltered', full: 'region-sheltered' },
    accessibility: { interactive: false, labelKey: null, colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: 'region.soft-footprint',
    variantOf: 'region.soft-footprint',
    form: null,
    customization: ['material-family', 'regional-accent', 'detail-density'],
  },
  /*
   * Arrangements that carry their own form.
   *
   * These declare what they are built as instead of inheriting the active world style's single
   * choice for every module of the role at once. The style still owns material, colour and
   * proportion; the module owns what it is. Their canonical counterparts keep `form: null`, so a world style that switches
   * form still switches theirs and nothing already recorded changes shape.
   */
  {
    key: 'growth.survey-register',
    version: 1,
    role: 'expansion-point',
    allowedRungs: 'any',
    bounds: { radius: 0.2, height: 0.5 },
    sockets: [],
    collision: NO_COLLISION,
    navigation: DECORATIVE_NAVIGATION,
    lod: { stub: 'growth-dot', proxy: 'growth-mark', coarse: 'growth-stakes', full: 'growth-stakes' },
    accessibility: { interactive: false, labelKey: 'world.expansion-point', colorIsSoleCarrier: false },
    evidence: 'none',
    fallbackKey: 'growth.open-register',
    variantOf: 'growth.open-register',
    form: { kind: 'survey-stakes', parameters: { count: 6 } },
    customization: COMMON_CUSTOMIZATION,
  },
]);

// 4: removes the survey-strata orientation register. No renderer draws a landmark form any more,
// so a seed that chose it now chooses the canonical register, which also draws nothing.
// 3: adds arrangements that declare their own form rather than inheriting the world style's.
// 2: adds substitutable region footprint arrangements. Composition for an existing world only
// changes where its seed now selects one, which is why this version travels in every snapshot.
export const DEFAULT_WORLD_MODULE_CATALOG_VERSION = 4;
export const DEFAULT_WORLD_MODULES = new WorldModuleRegistry(
  DEFAULT_WORLD_MODULE_CATALOG_VERSION,
  moduleDefinitions,
);

const regionSlots = (contentModuleKey: string): readonly WorldRecipeSlot[] => Object.freeze([
  { key: 'foundation', moduleKey: 'region.soft-footprint', attachTo: null, required: true },
  {
    key: 'content',
    moduleKey: contentModuleKey,
    attachTo: { parentSlot: 'foundation', socket: 'content' },
    required: true,
  },
  {
    key: 'landmark',
    moduleKey: 'landmark.orientation-register',
    attachTo: { parentSlot: 'foundation', socket: 'landmark' },
    required: true,
  },
  {
    key: 'growth',
    moduleKey: 'growth.open-register',
    attachTo: { parentSlot: 'foundation', socket: 'growth' },
    required: true,
  },
]);

const recipeDefinitions: readonly WorldRecipeDefinition[] = Object.freeze([
  {
    key: 'world.grounded-field',
    version: 1,
    scope: 'world',
    allowedRungs: 'any',
    slots: [{ key: 'field', moduleKey: 'field.memory-ground', attachTo: null, required: true }],
  },
  {
    key: 'region.rung-1',
    version: 1,
    scope: 'region',
    allowedRungs: [1],
    slots: regionSlots('region.reconstruction-volume'),
  },
  {
    key: 'region.rung-2',
    version: 1,
    scope: 'region',
    allowedRungs: [2],
    slots: regionSlots('region.reconstruction-corridor'),
  },
  {
    key: 'region.rung-3',
    version: 1,
    scope: 'region',
    allowedRungs: [3],
    slots: regionSlots('region.photographic-panels'),
  },
  {
    key: 'region.rung-4',
    version: 1,
    scope: 'region',
    allowedRungs: [4],
    slots: regionSlots('region.evidence-cards'),
  },
  {
    key: 'relationship.confirmed',
    version: 1,
    scope: 'relationship',
    allowedRungs: 'any',
    slots: [{ key: 'trace', moduleKey: 'relationship.confirmed-trace', attachTo: null, required: true }],
  },
]);

export const DEFAULT_WORLD_RECIPE_CATALOG_VERSION = 1;
export const DEFAULT_WORLD_RECIPES = new WorldRecipeRegistry(
  DEFAULT_WORLD_RECIPE_CATALOG_VERSION,
  recipeDefinitions,
  DEFAULT_WORLD_MODULES,
);
