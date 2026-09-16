import type { OwnedDistrict } from './owned-district.js';
import { districtSegmentSupported, type DistrictPoint } from './district-geometry.js';

export type DistrictRecipe =
  | { readonly kind: 'source-footprint'; readonly feature_id: string }
  | { readonly kind: 'facade-grid'; readonly feature_id: string; readonly height_mm: number;
      readonly bay_width_mm: number; readonly floor_height_mm: number; readonly window_width_mm: number;
      readonly window_height_mm: number; readonly sill_height_mm: number; readonly recess_mm: number; readonly material_index: number }
  | { readonly kind: 'roof-parapet'; readonly feature_id: string; readonly height_mm: number; readonly parapet_height_mm: number }
  | { readonly kind: 'flat-ground'; readonly height_mm: 0 }
  | { readonly kind: 'residual-ground'; readonly excluded_subject_ids: readonly string[] }
  | { readonly kind: 'walk-envelope'; readonly bounds_mm: readonly [number, number, number, number]; readonly grid_spacing_mm: number }
  | { readonly kind: 'entrance-marker'; readonly building_subject_id: string; readonly position_mm: DistrictPoint;
      readonly polygon_index: number; readonly facade_edge_index: number; readonly width_mm: number; readonly height_mm: number }
  | { readonly kind: 'rest-pad'; readonly position_mm: DistrictPoint; readonly radius_mm: number; readonly height_mm: 0 };
export interface DistrictSubject {
  readonly subject_id: string;
  readonly kind: 'building' | 'sidewalk' | 'facade' | 'roof' | 'ground' | 'road-completion' | 'walk-envelope' | 'entrance' | 'civic-object';
  readonly epistemic_status: 'observation' | 'interpretation' | 'generated' | 'authored';
  readonly source_refs: readonly { readonly dataset_id: string; readonly sha256: string; readonly feature_id: string }[];
  readonly uncertainty: string;
  readonly permitted_uses: readonly ('render' | 'select' | 'collide' | 'navigate' | 'simulate' | 'modify')[];
  readonly recipe: DistrictRecipe;
}
export interface DistrictFrame {
  readonly name: 'flatiron-local-mm'; readonly origin_crs84_e7: DistrictPoint;
  readonly axis_order: readonly ['east', 'south']; readonly horizontal_unit: 'millimetre';
  readonly altitude_reference: 'authored-flat-ground';
}
export interface DistrictNavigation {
  readonly profile: 'bounded-sidewalk-graph/v1'; readonly clearance_mm: 450;
  readonly nodes: readonly { readonly node_id: string; readonly subject_id: string; readonly position_mm: DistrictPoint }[];
  readonly edges: readonly { readonly edge_id: string; readonly from_node_id: string; readonly to_node_id: string; readonly length_mm: number; readonly subject_id: string }[];
  readonly destinations: readonly { readonly destination_id: string; readonly subject_id: string; readonly node_id: string; readonly affordance: 'visit' | 'rest'; readonly duration_ticks: number }[];
  readonly unavailable_reason: 'no-supported-connected-sidewalk' | null;
}
export interface DistrictInterpretation {
  readonly profile: 'exulanica.district-interpretation/v1'; readonly district_id: string;
  readonly base_artifact_sha256: string; readonly document_sha256: string;
  readonly producer: 'flatiron-interpretation/1'; readonly seed: number; readonly frame: DistrictFrame;
  readonly bounds_mm: readonly [number, number, number, number];
  readonly source_dependencies: readonly { readonly dataset_id: string; readonly provider_revision: string;
    readonly sha256: string; readonly source_url: string; readonly attribution: string;
    readonly operation_rights: Readonly<Record<string, boolean>> }[];
  readonly subjects: readonly DistrictSubject[];
  readonly navigation: DistrictNavigation; readonly unsupported: readonly string[];
}

