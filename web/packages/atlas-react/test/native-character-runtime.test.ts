import { describe,it,expect,vi } from 'vitest';
import type * as pc from 'playcanvas';
import { NativeCharacterRuntime,type NativeCharacterFrame } from '../src/playcanvas/native-character-runtime.js';
import type { NativeCharacterDescriptor } from '../src/playcanvas/native-character.js';
import { CharacterHost } from '../src/playcanvas/character/host.js';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { NEAR_CHARACTER_BUDGET } from '../src/playcanvas/character/budget.js';
const state=vi.hoisted(()=>({releases:0,destroys:0,appearances:[] as unknown[]}));
vi.mock('../src/playcanvas/native-character-pool.js',()=>({NativeCharacterPool:class{async acquire(){return{release:()=>state.releases++};}destroy(){}}}));
vi.mock('../src/playcanvas/native-character-actor.js',()=>({
 currentNativeAuthorityStatus:(fn:()=>{presence:string;source:string})=>{try{const a=fn();return a.presence!=='allowed'?'hidden':a.source==='available'?'ready':'fallback';}catch{return'hidden';}},
 NativeCharacterActor:class{status='ready';currentGait='idle';resolvedSpeed=0;mutableResidentBytes=0;constructor(readonly subject:unknown,readonly descriptor:unknown,private lease:{release():void},_parent?:unknown,_authority?:unknown,appearance?:unknown){state.appearances.push(appearance);}update(){}setAppearance(){}destroy(){state.destroys++;this.lease.release();}}
}));
const descriptor={} as NativeCharacterDescriptor;
const app=()=>({once:vi.fn()}) as unknown as pc.AppBase;
function frame(id:string,branch='main',position:readonly [number,number,number]=[0,0,0]):NativeCharacterFrame{
 const render={enabled:true};return{subject:{kind:'synthetic-inhabitant',societyId:'society',branchId:branch,inhabitantId:id},parent:{} as pc.Entity,fallback:{findComponents:()=>[render],tags:{add:vi.fn(),remove:vi.fn(),has:()=>false}} as unknown as pc.Entity,visible:true,position,yaw:0,deltaSeconds:1/60};
}
const player=():NativeCharacterFrame=>({...frame('viewer'),subject:{kind:'player',playerId:'viewer'}});
const drawn=(f:NativeCharacterFrame)=>(f.fallback.findComponents('render') as unknown as {enabled:boolean}[])[0]!.enabled;
const allowed=()=>({presence:'allowed' as const,source:'available' as const});
describe('native residency and current permission',()=>{
 it('draws the nearest people in full up to the measured budget, the rest in far form, and releases an old branch',async()=>{
  const runtime=new NativeCharacterRuntime(app(),vi.fn()),viewer=player();
  // One metre apart outwards from the player, who takes one full place of the budget.
  const people=Array.from({length:NEAR_CHARACTER_BUDGET+3},(_,i)=>frame(String(i),'main',[i+1,0,0]));
  runtime.syncFrames([viewer,...people]);
  await Promise.all(people.map(f=>runtime.install(f.subject,descriptor,{},allowed)));
  const statuses=people.map(f=>runtime.inspect(f.subject)?.status);
  expect(statuses.slice(0,NEAR_CHARACTER_BUDGET-1).every(s=>s==='ready')).toBe(true);
  expect(statuses.slice(NEAR_CHARACTER_BUDGET-1)).toEqual(['far','far','far','far']);
  expect(people.map(drawn)).toEqual(statuses.map(s=>s!=='ready'));
  expect(()=>runtime.syncFrames([viewer,people[0]!,people[0]!])).toThrow('resident');
  runtime.syncFrames([frame('0','branch-two')]);expect(runtime.inspect(people[0]!.subject)).toBeNull();
  expect(state.destroys).toBeGreaterThan(0);runtime.destroy();
 });
 it('hands a full place to someone nearer only for a clear gain, wearing their latest appearance',async()=>{
  const runtime=new NativeCharacterRuntime(app(),vi.fn()),viewer=player();
  const people=Array.from({length:NEAR_CHARACTER_BUDGET},(_,i)=>frame(String(i),'main',[i+1,0,0]));
  const sync=(moved:NativeCharacterFrame)=>runtime.syncFrames([viewer,...people.slice(0,-1),moved]);
  const edge=people.at(-2)!,waiting=people.at(-1)!;
  runtime.syncFrames([viewer,...people]);
  await Promise.all(people.map(f=>runtime.install(f.subject,descriptor,{},allowed)));
  expect(runtime.inspect(waiting.subject)?.status).toBe('far');
  runtime.setAppearance(waiting.subject,{colors:{cloth:'#334455'}});
  // A metre nearer than the farthest full body is not enough to trade places.
  sync({...waiting,position:[edge.position[0]-1,0,0]});
  expect(runtime.inspect(waiting.subject)?.status).toBe('far');
  expect(runtime.inspect(edge.subject)?.status).toBe('ready');
  sync({...waiting,position:[edge.position[0]-3,0,0]});
  expect(runtime.inspect(edge.subject)?.status).toBe('far');
  expect(drawn(edge)).toBe(true);
  await vi.waitFor(()=>expect(runtime.inspect(waiting.subject)?.status).toBe('ready'));
  expect(state.appearances.at(-1)).toEqual({colors:{cloth:'#334455'}});
  runtime.destroy();
 });
 it('restores fallback on withdrawal and hides both representations on denied or failed presence checks',async()=>{
  const runtime=new NativeCharacterRuntime(app(),vi.fn()),f=frame('one');runtime.syncFrames([f]);
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
  const runtime=new NativeCharacterRuntime(app(),vi.fn()),f=frame('one');runtime.syncFrames([f]);let available=true;
  await runtime.install(f.subject,descriptor,{},()=>({presence:'allowed',source:available?'available':'withdrawn'}));
  available=false;runtime.syncFrames([f]);available=true;runtime.syncFrames([f]);expect(runtime.inspect(f.subject)?.status).toBe('fallback');
  runtime.clear(f.subject);expect(runtime.inspect(f.subject)?.status).toBe('abstract');runtime.destroy();
 });
});

