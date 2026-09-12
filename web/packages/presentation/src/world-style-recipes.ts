import type { WorldStyleParameterDefinition } from '@exulanica/atlas-core';
import type { WorldArtProfileSource } from './world-style-model.js';

export type WorldStyleAvailability = 'product' | 'developer';
export type WorldStyleRecipeOrigin = 'authored' | 'generated';

/**
 * Serializable style input. A future service or local agent may produce this data, but executable
 * renderer behavior remains limited to the reviewed module IDs registered by the client.
 */
export interface WorldStyleRecipeV1 {
  readonly schemaVersion: 1;
  readonly availability: WorldStyleAvailability;
  readonly origin: WorldStyleRecipeOrigin;
  readonly profile: WorldArtProfileSource;
  readonly controls: readonly WorldStyleParameterDefinition[];
  readonly modules: readonly string[];
  /** Exact reviewed historical bindings accepted for saved reads, never for new proposals. */
  readonly readCompatibleBindings?: readonly {
    readonly modules: readonly string[];
    readonly capabilityMapping: Readonly<Record<string, string>>;
  }[];
}

export const AEROHEART_CONTROLS: readonly WorldStyleParameterDefinition[] = [
  {
    key: 'vitality', capability: 'world.vitality', kind: 'range', group: 'world',
    // It used to claim the interface too. Once the interface had its own four controls, two
    // modules were writing the same output and the later one silently won, which is the exact
    // shape of bug that costs an afternoon. One owner per output: this one owns the field.
    label: 'Color vitality', description: 'Tunes the colour of the memory field itself.',
    min: 0, max: 1, step: 0.05, defaultValue: 0.82,
  },
  {
    key: 'glass', capability: 'material.transmission', kind: 'range', group: 'material',
    label: 'Veil clarity', description: 'Changes the memory weave from soft optical thread to a crisp source image.',
    min: 0, max: 1, step: 0.05, defaultValue: 0.76,
  },
  {
    key: 'relationship-energy', capability: 'relationships.energy', kind: 'range', group: 'motion',
    label: 'Relationship energy', description: 'Controls the visual strength of confirmed relationship filaments.',
    min: 0, max: 1, step: 0.05, defaultValue: 0.68,
  },
  {
    key: 'garden-density', capability: 'detail.ecology', kind: 'range', group: 'detail',
    label: 'Weave detail', description: 'Controls bounded source-thread detail without adding, removing, or implying evidence.',
    min: 0, max: 1, step: 0.05, defaultValue: 0.72,
  },
  {
    key: 'horizon-softness', capability: 'atmosphere.softness', kind: 'range', group: 'atmosphere',
    label: 'Horizon softness', description: 'Changes atmospheric depth without hiding destinations.',
    min: 0, max: 1, step: 0.05, defaultValue: 0.46,
  },
  {
    key: 'surface-finish', capability: 'surface.finish', kind: 'choice', group: 'material',
    label: 'Surface finish', description: 'Uses one registered finish across the field and summoned interface surfaces.',
    options: [
      { value: 'source-paper', label: 'Source paper' },
      { value: 'clear-lens', label: 'Clear lens' },
    ],
    defaultValue: 'source-paper',
  },
  {
    key: 'source-hue', capability: 'interface.hue', kind: 'range', group: 'world',
    label: 'Interface hue',
    description: 'The colour the interface is built from. Reading it from your photographs sets this.',
    min: 0, max: 1, step: 0.01, defaultValue: 0.6,
  },
  {
    key: 'source-warmth', capability: 'interface.warmth', kind: 'range', group: 'world',
    label: 'Evidence warmth',
    description: 'How warm the mark for your own words and your own photographs runs.',
    min: 0, max: 1, step: 0.01, defaultValue: 0.19,
  },
  {
    key: 'source-depth', capability: 'interface.depth', kind: 'range', group: 'world',
    label: 'Reading depth',
    description: 'How deep the reading colour sits. It never goes light enough to be hard to read.',
    min: 0, max: 1, step: 0.01, defaultValue: 0.36,
  },
  {
    key: 'source-light', capability: 'interface.light', kind: 'range', group: 'world',
    label: 'Plate light',
    description: 'How much light the summoned surfaces hold.',
    min: 0, max: 1, step: 0.01, defaultValue: 0.86,
  },
  {
    key: 'world-tempo', capability: 'motion.tempo', kind: 'range', group: 'motion',
    label: 'Memory tempo', description: 'Changes the shared ambient and interface cadence inside a calm, bounded range.',
    min: 0.75, max: 1.25, step: 0.05, defaultValue: 1,
  },
];

