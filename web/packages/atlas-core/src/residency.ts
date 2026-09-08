import type { IslandId, NeighborhoodId } from './ids.js';
import type { NeighborhoodIndex } from './neighborhood.js';
import type { RepresentationTier, TierState } from './tiers.js';

export type ResidencyStage = 'stub' | 'proxy' | 'coarse' | 'full';

export const RESIDENCY_STAGE_ORDER: readonly ResidencyStage[] = Object.freeze([
  'stub',
  'proxy',
  'coarse',
  'full',
]);
export const DEFAULT_RESIDENCY_GRACE_REVISIONS = 3;

const stageRank = (stage: ResidencyStage): number => RESIDENCY_STAGE_ORDER.indexOf(stage);

export interface ResidencyCost {
  /** Lightweight index/sigil state. Required to be zero; it is not a streamed visual asset. */
  readonly stub: number;
  readonly proxy: number;
  readonly coarse: number;
  readonly full: number;
}

export interface ResidencyAsset {
  readonly islandId: IslandId;
  /** Total cost at each stage, not an incremental delta. Must be monotonic. */
  readonly cost: ResidencyCost;
}

export interface ResidencyBudget {
  readonly maxCost: number;
  readonly graceRevisions?: number;
  /** Measurement-driven ceiling. A pressure controller may lower it; device sniffing may not. */
  readonly maxStage?: ResidencyStage;
}

export interface ResidencyDemand {
  readonly islandId: IslandId;
  readonly desired: ResidencyStage;
  /** Higher wins. Used only among demands; never interpreted as epistemic importance. */
  readonly priority: number;
  /** A direct-navigation target is pinned until arrival or cancellation. */
  readonly pin?: boolean;
  /**
   * The visitor is standing in this region. A ceiling bounds what may be LOADED next; the region
   * under the visitor is already loaded, so stubbing it empties the world they are looking at and
   * saves nothing that is still being paid for. Exempt from `maxStage`, and floored at the
   * cheapest drawn stage when even that does not fit the scaled budget.
   */
  readonly occupied?: boolean;
}

export interface ResidencyRequest {
  readonly requestId: string;
  readonly islandId: IslandId;
  readonly from: ResidencyStage;
  readonly to: ResidencyStage;
}

export interface ResidencyEntry {
  readonly islandId: IslandId;
  readonly current: ResidencyStage;
  readonly pending: ResidencyRequest | null;
  readonly lastDemandedRevision: number;
}

export interface ResidencyState {
  readonly revision: number;
  readonly entries: ReadonlyMap<IslandId, ResidencyEntry>;
}

export const EMPTY_RESIDENCY_STATE: ResidencyState = Object.freeze({
  revision: 0,
  entries: new Map(),
});

export type ResidencyAction =
  | { readonly type: 'load'; readonly request: ResidencyRequest }
  | { readonly type: 'cancel'; readonly requestId: string; readonly islandId: IslandId }
  | {
      readonly type: 'release';
      readonly islandId: IslandId;
      readonly from: ResidencyStage;
      readonly to: ResidencyStage;
    };

export interface ResidencyPlan {
  readonly state: ResidencyState;
  readonly actions: readonly ResidencyAction[];
  readonly allocated: ReadonlyMap<IslandId, ResidencyStage>;
  readonly deferred: readonly ResidencyDemand[];
  readonly reservedCost: number;
}

function validateCatalog(catalog: readonly ResidencyAsset[]): ReadonlyMap<IslandId, ResidencyAsset> {
  const byId = new Map<IslandId, ResidencyAsset>();
  for (const asset of catalog) {
    if (byId.has(asset.islandId)) throw new TypeError(`duplicate residency asset: ${asset.islandId}`);
    const values = RESIDENCY_STAGE_ORDER.map((stage) => asset.cost[stage]);
    if (values.some((value) => !Number.isFinite(value) || value < 0)) {
      throw new TypeError(`residency costs must be finite and non-negative: ${asset.islandId}`);
    }
    if (asset.cost.stub !== 0) {
      throw new TypeError(`stub cost must be zero: ${asset.islandId}`);
    }
    for (let i = 1; i < values.length; i += 1) {
      if (values[i]! < values[i - 1]!) {
        throw new TypeError(`residency costs must be monotonic: ${asset.islandId}`);
      }
    }
    byId.set(asset.islandId, asset);
  }
  return byId;
}

