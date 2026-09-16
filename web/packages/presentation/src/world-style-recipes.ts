import type { WorldStyleParameterDefinition } from '@exulanica/atlas-core';
import type { WorldArtProfileSource } from './world-style-model.js';
import { WORLD_STYLE_REGISTRY_V1_JSON } from './world-style-registry-v1.generated.js';

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

/*
 * One authored source for what a world profile IS.
 *
 * Which profiles exist, their names and descriptions, who may use them, which reviewed modules
 * they run and every control they expose are authored once, in the backend registry
 * `exulanica/world/style-registry.v1.json`. This file used to restate all of it by hand, and the
 * two copies were held together by a pinned commit hash rather than by comparing them; by
 * 2026-09-16 the Aeroheart description had already drifted. The registry now arrives here as its
 * exact bytes (see `world-style-registry-v1.generated.ts`) and everything below is read from it.
 *
 * What this file still authors is what the backend has no field for: how a profile LOOKS
 * (`WorldArtAppearanceSource`), and the historical module bindings a saved world may still carry.
 */

export interface WorldStyleRegistryControlDocument {
  readonly key: string;
  readonly capability: string;
  readonly kind: WorldStyleParameterDefinition['kind'];
  readonly group: WorldStyleParameterDefinition['group'];
  readonly label: string;
  readonly description: string;
  readonly min?: number;
  readonly max?: number;
  readonly step?: number;
  readonly options?: readonly (string | { readonly value: string; readonly label: string })[];
  readonly default_value: number | string | boolean;
}

export interface WorldStyleRegistryProfileDocument {
  readonly profile_id: string;
  readonly profile_version: number;
  readonly display_name: string;
  readonly description: string;
  readonly compatibility_key: string;
  readonly status: string;
  readonly fallback: { readonly profile_id: string; readonly profile_version: number };
  readonly recipe: {
    readonly schema_version: number;
    readonly availability: string;
    readonly origin: string;
    readonly modules: readonly string[];
  };
  readonly controls: readonly WorldStyleRegistryControlDocument[];
}