export const SURVEY_RELIEF_CONTROLS: readonly WorldStyleParameterDefinition[] = [
  {
    key: 'contour-density', capability: 'detail.contours', kind: 'range', group: 'detail',
    label: 'Contour density', description: 'Changes the number of non-semantic survey contour marks.',
    min: 0, max: 1, step: 0.1, defaultValue: 0.55,
  },
  {
    key: 'technical-contrast', capability: 'material.technical-contrast', kind: 'range', group: 'material',
    label: 'Technical contrast', description: 'Controls separation between survey strata and their field.',
    min: 0, max: 1, step: 0.1, defaultValue: 0.7,
  },
];

const AEROHEART_SOURCE: WorldArtProfileSource = {
  profileId: 'origin-landscape',
  profileVersion: 1,
  displayName: 'Aeroheart',
  description: 'A clear memory field shaped by diffuse colour entering from its edges.',
  compatibilityKey: 'atlas-topology-v1',
  geometry: {
    landmark: 'aero-beacon',
    evidence: 'memory-lens',
    expansion: 'living-buds',
    // The orientation register is a REGION-scale reference, not a cross-field one: the landmark
    // socket puts it about three units from its region centre and the opening camera spawns 3.6
    // units out, so a person always stands beside one. Taller does not read as further away, it
    // reads as a wall: at 6.4 this spans more than the full vertical field of view from spawn.
    // Tall enough to clear the horizon dissolve and still be found from the opening position.
    landmarkHeight: 3.4,
    landmarkWidth: 2.4,
    evidenceSpread: 1.7,
    detailCount: 8,
    expansionCount: 5,
  },
  field: {
    atmosphere: 'diffuse-canvas',
    surface: 'paper-contour',
    surfacePresence: 0.62,
  },
  material: {
    emissiveStrength: 0.58,
    opacity: 0.72,
    metalness: 0.18,
    gloss: 0.82,
    edgeStrength: 0.86,
  },
  /*
   * The resting field, and exactly what `aeroheart-optics-v1` builds at its control defaults.
   *
   * Eight of these ten drifted by one to six units from what the module constructs, so a world
   * read without parameters and the same world read at its own defaults were not the same world.
   * Nothing visible depended on it yet, which is precisely why it was worth closing: it is the
   * same two-writers hazard that has already cost this project three broken renders, sitting
   * quietly in the values everything else is derived from.
   */
  palette: {
    sky: '#a2d4df',
    haze: '#fffaf3',
    terrain: '#eaf6f0',
    terrainLift: '#d6ecdc',
    path: '#ffac38',
    stone: '#fffcf6',
    stoneShadow: '#b3c3e3',
    paper: '#fffdf9',
    brass: '#f96858',
    sun: '#fff6cc',
  },
  /*
   * Aeroheart says what its interface is made of rather than inheriting it from the field.
   *
   * The scene is deliberately pale: eight of its ten roots sit under 0.05 chroma, which is
   * correct for a world made of light and leaves nothing for an interface to be built out of.
   * Borrowing scene parts meant the reading colour was the ground, the plate was the paper, and
   * the only hue with any strength, the coral, had to serve as accent, provenance and caution at
   * once. These five each mean one thing, and the field stays as pale as it should be.
   */
  /*
   * The resting interface, and exactly what `source-light-v1` builds at its control defaults.
   *
   * These two paths have to agree byte for byte. An unparameterised read of this recipe returns
   * these literals without running a module, and a read with defaults supplied runs the module and
   * constructs them; if the two disagreed, a world would change colour the first time anybody
   * touched an unrelated slider, and a test comparing against "the resting state" would be
   * comparing against whichever path it happened to take.
   */
  interfacePalette: {
    ink: '#17333b',
    plate: '#fffaf0',
    structure: '#318fa5',
    evidence: '#fa6a5b',
    uncertain: '#7b71b5',
  },
  semanticChannels: {
    provenance: ['hue', 'shape'],
    confirmation: ['hue', 'stroke'],
    focus: ['contrast', 'outline'],
  },
  ui: {
    typography: {
      body: '"Avenir Next", "Segoe UI Variable", ui-sans-serif, system-ui, sans-serif',
      display: '"Avenir Next", "Segoe UI Variable Display", ui-sans-serif, system-ui, sans-serif',
      utility: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      companion: '"Avenir Next", Avenir, ui-sans-serif, system-ui, sans-serif',
    },
    material: {
      worldBlur: 8,
      systemBlur: 18,
      companionBlur: 24,
      worldSaturation: 1,
      systemSaturation: 1.15,
      companionSaturation: 1.12,
      textureOpacity: 0.08,
    },
    texture: { kind: 'paper-grain', blendMode: 'multiply' },
    motion: {
      quickMs: 130,
      standardMs: 220,
      deliberateMs: 320,
      idleCycleMs: 5_200,
      workingCycleMs: 1_250,
      staggerMs: 140,
      easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)',
    },
  },
};

