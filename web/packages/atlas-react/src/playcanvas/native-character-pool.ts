import * as pc from 'playcanvas';
import { createObjectContainerAsset, type AuthoredObjectAssetReference } from './scene-objects.js';
import { inspectCharacterGlb, type InspectedCharacterGlb } from './native-character.js';
export type CharacterByteLoader=(reference:AuthoredObjectAssetReference,signal:AbortSignal)=>Promise<ArrayBuffer>;
interface Entry { references:number; controller:AbortController; promise:Promise<{asset:pc.Asset;inspection:InspectedCharacterGlb}>;asset:pc.Asset|undefined; byteSize:number }
export interface CharacterAssetLease {readonly asset:pc.Asset;readonly inspection:InspectedCharacterGlb;release():void}
/** Shared immutable GLB resources; each live subject acquires a separately cancellable lease. */
export class NativeCharacterPool {
  private readonly entries=new Map<string,Entry>();
  private destroyed=false;
  constructor(private readonly app:pc.AppBase,private readonly loadBytes:CharacterByteLoader){}
  get residentBundleCount():number{return this.entries.size;}
  get residentBytes():{geometry:number;textures:number;encoded:number}{
    const meshes=new Set<pc.Mesh>(),textures=new Set<pc.Texture>();let encoded=0;
    for(const entry of this.entries.values()){
      if(!entry.asset)continue;
      encoded+=entry.byteSize;
      const resource=entry.asset.resource as pc.ContainerResource & {renders:pc.Asset[];textures:pc.Asset[]};
      for(const render of resource.renders)for(const mesh of (render.resource as {meshes:pc.Mesh[]}).meshes)meshes.add(mesh);
      for(const texture of resource.textures)textures.add(texture.resource as pc.Texture);
    }
    return {geometry:[...meshes].reduce((n,m)=>n+(m.vertexBuffer?.numBytes??0)+m.indexBuffer.reduce((s,b)=>s+(b?.numBytes??0),0),0),textures:[...textures].reduce((n,t)=>n+t.gpuSize,0),encoded};
  }
  async acquire(reference:AuthoredObjectAssetReference,signal:AbortSignal):Promise<CharacterAssetLease>{
    if(this.destroyed||signal.aborted)throw new DOMException('Character request cancelled','AbortError');
    if(reference.mediaType!=='model/gltf-binary'||!/^[a-f0-9]{64}$/.test(reference.contentSha256)||!Number.isSafeInteger(reference.byteSize)||reference.byteSize<=0)throw new Error('Invalid pinned character reference');
    const key=reference.contentSha256;
    let entry=this.entries.get(key);
    if(entry&&entry.byteSize!==reference.byteSize)throw new Error('Conflicting character byte count');
    if(!entry){
      const controller=new AbortController();
      const created:Entry={references:0,controller,promise:undefined!,asset:undefined,byteSize:reference.byteSize};
      created.promise=(async()=>{
        const bytes=await this.loadBytes(reference,controller.signal);
        if(bytes.byteLength!==reference.byteSize)throw new Error('Character byte count mismatch');
        const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
        if(hash!==key)throw new Error('Character digest mismatch');
        if(controller.signal.aborted)throw new DOMException('Character request cancelled','AbortError');
        const inspection=inspectCharacterGlb(bytes);
        const asset=await createObjectContainerAsset(this.app,`character-${key}`,bytes);
        created.asset=asset;
        if(created.references===0||controller.signal.aborted){this.disposeAsset(asset);created.asset=undefined;throw new DOMException('Character request cancelled','AbortError');}
        return {asset,inspection};
      })();
      entry=created;this.entries.set(key,entry);
    }
    const held=entry;held.references++;
    let released=false;
    const release=()=>{if(released)return;released=true;held.references--;if(held.references===0){if(this.entries.get(key)===held)this.entries.delete(key);held.controller.abort();if(held.asset){this.disposeAsset(held.asset);held.asset=undefined;}}};
    let rejectAbort:(reason:unknown)=>void=()=>{};
    const onAbort=()=>{release();rejectAbort(new DOMException('Character request cancelled','AbortError'));};
    signal.addEventListener('abort',onAbort,{once:true});
    try {
      const loaded=await Promise.race([held.promise,new Promise<never>((_,reject)=>{rejectAbort=reject;})]);
      if(signal.aborted||this.destroyed)throw new DOMException('Character request cancelled','AbortError');
      return {...loaded,release};
    }catch(error){release();throw error;}finally{signal.removeEventListener('abort',onAbort);}
  }
  private disposeAsset(asset:pc.Asset):void{asset.unload();this.app.assets.remove(asset);}
  destroy():void{this.destroyed=true;for(const entry of this.entries.values()){entry.controller.abort();if(entry.asset){this.disposeAsset(entry.asset);entry.asset=undefined;}}this.entries.clear();}
}
