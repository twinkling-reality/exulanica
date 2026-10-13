// @vitest-environment happy-dom
import {readFileSync} from 'node:fs';
import {expect, it, vi} from 'vitest';
import * as pc from 'playcanvas';
import {FirstPersonControls} from '../src/playcanvas/controls.js';
import {canonicalJson, sha256Hex} from '../src/playcanvas/character/digest.js';
import {parseSiteDrawing} from '../src/playcanvas/generated-site/site-drawing.js';
import {attachTerrainDressing, prepareTerrainDressing, readTerrainDressing, createDressingReadiness} from '../src/playcanvas/generated-site/terrain-dressing.js';
import {siteMount} from '../src/playcanvas/generated-site/site-mount.js';
const raw = () => JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-terrain.v4.json','utf8'));
const bytes = () => Uint8Array.from(readFileSync('packages/atlas-react/test/fixtures/terrain-component.glb')).buffer;
const hash = (value:unknown) => sha256Hex(new TextEncoder().encode(canonicalJson(value)));
function drawing() {const d=parseSiteDrawing(raw());if(d.profile!=='exulanica.site-drawing/v4')throw Error('dressed');return d;}
function host() {
 const canvas=document.createElement('canvas'),device=new pc.NullGraphicsDevice(canvas),app=new pc.AppBase(canvas),options=new pc.AppOptions();
 options.graphicsDevice=device;options.componentSystems=[pc.RenderComponentSystem,pc.CameraComponentSystem,pc.LightComponentSystem];options.resourceHandlers=[pc.ContainerHandler,pc.TextureHandler];app.init(options);
 const camera=new pc.Entity('camera');camera.addComponent('camera');app.root.addChild(camera);const environmentRoot=new pc.Entity('environment');app.root.addChild(environmentRoot);
 return {app,camera,environmentRoot};
}
it('requires the successor composer and exact nested dressing digest, preserving earlier readers',()=>{
 const d=drawing();expect(d.dressing.instances[0]?.instance_id).toBe('wall');
 for(const mutate of [(v:ReturnType<typeof raw>)=>{v.composer.version=3;},(v:ReturnType<typeof raw>)=>{v.terrain.dressing.instances[0].position_mm[1]++;},(v:ReturnType<typeof raw>)=>{v.dressing=v.terrain.dressing;}]){const v=raw();mutate(v);expect(()=>parseSiteDrawing(v)).toThrow();}
 const legacy=JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-terrain.v3.json','utf8'));
 expect(parseSiteDrawing(legacy)).not.toHaveProperty('dressing');
});
it('checks every source key, deduplicates bytes/textures, and charges geometry per instance',async()=>{
 const value=raw().terrain.dressing;value.instances.push({...value.instances[0],instance_id:'wall2',source:{...value.instances[0].source,asset_key:'fixture.alias.v1'}});
 const d=readTerrainDressing(value,hash(value));const read=vi.fn(async()=>bytes());
 const result=await prepareTerrainDressing(d,read,new AbortController().signal);
 expect(read).toHaveBeenCalledTimes(2);expect(result.files.size).toBe(1);expect(result.transferredBytes).toBe(bytes().byteLength);expect(result.draws).toBe(2);
 await expect(prepareTerrainDressing(d,async()=>{const b=bytes();new Uint8Array(b)[b.byteLength-1] = 1;return b;},new AbortController().signal)).rejects.toThrow(/digest/);
});
it('decodes the actual pinned scene, preserves material/ancestor transforms and picks source mesh identity',async()=>{
 const wire=raw();wire.terrain.dressing.instances[0].quarter_turns=1;wire.terrain.dressing.instances[0].scale_per_mille=2000;wire.terrain.dressing_sha256=hash(wire.terrain.dressing);
 const d=parseSiteDrawing(wire);if(d.profile!=='exulanica.site-drawing/v4')throw Error('dressed');
 const prepared=await prepareTerrainDressing(d.dressing,async()=>bytes(),new AbortController().signal),h=host();
 const a=attachTerrainDressing(h.app,h.environmentRoot,prepared,()=>true);await a.ready;
 expect(a.surfaces).toHaveLength(1);const surface=a.surfaces[0]!;
 expect(surface).toMatchObject({instanceId:'wall',assetKey:'fixture.component.v1',nodeIndex:1,meshIndex:0,primitiveIndex:0});
 expect(surface.meshInstance.node.getPosition().y).toBeCloseTo(5.25);expect((surface.meshInstance.material as pc.StandardMaterial).diffuse.b).toBeCloseTo(.6 ** (1 / 2.2));
 expect(a.pick([2,5.25,-3],[-1,0,0])?.surface).toBe(surface);
 a.dispose();expect(h.environmentRoot.children).toHaveLength(0);expect(a.pick([2,5.25,-3],[-1,0,0])).toBeNull();h.app.destroy();
});
it('disposes a container that completes after withdrawal and never creates selectable geometry',async()=>{
 const prepared=await prepareTerrainDressing(drawing().dressing,async()=>bytes(),new AbortController().signal),h=host();let release!:(a:pc.Asset)=>void;let current=true;
 const asset=new pc.Asset('late','container');const unload=vi.spyOn(asset,'unload');h.app.assets.add(asset);
 const a=attachTerrainDressing(h.app,h.environmentRoot,prepared,()=>current,async()=>new Promise(resolve=>{release=resolve;}));
 current=false;release(asset);await expect(a.ready).rejects.toThrow(/superseded/);expect(unload).toHaveBeenCalledOnce();expect(h.app.assets.get(asset.id)).toBeUndefined();expect(h.environmentRoot.children).toHaveLength(0);h.app.destroy();
});
it('withholds walking until complete decode and revokes it with source or attachment replacement',async()=>{
 const d=drawing(),prepared=await prepareTerrainDressing(d.dressing,async()=>bytes(),new AbortController().signal),h=host();let available=true;
 const readiness=createDressingReadiness(),occupancy=()=>available?{status:'verified' as const,worldId:d.worldId,versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:d.receiptSha256,geometrySha256:d.terrain.geometry.sha256,contactSha256:d.terrain.sha256,authoredStateSha256:'a'.repeat(64)}:{status:'unavailable' as const};
 const mount=siteMount(d,{servedBytes:1,preparedDressing:prepared,dressingReadiness:readiness,terrainOccupancy:occupancy});
 expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');const attached=mount.attach(h);
 await vi.waitFor(()=>expect(mount.navigationWorld.terrain?.occupancy.status).toBe('verified'));
 expect(attached.sourceCurrent?.()).toBe(true);
 expect(attached.pickSource?.([1,3.25,-2],[0,0,-1])?.surface.assetKey).toBe('fixture.component.v1');
 available=false;expect(attached.sourceCurrent?.()).toBe(false);expect(attached.pickSource?.([1,3.25,-2],[0,0,-1])).toBeNull();h.app.fire('update',.01);expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');expect(h.environmentRoot.children.every(n=>!n.enabled)).toBe(true);
 attached.dispose();h.app.destroy();
 const first=readiness.begin(),second=readiness.begin();first.ready();expect(readiness.read()).toBe(false);second.ready();first.dispose();expect(readiness.read()).toBe(true);second.dispose();expect(readiness.read()).toBe(false);
});
it('revokes readiness synchronously outside the source-frame error envelope and cannot revive by moving back',async()=>{
 const d=drawing(),prepared=await prepareTerrainDressing(d.dressing,async()=>bytes(),new AbortController().signal),h=host();
 h.environmentRoot.setLocalPosition(1024,0,0);
 const mount=siteMount(d,{servedBytes:1,preparedDressing:prepared,terrainOccupancy:{status:'verified',worldId:d.worldId,versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:d.receiptSha256,geometrySha256:d.terrain.geometry.sha256,contactSha256:d.terrain.sha256,authoredStateSha256:'a'.repeat(64)}});
 const attached=mount.attach(h);await vi.waitFor(()=>expect(mount.navigationWorld.terrain?.occupancy.status).toBe('verified'));
 h.environmentRoot.setLocalPosition(1025,0,0);expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');
 h.environmentRoot.setLocalPosition(0,0,0);expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');
 attached.dispose();h.app.destroy();
});
it('rejects unsupported source syntax even with a recomputed dressing digest',()=>{
 for(const mutate of [(v:ReturnType<typeof raw>)=>{v.instances[0].source.kind='url';},(v:ReturnType<typeof raw>)=>{v.instances[0].source.url='https://elsewhere.test/mesh.glb';},(v:ReturnType<typeof raw>)=>{v.instances[0].position_mm[0]=.5;},(v:ReturnType<typeof raw>)=>{v.instances[0].scale_per_mille=4001;},(v:ReturnType<typeof raw>)=>{v.instances.push(v.instances[0]);}]){
  const value=raw().terrain.dressing;mutate(value);expect(()=>readTerrainDressing(value,hash(value))).toThrow();
 }
});
it('refuses navigation immediately after an outer or source ancestor frame changes',async()=>{
 for(const target of ['outer','source'] as const){
  const d=drawing(),prepared=await prepareTerrainDressing(d.dressing,async()=>bytes(),new AbortController().signal),h=host();
  const mount=siteMount(d,{servedBytes:1,preparedDressing:prepared,terrainOccupancy:{status:'verified',worldId:d.worldId,versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:d.receiptSha256,geometrySha256:d.terrain.geometry.sha256,contactSha256:d.terrain.sha256,authoredStateSha256:'a'.repeat(64)}});
  const attached=mount.attach(h);await vi.waitFor(()=>expect(mount.navigationWorld.terrain?.occupancy.status).toBe('verified'));
  const outer=h.environmentRoot.findByName('dressing:wall')!;const moved=target==='outer'?outer:outer.children[0]!;
  const before=moved.getLocalPosition().clone();moved.setLocalPosition(before.x+1,before.y,before.z);
  expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');moved.setLocalPosition(before);
  expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');h.app.fire('update',.01);
  expect(h.environmentRoot.findByName('dressing:wall')).toBeNull();attached.dispose();h.app.destroy();
 }
});

