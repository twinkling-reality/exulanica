import { describe,it,expect,vi } from 'vitest';
import type * as pc from 'playcanvas';
import { NativeCharacterRuntime,type NativeCharacterFrame } from '../src/playcanvas/native-character-runtime.js';
import type { NativeCharacterDescriptor } from '../src/playcanvas/native-character.js';
const state=vi.hoisted(()=>({releases:0,destroys:0}));
vi.mock('../src/playcanvas/native-character-pool.js',()=>({NativeCharacterPool:class{async acquire(){return{release:()=>state.releases++};}destroy(){}}}));
vi.mock('../src/playcanvas/native-character-actor.js',()=>({
 currentNativeAuthorityStatus:(fn:()=>{presence:string;source:string})=>{try{const a=fn();return a.presence!=='allowed'?'hidden':a.source==='available'?'ready':'fallback';}catch{return'hidden';}},
 NativeCharacterActor:class{status='ready';currentGait='idle';resolvedSpeed=0;mutableResidentBytes=0;constructor(readonly subject:unknown,readonly descriptor:unknown,private lease:{release():void}){}update(){}setAppearance(){}destroy(){state.destroys++;this.lease.release();}}
}));
const descriptor={} as NativeCharacterDescriptor;
function frame(id:string,branch='main'):NativeCharacterFrame{
 const render={enabled:true};return{subject:{kind:'synthetic-inhabitant',societyId:'society',branchId:branch,inhabitantId:id},parent:{} as pc.Entity,fallback:{findComponents:()=>[render],tags:{add:vi.fn(),remove:vi.fn()}} as unknown as pc.Entity,visible:true,position:[0,0,0],yaw:0,deltaSeconds:1/60};
}
describe('native residency and current permission',()=>{
 it('uses capped subjects, rejects overflow, and releases an old branch even for matching inhabitant IDs',async()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn());const frames=Array.from({length:24},(_,i)=>frame(String(i)));runtime.syncFrames(frames);
  await runtime.install(frames[0]!.subject,descriptor,{},()=>({presence:'allowed',source:'available'}));
  expect(runtime.inspect(frames[0]!.subject)?.status).toBe('ready');
  expect(()=>runtime.syncFrames([...frames,frame('25')])).toThrow('resident');
  expect(runtime.inspect(frames[0]!.subject)?.status).toBe('ready');
  runtime.syncFrames([frame('0','branch-two')]);expect(runtime.inspect(frames[0]!.subject)).toBeNull();
  expect(state.destroys).toBeGreaterThan(0);runtime.destroy();
 });
 it('restores fallback on withdrawal and hides both representations on denied or failed presence checks',async()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn()),f=frame('one');runtime.syncFrames([f]);
  let authority:{presence:'allowed'|'denied';source:'available'|'withdrawn'}={presence:'allowed',source:'available'};
  await runtime.install(f.subject,descriptor,{},()=>authority);
  const render=(f.fallback.findComponents('render') as pc.RenderComponent[])[0]!;
  expect(render.enabled).toBe(false);
  authority={presence:'allowed',source:'withdrawn'};runtime.syncFrames([f]);expect(render.enabled).toBe(true);expect(runtime.inspect(f.subject)?.status).toBe('fallback');
  authority={presence:'denied',source:'available'};runtime.syncFrames([f]);expect(render.enabled).toBe(false);expect(runtime.inspect(f.subject)?.status).toBe('hidden');
  await runtime.install(f.subject,descriptor,{},()=>{throw new Error('offline');});expect(render.enabled).toBe(false);
  runtime.destroy();
 });
 it('does not restore a native instance automatically when a withdrawn source becomes available again',async()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn()),f=frame('one');runtime.syncFrames([f]);let available=true;
  await runtime.install(f.subject,descriptor,{},()=>({presence:'allowed',source:available?'available':'withdrawn'}));
  available=false;runtime.syncFrames([f]);available=true;runtime.syncFrames([f]);expect(runtime.inspect(f.subject)?.status).toBe('fallback');
  runtime.clear(f.subject);expect(runtime.inspect(f.subject)?.status).toBe('abstract');runtime.destroy();
 });
});

