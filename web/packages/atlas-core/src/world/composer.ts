import type { AtlasVec3, LocalVec3 } from '../coords.js';
import { atlasVec3 } from '../coords.js';
import type { IslandId } from '../ids.js';
import { buildNavigationWorld } from '../navigation.js';
import type { ReconstructionRung } from '../rung.js';
import type { AtlasScene } from '../scene.js';
import { DEFAULT_WORLD_MODULES, DEFAULT_WORLD_RECIPES } from './default-catalog.js';
import type {
  ModuleCollisionContract,
  ModuleEvidenceRequirement,
  ModuleNavigationContract,
  WorldModuleDefinition,
  WorldModuleRole,
} from './module-registry.js';
import { WorldModuleRegistry } from './module-registry.js';
import type { WorldRecipeDefinition } from './recipe-registry.js';
import { WorldRecipeRegistry } from './recipe-registry.js';

export const WORLD_TOPOLOGY_SCHEMA_VERSION = 1;
export const ATLAS_COMPOSER_KEY = 'atlas-world-composer';
export const ATLAS_COMPOSER_VERSION = 1;
export const DEFAULT_WORLD_ID = 'atlas:default';

export type WorldElementOrigin = 'generated' | 'authored-override';

export type WorldElementOwner =
  | { readonly kind: 'world'; readonly id: string }
  | { readonly kind: 'region'; readonly id: IslandId }
  | {
      readonly kind: 'relationship';
      readonly id: string;
      readonly from: IslandId;
      readonly to: IslandId;
    };

export type WorldElementCause =
  | { readonly kind: 'region'; readonly ref: string }
  | { readonly kind: 'confirmed-relationship'; readonly ref: string }
  | { readonly kind: 'reconstruction-rung'; readonly ref: `${ReconstructionRung}` }
  | { readonly kind: 'presentation-rule'; readonly ref: string };

export interface WorldElementProvenance {
  readonly owner: WorldElementOwner;
  readonly origin: WorldElementOrigin;
  readonly causes: readonly WorldElementCause[];
  readonly generatedBy: {
    readonly composerKey: typeof ATLAS_COMPOSER_KEY;
    readonly composerVersion: typeof ATLAS_COMPOSER_VERSION;
    readonly recipeKey: string;
    readonly recipeVersion: number;
    readonly slotKey: string;
  };
}

export interface WorldTransform {
  readonly position: AtlasVec3;
  readonly yaw: number;
  readonly scale: number;
}

export interface WorldModuleAttachment {
  readonly parentInstanceId: string;
  readonly socketKey: string;
}

export interface WorldPathGeometry {
  readonly start: AtlasVec3;
  readonly end: AtlasVec3;
  readonly strength: number;
}

export interface WorldModuleInstance {
  readonly instanceId: string;
  readonly moduleKey: string;
  readonly moduleVersion: number;
  /** What the recipe slot declares, before the seed chose among that module's variants. */
  readonly slotModuleKey: string;
  /** The recipe request is retained when honesty or compatibility selected a fallback. */
  readonly requestedModuleKey: string;
  readonly role: WorldModuleRole;
  readonly recipeKey: string;
  readonly recipeVersion: number;
  readonly slotKey: string;
  readonly transform: WorldTransform;
  readonly attachment: WorldModuleAttachment | null;
  readonly collision: ModuleCollisionContract;
  readonly navigation: ModuleNavigationContract;
  readonly evidence: ModuleEvidenceRequirement;
  /**
   * The module's declared form, or null when the world style still chooses it.
   *
   * Not part of the topology digest: the module key and version that carry it already are, so the
   * digest pins the form without restating it.
   */
  readonly form: WorldModuleDefinition['form'];
  readonly accessibility: WorldModuleDefinition['accessibility'];
  readonly streamingKey: string;
  readonly path: WorldPathGeometry | null;
  readonly provenance: WorldElementProvenance;
}

export interface WorldNavigationDestination {
  readonly id: string;
  readonly islandId: IslandId;
  readonly position: AtlasVec3;
  readonly required: true;
}

export interface WorldNavigationEdge {
  readonly from: string;
  readonly to: string;
  /** Field edges guarantee travel but make no semantic claim. */
  readonly kind: 'field' | 'confirmed-relationship';
  readonly visible: boolean;
  readonly maxSlopeDegrees: number;
}

