import { canonicalJson } from './style-pack.js';
/** Explicit actor support, in the canonical network's east/south millimetres. */
export interface SupportState {
  readonly networkSha256: string;
  readonly surfaceId: string;
  readonly connectionId: string | null;
}
type Point = readonly [
  number,
  number
];
type Rect = readonly [
  number,
  number,
  number,
  number
];
export interface SupportSurface {
  readonly surface_id: string;
  readonly rect_mm: Rect;
  readonly support_z_mm: number;
}
interface SupportNode {
  readonly node_id: string;
  readonly surface_id: string;
  readonly position_mm: Point;
}
interface SupportConnection {
  readonly connection_id: string;
  readonly from_node_id: string;
  readonly to_node_id: string;
  readonly kind: 'walk' | 'step';
}
export interface SupportNetworkDocument {
  readonly profile: 'exulanica.support-network/v1';
  readonly network_id: string;
  readonly source: {
    readonly world_id: string;
    readonly geometry_profile: string;
    readonly geometry_sha256: string;
  };
  readonly frame: {
    readonly name: string;
    readonly axis_order: readonly string[];
    readonly horizontal_unit: string;
    readonly vertical_unit: string;
    readonly datum: string;
  };
  readonly actor: {
    readonly radius_mm: number;
    readonly height_mm: number;
    readonly maximum_step_mm: number;
  };
  readonly surfaces: readonly SupportSurface[];
  readonly solids: readonly {
    readonly solid_id: string;
    readonly box_mm: readonly [
      number,
      number,
      number,
      number,
      number,
      number
    ];
  }[];
  readonly nodes: readonly SupportNode[];
  readonly connections: readonly SupportConnection[];
  readonly entry_node_id: string;
  readonly document_sha256: string;
}
export class SupportNavigationError extends Error {
  readonly code = 'support_network_invalid';
  constructor(readonly where: string, detail: string) { super(`${where}: ${detail}`); }
}
const require = (okay: boolean, where: string, detail: string): void => { if (!okay)
  throw new SupportNavigationError(where, detail); };
