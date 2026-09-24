import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { parseOwnedDistrict } from '@exulanica/atlas-core';
import { parseSocietyDistrict, SocietyDistrictClient } from '../src/society-district-api.js';

const baseJson=readFileSync(new URL('../../../../assets/owned-world/flatiron/flatiron-owned-district.json',import.meta.url),'utf8');
const interpretationJson=readFileSync(new URL('../../../../assets/owned-world/flatiron-interpretation-v1/district-interpretation.json',import.meta.url),'utf8');
const hash=(text:string)=>createHash('sha256').update(text).digest('hex');
const base=parseOwnedDistrict(JSON.parse(baseJson)), interpretation=JSON.parse(interpretationJson);
const scope={worldId:'atlas:default',versionId:'version',sourceSnapshotId:'source',placeId:'place',renderedBase:base};
const response=()=>({profile:'exulanica.society-district-view/v1',registration:{world_id:'atlas:default',version_id:'version',source_snapshot_id:'source',region_id:'registered-region',district_id:base.district_id,frame_name:interpretation.frame.name,translation_mm:[1000,0,-2000],yaw_microradians:0,scale_milli:1000},place_id:'place',base_artifact_sha256:hash(baseJson),interpretation_artifact_sha256:hash(interpretationJson),interpretation_document_sha256:interpretation.document_sha256,current_dependencies:Object.fromEntries(interpretation.source_dependencies.map((s:{sha256:string})=>[s.sha256,'available'])),base_json:baseJson,interpretation_json:interpretationJson});
vi.stubGlobal('crypto',webcrypto);

describe('authorized society district frame',()=>{
  it('verifies exact artifact bytes and semantic parser, retaining registered local translation and bounds',async()=>{
    const result=await parseSocietyDistrict(response(),scope);
    expect(result.placement).toEqual({versionId:'version',regionId:'registered-region',translationMm:[1000,0,-2000],boundsMm:base.bounds_cm.map(x=>x*10)});
    expect(result.interpretation.document_sha256).toBe(interpretation.document_sha256);
    expect(Object.isFrozen(result.placement.translationMm)).toBe(true);
  });
  it('authenticates the exact version route',async()=>{
    const fetch=vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(JSON.stringify(response())));
    await new SocietyDistrictClient({baseUrl:'https://api.test',token:'test',fetch}).read(scope);
    // Read in the scope's own world, which the registration it answers with must also name.
    expect(fetch).toHaveBeenCalledWith(`https://api.test/world/versions/version/society/district?world_id=${encodeURIComponent(scope.worldId)}`,expect.objectContaining({headers:{authorization:'Bearer test'}}));
  });
  it('rejects artifact tampering, including whitespace changes despite identical parsed objects',async()=>{
    for(const change of [{base_json:baseJson+'\n'},{interpretation_json:interpretationJson+' '},{base_artifact_sha256:'a'.repeat(64)}]) {
      await expect(parseSocietyDistrict({...response(),...change},scope)).rejects.toThrow(/digest/);
    }
  });
  it('rejects wrong scope, unsupported rotation/scale and invalid translation',async()=>{
    for(const change of [{version_id:'other'},{world_id:'other'},{source_snapshot_id:'other'},{yaw_microradians:1},{scale_milli:999},{translation_mm:[0,0,1.1]},{translation_mm:[0,0,1e10]}]) {
      const row=response();await expect(parseSocietyDistrict({...row,registration:{...row.registration,...change}},scope)).rejects.toThrow();
    }
    await expect(parseSocietyDistrict({...response(),place_id:'other'},scope)).rejects.toThrow(/scope/);
    await expect(parseSocietyDistrict({...response(),profile:'next-profile'},scope)).rejects.toThrow(/profile/);
  });
  it('rejects valid but different renderer data and mismatched semantic frame/document pins',async()=>{
    await expect(parseSocietyDistrict(response(),{...scope,renderedBase:{...base,name:'Other district'}})).rejects.toThrow(/rendered district/);
    const row=response();await expect(parseSocietyDistrict({...row,registration:{...row.registration,frame_name:'other'}},scope)).rejects.toThrow(/frame/);
    await expect(parseSocietyDistrict({...row,interpretation_document_sha256:'a'.repeat(64)},scope)).rejects.toThrow(/document/);
  });
  it('refuses unresolved, withdrawn, missing or extra dependencies',async()=>{
    for(const current of [{}, {...response().current_dependencies,extra:'available'},Object.fromEntries(Object.keys(response().current_dependencies).map(k=>[k,'withdrawn']))]) {
      await expect(parseSocietyDistrict({...response(),current_dependencies:current},scope)).rejects.toThrow(/dependencies/);
    }
  });
});
