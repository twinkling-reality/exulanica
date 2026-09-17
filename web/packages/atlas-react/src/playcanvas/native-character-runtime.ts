import * as pc from 'playcanvas';
import { characterSubjectKey, type CharacterSubject } from '@exulanica/atlas-core';
import { NativeCharacterActor, currentNativeAuthorityStatus } from './native-character-actor.js';
import { NativeCharacterPool, type CharacterByteLoader } from './native-character-pool.js';
import type { NativeCharacterAppearance, NativeCharacterAuthority, NativeCharacterDescriptor, NativeCharacterMotion } from './native-character.js';
import { CHARACTER_RENDERABLE_TAG } from './character/renderable.js';
import { CharacterHost } from './character/host.js';
import { CHARACTER_CATALOG } from './character/catalog-data.js';
import { NEAR_CHARACTER_BUDGET } from './character/budget.js';

export interface NativeCharacterFrame extends NativeCharacterMotion {
  readonly subject:CharacterSubject;
  readonly parent:pc.Entity;
  readonly fallback:pc.Entity;
  readonly visible:boolean;
}
/** What an owner asked to draw, kept while the resident waits beyond the budget in its far form. */
interface Intent {readonly descriptor:NativeCharacterDescriptor;appearance:NativeCharacterAppearance;readonly authority:()=>NativeCharacterAuthority}
interface Resident {frame:NativeCharacterFrame;actor:NativeCharacterActor|null;request:AbortController|null;status:'abstract'|'loading'|'ready'|'fallback'|'hidden'|'far';authority:(()=>NativeCharacterAuthority)|null;error:string|null;intent:Intent|null;near:boolean}
/** A full place changes hands only when the newcomer is this much nearer than the one it replaces. */
const SWAP_MARGIN_METRES=2;
/** Bindings provide only the resident display subjects, never the whole persistent population. */
export class NativeCharacterRuntime {
  readonly pool:NativeCharacterPool;
  private readonly app:pc.AppBase;
  private readonly residents=new Map<string,Resident>();
  private readonly residentListeners=new Set<(subjects:readonly CharacterSubject[])=>void>();
  private destroyed=false;
  constructor(app:pc.AppBase,loadBytes:CharacterByteLoader){
    this.app=app;
    this.pool=new NativeCharacterPool(app,loadBytes);
    // Catalog people fetch through the same authority; renderables waiting for it upgrade now.
    CharacterHost.forApp(app,CHARACTER_CATALOG).setLoader(loadBytes);
  }
  /** Initial snapshot, then residency changes only. Pose/visibility updates do not notify. */
  subscribeResidents(listener:(subjects:readonly CharacterSubject[])=>void):()=>void{
    if(this.destroyed)return ()=>{};
    // Each subscription can be removed independently, even when callbacks are reused.
    const subscribed=(subjects:readonly CharacterSubject[])=>listener(subjects);
    this.residentListeners.add(subscribed);
    try{subscribed(this.residentSubjects());}catch(error){this.residentListeners.delete(subscribed);throw error;}
    return ()=>{this.residentListeners.delete(subscribed);};
  }
  private residentSubjects():readonly CharacterSubject[]{
    return Object.freeze([...this.residents.values()].map(resident=>Object.freeze({...resident.frame.subject})));
  }
  private notifyResidents():void{
    const subjects=this.residentSubjects();
    for(const listener of [...this.residentListeners]){
      if(this.destroyed)break;
      if(this.residentListeners.has(listener))listener(subjects);
    }
  }
  syncFrames(all:readonly NativeCharacterFrame[]):void{
    if(this.destroyed)return;
    // Catalog renderables draw and animate themselves; this runtime never adopts them.
    const frames=all.filter(frame=>!frame.fallback.tags.has(CHARACTER_RENDERABLE_TAG));
    let residencyChanged=false;
    const keys=new Set(frames.map(frame=>characterSubjectKey(frame.subject)));
    if(keys.size!==frames.length)throw new Error('Invalid native character resident set');
    for(const [key,resident] of this.residents)if(!keys.has(key)){this.release(resident);this.residents.delete(key);residencyChanged=true;}
    for(const frame of frames){
      const key=characterSubjectKey(frame.subject);
      let resident=this.residents.get(key);
      if(!resident){resident={frame,actor:null,request:null,status:'abstract',authority:null,error:null,intent:null,near:false};this.residents.set(key,resident);residencyChanged=true;}
      // A replaced fallback node denotes a new renderer residency, even when identity is unchanged.
      if(resident.frame.fallback!==frame.fallback){this.release(resident);resident.authority=null;resident.intent=null;resident.status='abstract';residencyChanged=true;}
      resident.frame=frame;
      if(resident.authority){
        let status:'ready'|'fallback'|'hidden'='hidden';
        try{status=currentNativeAuthorityStatus(resident.authority);}catch{resident.error='Current authority unavailable';}
        if(status!=='ready'){this.release(resident);resident.status=status;}
      }
      if(resident.actor){resident.actor.update(frame,frame.visible);resident.status=resident.actor.status;}
      this.present(resident);
    }
    this.applyBudget();
    if(residencyChanged)this.notifyResidents();
  }
  /**
   * The nearest people are drawn in full, up to the measured budget; everyone beyond keeps a far
   * form. The player and scene people always take their full place, and it counts against the budget.
   */
  private applyBudget():void{
    const residents=[...this.residents.values()];
    const people=residents.filter(r=>r.frame.subject.kind==='synthetic-inhabitant');
    const others=residents.filter(r=>r.frame.subject.kind!=='synthetic-inhabitant');
    for(const r of others)this.setNear(r,true);
    const origin=others.find(r=>r.frame.subject.kind==='player')?.frame.position??this.cameraPosition();
    const ranked=people.map(r=>({r,d:origin?Math.hypot(r.frame.position[0]-origin[0],r.frame.position[1]-origin[1],r.frame.position[2]-origin[2]):0}))
      .sort((a,b)=>a.d-b.d);
    const budget=Math.max(0,NEAR_CHARACTER_BUDGET-others.length);
    const holding=ranked.filter(e=>e.r.near),waiting=ranked.filter(e=>!e.r.near);
    const kept=holding.slice(0,budget),free=budget-kept.length;
    // Someone walking along the edge of the budget must not switch between forms every frame.
    const contenders=waiting.slice(free),holders=[...kept].reverse();
    let swaps=0;
    while(swaps<contenders.length&&swaps<holders.length&&contenders[swaps]!.d+SWAP_MARGIN_METRES<holders[swaps]!.d)swaps++;
    for(const e of [...holding.slice(budget),...holders.slice(0,swaps)])this.setNear(e.r,false);
    for(const e of [...waiting.slice(0,free),...contenders.slice(0,swaps)])this.setNear(e.r,true);
  }
  private cameraPosition():readonly [number,number,number]|null{
    // The world camera sees farthest; overlay cameras (a first-person gesture) clip within metres.
    const cameras=this.app.systems?.camera?.cameras??[];
    const camera=cameras.reduce<pc.CameraComponent|null>((best,c)=>!best||c.farClip>best.farClip?c:best,null);
    if(!camera)return null;
    const p=camera.entity.getPosition();
    return [p.x,p.y,p.z];
  }
  private setNear(resident:Resident,near:boolean):void{
    if(resident.near===near)return;
    resident.near=near;
    if(!near){
      if(resident.actor||resident.request){this.release(resident);resident.status='far';this.present(resident);}
      return;
    }
    // A failed promotion is recorded on the resident, where inspect reports it; nobody awaits it.
    if(resident.status==='far')this.activate(resident).catch(()=>{});
  }
  async install(subject:CharacterSubject,descriptor:NativeCharacterDescriptor,appearance:NativeCharacterAppearance,currentAuthority:()=>NativeCharacterAuthority):Promise<void>{
    const resident=this.residents.get(characterSubjectKey(subject));
    if(!resident)throw new Error('Character subject is outside the resident display set');
    resident.intent={descriptor,appearance,authority:currentAuthority};
    await this.activate(resident);
  }
  private async activate(resident:Resident):Promise<void>{
    const intent=resident.intent;
    if(!intent)return;
    this.release(resident);resident.authority=intent.authority;resident.error=null;
    const status=currentNativeAuthorityStatus(intent.authority);
    if(status==='ready'&&!resident.near){resident.status='far';this.present(resident);return;}
    resident.status=status==='ready'?'loading':status;this.present(resident);
    if(status!=='ready')return;
    const request=new AbortController();resident.request=request;
    let lease:Awaited<ReturnType<NativeCharacterPool['acquire']>>|null=null;
    try{
      lease=await this.pool.acquire(intent.descriptor.asset,request.signal);
      if(request.signal.aborted)throw new DOMException('Character request cancelled','AbortError');
      const actor=new NativeCharacterActor(resident.frame.subject,intent.descriptor,lease,resident.frame.parent,intent.authority,intent.appearance);
      lease=null;resident.actor=actor;resident.status='ready';
      actor.update({...resident.frame,discontinuity:true},resident.frame.visible);resident.status=actor.status;
    }catch(error){
      lease?.release();
      if(!request.signal.aborted){resident.status=currentNativeAuthorityStatus(intent.authority)==='hidden'?'hidden':'fallback';resident.error=error instanceof Error?error.message:String(error);throw error;}
    }finally{if(resident.request===request){resident.request=null;this.present(resident);}}
  }
  setAppearance(subject:CharacterSubject,appearance:NativeCharacterAppearance):void{
    const resident=this.residents.get(characterSubjectKey(subject));
    // A person waiting in far form wears the new appearance when it is next drawn in full.
    if(resident?.intent&&resident.status==='far'){resident.intent.appearance=appearance;return;}
    if(!resident?.actor)throw new Error('Native character is unavailable');
    if(!resident.authority||currentNativeAuthorityStatus(resident.authority)!=='ready'){this.release(resident);resident.status=resident.authority?currentNativeAuthorityStatus(resident.authority):'hidden';this.present(resident);throw new Error('Character authority changed');}
    if(resident.intent)resident.intent.appearance=appearance;
    resident.actor.setAppearance(appearance);
  }
  inspect(subject:CharacterSubject){const r=this.residents.get(characterSubjectKey(subject));return r?{subject:r.frame.subject,status:r.status,error:r.error,rigId:r.actor?.descriptor.rigId??null,asset:r.actor?.descriptor.asset??null,gait:r.actor?.currentGait??null,speed:r.actor?.resolvedSpeed??0,mutableBytes:r.actor?.mutableResidentBytes??0}:null;}
  get mutableResidentBytes():number{return [...this.residents.values()].reduce((sum,r)=>sum+(r.actor?.mutableResidentBytes??0),0);}
  private present(resident:Resident):void{
    // An abstract resident was never installed: its owner decides what its root draws.
    if(resident.status==='abstract')return;
    if(resident.status==='hidden')resident.frame.fallback.tags.add('native-character-hidden');
    else resident.frame.fallback.tags.remove('native-character-hidden');
    // Keep the fallback root available to existing stable-subject picking and co-location logic.
    for(const component of resident.frame.fallback.findComponents('render') as pc.RenderComponent[])component.enabled=resident.status!=='ready'&&resident.status!=='hidden';
  }
  private release(resident:Resident):void{
    resident.request?.abort();resident.request=null;resident.actor?.destroy();resident.actor=null;
    if(resident.status==='abstract')return;
    resident.frame.fallback.tags.remove('native-character-hidden');
    for(const component of resident.frame.fallback.findComponents('render') as pc.RenderComponent[])component.enabled=true;
  }
  clear(subject:CharacterSubject):void{const r=this.residents.get(characterSubjectKey(subject));if(r){this.release(r);r.authority=null;r.intent=null;r.status='abstract';r.error=null;}}
  destroy():void{if(this.destroyed)return;this.destroyed=true;this.residentListeners.clear();for(const r of this.residents.values())this.release(r);this.residents.clear();this.pool.destroy();}
}