it('accepts only the original pending entry after real asynchronous decode and moves, then preserves revoked pose',async()=>{
 const d=drawing(),prepared=await prepareTerrainDressing(d.dressing,async()=>bytes(),new AbortController().signal),h=host();let available=true;
 const mount=siteMount(d,{servedBytes:1,preparedDressing:prepared,terrainOccupancy:()=>available?{status:'verified',worldId:d.worldId,versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:d.receiptSha256,geometrySha256:d.terrain.geometry.sha256,contactSha256:d.terrain.sha256,authoredStateSha256:'a'.repeat(64)}:{status:'unavailable'}});
 const canvas=h.app.graphicsDevice.canvas as HTMLCanvasElement;document.body.append(canvas);
 const controls=new FirstPersonControls(canvas,mount.start,undefined,mount.navigationWorld);expect(controls.state.terrain).toBeUndefined();
 canvas.focus();window.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW'}));controls.update(.05);expect(controls.state.x).toBe(mount.start.x);
 const attached=mount.attach(h);await vi.waitFor(()=>expect(mount.navigationWorld.terrain?.occupancy.status).toBe('verified'));
 controls.update(.05);expect(controls.state.terrain).toBeDefined();expect(controls.state.x).toBeGreaterThan(mount.start.x);
 available=false;controls.update(.05);const held={...controls.state};h.app.fire('update',.01);available=true;controls.update(.05);
 expect(controls.state).toEqual(held);expect(canvas.dataset['navigationTerrainFailure']).toBe('unbound_occupancy');
 window.dispatchEvent(new KeyboardEvent('keyup',{code:'KeyW'}));controls.destroy();attached.dispose();h.app.destroy();canvas.remove();
});
