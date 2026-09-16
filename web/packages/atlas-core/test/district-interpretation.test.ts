import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseOwnedDistrict, ownedDistrictNavigation } from '../src/owned-district.js';
import { districtSegmentSupported } from '../src/district-geometry.js';
import { districtCanonicalJson, districtInterpretationAvailability, districtShortestRoute, parseDistrictInterpretation } from '../src/district-interpretation.js';

const baseBytes = readFileSync(new URL('../../../../assets/owned-world/flatiron/flatiron-owned-district.json', import.meta.url));
const base = parseOwnedDistrict(JSON.parse(baseBytes.toString()));
const raw = JSON.parse(readFileSync(new URL('../../../../assets/owned-world/flatiron-interpretation-v1/district-interpretation.json', import.meta.url), 'utf8'));
const sha = (text: string): string => createHash('sha256').update(text).digest('hex');
const verification = { baseArtifactSha256: createHash('sha256').update(baseBytes).digest('hex'), sha256: async (text: string) => sha(text) };
const parse = (value: unknown) => parseDistrictInterpretation(value, base, verification);
const resign = (doc: typeof raw) => { delete doc.document_sha256; doc.document_sha256 = sha(districtCanonicalJson(doc)); return doc; };

describe('source-bound district interpretation', () => {
  it('verifies the Python artifact digest, coordinate agreement and every route segment', async () => {
    const doc = await parse(raw);
    const current = Object.fromEntries(doc.source_dependencies.map(s => [s.sha256, 'available']));
    const nodes = new Map(doc.navigation.nodes.map(n => [n.node_id, n]));
    for (const edge of doc.navigation.edges) {
      const a = nodes.get(edge.from_node_id)!.position_mm; const b = nodes.get(edge.to_node_id)!.position_mm;
      expect(districtSegmentSupported(base, a, b)).toBe(true);
    }
    for (const target of doc.navigation.destinations) {
      const route = districtShortestRoute(doc, doc.navigation.destinations[0]!.node_id, target.node_id, current);
      expect(route?.at(-1)).toBe(target.node_id);
      const point = nodes.get(target.node_id)!.position_mm;
      expect(ownedDistrictNavigation(base).surface.sample(point[0] / 1000, point[1] / 1000)?.height).toBe(0);
    }
    const paths = doc.navigation.destinations.map(target => districtShortestRoute(doc, doc.navigation.destinations[0]!.node_id, target.node_id, current));
    // Independently computed by Python from the retained artifact and lexicographic route policy.
    expect(sha(districtCanonicalJson(paths))).toBe('0e06d22ffdbc3c44c4a5d1b0aa576adff0a1b1406be84e4fbba63bad93117817');
    expect(doc.navigation.destinations.some(d => d.subject_id.endsWith('doitt_id:507159'))).toBe(true);
    expect(Object.isFrozen(doc.subjects[0]!.recipe)).toBe(true);
  });
  it('fails closed for missing extension, unresolved, withdrawn and changed source bindings', async () => {
    const doc = await parse(raw); const start = doc.navigation.nodes[0]!.node_id;
    expect(districtInterpretationAvailability(null, {})).toEqual(['interpretation-unavailable']);
    expect(districtShortestRoute(doc, start, start, {})).toBeNull();
    for (const status of ['withdrawn', 'unavailable', 'binding_drift']) {
      const current = Object.fromEntries(doc.source_dependencies.map(s => [s.sha256, status]));
      expect(districtShortestRoute(doc, start, start, current)).toBeNull();
    }
    await expect(parseDistrictInterpretation(raw, base, {...verification, baseArtifactSha256: 'a'.repeat(64)})).rejects.toThrow(/base binding/);
  });
  it.each([
    (d: typeof raw) => { d.profile = 'new'; },
    (d: typeof raw) => { d.extra = true; },
    (d: typeof raw) => { d.seed = true; },
    (d: typeof raw) => { d.frame.origin_crs84_e7 = [0, 0]; },
    (d: typeof raw) => { d.navigation.nodes[0].position_mm = [0, 0]; },
    (d: typeof raw) => { d.navigation.edges[0].to_node_id = 'absent'; },
    (d: typeof raw) => { d.navigation.edges[0].length_mm = 1; },
    (d: typeof raw) => { d.navigation.destinations[0].duration_ticks = 99; },
    (d: typeof raw) => { d.navigation.destinations[0].affordance = 'enter'; },
    (d: typeof raw) => { d.subjects.push(d.subjects[0]); },
    (d: typeof raw) => { d.source_dependencies[0].sha256 = 'a'.repeat(64); },
    (d: typeof raw) => { d.subjects.find((s: {kind:string}) => s.kind === 'facade').epistemic_status = 'observation'; },
  ])('rejects resigned malformed input', async mutate => {
    const doc = JSON.parse(JSON.stringify(raw)); mutate(doc);
    await expect(parse(resign(doc))).rejects.toThrow();
  });
  it('checks whole-segment safety rather than only endpoints', async () => {
    const doc = await parse(raw);
    const pair = doc.navigation.nodes.flatMap(a => doc.navigation.nodes.map(b => [a,b] as const)).find(([a,b]) => a.node_id < b.node_id && !districtSegmentSupported(base, a.position_mm, b.position_mm))!;
    const changed = JSON.parse(JSON.stringify(raw));
    changed.navigation.edges[0].from_node_id = pair[0].node_id;
    changed.navigation.edges[0].to_node_id = pair[1].node_id;
    changed.navigation.edges[0].length_mm = Math.ceil(Math.hypot(pair[0].position_mm[0] - pair[1].position_mm[0], pair[0].position_mm[1] - pair[1].position_mm[1]));
    await expect(parse(resign(changed))).rejects.toThrow(/collision/);
  });
  it('retains holes and rejects malformed old geometry before navigation', () => {
    const old = JSON.parse(baseBytes.toString());
    old.sidewalks[0].polygons[0][0][0] = [0.5, 0];
    expect(() => parseOwnedDistrict(old)).toThrow();
    expect(base.sidewalks.some(s => s.polygons.some(p => p.length > 1))).toBe(true);
  });
  it('does not freeze caller input and protects against mutation while hashing', async () => {
    const value = JSON.parse(JSON.stringify(raw));
    const doc = await parseDistrictInterpretation(value, base, { ...verification, sha256: async text => {
      value.navigation.nodes[0].position_mm[0] = 999; return sha(text);
    }});
    expect(doc.navigation.nodes[0]!.position_mm[0]).not.toBe(999);
    expect(Object.isFrozen(value)).toBe(false);
  });
});

