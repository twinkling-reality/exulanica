import type { SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api';
import {canonicalJson} from '../../../web/packages/atlas-core/src/style-pack';
import {WORLD_STYLE_RECIPES} from '../../../web/packages/presentation/src/world-style-recipes';
import { icon } from '../../../web/packages/app/src/ui/system/icon';

function node(tag:string,text='',className='') { const n=document.createElement(tag); n.textContent=text; n.className=className; return n; }
const metres=(value:number) => new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(value/1000)+' m';

export function showEntryDetails(entry:SavedWorldEntry, customize:(()=>Promise<void>)|null=null): void {
  const dialog=document.createElement('dialog'); dialog.className='ux-entry-details ux-noveuis'; dialog.setAttribute('aria-labelledby','ux-entry-details-title');
  const previous=document.activeElement as HTMLElement|null;
  const header=node('header'); const heading=node('h2',entry.title); heading.id='ux-entry-details-title';
  const close=node('button','','ux-details-close') as HTMLButtonElement; close.type='button'; close.setAttribute('aria-label','Close world details'); close.append(icon('close'));
  header.append(heading,close); dialog.append(header);
  const body=node('div','','ux-details-body'); body.append(node('p','Reading world details…')); dialog.append(body);
  const footer=node('footer'); const change=node('button','Customize appearance','ux-details-action') as HTMLButtonElement; change.type='button';
  change.hidden=customize===null || entry.availability!=='available' || !(entry.generatedGround || entry.generatedSite || entry.generatedTerrain); footer.hidden=change.hidden;
  footer.append(change); dialog.append(footer);
  const abort=new AbortController();
  const dismiss=()=>{abort.abort(); dialog.close(); dialog.remove(); previous?.isConnected && previous.focus({preventScroll:true});};
  close.onclick=dismiss; dialog.addEventListener('cancel',event=>{event.preventDefault();dismiss();});
  change.onclick=()=>{dismiss(); if(customize) void customize();};
  const read=async(path:string) => {const r=await fetch('/review-api'+path,{signal:abort.signal,cache:'no-store'}); if(!r.ok) throw Error('World details could not be read.'); return r.json();};
  const fact=(parent:HTMLElement,label:string,value:string) => {const row=node('div','','ux-details-fact'); row.append(node('dt',label),node('dd',value)); parent.append(row);};
  const section=(title:string)=>{const s=node('section'); s.append(node('h3',title)); body.append(s); return s;};
  const load=async()=>{
    body.replaceChildren(node('p','Reading world details…'));
    const world='?world_id='+encodeURIComponent(entry.worldId);
    const [site,styles,packs]=await Promise.allSettled([
      read('/world/versions/'+encodeURIComponent(entry.authoredVersionId)+'/site'+world),
      read('/world/styles/versions'+world), read('/world/style-packs'),
    ]);
    if (!dialog.isConnected || abort.signal.aborted) return;
    body.replaceChildren();
    const facts=node('dl'); body.append(facts);
    fact(facts,'World type',entry.generatedSite?.kindLabel ?? entry.generatedGround?.recipeLabel ?? (entry.generatedTerrain ? 'Terrain world' : entry.sourceKind==='personal' ? 'World from photographs' : 'Authored world'));
    const parameters=section('Parameters');
    if (site.status==='fulfilled' && site.value.world_id===entry.worldId && site.value.extent) {
      const dimensions=node('dl'); fact(dimensions,'Width',metres(site.value.extent.widthMm)); fact(dimensions,'Depth',metres(site.value.extent.depthMm)); parameters.append(dimensions);
    } else if(entry.generatedSite) parameters.append(node('p','Site dimensions could not be read.'));
    if(entry.generatedGround?.values) {
      const values=node('dl'); for(const [key,value] of Object.entries(entry.generatedGround.values)) fact(values,key,String(value)); parameters.append(values);
      parameters.append(node('p','Generation inputs are read-only. Changing them creates another world.','ux-details-note'));
    } else if(entry.generatedSite) parameters.append(node('p','Generation inputs are not available for this saved site.','ux-details-note'));
    else if(entry.declaredFloor) { const floor=node('dl'); fact(floor,'Floor width',metres(entry.declaredFloor.halfExtentMm*2)); fact(floor,'Floor elevation',metres(entry.declaredFloor.elevationMm)); parameters.append(floor); }
    else parameters.append(node('p','No generation parameters are available for this world.','ux-details-note'));
    const appearance=section('Appearance');
    if(styles.status==='fulfilled' && packs.status==='fulfilled') {
      const versions=Array.isArray(styles.value) ? styles.value : styles.value.versions;
      const version=versions?.find((v)=>v.version_id===entry.styleVersionId);
      const listed=Array.isArray(packs.value) ? packs.value : packs.value.packs;
      const bound=version?.style_pack;
      let chosen=bound ? listed?.find((p)=>p.pack_id===bound.pack_id && (p.manifest_sha256===bound.manifest_sha256 || p.earlier_versions?.some(v=>v.manifest_sha256===bound.manifest_sha256))) : listed?.find(p=>p.default===true);
      if(bound?.source==='workspace') {
        try {
          const held=await read('/workspace-style-packs/'+encodeURIComponent(bound.manifest_sha256));
          if(held.ready===true && held.pack_id===bound.pack_id && held.manifest_sha256===bound.manifest_sha256 && held.manifest?.version===bound.version) {
            const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonicalJson(held.manifest))))).map(byte=>byte.toString(16).padStart(2,'0')).join('');
            if(digest===bound.manifest_sha256) chosen=held.manifest;
          }
        } catch {}
      }
      if(abort.signal.aborted) return;
      const lookFacts=node('dl'); fact(lookFacts,'Look',version ? chosen?.title ?? (bound ? bound.pack_id : 'Host default') : 'Appearance record unavailable'); appearance.append(lookFacts);
      const profile=version?.global_style;
      if(profile?.parameters) {
        const recipe=WORLD_STYLE_RECIPES.find(r=>r.profile.profileId===profile.profile_id && r.profile.profileVersion===profile.profile_version);
        const more=node('details','','ux-details-parameters'); more.append(node('summary','Appearance parameters'));
        const values=node('dl');
        for(const [key,value] of Object.entries(profile.parameters)) {
          const control=recipe?.controls.find(c=>c.key===key);
          const label=control?.label ?? key;
          const named=control?.kind==='choice' ? control.options.find(o=>o.value===value)?.label : null;
          fact(values,label,named ?? String(value));
        }
        more.append(values); appearance.append(more);
      }
    } else appearance.append(node('p','The appearance record could not be read. Close this view and try again.','ux-details-note'));
  };
  document.body.append(dialog); dialog.showModal(); close.focus();
  const retryLoad=()=>void load().catch(()=>{if(!abort.signal.aborted) {body.replaceChildren(node('p','World details could not be read.')); const retry=node('button','Retry','ux-details-action') as HTMLButtonElement; retry.type='button'; retry.onclick=retryLoad; body.append(retry);}});
  retryLoad();
}
