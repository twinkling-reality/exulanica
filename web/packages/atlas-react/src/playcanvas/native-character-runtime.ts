import * as pc from 'playcanvas';
import { characterSubjectKey, type CharacterSubject } from '@exulanica/atlas-core';
import { NativeCharacterActor, currentNativeAuthorityStatus } from './native-character-actor.js';
import { NativeCharacterPool, type CharacterByteLoader } from './native-character-pool.js';
import type { NativeCharacterAppearance, NativeCharacterAuthority, NativeCharacterDescriptor, NativeCharacterMotion } from './native-character.js';
import { CHARACTER_RENDERABLE_TAG } from './character/renderable.js';

export interface NativeCharacterFrame extends NativeCharacterMotion {
  readonly subject:CharacterSubject;
  readonly parent:pc.Entity;
  readonly fallback:pc.Entity;
  readonly visible:boolean;
}
interface Resident {frame:NativeCharacterFrame;actor:NativeCharacterActor|null;request:AbortController|null;status:'abstract'|'loading'|'ready'|'fallback'|'hidden';authority:(()=>NativeCharacterAuthority)|null;error:string|null}
/** Bindings provide only the resident display subjects, never the whole persistent population. */
export class NativeCharacterRuntime {
  readonly pool:NativeCharacterPool;
  private readonly residents=new Map<string,Resident>();
  private readonly residentListeners=new Set<(subjects:readonly CharacterSubject[])=>void>();
  private destroyed=false;
  constructor(app:pc.AppBase,loadBytes:CharacterByteLoader){this.pool=new NativeCharacterPool(app,loadBytes);}
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
    if(keys.size!==frames.length||frames.filter(frame=>frame.subject.kind==='synthetic-inhabitant').length>24)throw new Error('Invalid native character resident set');
    for(const [key,resident] of this.residents)if(!keys.has(key)){this.release(resident);this.residents.delete(key);residencyChanged=true;}
    for(const frame of frames){
      const key=characterSubjectKey(frame.subject);
      let resident=this.residents.get(key);
      if(!resident){resident={frame,actor:null,request:null,status:'abstract',authority:null,error:null};this.residents.set(key,resident);residencyChanged=true;}
      // A replaced fallback node denotes a new renderer residency, even when identity is unchanged.
      if(resident.frame.fallback!==frame.fallback){this.release(resident);resident.authority=null;resident.status='abstract';residencyChanged=true;}
      resident.frame=frame;
      if(resident.authority){
        let status:'ready'|'fallback'|'hidden'='hidden';
        try{status=currentNativeAuthorityStatus(resident.authority);}catch{resident.error='Current authority unavailable';}
        if(status!=='ready'){this.release(resident);resident.status=status;}
      }
      if(resident.actor){resident.actor.update(frame,frame.visible);resident.status=resident.actor.status;}
      this.present(resident);
    }
    if(residencyChanged)this.notifyResidents();
  }
  async install(subject:CharacterSubject,descriptor:NativeCharacterDescriptor,appearance:NativeCharacterAppearance,currentAuthority:()=>NativeCharacterAuthority):Promise<void>{
    const resident=this.residents.get(characterSubjectKey(subject));
    if(!resident)throw new Error('Character subject is outside the resident display set');
    this.release(resident);resident.authority=currentAuthority;resident.error=null;
    const status=currentNativeAuthorityStatus(currentAuthority);
    resident.status=status==='ready'?'loading':status;this.present(resident);
    if(status!=='ready')return;
    const request=new AbortController();resident.request=request;
    let lease:Awaited<ReturnType<NativeCharacterPool['acquire']>>|null=null;
    try{
      lease=await this.pool.acquire(descriptor.asset,request.signal);
      if(request.signal.aborted)throw new DOMException('Character request cancelled','AbortError');
      const actor=new NativeCharacterActor(subject,descriptor,lease,resident.frame.parent,currentAuthority,appearance);
      lease=null;resident.actor=actor;resident.status='ready';
      actor.update({...resident.frame,discontinuity:true},resident.frame.visible);resident.status=actor.status;
    }catch(error){
      lease?.release();
      if(!request.signal.aborted){resident.status=currentNativeAuthorityStatus(currentAuthority)==='hidden'?'hidden':'fallback';resident.error=error instanceof Error?error.message:String(error);throw error;}
    }finally{if(resident.request===request){resident.request=null;this.present(resident);}}
  }
  setAppearance(subject:CharacterSubject,appearance:NativeCharacterAppearance):void{
    const resident=this.residents.get(characterSubjectKey(subject));
    if(!resident?.actor)throw new Error('Native character is unavailable');
    if(!resident.authority||currentNativeAuthorityStatus(resident.authority)!=='ready'){this.release(resident);resident.status=resident.authority?currentNativeAuthorityStatus(resident.authority):'hidden';this.present(resident);throw new Error('Character authority changed');}
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
  clear(subject:CharacterSubject):void{const r=this.residents.get(characterSubjectKey(subject));if(r){this.release(r);r.authority=null;r.status='abstract';r.error=null;}}
  destroy():void{if(this.destroyed)return;this.destroyed=true;this.residentListeners.clear();for(const r of this.residents.values())this.release(r);this.residents.clear();this.pool.destroy();}
}
