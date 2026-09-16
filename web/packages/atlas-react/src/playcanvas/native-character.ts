import type { AuthoredObjectAssetReference } from './scene-objects.js';
import { validateGlbContainer } from './scene-objects.js';

export interface NativeCharacterClip { readonly name:string; readonly metresPerSecond:number }
/** Renderer catalog descriptor. The rig ID names the inspected asset rig, not abstract-human/v1. */
export interface NativeCharacterDescriptor {
  readonly asset:AuthoredObjectAssetReference;
  readonly rigId:string;
  readonly joints:readonly string[];
  readonly unitScale:number;
  readonly forwardYawDegrees:number;
  readonly groundOffset:number;
  readonly standingHeight:number;
  readonly clips:Readonly<Record<'idle'|'walk'|'run',NativeCharacterClip>>;
  readonly rootMotion:{readonly mode:'in-place'}|{readonly mode:'remove-horizontal';readonly node:string};
  readonly materialSlots:Readonly<Record<string,{readonly materials:readonly string[]}>>;
  readonly morphParameters:Readonly<Record<string,{readonly nodes:readonly string[];readonly target:string;readonly min:number;readonly max:number;readonly default:number}>>;
  readonly variantSlots:Readonly<Record<string,{readonly options:Readonly<Record<string,readonly string[]>>;readonly default:string}>>;
}
export interface NativeCharacterAppearance {
  readonly colors?:Readonly<Record<string,string>>;
  readonly morphs?:Readonly<Record<string,number>>;
  readonly variants?:Readonly<Record<string,string>>;
}
export interface NativeCharacterAuthority {
  readonly presence:'allowed'|'denied'|'unresolved';
  readonly source:'available'|'withdrawn'|'unavailable'|'unresolved';
}
export interface NativeCharacterMotion {
  /** Ground position already resolved by traversal/simulation authority, in world metres. */
  readonly position:readonly [number,number,number];
  readonly yaw:number;
  readonly deltaSeconds:number;
  readonly reducedMotion?:boolean;
  /** A branch/time discontinuity relocates; it must not produce a traversal animation. */
  readonly discontinuity?:boolean;
}
export interface InspectedCharacterGlb {
  readonly json:Record<string,unknown>;
  readonly nodeNames:readonly string[];
  readonly jointNames:readonly string[];
  readonly clipNames:readonly string[];
  readonly materialNames:readonly string[];
}
export function inspectCharacterGlb(bytes:ArrayBuffer):InspectedCharacterGlb {
  validateGlbContainer(bytes);
  const view=new DataView(bytes),length=view.getUint32(12,true);
  const json=JSON.parse(new TextDecoder().decode(new Uint8Array(bytes,20,length)).trim()) as Record<string,unknown>;
  const nodes=(json['nodes']??[]) as {name?:string}[];
  const skins=(json['skins']??[]) as {joints?:number[]}[];
  if(!skins.length)throw new Error('Character asset contains no skin');
  const jointIndices=new Set(skins.flatMap(skin=>skin.joints??[]));
  if(!jointIndices.size||[...jointIndices].some(i=>!Number.isInteger(i)||!nodes[i]?.name))throw new Error('Character rig requires named valid joints');
  return {json,nodeNames:nodes.map(n=>n.name??''),jointNames:[...jointIndices].map(i=>nodes[i]!.name!),clipNames:((json['animations']??[]) as {name?:string}[]).map(a=>a.name??''),materialNames:((json['materials']??[]) as {name?:string}[]).map(m=>m.name??'')};
}
export function validateNativeCharacterDescriptor(descriptor:NativeCharacterDescriptor,inspection:InspectedCharacterGlb):void {
  if(!descriptor.rigId||descriptor.rigId==='abstract-human/v1')throw new Error('Imported character requires its declared source rig ID');
  if(!Number.isFinite(descriptor.unitScale)||descriptor.unitScale<=0||!Number.isFinite(descriptor.standingHeight)||descriptor.standingHeight<=0||!Number.isFinite(descriptor.forwardYawDegrees)||!Number.isFinite(descriptor.groundOffset))throw new Error('Invalid character frame');
  if(descriptor.joints.length!==inspection.jointNames.length||new Set(descriptor.joints).size!==descriptor.joints.length||descriptor.joints.some(n=>!inspection.jointNames.includes(n)))throw new Error('Character joint mapping does not match pinned asset');
  for(const kind of ['idle','walk','run'] as const){
    const clip=descriptor.clips[kind];
    if(!clip)throw new Error(`Missing ${kind} clip`);
    if(inspection.clipNames.filter(name=>name===clip.name).length!==1)throw new Error(`Missing or ambiguous ${kind} clip: ${clip.name}`);
    if(!Number.isFinite(clip.metresPerSecond)||(kind==='idle'?clip.metresPerSecond!==0:clip.metresPerSecond<=0))throw new Error(`Invalid ${kind} clip calibration`);
  }
  if(!['in-place','remove-horizontal'].includes(descriptor.rootMotion.mode))throw new Error('Unknown root motion mode');
  const rootMotion=descriptor.rootMotion;
  if(rootMotion.mode==='remove-horizontal'&&inspection.nodeNames.filter(n=>n===rootMotion.node).length!==1)throw new Error('Root motion node is missing or ambiguous');
  for(const slot of Object.values(descriptor.materialSlots))if(!slot.materials.length||slot.materials.some(n=>!inspection.materialNames.includes(n)))throw new Error('Unknown character material slot');
  for(const parameter of Object.values(descriptor.morphParameters))if(!parameter.nodes.length||parameter.nodes.some(n=>!inspection.nodeNames.includes(n))||!Number.isFinite(parameter.min)||!Number.isFinite(parameter.max)||parameter.min>parameter.max||!Number.isFinite(parameter.default)||parameter.default<parameter.min||parameter.default>parameter.max)throw new Error('Invalid character morph parameter');
  for(const slot of Object.values(descriptor.variantSlots))if(!slot.options[slot.default]||Object.values(slot.options).flat().some(n=>!inspection.nodeNames.includes(n)))throw new Error('Invalid character variant slot');
}
export function validateNativeAppearance(descriptor:NativeCharacterDescriptor,appearance:NativeCharacterAppearance):void {
  for(const [slot,color] of Object.entries(appearance.colors??{}))if(!descriptor.materialSlots[slot]||!/^#[\da-f]{6}$/i.test(color))throw new Error(`Invalid color slot ${slot}`);
  for(const [name,value] of Object.entries(appearance.morphs??{})){const p=descriptor.morphParameters[name];if(!p||!Number.isFinite(value)||value<p.min||value>p.max)throw new Error(`Invalid morph parameter ${name}`);}
  for(const [name,value] of Object.entries(appearance.variants??{}))if(!descriptor.variantSlots[name]?.options[value])throw new Error(`Invalid variant ${name}`);
}
