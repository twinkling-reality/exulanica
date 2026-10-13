import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { canonicalStylePackBytes, readStylePackManifest, resolveStylePack, stylePackFamilies, StylePackRefusal, type LookFamily, type StylePackContext } from '../src/style-pack.js';
const cases = JSON.parse(readFileSync('../assets/style-packs/catalog-pin-cases.v1.json','utf8'));
const familiesOf = (families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>) => new Map(Object.entries(families).map(([key, value]) => [key, { fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille }]));
const context: StylePackContext = { families: familiesOf(cases.context.families), textureSets: new Set(cases.context.texture_sets), familyCatalogs: new Map(Object.entries(cases.context.family_catalogs).map(([version, value]) => { const catalog = value as { sha256: string; families: Parameters<typeof familiesOf>[0] }; return [Number(version), {sha256:catalog.sha256,families:familiesOf(catalog.families)}]; })) };
describe('shared Python/browser appearance catalog cases', () => {
 for(const test of cases.cases) it(test.name,()=>{
  if(test.expect.sha256!==undefined) { expect(createHash('sha256').update(canonicalStylePackBytes(readStylePackManifest(test.manifest,context))).digest('hex')).toBe(test.expect.sha256); return; }
  try { readStylePackManifest(test.manifest,context); throw Error('accepted refused case'); } catch(error) { expect(error).toBeInstanceOf(StylePackRefusal); expect({reason:(error as StylePackRefusal).reason,path:(error as StylePackRefusal).path}).toEqual({reason:test.expect.refusal,path:test.expect.path}); }
 });
 it('keeps unpinned bytes and legacy fitting while selecting only the known pinned catalog',()=>{
  const legacyCases=JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json','utf8'));
  const raw=legacyCases.cases.find((c:{name:string})=>c.name==='a complete pack with no base').manifest;
  const old=readStylePackManifest(raw,context); expect(old).not.toHaveProperty('look_family_catalog'); expect(stylePackFamilies(old,context).get('roof')!.fit).toBe('surface');
  const pin=context.familyCatalogs!.get(2)!;
  const next=readStylePackManifest({...raw,look_family_catalog:{version:2,sha256:pin.sha256}},context); expect(stylePackFamilies(next,context).get('roof')!.fit).toBe('contain');
  const child={...next,pack_id:'original.child',base:{pack_id:old.pack_id,version:old.version,manifest_sha256:'a'.repeat(64)}};
  try {resolveStylePack([child,old]);throw Error('accepted mixed chain');}catch(error){expect(error).toBeInstanceOf(StylePackRefusal);expect((error as StylePackRefusal).path).toBe('base');}
 });
});