const object = (raw: unknown, fields: string, where: string): Record<string, unknown> => {
  require(raw !== null && typeof raw === 'object' && !Array.isArray(raw), where, 'is an object');
  const row = raw as Record<string, unknown>;
  require(Object.keys(row).sort().join(' ') === fields.split(' ').sort().join(' '), where, 'states exactly its contract fields');
  return row;
};
const whole = (raw: unknown, low: number, high: number, where: string): number => {
  require(typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= low && raw <= high, where, 'is a bounded integer');
  return raw as number;
};
const identity = (raw: unknown, where: string): string => { require(typeof raw === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_:./-]{0,159}$/.test(raw), where, 'is a bounded identity'); return raw as string; };
const sha = (raw: unknown, where: string): string => { require(typeof raw === 'string' && /^[0-9a-f]{64}$/.test(raw), where, 'is a lowercase SHA-256'); return raw as string; };
function figures(raw: unknown, count: number, where: string): number[] {
  require(Array.isArray(raw) && raw.length === count, where, 'has its stated dimensions');
  return (raw as unknown[]).map(value => whole(value, -10000000, 10000000, where));
}
function rows(raw: unknown, key: string, max: number, minimum: number, fields: string): Record<string, unknown>[] {
  require(Array.isArray(raw) && raw.length >= minimum && raw.length <= max, key, 'is a bounded list');
  const list = (raw as unknown[]).map(value => object(value, fields, key));
  const ids = list.map(value => identity(value[key], key));
  require(new Set(ids).size === ids.length && ids.join('\n') === [...ids].sort().join('\n'), key, 'identities are unique and sorted');
  return list;
}
function overlaps(a: Rect, b: Rect): boolean { return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]; }
function covered(rect: Rect, supports: readonly Rect[]): boolean {
  const cuts = [...new Set([rect[0], rect[2], ...supports.flatMap(r => [r[0], r[2]]).filter(x => rect[0] < x && x < rect[2])])].sort((a, b) => a - b);
  for (let i = 0; i < cuts.length - 1; i++) {
    const left = cuts[i]!, right = cuts[i + 1]!;
    const intervals = supports.filter(r => r[0] <= left && right <= r[2]).map(r => [r[1], r[3]] as const).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    let reached = rect[1];
    for (const [low, high] of intervals) {
      if (low > reached)
        break;
      reached = Math.max(reached, high);
    }
    if (reached < rect[3])
      return false;
  }
  return true;
}
function clear(document: SupportNetworkDocument, rect: Rect, low: number, high: number, ignore: readonly string[] = []): void {
  for (const solid of document.solids) {
    const [x0, y0, z0, x1, y1, z1] = solid.box_mm;
    require(!(overlaps(rect, [x0, y0, x1, y1]) && low < z1 && z0 < high + document.actor.height_mm), 'solids', 'actor footprint/headroom intersects a declared solid');
  }
  for (const surface of document.surfaces)
    require(!(!ignore.includes(surface.surface_id)
      && low < surface.support_z_mm && surface.support_z_mm < high + document.actor.height_mm && overlaps(rect, surface.rect_mm)), 'surfaces', 'another support intrudes into actor headroom');
}
/** Pure queries and swept movement. No speculative query can select or mutate an actor's level. */
export class SupportNavigation {
  readonly entry: SupportState;
  readonly surfaces: ReadonlyMap<string, SupportSurface>;
  readonly nodes: ReadonlyMap<string, SupportNode>;
  readonly connections: ReadonlyMap<string, SupportConnection>;
  constructor(readonly document: SupportNetworkDocument, entrySurfaceId: string) {
    this.surfaces = new Map(document.surfaces.map(s => [s.surface_id, s]));
    this.nodes = new Map(document.nodes.map(n => [n.node_id, n]));
    this.connections = new Map(document.connections.map(c => [c.connection_id, c]));
    require(this.surfaces.has(entrySurfaceId), 'entry_surface_id', 'names a surface');
    this.entry = Object.freeze({ networkSha256: document.document_sha256, surfaceId: entrySurfaceId, connectionId: null });
  }
  private footprint(point: Point): Rect { const r = this.document.actor.radius_mm; return [point[0] - r, point[1] - r, point[0] + r, point[1] + r]; }
  supportAt(surfaceId: string, point: Point): number {
    const surface = this.surfaces.get(surfaceId);
    require(surface !== undefined, 'surface_id', 'names an admitted surface');
    require(covered(this.footprint(point), [surface!.rect_mm]), 'position_mm', 'whole footprint is supported');
    clear(this.document, this.footprint(point), surface!.support_z_mm, surface!.support_z_mm);
    return surface!.support_z_mm;
  }
  motionOnSurface(surfaceId: string, from: Point, to: Point): number {
    const height = this.supportAt(surfaceId, from);
    this.supportAt(surfaceId, to);
    clear(this.document, this.swept(from, to), height, height);
    return height;
  }
  private swept(from: Point, to: Point): Rect {
    const r = this.document.actor.radius_mm;
    return [Math.min(from[0], to[0]) - r, Math.min(from[1], to[1]) - r, Math.max(from[0], to[0]) + r, Math.max(from[1], to[1]) + r];
  }
  connectionAt(connectionId: string, fromSurfaceId: string, point: Point): {
    readonly surfaceId: string;
    readonly heightMm: number;
  } {
    const edge = this.connections.get(connectionId);
    require(edge !== undefined, 'connection_id', 'names an admitted connection');
    const a = this.nodes.get(edge!.from_node_id)!, b = this.nodes.get(edge!.to_node_id)!;
    require(fromSurfaceId === a.surface_id || fromSurfaceId === b.surface_id, 'from_surface_id', 'is an endpoint’s surface');
    const axis = a.position_mm[0] !== b.position_mm[0] ? 0 : 1, transverse = 1 - axis;
    require(Math.min(a.position_mm[axis]!, b.position_mm[axis]!) <= point[axis]! && point[axis]! <= Math.max(a.position_mm[axis]!, b.position_mm[axis]!), 'position_mm', 'lies in the connection’s travel span');
    const sa = this.surfaces.get(a.surface_id)!, sb = this.surfaces.get(b.surface_id)!, r = this.document.actor.radius_mm;
    require(Math.max(sa.rect_mm[transverse]!, sb.rect_mm[transverse]!) + r <= point[transverse]!
      && point[transverse]! <= Math.min(sa.rect_mm[transverse + 2]!, sb.rect_mm[transverse + 2]!) - r, 'position_mm', 'whole footprint fits the shared portal');
    require(covered(this.footprint(point), [sa.rect_mm, sb.rect_mm]), 'position_mm', 'straddling footprint has continuous support');
    clear(this.document, this.footprint(point), Math.min(sa.support_z_mm, sb.support_z_mm), Math.max(sa.support_z_mm, sb.support_z_mm), [sa.surface_id, sb.surface_id]);
    let current = this.surfaces.get(fromSurfaceId)!, target = current === sa ? sb : sa;
    const contains = (s: SupportSurface) => s.rect_mm[0] <= point[0] && point[0] <= s.rect_mm[2] && s.rect_mm[1] <= point[1] && point[1] <= s.rect_mm[3];
    if ((target.support_z_mm > current.support_z_mm && contains(target)) || !contains(current))
      current = target;
    return Object.freeze({ surfaceId: current.surface_id, heightMm: current.support_z_mm });
  }
  at(state: SupportState, point: Point): number {
    require(state.networkSha256 === this.document.document_sha256, 'state', 'belongs to this exact network');
    return state.connectionId === null ? this.supportAt(state.surfaceId, point) : this.connectionAt(state.connectionId, state.surfaceId, point).heightMm;
  }
  private connectionMotion(id: string, state: SupportState, from: Point, to: Point): {
    state: SupportState;
    heightMm: number;
  } {
    this.connectionAt(id, state.surfaceId, from);
    const end = this.connectionAt(id, state.surfaceId, to), edge = this.connections.get(id)!;
    const a = this.surfaces.get(this.nodes.get(edge.from_node_id)!.surface_id)!, b = this.surfaces.get(this.nodes.get(edge.to_node_id)!.surface_id)!;
    require(covered(this.swept(from, to), [a.rect_mm, b.rect_mm]), 'position_mm', 'swept footprint has continuous support');
    clear(this.document, this.swept(from, to), Math.min(a.support_z_mm, b.support_z_mm), Math.max(a.support_z_mm, b.support_z_mm), [a.surface_id, b.surface_id]);
    let connectionId: string | null = id;
    try {
      this.supportAt(end.surfaceId, to);
      connectionId = null;
    }
    catch (error) {
      if (!(error instanceof SupportNavigationError))
        throw error;
    }
    return { state: Object.freeze({ networkSha256: this.document.document_sha256, surfaceId: end.surfaceId, connectionId }), heightMm: end.heightMm };
  }
  move(initial: SupportState, from: Point, to: Point): {
    readonly state: SupportState;
    readonly heightMm: number;
  } {
    this.at(initial, from);
    const count = Math.max(1, Math.ceil(Math.hypot(to[0] - from[0], to[1] - from[1]) / 50));
    require(count <= 2048, 'position_mm', 'swept movement is bounded');
    let state = initial, previous = from, heightMm = this.at(initial, from);
    for (let i = 1; i <= count; i++) {
      const point: Point = [from[0] + (to[0] - from[0]) * i / count, from[1] + (to[1] - from[1]) * i / count];
      let accepted: {
        state: SupportState;
        heightMm: number;
      } | null = null;
      if (state.connectionId !== null)
        try {
          accepted = this.connectionMotion(state.connectionId, state, previous, point);
        }
        catch (error) {
          if (!(error instanceof SupportNavigationError))
            throw error;
        }
      if (accepted === null)
        try {
          accepted = { state: Object.freeze({ networkSha256: this.document.document_sha256, surfaceId: state.surfaceId, connectionId: null }), heightMm: this.motionOnSurface(state.surfaceId, previous, point) };
        }
        catch (error) {
          if (!(error instanceof SupportNavigationError))
            throw error;
        }
      if (accepted === null)
        for (const edge of this.document.connections) {
          if (edge.kind !== 'step' || ![this.nodes.get(edge.from_node_id)!.surface_id, this.nodes.get(edge.to_node_id)!.surface_id].includes(state.surfaceId))
            continue;
          try {
            accepted = this.connectionMotion(edge.connection_id, state, previous, point);
            break;
          }
          catch (error) {
            if (!(error instanceof SupportNavigationError))
              throw error;
          }
        }
      require(accepted !== null, 'position_mm', 'no accepted surface or explicit connection');
      state = accepted!.state;
      heightMm = accepted!.heightMm;
      previous = point;
    }
    return Object.freeze({ state, heightMm });
  }
}
/** Same closed integer declaration and geometry gates as the canonical server reader. */
export function readSupportNavigation(raw: unknown, worldId: string, entrySurface: string, digest: (bytes: Uint8Array) => string): SupportNavigation {
  const row = object(raw, 'profile network_id source frame actor surfaces solids nodes connections entry_node_id document_sha256', '');
  require(row['profile'] === 'exulanica.support-network/v1', 'profile', 'is the support-network profile');
  identity(row['network_id'], 'network_id');
  const source = object(row['source'], 'world_id geometry_profile geometry_sha256', 'source');
  require(identity(source['world_id'], 'source.world_id') === worldId, 'source', 'matches the saved world');
  identity(source['geometry_profile'], 'source.geometry_profile');
  sha(source['geometry_sha256'], 'source.geometry_sha256');
  const frame = object(row['frame'], 'name axis_order horizontal_unit vertical_unit datum', 'frame');
  identity(frame['name'], 'frame.name');
  identity(frame['datum'], 'frame.datum');
  require(canonicalJson(frame['axis_order']) === '["east","south"]' && frame['horizontal_unit'] === 'millimetre' && frame['vertical_unit'] === 'millimetre', 'frame', 'is east/south millimetres');
  const actor = object(row['actor'], 'radius_mm height_mm maximum_step_mm', 'actor');
  whole(actor['radius_mm'], 1, 50000, 'actor.radius_mm');
  whole(actor['height_mm'], 1, 40000, 'actor.height_mm');
  whole(actor['maximum_step_mm'], 0, 180, 'actor.maximum_step_mm');
  for (const surface of rows(row['surfaces'], 'surface_id', 32, 1, 'surface_id rect_mm support_z_mm')) {
    const r = figures(surface['rect_mm'], 4, 'surfaces.rect_mm');
    require(r[0]! < r[2]! && r[1]! < r[3]!, 'surfaces.rect_mm', 'has positive extent');
    whole(surface['support_z_mm'], -10000000, 10000000, 'surfaces.support_z_mm');
  }
  for (const solid of rows(row['solids'], 'solid_id', 128, 0, 'solid_id box_mm')) {
    const b = figures(solid['box_mm'], 6, 'solids.box_mm');
    require(b[0]! < b[3]! && b[1]! < b[4]! && b[2]! < b[5]!, 'solids.box_mm', 'has positive volume');
  }
  const document = JSON.parse(canonicalJson(raw)) as SupportNetworkDocument;
  const freezeData = (value: unknown): void => {
    if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value))
        freezeData(child);
      Object.freeze(value);
    }
  };
  freezeData(document);
  const nodes = rows(row['nodes'], 'node_id', 512, 1, 'node_id surface_id position_mm');
  const edges = rows(row['connections'], 'connection_id', 1024, 0, 'connection_id from_node_id to_node_id kind');
  const nav = new SupportNavigation(document, entrySurface);
  for (const node of nodes) {
    identity(node['surface_id'], 'nodes.surface_id');
    figures(node['position_mm'], 2, 'nodes.position_mm');
    nav.supportAt(node['surface_id'] as string, node['position_mm'] as unknown as Point);
  }
  require(nav.nodes.has(identity(row['entry_node_id'], 'entry_node_id')), 'entry_node_id', 'names a node');
  require(nav.nodes.get(document.entry_node_id)!.surface_id === entrySurface, 'entry_surface_id', 'matches the network entry');
  const pairs = new Set<string>();
  for (const edge of edges) {
    const a = nav.nodes.get(identity(edge['from_node_id'], 'connections.from_node_id')), b = nav.nodes.get(identity(edge['to_node_id'], 'connections.to_node_id'));
    require(a !== undefined && b !== undefined && a !== b, 'connections', 'names distinct admitted nodes');
    const pair = [a!.node_id, b!.node_id].sort().join('\n');
    require(!pairs.has(pair), 'connections', 'does not repeat a node pair');
    pairs.add(pair);
    require((a!.position_mm[0] === b!.position_mm[0]) !== (a!.position_mm[1] === b!.position_mm[1]), 'connections', 'is nonzero and axis-aligned');
    const sa = nav.surfaces.get(a!.surface_id)!, sb = nav.surfaces.get(b!.surface_id)!;
    require(edge['kind'] === 'walk' ? sa.surface_id === sb.surface_id : edge['kind'] === 'step' && sa.surface_id !== sb.surface_id && Math.abs(sa.support_z_mm - sb.support_z_mm) <= document.actor.maximum_step_mm, 'connections', 'declares a valid walk or bounded step');
    const r = document.actor.radius_mm, swept: Rect = [Math.min(a!.position_mm[0], b!.position_mm[0]) - r, Math.min(a!.position_mm[1], b!.position_mm[1]) - r, Math.max(a!.position_mm[0], b!.position_mm[0]) + r, Math.max(a!.position_mm[1], b!.position_mm[1]) + r];
    require(covered(swept, [sa.rect_mm, sb.rect_mm]), 'connections', 'whole swept footprint has continuous support');
    clear(document, swept, Math.min(sa.support_z_mm, sb.support_z_mm), Math.max(sa.support_z_mm, sb.support_z_mm), [sa.surface_id, sb.surface_id]);
  }
  const { document_sha256: claimed, ...unsigned } = document;
  require(sha(claimed, 'document_sha256') === digest(new TextEncoder().encode(canonicalJson(unsigned))), 'document_sha256', 'matches the canonical network');
  return nav;
}
