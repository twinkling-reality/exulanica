// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { canonicalJson, resolveGroundMovement, terrainGroundPose, atlasVec3 } from '@exulanica/atlas-core';
import { sha256Hex } from '@exulanica/atlas-react/playcanvas';
import { loadSiteWorld } from '../src/composition/site-world.js';
import { holdTerrainVersion } from '../src/composition/terrain-occupancy.js';
import { WorldObjectsClient, parseVersion, type AlternateVersion } from '../src/world-objects-api.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';
const drawing = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-terrain.v3.json','utf8'));
const versionRaw = JSON.parse(readFileSync('packages/graph-client/test/fixtures/world-objects.json','utf8'));
const version = parseVersion({...versionRaw,world_id:drawing.world_id});
const entry = {entryId:'entry:terrain',worldId:drawing.world_id,sourceSnapshotId:version.sourceSnapshotId,
 authoredVersionId:version.versionId,authoredStateSha256:version.stateSha256,currentAuthoredStateSha256:version.stateSha256,
 authoredEditSeq:version.editSeq,currentAuthoredEditSeq:version.editSeq,availability:'available',generatedTerrain:{regionId:drawing.region_id,geometrySha256:drawing.terrain.geometry_sha256,
 contactSha256:drawing.terrain.contact_sha256,arrivalMm:drawing.arrival.position_mm,arrivalFacingMm:drawing.arrival.facing_mm}} as SavedWorldEntry;
const access={baseUrl:'https://terrain.test',token:'t'};
function proof(){return {profile:'exulanica.terrain-source-proof/v1',world_id:entry.worldId,version_id:entry.authoredVersionId,
 source_snapshot_id:entry.sourceSnapshotId,receipt_sha256:drawing.receipt_sha256,geometry_sha256:drawing.terrain.geometry_sha256,
 contact_sha256:drawing.terrain.contact_sha256,authored_state_sha256:entry.authoredStateSha256,status:'verified',reason:null};}