function combineDemands(demands: readonly ResidencyDemand[]): ReadonlyMap<IslandId, ResidencyDemand> {
  const combined = new Map<IslandId, ResidencyDemand>();
  for (const demand of demands) {
    if (!Number.isFinite(demand.priority)) throw new TypeError('residency priority must be finite');
    const prior = combined.get(demand.islandId);
    if (prior === undefined) {
      combined.set(demand.islandId, Object.freeze({ ...demand }));
      continue;
    }
    // A pin is an independent constraint, not a competing demand. Merge every dimension so a
    // low-detail navigation pin cannot accidentally erase a full-detail neighborhood demand.
    const desired =
      stageRank(demand.desired) > stageRank(prior.desired) ? demand.desired : prior.desired;
    combined.set(demand.islandId, Object.freeze({
      islandId: demand.islandId,
      desired,
      priority: Math.max(prior.priority, demand.priority),
      ...(prior.pin === true || demand.pin === true ? { pin: true } : {}),
      ...(prior.occupied === true || demand.occupied === true ? { occupied: true } : {}),
    }));
  }
  return combined;
}

/**
 * Pure, budgeted planner. Loading is explicit and cancellable: a plan reserves the target stage,
 * but `current` changes only when `completeResidencyRequest` acknowledges the request.
 */
export function planResidency(
  catalog: readonly ResidencyAsset[],
  demands: readonly ResidencyDemand[],
  budget: ResidencyBudget,
  previous: ResidencyState = EMPTY_RESIDENCY_STATE,
): ResidencyPlan {
  if (!Number.isFinite(budget.maxCost) || budget.maxCost < 0) {
    throw new RangeError('residency maxCost must be finite and non-negative');
  }
  const grace = budget.graceRevisions ?? DEFAULT_RESIDENCY_GRACE_REVISIONS;
  if (!Number.isSafeInteger(grace) || grace < 0) {
    throw new RangeError('residency graceRevisions must be a non-negative safe integer');
  }
  const maxStage = budget.maxStage ?? 'full';
  if (stageRank(maxStage) < 0) throw new RangeError(`unknown residency stage: ${String(maxStage)}`);
  const assets = validateCatalog(catalog);
  const requested = combineDemands(demands);
  for (const id of requested.keys()) {
    if (!assets.has(id)) throw new TypeError(`residency demand has no catalog asset: ${id}`);
  }
  const revision = previous.revision + 1;
  const allocated = new Map<IslandId, ResidencyStage>();
  for (const id of assets.keys()) allocated.set(id, 'stub');
  let reservedCost = 0;

  const ranked = [...requested.values()].sort(
    (a, b) =>
      Number(b.pin === true) - Number(a.pin === true) ||
      b.priority - a.priority ||
      stageRank(b.desired) - stageRank(a.desired) ||
      (a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0),
  );
  const deferred: ResidencyDemand[] = [];
  for (const demand of ranked) {
    const asset = assets.get(demand.islandId)!;
    let granted: ResidencyStage = 'stub';
    const occupied = demand.occupied === true && stageRank(demand.desired) > 0;
    const desiredRank = occupied
      ? stageRank(demand.desired)
      : Math.min(stageRank(demand.desired), stageRank(maxStage));
    for (let rank = desiredRank; rank > 0; rank -= 1) {
      const candidate = RESIDENCY_STAGE_ORDER[rank]!;
      if (reservedCost + asset.cost[candidate] <= budget.maxCost) {
        granted = candidate;
        break;
      }
    }
    // A region whose cheapest drawn stage costs more than the scaled budget would otherwise fall
    // to a stub. For the region the visitor occupies that is the failure, not the saving: it is
    // what emptied the world thirteen seconds after arrival while the status panel still said the
    // trained reconstruction was showing. Overshoot the ceiling for that one region and let every
    // other region absorb the pressure.
    if (granted === 'stub' && occupied) granted = RESIDENCY_STAGE_ORDER[1]!;
    allocated.set(demand.islandId, granted);
    reservedCost += asset.cost[granted];
    if (granted !== demand.desired) deferred.push(demand);
  }

  // Retention candidates come after current demands. Hysteresis prevents churn but never evicts a
  // newly requested target just to keep an old visual warm.
  const retained = [...assets.values()].filter((asset) => {
    if (requested.has(asset.islandId)) return false;
    const prior = previous.entries.get(asset.islandId);
    return (
      prior !== undefined &&
      stageRank(prior.current) > 0 &&
      revision - prior.lastDemandedRevision <= grace
    );
  }).sort((a, b) => {
    const pa = previous.entries.get(a.islandId)!;
    const pb = previous.entries.get(b.islandId)!;
    return (
      pb.lastDemandedRevision - pa.lastDemandedRevision ||
      (a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0)
    );
  });
  for (const asset of retained) {
    const current = previous.entries.get(asset.islandId)!.current;
    const cost = asset.cost[current];
    if (reservedCost + cost > budget.maxCost) continue;
    allocated.set(asset.islandId, current);
    reservedCost += cost;
  }

  const actions: ResidencyAction[] = [];
  const entries = new Map<IslandId, ResidencyEntry>();
  for (const asset of assets.values()) {
    const prior = previous.entries.get(asset.islandId) ?? Object.freeze({
      islandId: asset.islandId,
      current: 'stub' as const,
      pending: null,
      lastDemandedRevision: 0,
    });
    const target = allocated.get(asset.islandId)!;
    let pending = prior.pending;
    if (pending !== null && pending.to !== target) {
      actions.push(Object.freeze({
        type: 'cancel' as const,
        requestId: pending.requestId,
        islandId: asset.islandId,
      }));
      pending = null;
    }
    let current = prior.current;
    if (stageRank(target) < stageRank(current)) {
      actions.push(Object.freeze({
        type: 'release' as const,
        islandId: asset.islandId,
        from: current,
        to: target,
      }));
      current = target;
      pending = null;
    } else if (stageRank(target) > stageRank(current) && pending === null) {
      pending = Object.freeze({
        requestId: `residency:${revision}:${asset.islandId}:${target}`,
        islandId: asset.islandId,
        from: current,
        to: target,
      });
      actions.push(Object.freeze({ type: 'load' as const, request: pending }));
    }
    entries.set(asset.islandId, Object.freeze({
      islandId: asset.islandId,
      current,
      pending,
      lastDemandedRevision: requested.has(asset.islandId)
        ? revision
        : prior.lastDemandedRevision,
    }));
  }
  return Object.freeze({
    state: Object.freeze({ revision, entries }),
    actions: Object.freeze(actions),
    allocated,
    deferred: Object.freeze(deferred),
    reservedCost,
  });
}