describe('native resident subscriptions',()=>{
 it('starts with an immutable current snapshot and ignores pose, visibility and order changes',()=>{
  const runtime=new NativeCharacterRuntime(app(),vi.fn());
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
  const runtime=new NativeCharacterRuntime(app(),vi.fn());
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
  const runtime=new NativeCharacterRuntime(app(),vi.fn()),listener=vi.fn();
  const first=runtime.subscribeResidents(listener),second=runtime.subscribeResidents(listener);
  expect(listener).toHaveBeenCalledTimes(2);first();runtime.syncFrames([frame('one')]);
  expect(listener).toHaveBeenCalledTimes(3);second();runtime.syncFrames([]);
  expect(listener).toHaveBeenCalledTimes(3);runtime.destroy();
 });
 it('stops dispatch when a listener destroys the runtime and stays quiet afterward',()=>{
  const runtime=new NativeCharacterRuntime(app(),vi.fn());
  const first=vi.fn((subjects:readonly NativeCharacterFrame['subject'][])=>{if(subjects.length)runtime.destroy();});
  const second=vi.fn();runtime.subscribeResidents(first);runtime.subscribeResidents(second);
  runtime.syncFrames([frame('one')]);expect(first).toHaveBeenCalledTimes(2);expect(second).toHaveBeenCalledTimes(1);
  runtime.syncFrames([frame('two')]);const late=vi.fn();runtime.subscribeResidents(late)();runtime.destroy();
  expect(late).not.toHaveBeenCalled();expect(first).toHaveBeenCalledTimes(2);expect(second).toHaveBeenCalledTimes(1);
  expect(runtime.inspect(frame('two').subject)).toBeNull();
 });
 it('hands its byte authority to the catalog people of the same application',()=>{
  const application=app(),loader=vi.fn();
  expect(CharacterHost.forApp(application,CHARACTER_CATALOG).hasLoader).toBe(false);
  new NativeCharacterRuntime(application,loader);
  expect(CharacterHost.forApp(application,CHARACTER_CATALOG).hasLoader).toBe(true);
  expect(CharacterHost.forApp(app(),CHARACTER_CATALOG).hasLoader).toBe(false);
 });
});