function fetcher(proofBody:unknown=proof()){
 return vi.fn(async(input:RequestInfo|URL)=>{
  const path=new URL(String(input)).pathname;
  if(path.endsWith('/terrain-contact'))return Response.json(proofBody);
  if(path.endsWith('/site'))return new Response(canonicalJson(drawing),{headers:{ETag:`"${sha256Hex(new TextEncoder().encode(canonicalJson(drawing)))}"`}});
  return new Response('',{status:404});
 });
}
afterEach(()=>vi.unstubAllGlobals());
it('loads the Python-emitted terrain drawing and gates walking on the current source proof',async()=>{
 let current:SavedWorldEntry|null=entry;const fetched=fetcher();vi.stubGlobal('fetch',fetched);
 const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>current))!;
 expect(world.mount.drawing.profile).toBe('exulanica.site-drawing/v3');const nav=world.mount.navigationWorld;
 expect(nav.terrain?.occupancy.status).toBe('verified');expect(world.mount.start.terrain).toBeDefined();
 const held=terrainGroundPose(nav,[1000,-2000])!;
 expect(resolveGroundMovement(nav,{current:held.position,desired:atlasVec3(1.5,0,-2),lastSafe:held.position,terrainState:held.state}).collided).toBe(false);
 const call=fetched.mock.calls.find(([url])=>String(url).includes('/terrain-contact'))!;
 expect(String(call[0])).toContain(`expected_state_sha256=${entry.authoredStateSha256}`);
 current={...entry,authoredStateSha256:'f'.repeat(64)};
 expect(nav.terrain?.occupancy.status).toBe('unavailable');
 const rejected=resolveGroundMovement(nav,{current:held.position,desired:atlasVec3(1.5,0,-2),lastSafe:held.position,terrainState:held.state});
 expect(rejected.terrainFailure).toBe('unbound_occupancy');expect(rejected.position).toEqual(held.position);
 current=entry;expect(nav.terrain?.occupancy.status).toBe('unavailable');
 const redressed=await world.relook({packId:null,manifestSha256:null,source:'address'});
 expect(redressed.mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');
 expect(fetched.mock.calls.filter(([url])=>String(url).includes('/terrain-contact'))).toHaveLength(1);
});
it('does not accept mismatched or unavailable proof and still mounts the admitted visible terrain',async()=>{
 for(const patch of [{world_id:'world:other'},{version_id:'other'},{source_snapshot_id:'other'},{receipt_sha256:'e'.repeat(64)},
  {geometry_sha256:'e'.repeat(64)},{contact_sha256:'e'.repeat(64)},{authored_state_sha256:'e'.repeat(64)},
  {status:'unavailable',reason:'authored_occupancy_unreconciled'}]){
  vi.stubGlobal('fetch',fetcher({...proof(),...patch}));
  const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>entry))!;
  expect(world.mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');expect(world.mount.start.terrain).toBeUndefined();
 }
 vi.stubGlobal('fetch',fetcher());const unobserved=(await loadSiteWorld(access,entry))!;
 expect(unobserved.mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');
});
it('revokes before an asynchronous version paint completes and cannot revive on old state',async()=>{
 const guard=holdTerrainVersion(entry);vi.stubGlobal('fetch',fetcher());
 const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>guard.current()?entry:null))!;
 const nav=world.mount.navigationWorld,held=terrainGroundPose(nav,[1000,-2000])!;
 let release!:()=>void;const pending=new Promise<void>(r=>{release=r;});let entered!:()=>void;const painting=new Promise<void>(r=>{entered=r;});
 const changed={...versionRaw,world_id:entry.worldId,state_sha256:'e'.repeat(64),edit_seq:version.editSeq+1};
 const client=new WorldObjectsClient({...access,worldId:entry.worldId,
  fetch:async()=>Response.json(changed),onVersionObserved:guard.observe,onVersionChange:async()=>{entered();await pending;}});
 const write=client.createVersion({title:'Changed',sourceSnapshotId:entry.sourceSnapshotId});await painting;
 expect(client.version()?.stateSha256).toBe('e'.repeat(64));expect(guard.current()).toBe(false);
 expect(resolveGroundMovement(nav,{current:held.position,desired:held.position,lastSafe:held.position,terrainState:held.state}).terrainFailure).toBe('unbound_occupancy');
 guard.observe(version);expect(guard.current()).toBe(false);release();await write;
});
it('revokes on a stale reconciliation read or invalidated source before yielding a version',async()=>{
 for(const patch of [{state_sha256:'e'.repeat(64)},{source_invalidated:true}]){
  const guard=holdTerrainVersion(entry),raw={...versionRaw,world_id:entry.worldId,...patch};
  const client=new WorldObjectsClient({...access,worldId:entry.worldId,fetch:async()=>Response.json(raw),onVersionObserved:guard.observe});
  await client.readVersion(version.versionId);expect(guard.current()).toBe(false);
 }
 const guard=holdTerrainVersion(entry),changed={...versionRaw,world_id:entry.worldId,state_sha256:'e'.repeat(64)};
 const client=new WorldObjectsClient({...access,worldId:entry.worldId,onVersionObserved:guard.observe,
  savedEntry:()=>({entryId:entry.entryId,revision:1,authoredVersionId:version.versionId,authoredStateSha256:version.stateSha256,authoredEditSeq:version.editSeq}),
  fetch:async(url)=>Response.json(String(url).includes('/world/assets')?[]:changed)});
 await expect(client.connect(version.versionId)).rejects.toThrow('changed elsewhere');expect(guard.current()).toBe(false);
});
it('compares world, source, version, state and source invalidation in the mount lifetime guard',()=>{
 for(const changed of [null,{...version,worldId:'other'},{...version,sourceSnapshotId:'other'},{...version,versionId:'other'},
  {...version,stateSha256:'e'.repeat(64)},{...version,editSeq:version.editSeq+2},{...version,sourceInvalidated:true}] as (AlternateVersion|null)[]){
  const guard=holdTerrainVersion(entry);guard.observe(version);expect(guard.current()).toBe(true);guard.observe(changed);expect(guard.current()).toBe(false);
  guard.observe(version);expect(guard.current()).toBe(false);
 }
});

it('revokes live terrain proof after a failed authoritative refresh or a saved-entry conflict',async()=>{
 for(const [status,code,write] of [[409,'invalidated_source_version',false],[404,'unknown_reference',false],[409,'stale_saved_world_entry',true],[409,'invalidated_source_version',true]] as const){
  const guard=holdTerrainVersion(entry);vi.stubGlobal('fetch',fetcher());
  const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>guard.current()?entry:null))!;
  const nav=world.mount.navigationWorld,held=terrainGroundPose(nav,[1000,-2000])!;
  const client=new WorldObjectsClient({...access,worldId:entry.worldId,onVersionObserved:guard.observe,
   fetch:async()=>Response.json({code,detail:'source unavailable'},{status})});
  if(write)await expect(client.place(version,{objectId:'object:terrain-test',assetSha256:'b'.repeat(64),regionId:'region:generated',
   transform:{xMm:1000,yMm:1250,zMm:-2000,yawMicroradians:0,scaleMilli:1000},originRole:'fictional',behaviour:null})).rejects.toThrow();
  else await expect(client.readVersion(version.versionId)).rejects.toThrow();
  expect(guard.current()).toBe(false);expect(resolveGroundMovement(nav,{current:held.position,desired:held.position,lastSafe:held.position,terrainState:held.state}).terrainFailure).toBe('unbound_occupancy');
 }
});
it('revokes when creating a version reports a withdrawn source',async()=>{
 const guard=holdTerrainVersion(entry);
 const client=new WorldObjectsClient({...access,worldId:entry.worldId,onVersionObserved:guard.observe,
  fetch:async()=>Response.json({code:'invalidated_source_version',detail:'withdrawn'},{status:409})});
 await expect(client.createVersion({title:'Requested',sourceSnapshotId:entry.sourceSnapshotId})).rejects.toThrow();
 expect(guard.current()).toBe(false);
});
