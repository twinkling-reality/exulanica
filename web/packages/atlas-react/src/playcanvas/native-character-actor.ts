import * as pc from 'playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { characterSubjectKey } from '@exulanica/atlas-core';
import { validateNativeAppearance, validateNativeCharacterDescriptor, type NativeCharacterAppearance, type NativeCharacterAuthority, type NativeCharacterDescriptor, type NativeCharacterMotion } from './native-character.js';
import type { CharacterAssetLease } from './native-character-pool.js';

type Gait='idle'|'walk'|'run';
export function resolvedCharacterGait(descriptor:NativeCharacterDescriptor,previous:readonly number[]|null,motion:NativeCharacterMotion):{gait:Gait;speed:number;metresPerSecond:number}{
  const distance=previous?Math.hypot(motion.position[0]-previous[0]!,motion.position[2]-previous[2]!):0;
  const speed=!previous||motion.discontinuity||motion.reducedMotion||!Number.isFinite(motion.deltaSeconds)||motion.deltaSeconds<=0?0:distance/motion.deltaSeconds;
  const gait=speed<.015?'idle':speed<(descriptor.clips.walk.metresPerSecond+descriptor.clips.run.metresPerSecond)/2?'walk':'run';
  return {gait,speed:gait==='idle'?(motion.reducedMotion?0:1):speed/descriptor.clips[gait].metresPerSecond,metresPerSecond:speed};
}
export function nativeAuthorityStatus(authority:NativeCharacterAuthority):'ready'|'fallback'|'hidden'{
  return authority.presence!=='allowed'?'hidden':authority.source==='available'?'ready':'fallback';
}
export function currentNativeAuthorityStatus(current:()=>NativeCharacterAuthority):'ready'|'fallback'|'hidden'{
  try{return nativeAuthorityStatus(current());}catch{return 'hidden';}
}
/** One mutable rig instance. Meshes, textures and tracks remain owned by its shared bundle lease. */
export class NativeCharacterActor {
  readonly root:pc.Entity;
  readonly model:pc.Entity;
  readonly subjectKey:string;
  private readonly materials=new Map<pc.Material,pc.Material>();
  private readonly meshes:pc.MeshInstance[];
  private readonly rootMotionNode:pc.GraphNode|null;
  private readonly rootMotionOrigin:pc.Vec3|null;
  private previous:readonly number[]|null=null;
  private wasVisible=false;
  private gait:Gait='idle';
  private disposed=false;
  private state:'ready'|'fallback'|'hidden'='ready';
  private velocity=0;
  constructor(
    readonly subject:CharacterSubject,
    readonly descriptor:NativeCharacterDescriptor,
    private readonly lease:CharacterAssetLease,
    parent:pc.Entity,
    private readonly currentAuthority:()=>NativeCharacterAuthority,
    appearance:NativeCharacterAppearance={},
  ){
    this.subjectKey=characterSubjectKey(subject);
    validateNativeCharacterDescriptor(descriptor,lease.inspection);
    validateNativeAppearance(descriptor,appearance);
    if(currentNativeAuthorityStatus(currentAuthority)!=='ready')throw new Error('Character source or presence unavailable');
    this.root=new pc.Entity(`native-character:${this.subjectKey}`);
    this.model=(lease.asset.resource as pc.ContainerResource).instantiateRenderEntity({castShadows:true,receiveShadows:true});
    this.root.addChild(this.model);
    this.model.setLocalScale(descriptor.unitScale,descriptor.unitScale,descriptor.unitScale);
    this.model.setLocalEulerAngles(0,descriptor.forwardYawDegrees,0);
    this.model.setLocalPosition(0,-descriptor.groundOffset*descriptor.unitScale,0);
    this.meshes=(this.model.findComponents('render') as pc.RenderComponent[]).flatMap(render=>render.meshInstances);
    this.rootMotionNode=descriptor.rootMotion.mode==='remove-horizontal'?this.model.findByName(descriptor.rootMotion.node):null;
    this.rootMotionOrigin=this.rootMotionNode?.getLocalPosition().clone()??null;
    try {
      for(const mi of this.meshes){
        const original=mi.material;
        let clone=this.materials.get(original);
        if(!clone){clone=original.clone();this.materials.set(original,clone);}
        mi.material=clone;
      }
      this.model.addComponent('anim',{activate:true});
      const anim=this.model.anim!;
      anim.loadStateGraph({layers:[{name:'Base',states:[{name:'START'},...(['idle','walk','run'] as const).map(name=>({name,speed:1,loop:true}))],transitions:[{from:'START',to:'idle'}]}],parameters:{}});
      const resources=(lease.asset.resource as pc.ContainerResource & {animations:pc.Asset[]}).animations;
      for(const kind of ['idle','walk','run'] as const){
        const index=lease.inspection.clipNames.indexOf(descriptor.clips[kind].name);
        const track=resources[index]?.resource as pc.AnimTrack|undefined;
        if(!track)throw new Error(`Native clip unavailable: ${kind}`);
        anim.assignAnimation(kind,track);
      }
      this.setAppearance(appearance);
      parent.addChild(this.root);
    }catch(error){this.root.destroy();for(const material of this.materials.values())material.destroy();throw error;}
  }
  get status(){return this.state;}
  get currentGait(){return this.gait;}
  get resolvedSpeed(){return this.velocity;}
  get skinInstances():readonly pc.SkinInstance[]{return [...new Set(this.meshes.flatMap(mi=>mi.skinInstance?[mi.skinInstance]:[]))];}
  get meshInstances():readonly pc.MeshInstance[]{return this.meshes;}
  get mutableResidentBytes():number{return this.skinInstances.reduce((n,skin)=>n+(skin.boneTexture?.gpuSize??0),0);}
  /** Appearance replaces the previous edit. Omitted slots restore the pinned asset's defaults. */
  setAppearance(appearance:NativeCharacterAppearance):void{
    if(this.disposed)throw new Error('Character disposed');
    validateNativeAppearance(this.descriptor,appearance);
    for(const [original,material] of this.materials){if(original instanceof pc.StandardMaterial&&material instanceof pc.StandardMaterial){material.diffuse.copy(original.diffuse);material.update();}}
    for(const [slot,color] of Object.entries(appearance.colors??{}))for(const [original,material] of this.materials)if(this.descriptor.materialSlots[slot]!.materials.includes(original.name)&&material instanceof pc.StandardMaterial){material.diffuse.fromString(color);material.update();}
    for(const [name,parameter] of Object.entries(this.descriptor.morphParameters)){
      const value=appearance.morphs?.[name]??parameter.default;
      for(const nodeName of parameter.nodes){
        const node=this.model.findByName(nodeName) as pc.Entity|null;
        const instances=node?.render?.meshInstances.filter(mi=>mi.morphInstance&&mi.mesh.morph?.targets.some(t=>t.name===parameter.target));
        if(!instances?.length)throw new Error(`Morph target unavailable: ${name}/${nodeName}`);
        for(const mi of instances)mi.morphInstance!.setWeight(parameter.target,value);
      }
    }
    for(const [name,slot] of Object.entries(this.descriptor.variantSlots)){
      const selected=new Set(slot.options[appearance.variants?.[name]??slot.default]);
      for(const nodeName of new Set(Object.values(slot.options).flat()))this.model.findByName(nodeName)!.enabled=selected.has(nodeName);
    }
  }
  /** Called after native animationUpdate, using collision-resolved ground positions only. */
  update(motion:NativeCharacterMotion,visible=true):void{
    if(this.disposed)return;
    this.state=currentNativeAuthorityStatus(this.currentAuthority);
    if(this.state!=='ready'){this.destroy();return;}
    if(!motion.position.every(Number.isFinite)||!Number.isFinite(motion.yaw))throw new Error('Invalid resolved character pose');
    const movement=resolvedCharacterGait(this.descriptor,this.wasVisible&&visible?this.previous:null,motion);
    this.previous=[...motion.position];this.wasVisible=visible;
    this.velocity=movement.metresPerSecond;
    this.root.enabled=visible;
    this.root.setLocalPosition(...motion.position);
    this.root.setLocalEulerAngles(0,motion.yaw*180/Math.PI,0);
    if(movement.gait!==this.gait){if(motion.reducedMotion){this.model.anim!.baseLayer!.play('idle');this.model.anim!.baseLayer!.activeStateCurrentTime=0;this.model.anim!.update(0);}else this.model.anim!.baseLayer!.transition(movement.gait,.14);this.gait=movement.gait;}
    this.model.anim!.speed=movement.speed;
    // Strip only the declared horizontal motion, preserving vertical bob and joint animation.
    if(this.rootMotionNode&&this.rootMotionOrigin){const p=this.rootMotionNode.getLocalPosition();this.rootMotionNode.setLocalPosition(this.rootMotionOrigin.x,p.y,this.rootMotionOrigin.z);}
  }
  destroy():void{
    if(this.disposed)return;
    this.disposed=true;this.root.destroy();
    for(const material of this.materials.values())material.destroy();
    this.materials.clear();this.lease.release();
  }
}
