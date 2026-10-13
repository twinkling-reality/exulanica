// @vitest-environment happy-dom
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import {afterEach,expect,it,vi} from 'vitest';
import {canonicalJson} from '@exulanica/atlas-core';
import {sha256Hex} from '@exulanica/atlas-react/playcanvas';
import {loadSiteWorld} from '../src/composition/site-world.js';
import {loadTerrainDressing} from '../src/composition/terrain-dressing.js';
import {parseSiteDrawing} from '@exulanica/atlas-react/generated-site';
import type {SavedWorldEntry} from '../src/world-entry-api.js';
const raw=JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-terrain.v4.json','utf8'));
const bytes=()=>Uint8Array.from(readFileSync('packages/atlas-react/test/fixtures/terrain-component.glb')).buffer;
const entry={entryId:'entry',worldId:raw.world_id,sourceSnapshotId:'source',authoredVersionId:'version',authoredStateSha256:'a'.repeat(64),currentAuthoredStateSha256:'a'.repeat(64),authoredEditSeq:0,currentAuthoredEditSeq:0,availability:'available',generatedTerrain:{regionId:raw.region_id,geometrySha256:raw.terrain.geometry_sha256,contactSha256:raw.terrain.contact_sha256,arrivalMm:raw.arrival.position_mm,arrivalFacingMm:raw.arrival.facing_mm}} as SavedWorldEntry;
const access={baseUrl:'https://terrain.test',token:'t'};
const proof=()=>({profile:'exulanica.terrain-source-proof/v2',world_id:entry.worldId,version_id:entry.authoredVersionId,source_snapshot_id:entry.sourceSnapshotId,receipt_sha256:raw.receipt_sha256,geometry_sha256:raw.terrain.geometry_sha256,contact_sha256:raw.terrain.contact_sha256,dressing_sha256:raw.terrain.dressing_sha256,authored_state_sha256:entry.authoredStateSha256,status:'verified',reason:null});
function fetcher(p:unknown=proof(),content=bytes(),available=true){return vi.fn(async(input:RequestInfo|URL)=>{
 const path=new URL(String(input)).pathname;
 if(path.endsWith('/site'))return new Response(canonicalJson(raw),{headers:{ETag:`"${sha256Hex(new TextEncoder().encode(canonicalJson(raw)))}"`}});
 if(path.endsWith('/terrain-contact'))return Response.json(p);
 if(path.endsWith('/bytes'))return new Response(content);
 if(path.includes('/assets/'))return Response.json({asset_key:'fixture.component.v1',content_sha256:raw.terrain.dressing.instances[0].source.content_sha256,media_type:'model/gltf-binary',byte_size:bytes().byteLength,availability:available?'available':'unavailable'});
 return new Response('',{status:404});
});}
afterEach(()=>vi.unstubAllGlobals());
it('binds proof2 to the attachment readiness gate shared across lighting replacements',async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',fetcher());let current:SavedWorldEntry|null=entry;
 const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>current))!,nav=world.mount.navigationWorld;
 expect(nav.terrain?.occupancy.status).toBe('unavailable');const first=world.mount.dressingReadiness!.begin();first.ready();expect(nav.terrain?.occupancy.status).toBe('verified');
 const relook=await world.relook({packId:null,manifestSha256:null,source:'address'});const next=relook.mount.dressingReadiness!.begin();first.dispose();next.ready();
 await vi.waitFor(()=>expect(nav.terrain?.occupancy.status).toBe('verified'));
 current={...entry,generatedTerrain:{...entry.generatedTerrain!,dressingSha256:'f'.repeat(64)}};
 expect(nav.terrain?.occupancy.status).toBe('unavailable');next.dispose();
});
it('refuses stale proof/profile/dressing and unavailable bytes without a usable bare terrain mount',async()=>{
 vi.stubGlobal('crypto',webcrypto);
 for(const patch of [{profile:'exulanica.terrain-source-proof/v1'},{dressing_sha256:'f'.repeat(64)},{status:'unavailable',reason:'source_unavailable'}]){
  vi.stubGlobal('fetch',fetcher({...proof(),...patch}));const world=(await loadSiteWorld(access,entry,undefined,undefined,'',null,()=>entry))!;
  expect(world.mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');
 }
 vi.stubGlobal('fetch',fetcher(proof(),bytes(),false));await expect(loadSiteWorld(access,entry,undefined,undefined,'',null,()=>entry)).rejects.toThrow(/component/);
 const bad=bytes();new Uint8Array(bad)[bad.byteLength-1] = 1;vi.stubGlobal('fetch',fetcher(proof(),bad));await expect(loadSiteWorld(access,entry,undefined,undefined,'',null,()=>entry)).rejects.toThrow();
});
it('refuses an oversized byte stream using the existing source byte count',async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',fetcher(proof(),new ArrayBuffer(bytes().byteLength+1)));
 const d=parseSiteDrawing(raw);if(d.profile!=='exulanica.site-drawing/v4')throw Error('dressed');
 await expect(loadTerrainDressing(access,d.dressing)).rejects.toThrow(/stream/);
});