export interface WorldNavigationGraph {
  readonly eyeHeight: number;
  readonly cameraRadius: number;
  readonly maximumSlopeDegrees: number;
  readonly maximumStepHeight: number;
  readonly minimumClearWidth: number;
  readonly destinations: readonly WorldNavigationDestination[];
  readonly edges: readonly WorldNavigationEdge[];
}

export interface WorldTopologyDiagnostic {
  readonly code: 'reconstruction-asset-unavailable';
  readonly instanceId: string;
  readonly detail: string;
}

export interface WorldTopologySnapshot {
  readonly schemaVersion: typeof WORLD_TOPOLOGY_SCHEMA_VERSION;
  readonly worldId: string;
  readonly snapshotId: string;
  readonly persistenceStatus: 'draft';
  readonly layoutVersion: number;
  readonly inputStateVersion: number;
  readonly composerKey: typeof ATLAS_COMPOSER_KEY;
  readonly composerVersion: typeof ATLAS_COMPOSER_VERSION;
  readonly moduleCatalogVersion: number;
  readonly recipeCatalogVersion: number;
  readonly seed: string;
  readonly topologyDigest: string;
  readonly instances: readonly WorldModuleInstance[];
  readonly navigation: WorldNavigationGraph;
  readonly diagnostics: readonly WorldTopologyDiagnostic[];
}

export interface ComposeWorldOptions {
  readonly worldId?: string;
  readonly seed?: string;
  readonly modules?: WorldModuleRegistry;
  readonly recipes?: WorldRecipeRegistry;
  /** Only IDs with an actually available reconstruction representation may realize rungs 1–3. */
  readonly availableReconstruction?: ReadonlySet<IslandId>;
}

const encode = (value: string): string => encodeURIComponent(value);

function ownerRef(owner: WorldElementOwner): string {
  return owner.kind === 'relationship'
    ? `${owner.from}|${owner.to}`
    : owner.id;
}

function stableInstanceId(owner: WorldElementOwner, recipeKey: string, slotKey: string): string {
  return `world-module:${owner.kind}:${encode(ownerRef(owner))}:${encode(recipeKey)}:${encode(slotKey)}`;
}

function relationshipOwner(fromInput: IslandId, toInput: IslandId): Extract<WorldElementOwner, { kind: 'relationship' }> {
  const [from, to] = fromInput < toInput ? [fromInput, toInput] : [toInput, fromInput];
  return Object.freeze({ kind: 'relationship', id: `relationship:${from}:${to}`, from, to });
}

function causesFor(owner: WorldElementOwner, rung: ReconstructionRung | null): readonly WorldElementCause[] {
  const causes: WorldElementCause[] = [{ kind: 'presentation-rule', ref: 'grounded-memory-archipelago' }];
  if (owner.kind === 'region') causes.unshift({ kind: 'region', ref: owner.id });
  if (owner.kind === 'relationship') {
    causes.unshift({ kind: 'confirmed-relationship', ref: `${owner.from}|${owner.to}` });
  }
  if (rung !== null) causes.push({ kind: 'reconstruction-rung', ref: `${rung}` });
  return Object.freeze(causes.map((cause) => Object.freeze(cause)));
}

function rotatedSocketPosition(parent: WorldTransform, local: LocalVec3): AtlasVec3 {
  const c = Math.cos(parent.yaw);
  const s = Math.sin(parent.yaw);
  const x = local.x * parent.scale;
  const y = local.y * parent.scale;
  const z = local.z * parent.scale;
  return atlasVec3(
    parent.position.x + x * c + z * s,
    parent.position.y + y,
    parent.position.z - x * s + z * c,
  );
}

interface ResolvedModule {
  readonly definition: WorldModuleDefinition;
  readonly requestedKey: string;
  readonly fellBack: boolean;
}

