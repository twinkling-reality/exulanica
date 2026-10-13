// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { HEIGHTFIELD_PERSON_POLICY, heightfieldAt, readHeightfieldGeometry, readHeightfieldContact, type TerrainOccupancyProof } from '@exulanica/atlas-core';
import { sha256Hex } from '../src/playcanvas/character/digest.js';
import { parseSiteDrawing, SITE_DRAWING_TERRAIN_PROFILE, type TerrainSiteDrawing } from '../src/playcanvas/generated-site/site-drawing.js';
import { siteNavigationWorld, siteStart } from '../src/playcanvas/generated-site/site-navigation.js';
import { siteMount } from '../src/playcanvas/generated-site/site-mount.js';
import { heightfieldMeshPart } from '../src/playcanvas/generated-site/heightfield-mesh.js';
import { FirstPersonControls } from '../src/playcanvas/controls.js';

function served() {
  const geometry = readHeightfieldGeometry({profile:'exulanica.heightfield-geometry/v1', component_id:'terrain:arrival', frame:'region-local-east-up-south-mm', east_mm:[0,2000,4000],south_mm:[-4000,-2000,0],height_mm:[1000,1500,2000,1000,1500,2000,1000,1500,2000],diagonal:'a-c-b,b-c-d',provenance:{kind:'authored',source_sha256:'a'.repeat(64),generator_id:'fixture:terrain',generator_version:1,input_sha256:'b'.repeat(64)}},sha256Hex);
  const contact = readHeightfieldContact({profile:'exulanica.heightfield-contact/v1',geometry_sha256:geometry.sha256,component_id:geometry.data.component_id,policy:HEIGHTFIELD_PERSON_POLICY,obstructions:[]},geometry,sha256Hex);
  return {profile:SITE_DRAWING_TERRAIN_PROFILE,world_id:'world:terrain',region_id:'region:generated',receipt_sha256:'c'.repeat(64),composer:{key:'site-plan',version:3},frame:'region-local-east-up-south-mm',bounds_mm:{east:[0,4000],south:[-4000,0]},terrain:{geometry:geometry.document(),geometry_sha256:geometry.sha256,contact:contact.document(),contact_sha256:contact.sha256},arrival:{position_mm:[1000,1250,-2000],facing_mm:[1000,0],contact:heightfieldAt(contact,[1000,-2000]).contact!},capabilities:{person_navigation:true,passive_flat_patch:true,society_projection:'unavailable'}};
}
function admitted(): TerrainSiteDrawing {
  const drawing = parseSiteDrawing(served());
  if(drawing.profile !== SITE_DRAWING_TERRAIN_PROFILE) throw Error('expected terrain');
  return drawing;
}
function proof(d: TerrainSiteDrawing): TerrainOccupancyProof {return {status:'verified',worldId:d.worldId,versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:d.receiptSha256,geometrySha256:d.terrain.geometry.sha256,contactSha256:d.terrain.sha256,authoredStateSha256:'d'.repeat(64)};}
function controls(d: TerrainSiteDrawing, occupancy: TerrainOccupancyProof = proof(d)) {
 const w=siteNavigationWorld(d,occupancy),canvas=document.createElement('canvas'); document.body.append(canvas);
 return {w,canvas,c:new FirstPersonControls(canvas,siteStart(d,w),undefined,w)};
}
it('admits exact drawing 3 with semantic triangle identity and no structured-site fields',()=>{
 const d=admitted();expect(d).not.toHaveProperty('slots');expect(d).not.toHaveProperty('walk');
 expect(d.arrival.contact.triangle).toEqual(heightfieldMeshPart(d.terrain.geometry,1).triangle);
 const w=siteNavigationWorld(d,proof(d)),start=siteStart(d,w);
 expect(start).toMatchObject({x:1,y:1.25+w.eyeHeight,z:-2,yaw:-Math.PI/2,terrain:{positionMm:[1000,-2000]}});
 expect(w.surface.sample(1,-2)).toBeNull();expect(w.support).toBeUndefined();
});
it('rejects profile/composer, source digest, capabilities, bounds, contact and rounded-height mismatches',()=>{
 const mutations:((d:ReturnType<typeof served>)=>void)[]=[d=>{d.composer.version=2;},d=>{d.terrain.geometry={...d.terrain.geometry,height_mm:[1010,...d.terrain.geometry.height_mm.slice(1)]};},d=>{d.terrain.contact_sha256='f'.repeat(64);},d=>{d.capabilities.society_projection='ready';},d=>{d.bounds_mm.south[0]=-3999;},d=>{d.arrival.position_mm[1]=1251;},d=>{d.arrival.contact={...d.arrival.contact,triangle:[0,1,0]};},d=>{Object.assign(d,{slots:[]});}];
 for(const mutate of mutations){const raw=served();mutate(raw);expect(()=>parseSiteDrawing(raw)).toThrow();}
});
it('keeps source-only terrain visible but does not accept or move a grounded pose',()=>{
 const d=admitted(),{c,canvas,w}=controls(d,{status:'unavailable'}),before={...c.state};
 expect(w.terrain?.occupancy.status).toBe('unavailable');expect(c.state.terrain).toBeUndefined();
 canvas.focus();window.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW'}));c.update(.05);
 expect(c.state).toEqual(before);expect(canvas.dataset['navigationTerrainFailure']).toBe('unbound_occupancy');c.destroy();canvas.remove();
});
it('moves uphill with pinned exact contact and refuses stale ground restoration',()=>{
 const {c,canvas,w}=controls(admitted());canvas.focus();window.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW'}));c.update(.05);
 expect(c.state.x).toBeGreaterThan(1);expect(c.state.y).toBeCloseTo(1+c.state.x*.25+w.eyeHeight,12);
 window.dispatchEvent(new KeyboardEvent('keyup',{code:'KeyW'}));const held={...c.state};
 c.setView({...held,x:3,terrain:{...held.terrain!,authoredStateSha256:'f'.repeat(64)}},'ground');expect(c.state).toEqual(held);
 c.setView({...held,x:3,y:50,terrain:{...held.terrain!,geometrySha256:'f'.repeat(64)}},'altitude');
 expect(c.state.terrain).toEqual(held.terrain);expect(c.state.y).toBe(50);c.holdGround();expect(c.state).toEqual(held);
 c.destroy();expect(canvas.dataset['navigationTerrain']).toBeUndefined();canvas.remove();
});
it('mounts and disposes original terrain topology without adding a level ground substitute',()=>{
 const canvas=document.createElement('canvas'),device=new pc.NullGraphicsDevice(canvas),app=new pc.AppBase(canvas),options=new pc.AppOptions();
 options.graphicsDevice=device;options.componentSystems=[pc.RenderComponentSystem,pc.CameraComponentSystem,pc.LightComponentSystem];app.init(options);
 const camera=new pc.Entity('camera');camera.addComponent('camera');app.root.addChild(camera);const environmentRoot=new pc.Entity('environment');app.root.addChild(environmentRoot);
 const d=admitted(),mount=siteMount(d,{servedBytes:500}),attached=mount.attach({app,camera,environmentRoot});
 expect(attached.metrics.triangles).toBe(8);expect(attached.metrics.drawBatches).toBe(1);
 expect(environmentRoot.children).toHaveLength(1);expect(canvas.dataset['terrainGeometry']).toBe(d.terrain.geometry.sha256);
 expect(canvas.dataset['terrainOccupancy']).toBeUndefined();expect(mount.navigationWorld.terrain?.occupancy.status).toBe('unavailable');attached.dispose();attached.dispose();expect(environmentRoot.children).toHaveLength(0);expect(canvas.dataset['terrainGeometry']).toBeUndefined();app.destroy();
});

it('reads the Python-emitted source drawing without schema or triangle normalization',()=>{
 const raw=JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-terrain.v3.json','utf8'));
 const drawing=parseSiteDrawing(raw);if(drawing.profile!==SITE_DRAWING_TERRAIN_PROFILE)throw Error('terrain expected');
 expect(drawing.terrain.document()).toEqual(raw.terrain.contact);expect(drawing.terrain.geometry.document()).toEqual(raw.terrain.geometry);
 expect(drawing.arrival.contact).toEqual(raw.arrival.contact);
});