it.each(['wrong-layer', 'wrong-kind', 'missing-source', 'wrong-use', 'wrong-edge-subject', 'wrong-footprint', 'outside-envelope'])('rejects semantic cross-binding %s', async which => {
  const doc = JSON.parse(JSON.stringify(raw));
  const building = doc.subjects.find((s: {kind:string}) => s.kind === 'building');
  if (which === 'wrong-layer') {
    const source = doc.source_dependencies.find((s: {dataset_id:string}) => s.dataset_id === '52n9-sdep');
    Object.assign(building.source_refs[0], {dataset_id: source.dataset_id, sha256: source.sha256});
  } else if (which === 'wrong-kind') building.kind = 'sidewalk';
  else if (which === 'missing-source') doc.subjects = doc.subjects.filter((s: unknown) => s !== building);
  else if (which === 'wrong-use') doc.subjects.find((s: {kind:string}) => s.kind === 'facade').permitted_uses.push('collide');
  else if (which === 'wrong-edge-subject') doc.navigation.edges[0].subject_id = building.subject_id;
  else if (which === 'wrong-footprint') building.recipe.feature_id = doc.subjects.find((s: {kind:string}) => s.kind === 'sidewalk').subject_id;
  else doc.subjects.find((s: {kind:string}) => s.kind === 'walk-envelope').recipe.bounds_mm = [0,0,100,100];
  await expect(parse(resign(doc))).rejects.toThrow();
});