/** The backend registry document, as authored. Snake case because that is its file form. */
export interface WorldStyleRegistryDocument {
  readonly schema_version: number;
  readonly frontend_contract: { readonly commit: string; readonly recipe_schema_version: number };
  readonly default_profile: { readonly profile_id: string; readonly profile_version: number };
  readonly capabilities: readonly {
    readonly capability: string;
    readonly kind: string;
    readonly group: string;
    readonly min?: number;
    readonly max?: number;
    readonly options?: readonly string[];
  }[];
  readonly modules: readonly { readonly module_id: string; readonly capabilities: readonly string[] }[];
  readonly profiles: readonly WorldStyleRegistryProfileDocument[];
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

export const WORLD_STYLE_REGISTRY_DOCUMENT: WorldStyleRegistryDocument = deepFreeze(
  JSON.parse(WORLD_STYLE_REGISTRY_V1_JSON) as WorldStyleRegistryDocument,
);

/** The identity half of a profile source. The backend registry authors it; nothing here does. */
type WorldArtProfileIdentity =
  | 'profileId'
  | 'profileVersion'
  | 'displayName'
  | 'description'
  | 'compatibilityKey';

/** How a registered profile looks. The backend registry has no field for any of this. */
export type WorldArtAppearanceSource = Omit<WorldArtProfileSource, WorldArtProfileIdentity>;

const AEROHEART_APPEARANCE: WorldArtAppearanceSource = {
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

const SURVEY_RELIEF_APPEARANCE: WorldArtAppearanceSource = {
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

const profileKey = (profileId: string, profileVersion: number): string =>
  `${profileId}@${profileVersion}`;

const APPEARANCES: ReadonlyMap<string, WorldArtAppearanceSource> = new Map([
  ['origin-landscape@1', AEROHEART_APPEARANCE],
  ['survey-relief@1', SURVEY_RELIEF_APPEARANCE],
]);

type ReadCompatibleBindings = NonNullable<WorldStyleRecipeV1['readCompatibleBindings']>;

/*
 * Worlds saved before `source-light-v1` joined Aeroheart carry the three-module binding below.
 * The backend registry describes only the current binding, so the exact historical one is kept
 * here, next to the only reader of it (`validateBinding` in the app's world-style adapter).
 */
const READ_COMPATIBLE_BINDINGS: ReadonlyMap<string, ReadCompatibleBindings> = new Map([
  ['origin-landscape@1', [{
    modules: ['aeroheart-optics-v1', 'registered-surface-v1', 'bounded-tempo-v1'],
    capabilityMapping: {
      vitality: 'world.vitality', glass: 'material.transmission',
      'relationship-energy': 'relationships.energy', 'garden-density': 'detail.ecology',
      'horizon-softness': 'atmosphere.softness', 'surface-finish': 'surface.finish',
      'world-tempo': 'motion.tempo',
    },
  }]],
]);

function finite(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`world style registry needs a finite ${label}`);
  }
  return value;
}

function textDefault(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new TypeError(`world style registry needs a text ${label}`);
  return value;
}

/** The same camel-case control the backend catalog serves, so the two compare exactly. */
export function worldStyleControlFromDocument(
  control: WorldStyleRegistryControlDocument,
): WorldStyleParameterDefinition {
  const base = {
    key: control.key,
    capability: control.capability,
    label: control.label,
    description: control.description,
    group: control.group,
  };
  const label = `${control.key} default`;
  switch (control.kind) {
    case 'range':
      return {
        ...base,
        kind: 'range',
        min: finite(control.min, `${control.key} min`),
        max: finite(control.max, `${control.key} max`),
        step: finite(control.step, `${control.key} step`),
        defaultValue: finite(control.default_value, label),
      };
    case 'choice':
      return {
        ...base,
        kind: 'choice',
        options: (control.options ?? []).map((option) =>
          typeof option === 'string' ? { value: option, label: option } : { ...option }),
        defaultValue: textDefault(control.default_value, label),
      };
    case 'color':
      return { ...base, kind: 'color', defaultValue: textDefault(control.default_value, label) };
    case 'toggle':
      if (typeof control.default_value !== 'boolean') {
        throw new TypeError(`world style registry needs a boolean ${label}`);
      }
      return { ...base, kind: 'toggle', defaultValue: control.default_value };
    default:
      throw new TypeError(`world style registry names an unknown control kind for ${control.key}`);
  }
}

function recipeFromDocument(profile: WorldStyleRegistryProfileDocument): WorldStyleRecipeV1 {
  const key = profileKey(profile.profile_id, profile.profile_version);
  const appearance = APPEARANCES.get(key);
  if (appearance === undefined) {
    throw new TypeError(`the backend registry names ${key}, which has no reviewed appearance`);
  }
  const { availability, origin } = profile.recipe;
  if (profile.recipe.schema_version !== 1) {
    throw new TypeError(`unsupported world style recipe schema in ${key}`);
  }
  if (availability !== 'product' && availability !== 'developer') {
    throw new TypeError(`invalid world style availability: ${key}`);
  }
  if (origin !== 'authored' && origin !== 'generated') {
    throw new TypeError(`invalid world style origin: ${key}`);
  }
  const compatibilityKey = profile.compatibility_key;
  if (compatibilityKey !== 'atlas-topology-v1') {
    throw new TypeError(`this Atlas cannot draw the ${key} topology ${compatibilityKey}`);
  }
  const readCompatibleBindings = READ_COMPATIBLE_BINDINGS.get(key);
  return {
    schemaVersion: 1,
    availability,
    origin,
    profile: {
      profileId: profile.profile_id,
      profileVersion: profile.profile_version,
      displayName: profile.display_name,
      description: profile.description,
      compatibilityKey,
      ...appearance,
    },
    controls: profile.controls.map(worldStyleControlFromDocument),
    modules: [...profile.recipe.modules],
    ...(readCompatibleBindings === undefined ? {} : { readCompatibleBindings }),
  };
}

export const WORLD_STYLE_RECIPES: readonly WorldStyleRecipeV1[] =
  WORLD_STYLE_REGISTRY_DOCUMENT.profiles.map(recipeFromDocument);

// An appearance or a historical binding for a profile the registry does not name is vocabulary
// nothing can reach, so it fails here rather than lingering.
for (const key of [...APPEARANCES.keys(), ...READ_COMPATIBLE_BINDINGS.keys()]) {
  if (!WORLD_STYLE_RECIPES.some((recipe) =>
    profileKey(recipe.profile.profileId, recipe.profile.profileVersion) === key)) {
    throw new TypeError(`${key} is authored here but the backend registry does not register it`);
  }
}