/** A loader acknowledgement. Stale completions are ignored after cancellation. */
export function completeResidencyRequest(
  state: ResidencyState,
  requestId: string,
  ok: boolean,
): ResidencyState {
  const entries = new Map(state.entries);
  for (const [id, entry] of entries) {
    if (entry.pending?.requestId !== requestId) continue;
    entries.set(id, Object.freeze({
      ...entry,
      current: ok ? entry.pending.to : entry.current,
      pending: null,
    }));
    return Object.freeze({ revision: state.revision, entries });
  }
  return state;
}

export interface ResidencyView {
  readonly map: boolean;
  readonly activeNeighborhood: NeighborhoodId | null;
  readonly tier: TierState;
  readonly target: IslandId | null;
  /** The region the visitor is standing in, from the spatial phase. Null between regions. */
  readonly occupied?: IslandId | null;
}

const stageForTier = (tier: RepresentationTier): ResidencyStage =>
  tier === 3 ? 'full' : tier === 2 ? 'coarse' : tier === 1 ? 'proxy' : 'stub';

/** Derive loader demands from spatial state. Map uses lightweight sigils; ground keeps one halo. */
export function residencyDemandsForView(
  index: NeighborhoodIndex,
  view: ResidencyView,
): readonly ResidencyDemand[] {
  if (view.map) return Object.freeze([]);
  const demands = new Map<IslandId, ResidencyDemand>();
  const active =
    view.activeNeighborhood === null ? undefined : index.byId.get(view.activeNeighborhood);
  if (active !== undefined) {
    for (const id of active.islandIds) {
      const tier = view.tier.tier.get(id) ?? 0;
      demands.set(id, Object.freeze({ islandId: id, desired: stageForTier(tier), priority: 200 + tier }));
    }
    for (const adjacentId of active.adjacent) {
      for (const id of index.byId.get(adjacentId)?.islandIds ?? []) {
        if (!demands.has(id)) {
          demands.set(id, Object.freeze({ islandId: id, desired: 'proxy', priority: 50 }));
        }
      }
    }
  }
  // Only a region the index knows: planResidency rejects a demand with no catalog asset, and this
  // runs inside the render loop, where a throw costs the frame.
  const occupied = view.occupied ?? null;
  if (occupied !== null && index.neighborhoodOf.has(occupied)) {
    const prior = demands.get(occupied);
    const tier = view.tier.tier.get(occupied) ?? 0;
    demands.set(occupied, Object.freeze({
      islandId: occupied,
      desired: prior?.desired ?? stageForTier(tier),
      priority: prior?.priority ?? 200 + tier,
      ...(prior?.pin === true ? { pin: true } : {}),
      occupied: true,
    }));
  }
  if (view.target !== null) {
    const prior = demands.get(view.target);
    demands.set(view.target, Object.freeze({
      islandId: view.target,
      desired:
        prior !== undefined && stageRank(prior.desired) > stageRank('proxy')
          ? prior.desired
          : 'proxy',
      priority: 10_000,
      pin: true,
      ...(prior?.occupied === true ? { occupied: true } : {}),
    }));
  }
  return Object.freeze([...demands.values()]);
}