const SURVEY_RELIEF_SOURCE: WorldArtProfileSource = {
  profileId: 'survey-relief',
  profileVersion: 1,
  displayName: 'Survey Relief (experimental)',
  description: 'A topology-compatible field-ledger study for renderer regression tests.',
  compatibilityKey: 'atlas-topology-v1',
  geometry: {
    landmark: 'survey-strata',
    evidence: 'indexed-bays',
    expansion: 'survey-stakes',
    landmarkHeight: 2.1,
    landmarkWidth: 0.9,
    evidenceSpread: 1.55,
    detailCount: 8,
    expansionCount: 5,
  },
  field: {
    atmosphere: 'layered-horizon',
    surface: 'reflective-tide',
    surfacePresence: 1,
  },
  material: {
    emissiveStrength: 0.02,
    opacity: 1,
    metalness: 0.14,
    gloss: 0.28,
    edgeStrength: 0.9,
  },
  palette: {
    sky: '#d9dfdc',
    haze: '#b7c0ba',
    terrain: '#74766c',
    terrainLift: '#8c8c7e',
    path: '#725f46',
    stone: '#59605c',
    stoneShadow: '#343b38',
    paper: '#ddd8c9',
    brass: '#896b42',
    sun: '#e7cf9d',
  },
  semanticChannels: {
    provenance: ['hue', 'shape'],
    confirmation: ['hue', 'stroke'],
    focus: ['contrast', 'outline'],
  },
  ui: {
    typography: {
      body: '"Arial Narrow", "Avenir Next Condensed", ui-sans-serif, system-ui, sans-serif',
      display: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      utility: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      companion: '"Arial Narrow", "Avenir Next Condensed", ui-sans-serif, system-ui, sans-serif',
    },
    material: {
      worldBlur: 0,
      systemBlur: 0,
      companionBlur: 0,
      worldSaturation: 0.82,
      systemSaturation: 0.88,
      companionSaturation: 0.9,
      textureOpacity: 0.14,
    },
    texture: { kind: 'contour-grid', blendMode: 'multiply' },
    motion: {
      quickMs: 80,
      standardMs: 120,
      deliberateMs: 160,
      idleCycleMs: 4_000,
      workingCycleMs: 900,
      staggerMs: 90,
      easing: 'linear',
    },
  },
};

export const WORLD_STYLE_RECIPES: readonly WorldStyleRecipeV1[] = [
  {
    schemaVersion: 1,
    availability: 'product',
    origin: 'authored',
    profile: AEROHEART_SOURCE,
    controls: AEROHEART_CONTROLS,
    modules: ['aeroheart-optics-v1', 'registered-surface-v1', 'bounded-tempo-v1', 'source-light-v1'],
    readCompatibleBindings: [{
      modules: ['aeroheart-optics-v1', 'registered-surface-v1', 'bounded-tempo-v1'],
      capabilityMapping: {
        vitality: 'world.vitality', glass: 'material.transmission',
        'relationship-energy': 'relationships.energy', 'garden-density': 'detail.ecology',
        'horizon-softness': 'atmosphere.softness', 'surface-finish': 'surface.finish',
        'world-tempo': 'motion.tempo',
      },
    }],
  },
  {
    schemaVersion: 1,
    availability: 'developer',
    origin: 'authored',
    profile: SURVEY_RELIEF_SOURCE,
    controls: SURVEY_RELIEF_CONTROLS,
    modules: ['survey-relief-response-v1'],
  },
];