describe('native resident subscriptions',()=>{
 it('starts with an immutable current snapshot and ignores pose, visibility and order changes',()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn());
  const a=frame('a'),b=frame('b');runtime.syncFrames([a,b]);
  const listener=vi.fn();const unsubscribe=runtime.subscribeResidents(listener);
  expect(listener).toHaveBeenCalledTimes(1);
  const subjects=listener.mock.calls[0]![0] as readonly NativeCharacterFrame['subject'][];
  expect(subjects).toEqual([a.subject,b.subject]);
  expect(Object.isFrozen(subjects)).toBe(true);expect(Object.isFrozen(subjects[0])).toBe(true);
  expect(subjects[0]).not.toBe(a.subject);
  runtime.syncFrames([{...b,visible:false,position:[2,0,3],yaw:1},a]);
  expect(listener).toHaveBeenCalledTimes(1);
  const c=frame('c');runtime.syncFrames([b,c]);
  expect(listener).toHaveBeenCalledTimes(2);
  expect(listener.mock.calls[1]![0]).toEqual([b.subject,c.subject]);
  expect(runtime.inspect(a.subject)).toBeNull();
  unsubscribe();unsubscribe();runtime.syncFrames([]);
  expect(listener).toHaveBeenCalledTimes(2);runtime.destroy();
 });
 it('notifies after the entire mutation and permits immediate installation, including replacement at the same identity',async()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn());
  const a=frame('a'),b=frame('b');const pending:Promise<void>[]=[];
  const statuses:(string|undefined)[][]=[];
  const withAsset={asset:{assetKey:'test',mediaType:'model/gltf-binary',contentSha256:'a'.repeat(64),byteSize:1}} as NativeCharacterDescriptor;
  const listener=vi.fn((subjects:readonly NativeCharacterFrame['subject'][])=>{
   statuses.push(subjects.map(subject=>runtime.inspect(subject)?.status));
   for(const subject of subjects)if(runtime.inspect(subject)?.status==='abstract')
    pending.push(runtime.install(subject,withAsset,{},()=>({presence:'allowed',source:'available'})));
  });
  runtime.subscribeResidents(listener);
  expect(statuses).toEqual([[]]);
  runtime.syncFrames([a,b]);await Promise.all(pending);
  expect(statuses[1]).toEqual(['abstract','abstract']);
  expect(runtime.inspect(a.subject)?.asset).toEqual(withAsset.asset);
  expect(runtime.inspect(b.subject)?.status).toBe('ready');
  runtime.syncFrames([a,b]);expect(listener).toHaveBeenCalledTimes(2);
  const replacement=frame('a');runtime.syncFrames([replacement,b]);await Promise.all(pending);
  expect(listener).toHaveBeenCalledTimes(3);
  expect(statuses[2]).toEqual(['abstract','ready']);
  expect(pending).toHaveLength(3);
  expect(runtime.inspect(replacement.subject)?.status).toBe('ready');
  expect((a.fallback.findComponents('render') as pc.RenderComponent[])[0]!.enabled).toBe(true);
  expect((replacement.fallback.findComponents('render') as pc.RenderComponent[])[0]!.enabled).toBe(false);
  runtime.destroy();
 });
 it('unsubscribes repeated callbacks independently',()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn()),listener=vi.fn();
  const first=runtime.subscribeResidents(listener),second=runtime.subscribeResidents(listener);
  expect(listener).toHaveBeenCalledTimes(2);first();runtime.syncFrames([frame('one')]);
  expect(listener).toHaveBeenCalledTimes(3);second();runtime.syncFrames([]);
  expect(listener).toHaveBeenCalledTimes(3);runtime.destroy();
 });
 it('stops dispatch when a listener destroys the runtime and stays quiet afterward',()=>{
  const runtime=new NativeCharacterRuntime({} as pc.AppBase,vi.fn());
  const first=vi.fn((subjects:readonly NativeCharacterFrame['subject'][])=>{if(subjects.length)runtime.destroy();});
  const second=vi.fn();runtime.subscribeResidents(first);runtime.subscribeResidents(second);
  runtime.syncFrames([frame('one')]);expect(first).toHaveBeenCalledTimes(2);expect(second).toHaveBeenCalledTimes(1);
  runtime.syncFrames([frame('two')]);const late=vi.fn();runtime.subscribeResidents(late)();runtime.destroy();
  expect(late).not.toHaveBeenCalled();expect(first).toHaveBeenCalledTimes(2);expect(second).toHaveBeenCalledTimes(1);
  expect(runtime.inspect(frame('two').subject)).toBeNull();
 });
});