function resolveModule(
  modules: WorldModuleRegistry,
  requestedKey: string,
  rung: ReconstructionRung | null,
  reconstructionAvailable: boolean,
): ResolvedModule {
  const requested = modules.get(requestedKey);
  let definition = requested;
  const allowed = (candidate: WorldModuleDefinition): boolean =>
    rung === null || candidate.allowedRungs === 'any' || candidate.allowedRungs.includes(rung);
  const usable = (candidate: WorldModuleDefinition): boolean =>
    allowed(candidate) &&
    (candidate.evidence !== 'reconstruction-asset' || reconstructionAvailable);
  while (!usable(definition)) {
    if (definition.fallbackKey === null) {
      throw new TypeError(
        `module ${requestedKey} has no honest fallback for rung ${String(rung)}`,
      );
    }
    definition = modules.get(definition.fallbackKey);
  }
  return Object.freeze({
    definition,
    requestedKey,
    fellBack: definition.key !== requested.key,
  });
}

interface InstantiateContext {
  readonly owner: WorldElementOwner;
  readonly recipe: WorldRecipeDefinition;
  readonly root: WorldTransform;
  readonly rung: ReconstructionRung | null;
  readonly reconstructionAvailable: boolean;
  readonly modules: WorldModuleRegistry;
  readonly path: WorldPathGeometry | null;
  readonly seed: string;
}

function instantiateRecipe(
  context: InstantiateContext,
): { readonly instances: readonly WorldModuleInstance[]; readonly diagnostics: readonly WorldTopologyDiagnostic[] } {
  const instances: WorldModuleInstance[] = [];
  const diagnostics: WorldTopologyDiagnostic[] = [];
  const bySlot = new Map<string, WorldModuleInstance>();
  for (const slot of context.recipe.slots) {
    const instanceId = stableInstanceId(context.owner, context.recipe.key, slot.key);
    const resolved = resolveModule(
      context.modules,
      selectVariant(context.modules, slot.moduleKey, context.seed, instanceId),
      context.rung,
      context.reconstructionAvailable,
    );
    const module = resolved.definition;
    let transform = context.root;
    let attachment: WorldModuleAttachment | null = null;
    if (slot.attachTo !== null) {
      const parent = bySlot.get(slot.attachTo.parentSlot);
      if (parent === undefined) {
        throw new TypeError(`recipe parent was not instantiated: ${slot.attachTo.parentSlot}`);
      }
      const socket = context.modules.assertAttachment(
        parent.moduleKey,
        slot.attachTo.socket,
        module.key,
      );
      transform = Object.freeze({
        position: rotatedSocketPosition(parent.transform, socket.local),
        yaw: parent.transform.yaw + socket.yaw,
        // Socket position scales with the owning footprint; attached module dimensions remain in
        // authored Atlas units so large archive regions do not inflate landmarks or evidence.
        scale: 1,
      });
      attachment = Object.freeze({
        parentInstanceId: parent.instanceId,
        socketKey: socket.key,
      });
    }
    const instance: WorldModuleInstance = Object.freeze({
      instanceId,
      moduleKey: module.key,
      moduleVersion: module.version,
      slotModuleKey: slot.moduleKey,
      requestedModuleKey: resolved.requestedKey,
      role: module.role,
      recipeKey: context.recipe.key,
      recipeVersion: context.recipe.version,
      slotKey: slot.key,
      transform,
      attachment,
      collision: module.collision,
      navigation: module.navigation,
      evidence: module.evidence,
      form: module.form,
      accessibility: module.accessibility,
      streamingKey: `world-asset:${encode(module.key)}@${module.version}`,
      path: context.path,
      provenance: Object.freeze({
        owner: context.owner,
        origin: 'generated',
        causes: causesFor(context.owner, context.rung),
        generatedBy: Object.freeze({
          composerKey: ATLAS_COMPOSER_KEY,
          composerVersion: ATLAS_COMPOSER_VERSION,
          recipeKey: context.recipe.key,
          recipeVersion: context.recipe.version,
          slotKey: slot.key,
        }),
      }),
    });
    instances.push(instance);
    bySlot.set(slot.key, instance);
    if (resolved.fellBack && context.rung !== null) {
      diagnostics.push(Object.freeze({
        code: 'reconstruction-asset-unavailable',
        instanceId,
        detail: `${resolved.requestedKey} was not realized; ${module.key} preserves source access without inventing geometry.`,
      }));
    }
  }
  return Object.freeze({ instances: Object.freeze(instances), diagnostics: Object.freeze(diagnostics) });
}

