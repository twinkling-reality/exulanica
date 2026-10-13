// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, type TextureSetDigest } from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing } from '../src/playcanvas/generated-site/site-drawing.js';
import { drawSiteSlots } from '../src/playcanvas/generated-site/site-primitives.js';
import { prepareTextureSet } from '../src/playcanvas/generated-tile/texture-materials.js';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import { SiteTextures, siteSurfaceMm } from '../src/playcanvas/style-pack/site-textures.js';
const directory = 'packages/loom-texture/test/conformance/';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync(`${directory}manifest.json`)));
const digest = webcrypto.subtle as unknown as TextureSetDigest;
const prepare = (id: string) => prepareTextureSet(manifest,id,entry => Promise.resolve(new Uint8Array(readFileSync(`${directory}${entry.setId}.ltex`))),digest);
function scene() {
 const app = new pc.AppBase(document.createElement('canvas'));
 const options = new pc.AppOptions(); options.graphicsDevice = new pc.NullGraphicsDevice(app.graphicsDevice?.canvas ?? document.createElement('canvas')); options.componentSystems=[pc.RenderComponentSystem]; app.init(options);
 const drawing=parseStructuredSiteDrawing({profile:'exulanica.site-drawing/v1',world_id:'world:textures',receipt_sha256:'a'.repeat(64),kind:{kind:'study',version:1,label:'Study'},extent:{widthMm:20000,depthMm:16000,enclosure:'open'},arrival:{positionMm:[1000,1000,0],facingMm:[0,1]},slots:[
 {identity:'paving',part:'paving',label:'Paving',lookRole:'ground.tile',positionMm:[6000,6000,0],yawQuarterTurns:1,boxMm:[12000,4000,0],front:'+y',fit:'surface',primitive:'plane',uvFrame:{originMm:[0,0,0],uAxisMm:[1000,0,0],vAxisMm:[0,1000,0]}},
 {identity:'wall',part:'wall',label:'Wall',lookRole:'wall.glass',positionMm:[6000,14000,0],yawQuarterTurns:0,boxMm:[8000,200,4000],front:'+y',fit:'surface',primitive:'box',uvFrame:{originMm:[0,14000,0],uAxisMm:[1000,0,0],vAxisMm:[0,0,1000]}},
 ],walk:{floorMm:[0,0,20000,16000],blockersMm:[[2000,13900,10000,14100]],keepOutMm:[]},seats:[]});
 const slots=drawSiteSlots(app.graphicsDevice,drawing); app.root.addChild(slots.root);
 const instance=(id:string)=>(slots.root.findByName(`${id}:shape`) as pc.Entity).render!.meshInstances[0]!;
 return {app,drawing,slots,instance};
}
describe('physical site texture dressing',()=>{
 it('keeps physical repeats under rotation and an origin shift, and restores unchanged geometry',async()=>{
  const {app,drawing,slots,instance}=scene(); const prepared=await prepare('fixture.opaque'); if(prepared.state!=='decoded')throw Error('fixture must decode');
  const textures=new SiteTextures(app.graphicsDevice,TILE_LOOK_V1,new Map([[prepared.setId,prepared]])); slots.root.setPosition(500,10,-700);
  const before=instance('paving').mesh, positions:number[]=[]; before.getPositions(positions);
  textures.wear(instance('paving'),drawing.slots[0]!,prepared.setId,null,slots.root);
  const after:number[]=[],uvs:number[]=[]; instance('paving').mesh.getPositions(after); instance('paving').mesh.getUvs(0,uvs); expect(after).toEqual(positions);
  const us=uvs.filter((_,i)=>i%2===0),vs=uvs.filter((_,i)=>i%2===1);
  expect(Math.max(...us)-Math.min(...us)).toBeCloseTo(4000/prepared.set.entry.extentUMm);
  expect(Math.max(...vs)-Math.min(...vs)).toBeCloseTo(12000/prepared.set.entry.extentVMm);
  expect(instance('paving').mesh.aabb).toEqual(before.aabb); textures.dispose(); textures.dispose(); expect(instance('paving').mesh).toBe(before); slots.destroy(); app.destroy();
 });
 it('keeps the beyond plane at the base ground’s physical texture scale', async () => {
  const { app, drawing, slots } = scene();
  const prepared = await prepare('fixture.opaque');
  if (prepared.state !== 'decoded') throw Error('fixture must decode');
  const root = new pc.Entity('beyond-root');
  app.root.addChild(root);
  root.setPosition(500, 0, -700);
  const plane = new pc.Entity('beyond');
  root.addChild(plane);
  plane.setLocalPosition(10, -.018, -8);
  plane.setLocalScale(80, 1, 64);
  const material = new pc.StandardMaterial();
  const original = pc.Mesh.fromGeometry(app.graphicsDevice, new pc.PlaneGeometry());
  const instance = new pc.MeshInstance(original, material, plane);
  const textures = new SiteTextures(app.graphicsDevice, TILE_LOOK_V1, new Map([[prepared.setId, prepared]]));
  textures.wear(instance, drawing.slots[0]!, prepared.setId, null, root);
  const uvs: number[] = [];
  instance.mesh.getUvs(0, uvs);
  const us = uvs.filter((_, i) => i % 2 === 0), vs = uvs.filter((_, i) => i % 2 === 1);
  expect(Math.max(...us) - Math.min(...us)).toBeCloseTo(80000 / prepared.set.entry.extentUMm);
  expect(Math.max(...vs) - Math.min(...vs)).toBeCloseTo(64000 / prepared.set.entry.extentVMm);
  textures.dispose();
  expect(instance.mesh).toBe(original);
  instance.destroy(); original.destroy(); material.destroy(); root.destroy(); slots.destroy(); app.destroy();
 });
 it('keeps opening strips on a common wall frame and thickness faces nondegenerate',()=>{
  const {app,drawing,slots}=scene(),wall=drawing.slots[1]!;
  expect(siteSurfaceMm(wall,[2000,14100,1000],[0,1,0])).toEqual([2000,-1000]);
  expect(siteSurfaceMm({...wall,positionMm:[11000,14000,0],boxMm:[2000,200,4000]},[10000,14100,1000],[0,1,0])).toEqual([10000,-1000]);
  expect(siteSurfaceMm(wall,[2000,13900,1000],[-1,0,0])[0]).toBe(0); expect(siteSurfaceMm(wall,[2000,14100,1000],[-1,0,0])[0]).toBe(200); slots.destroy();app.destroy();
 });
 it('shares verified uploads and restores glazing meshes, materials and shadow flags',async()=>{
  const {app,drawing,slots,instance}=scene(),prepared=await prepare('fixture.glazing');
  const textures=new SiteTextures(app.graphicsDevice,TILE_LOOK_V1,new Map([[prepared.setId,prepared]]));
  const originals=drawing.slots.map(slot=>({mesh:instance(slot.identity).mesh,material:instance(slot.identity).material,shadow:instance(slot.identity).castShadow,bucket:instance(slot.identity).drawBucket})),world=JSON.stringify(drawing);
  for(const slot of drawing.slots)expect(textures.wear(instance(slot.identity),slot,prepared.setId,null,slots.root)).toBe(true);
  expect(instance('paving').material).toBe(instance('wall').material); const glass=instance('wall').material as pc.StandardMaterial;
  expect(glass.depthWrite).toBe(false);expect(glass.blendType).toBe(pc.BLEND_NORMAL);expect(instance('wall').castShadow).toBe(false);
  expect(textures.metrics()).toMatchObject({transferredBytes:prepared.state==='decoded'?prepared.transferredBytes:-1,unavailableSurfaces:0});expect(textures.metrics().decodedTextureBytes).toBeGreaterThan(0);expect(JSON.stringify(drawing)).toBe(world);
  textures.dispose();drawing.slots.forEach((slot,i)=>{expect(instance(slot.identity).mesh).toBe(originals[i]!.mesh);expect(instance(slot.identity).material).toBe(originals[i]!.material);expect(instance(slot.identity).castShadow).toBe(originals[i]!.shadow);expect(instance(slot.identity).drawBucket).toBe(originals[i]!.bucket);});slots.destroy();app.destroy();
 });
 it('rejects corrupt pinned bytes and shows unavailable without a colour substitution',async()=>{
  const {app,drawing,slots,instance}=scene();const refused=await prepareTextureSet(manifest,'fixture.opaque',async()=>new Uint8Array([1,2,3]),digest);expect(refused.state).toBe('refused');
  const textures=new SiteTextures(app.graphicsDevice,TILE_LOOK_V1,new Map([[refused.setId,refused]]));expect(textures.wear(instance('wall'),drawing.slots[1]!,refused.setId,null,slots.root)).toBe(false);expect(instance('wall').material.name).toBe('generated-tile-unavailable');expect(textures.metrics()).toEqual({transferredBytes:0,decodedTextureBytes:0,unavailableSurfaces:1});textures.dispose();slots.destroy();app.destroy();
 });
});