type Obj = Record<string, unknown>;
function requireCondition(value: unknown, message: string): asserts value {
  if (!value) throw new Error(`District interpretation: ${message}`);
}
function object(v: unknown, keys: string): Obj {
  requireCondition(v !== null && typeof v === 'object' && !Array.isArray(v), 'expected object');
  const result = v as Obj;
  requireCondition(Object.keys(result).sort().join(',') === keys.split(' ').sort().join(','), 'unexpected or missing fields');
  return result;
}
function array(v: unknown, max = 10000): unknown[] {
  requireCondition(Array.isArray(v) && v.length <= max, 'expected bounded array'); return v;
}
function integer(v: unknown, min = -1e9, max = 1e9): asserts v is number {
  requireCondition(Number.isSafeInteger(v) && (v as number) >= min && (v as number) <= max, 'invalid integer');
}
function identity(v: unknown): asserts v is string {
  requireCondition(typeof v === 'string' && v.length > 0 && v.length <= 256, 'invalid identity');
}
function tuple(v: unknown, length: number): void { requireCondition(array(v).length === length, 'invalid tuple'); (v as unknown[]).forEach(x => integer(x)); }
function digest(v: unknown): void { requireCondition(typeof v === 'string' && /^[0-9a-f]{64}$/.test(v), 'invalid digest'); }
function sortedIds(values: unknown[], field: string): void {
  const ids = values.map(v => { const id = (v as Obj)[field]; identity(id); return id; });
  requireCondition(ids.every((v, i) => i === 0 || ids[i - 1]! < v), 'identities must be unique and sorted');
}
/** Canonical no-float JSON. SHA-256 is injected by the host; core has no DOM/Node dependency. */
export function districtCanonicalJson(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') { requireCondition(Number.isSafeInteger(value), 'noninteger digest input'); return String(value); }
  if (Array.isArray(value)) return `[${value.map(districtCanonicalJson).join(',')}]`;
  requireCondition(value !== null && typeof value === 'object', 'invalid canonical value');
  return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => `${JSON.stringify(k)}:${districtCanonicalJson(v)}`).join(',')}}`;
}
function freeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value;
}
const recipeFields: Record<string, string> = {
  'source-footprint': 'kind feature_id',
  'facade-grid': 'kind feature_id height_mm bay_width_mm floor_height_mm window_width_mm window_height_mm sill_height_mm recess_mm material_index',
  'roof-parapet': 'kind feature_id height_mm parapet_height_mm',
  'flat-ground': 'kind height_mm', 'residual-ground': 'kind excluded_subject_ids',
  'walk-envelope': 'kind bounds_mm grid_spacing_mm',
  'entrance-marker': 'kind building_subject_id position_mm polygon_index facade_edge_index width_mm height_mm',
  'rest-pad': 'kind position_mm radius_mm height_mm',
};

/** Host must hash exact original base bytes, not a reserialized object. No unverified fast path. */
export async function parseDistrictInterpretation(value: unknown, base: OwnedDistrict, verification: {
  readonly baseArtifactSha256: string;
  readonly sha256: (canonicalUtf8Text: string) => Promise<string>;
}): Promise<DistrictInterpretation> {
  // Copy before awaiting the host hash so callers cannot mutate validated state during verification.
  const copied: unknown = JSON.parse(districtCanonicalJson(value));
  const doc = object(copied, 'profile district_id base_artifact_sha256 producer seed frame bounds_mm source_dependencies subjects navigation unsupported document_sha256');
  requireCondition(doc.profile === 'exulanica.district-interpretation/v1' && doc.producer === 'flatiron-interpretation/1', 'unsupported profile/producer');
  identity(doc.district_id); integer(doc.seed); digest(doc.base_artifact_sha256); digest(doc.document_sha256);
  requireCondition(doc.district_id === base.district_id && doc.seed === base.seed && doc.base_artifact_sha256 === verification.baseArtifactSha256, 'base binding mismatch');
  const frame = object(doc.frame, 'name origin_crs84_e7 axis_order horizontal_unit altitude_reference');
  tuple(frame.origin_crs84_e7, 2);
  requireCondition(frame.name === 'flatiron-local-mm' && JSON.stringify(frame.axis_order) === '["east","south"]' && frame.horizontal_unit === 'millimetre' && frame.altitude_reference === 'authored-flat-ground', 'coordinate frame mismatch');
  requireCondition(base.frame !== undefined && JSON.stringify(frame.origin_crs84_e7) === JSON.stringify(base.frame.origin_crs84_e7), 'unresolved base frame');
  tuple(doc.bounds_mm, 4);
  requireCondition(JSON.stringify(doc.bounds_mm) === JSON.stringify(base.bounds_cm.map(v => v * 10)), 'coordinate bounds mismatch');
  const dependencies = array(doc.source_dependencies, 2);
  requireCondition(dependencies.length === 2, 'missing source dependencies');
  sortedIds(dependencies, 'dataset_id');
  for (const input of dependencies) {
    const dep = object(input, 'dataset_id provider_revision sha256 source_url attribution operation_rights');
    identity(dep.dataset_id); identity(dep.provider_revision); digest(dep.sha256);
    const source = base.source_records.find(s => s.dataset_id === dep.dataset_id);
    requireCondition(source && source.sha256 === dep.sha256 && source.provider_revision === dep.provider_revision && source.attribution === dep.attribution && source.source_url === dep.source_url && districtCanonicalJson(source.operation_rights) === districtCanonicalJson(dep.operation_rights), 'source dependency drift');
  }
  const features = new Map([...base.buildings, ...base.sidewalks].map(f => [f.id, f]));
  const featureDatasets = new Map([...base.buildings.map(b => [b.id, '5zhs-2jue'] as const), ...base.sidewalks.map(s => [s.id, '52n9-sdep'] as const)]);
  const buildingIds = new Set(base.buildings.map(b => b.id));
  const semantics: Record<string, readonly [string, string, readonly string[]]> = {
    'facade-grid': ['facade', 'generated', ['render','select']],
    'roof-parapet': ['roof', 'generated', ['render','select']],
    'flat-ground': ['ground', 'authored', ['render','select','collide']],
    'residual-ground': ['road-completion', 'generated', ['render','select']],
    'walk-envelope': ['walk-envelope', 'interpretation', ['render','select','navigate','simulate']],
    'entrance-marker': ['entrance', 'generated', ['render','select','simulate']],
    'rest-pad': ['civic-object', 'generated', ['render','select','simulate']],
  };
  const subjects = array(doc.subjects, 5000); sortedIds(subjects, 'subject_id');
  const subjectIds = new Map<string, DistrictSubject>();
  for (const input of subjects) {
    const sub = object(input, 'subject_id kind epistemic_status source_refs uncertainty permitted_uses recipe');
    identity(sub.subject_id);
    requireCondition(['building','sidewalk','facade','roof','ground','road-completion','walk-envelope','entrance','civic-object'].includes(String(sub.kind)), 'unknown subject kind');
    requireCondition(['observation','interpretation','generated','authored'].includes(String(sub.epistemic_status)) && typeof sub.uncertainty === 'string', 'invalid epistemic status');
    for (const use of array(sub.permitted_uses)) requireCondition(['render','select','collide','navigate','simulate','modify'].includes(String(use)), 'unsupported use');
    const refs = array(sub.source_refs);
    for (const inputRef of refs) {
      const ref = object(inputRef, 'dataset_id sha256 feature_id');
      requireCondition(dependencies.some(d => (d as Obj).dataset_id === ref.dataset_id && (d as Obj).sha256 === ref.sha256) && featureDatasets.get(String(ref.feature_id)) === ref.dataset_id, 'unresolved subject dependency');
    }
    const kind = (sub.recipe as Obj | null)?.kind;
    requireCondition(typeof kind === 'string' && Object.hasOwn(recipeFields, kind), 'unknown recipe');
    const recipe = object(sub.recipe, recipeFields[kind]!);
    for (const [key, v] of Object.entries(recipe)) {
      if (key.endsWith('_mm') && key !== 'position_mm' && key !== 'bounds_mm') integer(v, key === 'height_mm' && ['flat-ground','rest-pad'].includes(kind) ? 0 : 1, 1e6);
    }
    if ('position_mm' in recipe) tuple(recipe.position_mm, 2);
    if ('bounds_mm' in recipe) tuple(recipe.bounds_mm, 4);
    if ('material_index' in recipe) integer(recipe.material_index, 0, 6);
    if (kind === 'flat-ground' || kind === 'rest-pad') requireCondition(recipe.height_mm === 0, 'nonflat ground');
    const expected = kind === 'source-footprint'
      ? [buildingIds.has(String(recipe.feature_id)) ? 'building' : 'sidewalk', 'observation', buildingIds.has(String(recipe.feature_id)) ? ['render','select','collide'] : ['render','select']]
      : semantics[kind]!;
    requireCondition(sub.kind === expected[0] && sub.epistemic_status === expected[1] && JSON.stringify(sub.permitted_uses) === JSON.stringify(expected[2]), 'recipe kind, observation status or permitted uses mismatch');
    if (kind === 'source-footprint') requireCondition(sub.subject_id === recipe.feature_id, 'footprint subject identity mismatch');
    if (kind === 'facade-grid' || kind === 'roof-parapet') requireCondition(buildingIds.has(String(recipe.feature_id)), 'building recipe references nonbuilding');
    const expectedRefs = 'feature_id' in recipe ? [recipe.feature_id] : kind === 'entrance-marker' ? [recipe.building_subject_id] : [];
    requireCondition(JSON.stringify(refs.map(r => (r as Obj).feature_id)) === JSON.stringify(expectedRefs), 'recipe source references mismatch');
    if (kind === 'walk-envelope') {
      const [w,n,e,s] = recipe.bounds_mm as number[]; const [bw,bn,be,bs] = doc.bounds_mm as number[];
      requireCondition(bw! <= w! && w! < e! && e! <= be! && bn! <= n! && n! < s! && s! <= bs!, 'invalid navigation envelope bounds');
    }
    if ('feature_id' in recipe) requireCondition(features.has(String(recipe.feature_id)) && refs.some(r => (r as Obj).feature_id === recipe.feature_id), 'unresolved recipe feature');
    if (kind === 'residual-ground') requireCondition(JSON.stringify(array(recipe.excluded_subject_ids)) === JSON.stringify([...features.keys()].sort()), 'road exclusion mismatch');
    if (kind === 'entrance-marker') {
      integer(recipe.polygon_index, 0); integer(recipe.facade_edge_index, 0);
      const building = base.buildings.find(b => b.id === recipe.building_subject_id);
      requireCondition(building && recipe.polygon_index < building.polygons.length && recipe.facade_edge_index < building.polygons[recipe.polygon_index]![0]!.length - 1, 'unresolved entrance facade');
    }
    requireCondition(sub.epistemic_status !== 'observation' || kind === 'source-footprint', 'completion cannot claim observation');
    subjectIds.set(sub.subject_id, sub as unknown as DistrictSubject);
  }
  requireCondition([...features.keys()].every(id => subjectIds.has(id)), 'missing source subjects');
  const nav = object(doc.navigation, 'profile clearance_mm nodes edges destinations unavailable_reason');
  requireCondition(nav.profile === 'bounded-sidewalk-graph/v1' && nav.clearance_mm === 450, 'unsupported navigation');
  const nodes = array(nav.nodes); const edges = array(nav.edges, 40000); const destinations = array(nav.destinations);
  sortedIds(nodes, 'node_id'); sortedIds(edges, 'edge_id'); sortedIds(destinations, 'destination_id');
  const positions = new Map<string, DistrictPoint>();
  for (const input of nodes) {
    const node = object(input, 'node_id subject_id position_mm'); identity(node.node_id); tuple(node.position_mm, 2);
    requireCondition(subjectIds.get(String(node.subject_id))?.permitted_uses.includes('navigate'), 'unresolved navigation subject');
    const point = node.position_mm as unknown as DistrictPoint;
    const envelope = subjectIds.get(String(node.subject_id))!.recipe;
    requireCondition(envelope.kind === 'walk-envelope', 'invalid navigation envelope');
    const [w,n,e,s] = envelope.bounds_mm;
    requireCondition(point[0] >= w && point[0] <= e && point[1] >= n && point[1] <= s, 'node outside navigation envelope');
    requireCondition(districtSegmentSupported(base, point, point), 'unsupported navigation node');
    positions.set(node.node_id, point);
  }
  for (const input of edges) {
    const edge = object(input, 'edge_id from_node_id to_node_id length_mm subject_id'); integer(edge.length_mm, 1, 1e6);
    const a = positions.get(String(edge.from_node_id)); const b = positions.get(String(edge.to_node_id));
    requireCondition(a && b && edge.from_node_id !== edge.to_node_id && subjectIds.has(String(edge.subject_id)), 'unresolved edge dependency');
    requireCondition(nodes.filter(n => (n as Obj).node_id === edge.from_node_id || (n as Obj).node_id === edge.to_node_id).every(n => (n as Obj).subject_id === edge.subject_id), 'edge subject disagreement');
    requireCondition(Math.ceil(Math.hypot(a[0] - b[0], a[1] - b[1])) === edge.length_mm && districtSegmentSupported(base, a, b), 'route collision or length mismatch');
  }
  for (const input of destinations) {
    const target = object(input, 'destination_id subject_id node_id affordance duration_ticks');
    const subject = subjectIds.get(String(target.subject_id)); const point = positions.get(String(target.node_id));
    requireCondition(subject && point && subject.permitted_uses.includes('simulate') && 'position_mm' in subject.recipe && JSON.stringify(subject.recipe.position_mm) === JSON.stringify(point), 'destination coordinate disagreement');
    requireCondition((target.affordance === 'rest' && subject.recipe.kind === 'rest-pad' && target.duration_ticks === 3) || (target.affordance === 'visit' && subject.recipe.kind === 'entrance-marker' && target.duration_ticks === 1), 'unsupported affordance');
  }
  requireCondition(nodes.length ? nav.unavailable_reason === null : nav.unavailable_reason === 'no-supported-connected-sidewalk' && edges.length === 0 && destinations.length === 0, 'availability disagreement');
  array(doc.unsupported).forEach(v => requireCondition(typeof v === 'string', 'invalid unsupported declaration'));
  const { document_sha256: expected, ...payload } = doc;
  requireCondition(await verification.sha256(districtCanonicalJson(payload)) === expected, 'interpretation digest mismatch');
  return freeze(doc as unknown as DistrictInterpretation);
}

/** Recheck on every materialization; absent extension and absent current rights remain unavailable. */
export function districtInterpretationAvailability(document: DistrictInterpretation | null, current: Readonly<Record<string, string>>): readonly string[] {
  if (!document) return ['interpretation-unavailable'];
  return document.source_dependencies.filter(s => current[s.sha256] !== 'available').map(s => `${s.sha256}:${current[s.sha256] ?? 'unresolved'}`);
}

export function districtShortestRoute(document: DistrictInterpretation, start: string, end: string, current: Readonly<Record<string, string>>): readonly string[] | null {
  if (districtInterpretationAvailability(document, current).length || document.navigation.unavailable_reason) return null;
  const graph = new Map(document.navigation.nodes.map(n => [n.node_id, [] as [string, number][]]));
  if (!graph.has(start) || !graph.has(end)) return null;
  for (const e of document.navigation.edges) { graph.get(e.from_node_id)!.push([e.to_node_id, e.length_mm]); graph.get(e.to_node_id)!.push([e.from_node_id, e.length_mm]); }
  const pending = [{ distance: 0, path: [start], node: start }]; const done = new Set<string>();
  while (pending.length) {
    pending.sort((a,b) => a.distance - b.distance || (a.path.join('\0') < b.path.join('\0') ? -1 : 1));
    const item = pending.shift()!;
    if (done.has(item.node)) continue;
    done.add(item.node);
    if (item.node === end) return item.path;
    for (const [node, cost] of graph.get(item.node)!) if (!done.has(node)) pending.push({ distance: item.distance + cost, path: [...item.path, node], node });
  }
  return null;
}