function destinationId(islandId: IslandId): string {
  return `destination:${encode(islandId)}`;
}

function navigationGraph(scene: AtlasScene): WorldNavigationGraph {
  const world = buildNavigationWorld(scene);
  const ordered = [...scene.islands].sort(
    (a, b) => a.creationOrdinal - b.creationOrdinal ||
      (a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0),
  );
  const destinations: WorldNavigationDestination[] = ordered.map((island) => Object.freeze({
    id: destinationId(island.islandId),
    islandId: island.islandId,
    position: atlasVec3(island.placement.position.x, world.eyeHeight, island.placement.position.z),
    required: true as const,
  }));
  const edges: WorldNavigationEdge[] = [];
  for (let index = 0; index < destinations.length - 1; index += 1) {
    edges.push(Object.freeze({
      from: destinations[index]!.id,
      to: destinations[index + 1]!.id,
      kind: 'field' as const,
      visible: false,
      maxSlopeDegrees: 0,
    }));
  }
  for (const trace of world.traces) {
    edges.push(Object.freeze({
      from: destinationId(trace.from),
      to: destinationId(trace.to),
      kind: 'confirmed-relationship' as const,
      visible: true,
      maxSlopeDegrees: 0,
    }));
  }
  edges.sort((a, b) =>
    (a.from < b.from ? -1 : a.from > b.from ? 1 : 0) ||
    (a.to < b.to ? -1 : a.to > b.to ? 1 : 0) ||
    (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0));
  return Object.freeze({
    eyeHeight: world.eyeHeight,
    cameraRadius: world.cameraRadius,
    maximumSlopeDegrees: world.maximumSlopeDegrees,
    maximumStepHeight: world.maximumStepHeight,
    minimumClearWidth: 1.2,
    destinations: Object.freeze(destinations),
    edges: Object.freeze(edges),
  });
}

function quantized(value: number): number {
  return Math.round(value * 1000);
}

function canonicalTopology(
  instances: readonly WorldModuleInstance[],
  navigation: WorldNavigationGraph,
): string {
  return JSON.stringify({
    instances: [...instances].sort((a, b) => a.instanceId.localeCompare(b.instanceId)).map((value) => ({
      id: value.instanceId,
      module: `${value.moduleKey}@${value.moduleVersion}`,
      requested: value.requestedModuleKey,
      recipe: `${value.recipeKey}@${value.recipeVersion}:${value.slotKey}`,
      transform: [
        quantized(value.transform.position.x),
        quantized(value.transform.position.y),
        quantized(value.transform.position.z),
        quantized(value.transform.yaw),
        quantized(value.transform.scale),
      ],
      attachment: value.attachment,
      collision: value.collision,
      navigation: value.navigation,
      path: value.path === null ? null : [
        quantized(value.path.start.x),
        quantized(value.path.start.y),
        quantized(value.path.start.z),
        quantized(value.path.end.x),
        quantized(value.path.end.y),
        quantized(value.path.end.z),
        quantized(value.path.strength),
      ],
      owner: value.provenance.owner,
    })),
    navigation: {
      ...navigation,
      destinations: navigation.destinations.map((value) => ({
        ...value,
        position: [
          quantized(value.position.x),
          quantized(value.position.y),
          quantized(value.position.z),
        ],
      })),
    },
  });
}

/** Small deterministic content hash for fixture identity; persistence adapters may additionally use SHA-256. */
function fnv1a64Bits(value: string): bigint {
  let hash = 0xcbf29ce484222325n;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= BigInt(value.charCodeAt(index));
    hash = BigInt.asUintN(64, hash * 0x100000001b3n);
  }
  return hash;
}

function fnv1a64(value: string): string {
  return fnv1a64Bits(value).toString(16).padStart(16, '0');
}

/**
 * Which module fills this slot, for this seed.
 *
 * Hashed from the seed and the instance's own stable identity rather than drawn from a running
 * generator, so the choice for one region does not depend on how many regions were composed
 * before it. Adding a memory to a world therefore rearranges nothing that already existed, which
 * is the same anti-disorientation promise the view manifest makes.
 */
