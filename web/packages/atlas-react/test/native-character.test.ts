import { createHash } from 'node:crypto';
import { describe,it,expect,vi } from 'vitest';
import { inspectCharacterGlb,validateNativeCharacterDescriptor,validateNativeAppearance,type NativeCharacterDescriptor } from '../src/playcanvas/native-character.js';
import { resolvedCharacterGait,nativeAuthorityStatus } from '../src/playcanvas/native-character-actor.js';
import { NativeCharacterPool } from '../src/playcanvas/native-character-pool.js';
import type * as pc from 'playcanvas';
const fakeAsset=vi.hoisted(()=>({unload:vi.fn()}));
vi.mock('../src/playcanvas/scene-objects.js',async(importOriginal)=>({...await importOriginal<object>(),createObjectContainerAsset:vi.fn(async()=>fakeAsset)}));
// Minimal metadata containers test refusal logic only. Real skinning is exercised in browser review.
function container(extra:Record<string,unknown>={}):ArrayBuffer{
 const json=new TextEncoder().encode(JSON.stringify({asset:{version:'2.0'},nodes:[{name:'Hip'}],skins:[{joints:[0]}],animations:[{name:'Idle'},{name:'Walk'},{name:'Run'}],materials:[{name:'Cloth'}],...extra}));
 const bytes=new Uint8Array(20+Math.ceil(json.length/4)*4);bytes.fill(32,20);const view=new DataView(bytes.buffer);
 view.setUint32(0,0x46546c67,true);view.setUint32(4,2,true);view.setUint32(8,bytes.length,true);view.setUint32(12,bytes.length-20,true);view.setUint32(16,0x4e4f534a,true);bytes.set(json,20);return bytes.buffer;
}
const bytes=container(),digest=createHash('sha256').update(new Uint8Array(bytes)).digest('hex');
const descriptor:NativeCharacterDescriptor={asset:{assetKey:'test-rig',mediaType:'model/gltf-binary',contentSha256:digest,byteSize:bytes.byteLength},rigId:'test-rig/v1',joints:['Hip'],unitScale:1,forwardYawDegrees:0,groundOffset:0,standingHeight:1.8,clips:{idle:{name:'Idle',metresPerSecond:0},walk:{name:'Walk',metresPerSecond:1.4},run:{name:'Run',metresPerSecond:3.2}},rootMotion:{mode:'in-place'},materialSlots:{cloth:{materials:['Cloth']}},morphParameters:{},variantSlots:{}};
describe('native character boundaries',()=>{
 it('requires the exact named source rig and all three calibrated clips',()=>{
  const inspection=inspectCharacterGlb(bytes);expect(()=>validateNativeCharacterDescriptor(descriptor,inspection)).not.toThrow();
  for(const change of [{rigId:'abstract-human/v1'},{joints:['Other']},{clips:{idle:descriptor.clips.idle,walk:descriptor.clips.walk}},{clips:{...descriptor.clips,run:{name:'Missing',metresPerSecond:3}}}])expect(()=>validateNativeCharacterDescriptor({...descriptor,...change} as NativeCharacterDescriptor,inspection)).toThrow();
  expect(()=>inspectCharacterGlb(container({skins:[]}))).toThrow('no skin');
 });
 it('rejects appearance fields outside asset metadata',()=>{
  expect(()=>validateNativeAppearance(descriptor,{colors:{cloth:'#af1234'}})).not.toThrow();
  for(const appearance of [{colors:{hair:'#ffffff'}},{colors:{cloth:'red'}},{morphs:{height:1}},{variants:{hair:'long'}}])expect(()=>validateNativeAppearance(descriptor,appearance)).toThrow();
 });
 it('uses resolved displacement, with no walking into a wall or gait on discontinuity',()=>{
  const pose={position:[0,0,0] as const,yaw:0,deltaSeconds:.1};
  expect(resolvedCharacterGait(descriptor,[0,0,0],pose).gait).toBe('idle');
  expect(resolvedCharacterGait(descriptor,[0,0,-.14],pose).gait).toBe('walk');
  expect(resolvedCharacterGait(descriptor,[0,0,-.14],pose).speed).toBeCloseTo(1);
  expect(resolvedCharacterGait(descriptor,[0,0,-.32],pose).gait).toBe('run');
  expect(resolvedCharacterGait(descriptor,[0,0,-20],{...pose,discontinuity:true}).gait).toBe('idle');
  expect(resolvedCharacterGait(descriptor,[0,0,-20],{...pose,reducedMotion:true}).speed).toBe(0);
 });
 it('fails closed on presence while unavailable source permits only fallback',()=>{
  expect(nativeAuthorityStatus({presence:'unresolved',source:'available'})).toBe('hidden');
  expect(nativeAuthorityStatus({presence:'allowed',source:'withdrawn'})).toBe('fallback');
 });
});
describe('pinned shared character bundle',()=>{
 const app={assets:{remove:vi.fn()}} as unknown as pc.AppBase;
 it('shares one load, isolates cancellation, and unloads only the final lease',async()=>{
  fakeAsset.unload.mockClear();let resolve!:(b:ArrayBuffer)=>void;
  const loader=vi.fn(()=>new Promise<ArrayBuffer>(r=>{resolve=r;}));const pool=new NativeCharacterPool(app,loader);
  const a=new AbortController(),b=new AbortController();
  const first=pool.acquire(descriptor.asset,a.signal),second=pool.acquire(descriptor.asset,b.signal);
  const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});a.abort();resolve(bytes);await rejected;
  const lease=await second;expect(loader).toHaveBeenCalledTimes(1);expect(fakeAsset.unload).not.toHaveBeenCalled();
  lease.release();lease.release();expect(fakeAsset.unload).toHaveBeenCalledTimes(1);expect(pool.residentBundleCount).toBe(0);
 });
 it('rejects wrong bytes and conflicting reference metadata',async()=>{
  const pool=new NativeCharacterPool(app,async()=>bytes);
  await expect(pool.acquire({...descriptor.asset,contentSha256:'0'.repeat(64)},new AbortController().signal)).rejects.toThrow('digest');
  const lease=await pool.acquire(descriptor.asset,new AbortController().signal);
  await expect(pool.acquire({...descriptor.asset,byteSize:1},new AbortController().signal)).rejects.toThrow('Conflicting');
  lease.release();
 });
 it('destroys pending work without publishing a container',async()=>{
  let resolve!:(b:ArrayBuffer)=>void;const pool=new NativeCharacterPool(app,()=>new Promise(r=>{resolve=r;}));
  const pending=pool.acquire(descriptor.asset,new AbortController().signal);pool.destroy();resolve(bytes);
  await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(pool.residentBundleCount).toBe(0);
 });
});