function selectVariant(
  modules: WorldModuleRegistry,
  canonicalKey: string,
  seed: string,
  instanceId: string,
): string {
  const pool = modules.variantsOf(canonicalKey);
  if (pool.length === 1) return canonicalKey;
  const index = Number(fnv1a64Bits(`${seed}\u0000${instanceId}`) % BigInt(pool.length));
  return pool[index]!.key;
}

export function topologyReachability(snapshot: Pick<WorldTopologySnapshot, 'navigation'>): ReadonlySet<string> {
  const destinations = snapshot.navigation.destinations;
  if (destinations.length === 0) return new Set();
  const adjacent = new Map<string, string[]>();
  for (const destination of destinations) adjacent.set(destination.id, []);
  for (const edge of snapshot.navigation.edges) {
    adjacent.get(edge.from)?.push(edge.to);
    adjacent.get(edge.to)?.push(edge.from);
  }
  const seen = new Set<string>();
  const queue = [destinations[0]!.id];
  while (queue.length > 0) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const next of adjacent.get(id) ?? []) if (!seen.has(next)) queue.push(next);
  }
  return seen;
}

export class WorldTopologyValidationError extends TypeError {
  constructor(readonly issues: readonly string[]) {
    super(`invalid world topology: ${issues.join('; ')}`);
    this.name = 'WorldTopologyValidationError';
  }
}

export function validateWorldTopology(
  snapshot: WorldTopologySnapshot,
  modules: WorldModuleRegistry = DEFAULT_WORLD_MODULES,
  recipes: WorldRecipeRegistry = DEFAULT_WORLD_RECIPES,
): void {
  const issues: string[] = [];
  const ids = new Set<string>();
  const byId = new Map<string, WorldModuleInstance>();
  for (const instance of snapshot.instances) {
    if (ids.has(instance.instanceId)) issues.push(`duplicate instance ${instance.instanceId}`);
    ids.add(instance.instanceId);
    byId.set(instance.instanceId, instance);
    if (!modules.has(instance.moduleKey)) {
      issues.push(`unknown module ${instance.moduleKey}`);
      continue;
    }
    const definition = modules.get(instance.moduleKey);
    if (definition.version !== instance.moduleVersion) {
      issues.push(`module version mismatch for ${instance.instanceId}`);
    }
    try {
      const recipe = recipes.get(instance.recipeKey);
      if (recipe.version !== instance.recipeVersion) {
        issues.push(`recipe version mismatch for ${instance.instanceId}`);
      }
    } catch {
      issues.push(`unknown recipe ${instance.recipeKey}`);
    }
    if (
      !Number.isFinite(instance.transform.position.x) ||
      !Number.isFinite(instance.transform.position.y) ||
      !Number.isFinite(instance.transform.position.z) ||
      !Number.isFinite(instance.transform.yaw) ||
      !Number.isFinite(instance.transform.scale) ||
      instance.transform.scale <= 0
    ) {
      issues.push(`invalid transform for ${instance.instanceId}`);
    }
  }
  for (const instance of snapshot.instances) {
    if (instance.attachment === null) continue;
    const parent = byId.get(instance.attachment.parentInstanceId);
    if (parent === undefined) {
      issues.push(`missing attachment parent for ${instance.instanceId}`);
      continue;
    }
    try {
      modules.assertAttachment(parent.moduleKey, instance.attachment.socketKey, instance.moduleKey);
    } catch (error) {
      issues.push(error instanceof Error ? error.message : String(error));
    }
  }
  const destinationIds = new Set(snapshot.navigation.destinations.map((value) => value.id));
  for (const edge of snapshot.navigation.edges) {
    if (!destinationIds.has(edge.from) || !destinationIds.has(edge.to)) {
      issues.push(`navigation edge references an unknown destination: ${edge.from} → ${edge.to}`);
    }
    if (edge.maxSlopeDegrees > snapshot.navigation.maximumSlopeDegrees) {
      issues.push(`navigation edge exceeds the slope contract: ${edge.from} → ${edge.to}`);
    }
  }
  const reachable = topologyReachability(snapshot);
  for (const destination of snapshot.navigation.destinations) {
    if (destination.required && !reachable.has(destination.id)) {
      issues.push(`required destination is unreachable: ${destination.id}`);
    }
  }
  const actualDigest = fnv1a64(canonicalTopology(snapshot.instances, snapshot.navigation));
  if (snapshot.topologyDigest !== actualDigest) issues.push('topology digest does not match payload');
  if (issues.length > 0) throw new WorldTopologyValidationError(Object.freeze(issues));
}

/**
 * Deterministic, engine-neutral composition. It produces a draft artifact only; a backend-owned
 * compare-and-swap persistence transaction is required before it can become world authority.
 */
export function composeAtlasWorld(
  scene: AtlasScene,
  options: ComposeWorldOptions = {},
): WorldTopologySnapshot {
  const worldId = options.worldId ?? DEFAULT_WORLD_ID;
  const seed = options.seed ?? '0';
  const modules = options.modules ?? DEFAULT_WORLD_MODULES;
  const recipes = options.recipes ?? DEFAULT_WORLD_RECIPES;
  if (worldId.length === 0) throw new TypeError('worldId must not be empty');
  if (seed.length === 0) throw new TypeError('world seed must not be empty');
  const navWorld = buildNavigationWorld(scene);
  const instances: WorldModuleInstance[] = [];
  const diagnostics: WorldTopologyDiagnostic[] = [];

  const worldRecipe = recipes.get('world.grounded-field');
  const worldAssembly = instantiateRecipe({
    owner: Object.freeze({ kind: 'world', id: worldId }),
    recipe: worldRecipe,
    root: Object.freeze({
      position: navWorld.centre,
      yaw: 0,
      scale: Math.max(1, navWorld.recoveryRadius),
    }),
    rung: null,
    reconstructionAvailable: false,
    modules,
    path: null,
    seed,
  });
  instances.push(...worldAssembly.instances);

  const orderedIslands = [...scene.islands].sort(
    (a, b) => a.creationOrdinal - b.creationOrdinal ||
      (a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0),
  );
  for (const island of orderedIslands) {
    const recipe = recipes.get(`region.rung-${island.rung}`);
    const assembly = instantiateRecipe({
      owner: Object.freeze({ kind: 'region', id: island.islandId }),
      recipe,
      root: Object.freeze({
        position: island.placement.position,
        yaw: island.placement.yaw,
        scale: Math.max(1, island.footprintRadiusLocal * island.placement.scale),
      }),
      rung: island.rung,
      reconstructionAvailable: options.availableReconstruction?.has(island.islandId) ?? false,
      modules,
      path: null,
      seed,
    });
    instances.push(...assembly.instances);
    diagnostics.push(...assembly.diagnostics);
  }

  const relationshipRecipe = recipes.get('relationship.confirmed');
  for (const trace of navWorld.traces) {
    const owner = relationshipOwner(trace.from, trace.to);
    const assembly = instantiateRecipe({
      owner,
      recipe: relationshipRecipe,
      root: Object.freeze({ position: trace.start, yaw: 0, scale: 1 }),
      rung: null,
      reconstructionAvailable: false,
      modules,
      path: Object.freeze({
        start: trace.start,
        end: trace.end,
        strength: trace.strength,
      }),
      seed,
    });
    instances.push(...assembly.instances);
  }

  instances.sort((a, b) => a.instanceId.localeCompare(b.instanceId));
  diagnostics.sort((a, b) => a.instanceId.localeCompare(b.instanceId));
  const navigation = navigationGraph(scene);
  const topologyDigest = fnv1a64(canonicalTopology(instances, navigation));
  const snapshot: WorldTopologySnapshot = Object.freeze({
    schemaVersion: WORLD_TOPOLOGY_SCHEMA_VERSION,
    worldId,
    snapshotId: `world-snapshot:${encode(worldId)}:${scene.layoutVersion}:${topologyDigest}`,
    persistenceStatus: 'draft',
    layoutVersion: scene.layoutVersion,
    inputStateVersion: scene.stateVersion,
    composerKey: ATLAS_COMPOSER_KEY,
    composerVersion: ATLAS_COMPOSER_VERSION,
    moduleCatalogVersion: modules.version,
    recipeCatalogVersion: recipes.version,
    seed,
    topologyDigest,
    instances: Object.freeze(instances),
    navigation,
    diagnostics: Object.freeze(diagnostics),
  });
  validateWorldTopology(snapshot, modules, recipes);
  return snapshot;
}
