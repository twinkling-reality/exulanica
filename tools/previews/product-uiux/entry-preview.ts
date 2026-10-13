import {isScenePreview} from './world-handoff.mjs';
import type { SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api';

const READY = 'exulanica.review.scene-ready';
const TICK = 'exulanica.review.scene-motion';
const live = new URLSearchParams(location.search).get('livePreview')==='1';
const capture=isScenePreview(new URL(location.href));

// A preview has no write path, including during native startup.
if (capture) {
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET') {
      document.documentElement.dataset.previewWriteRefusals = String(Number(document.documentElement.dataset.previewWriteRefusals ?? 0) + 1);
      console.warn('Read-only world preview refused a ' + method + ' request.');
      return Promise.resolve(new Response(JSON.stringify({ detail: 'The world preview is read-only.' }), { status:405, headers:{'Content-Type':'application/json'} }));
    }
    return original(input, init);
  };
}

/** Native camera motion in a temporary, inert renderer. Simulation time is untouched. */
export function mountReadonlyScenePreview({state, renderer}): void {
  if (!live || window.parent === window) return;
  const entry = state.activeWorldEntry, binding = renderer.atlas?.binding;
  if (!entry || !binding) return;
  const pose = {...binding.controls.state};
  const pins = {entryId:entry.entryId, versionId:entry.authoredVersionId, styleVersionId:entry.styleVersionId, stateSha:entry.authoredStateSha256};
  let frame = 0, origin = performance.now(), lastNotice = 0;
  const tick = (now:number) => {
    if (!document.hidden) {
      const elapsed = (now-origin)/1000;
      const yaw = pose.yaw + Math.sin(elapsed/13)*.035;
      binding.controls.setView({...pose, yaw, pitch:pose.pitch+Math.sin(elapsed/19)*.006}, 'altitude');
      binding.invalidate();
      if (now-lastNotice>1000) { lastNotice=now; window.parent.postMessage({type:TICK,...pins,yaw},location.origin); }
    }
    frame=requestAnimationFrame(tick);
  };
  frame=requestAnimationFrame(tick);
  requestAnimationFrame(() => requestAnimationFrame(() => window.parent.postMessage({type:READY,...pins},location.origin)));
  window.addEventListener('pagehide',()=>cancelAnimationFrame(frame),{once:true});
}

/** Background lifecycle: recorded image while loading, then the same owned native scene. */
export function createEntryPreview(root:HTMLElement) {
  const field=document.createElement('div'); field.className='ux-entry-image'; field.setAttribute('aria-hidden','true'); root.prepend(field);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let enabled=!capture && !reduced.matches, selected:SavedWorldEntry|null=null, source:string|null=null;
  let still:HTMLElement|null=null, current:HTMLIFrameElement|null=null, waiting:HTMLIFrameElement|null=null;
  let disposed=false, sequence=0;
  const retire=(node:HTMLElement|null) => {
    if (!node) return;
    node.style.opacity='0'; setTimeout(()=>node.remove(),650);
  };
  const stopNative=() => { current?.remove(); waiting?.remove(); current=null; waiting=null; root.dataset.nativePreview='paused'; };
  const startNative=() => {
    if (!selected || !enabled || disposed) return;
    waiting?.remove();
    const iframe=document.createElement('iframe'); iframe.className='ux-entry-live'; iframe.title=selected.title+' scene preview'; iframe.tabIndex=-1; iframe.inert=true;
    const url=new URL(location.origin+'/'); url.searchParams.set('entry',selected.entryId); url.searchParams.set('capture','1'); url.searchParams.set('livePreview','1');
    iframe.src=url.href; iframe.style.opacity='0'; waiting=iframe; field.append(iframe); root.dataset.nativePreview='loading';
  };
  const receive=(event:MessageEvent) => {
    if (event.origin!==location.origin || !selected) return;
    const target = event.source===waiting?.contentWindow ? waiting : event.source===current?.contentWindow ? current : null;
    if (!target) return;
    const data=event.data;
    if (data?.entryId!==selected.entryId || data.versionId!==selected.authoredVersionId || data.styleVersionId!==selected.styleVersionId || data.stateSha!==selected.authoredStateSha256) return;
    if (data.type===READY && target===waiting) {
      const old=current; current=waiting; waiting=null; current!.style.opacity='1'; retire(old); root.dataset.nativePreview='ready';
    } else if (data.type===TICK && target===current) root.dataset.previewCameraYaw=String(data.yaw);
  };
  window.addEventListener('message',receive);
  const preference=() => { if (reduced.matches) { enabled=false; stopNative(); } };
  reduced.addEventListener('change',preference);
  return {
    field,
    get enabled() { return enabled; },
    select(entry:SavedWorldEntry,picture:string|null) {
      selected=entry; source=picture; const serial=++sequence;
      const next=document.createElement('div'); next.className='ux-entry-still'; next.style.backgroundImage=source ? `url("${source}")` : 'none'; next.style.opacity='0'; field.append(next);
      const prior=still; still=next;
      requestAnimationFrame(()=>{ if(serial!==sequence || disposed) { next.remove(); return; } next.style.opacity='1'; retire(prior); });
      if (current) retire(current); current=null;
      startNative();
    },
    toggle() { enabled=!enabled; if(enabled) startNative(); else stopNative(); return enabled; },
    dispose() { disposed=true; ++sequence; stopNative(); window.removeEventListener('message',receive); reduced.removeEventListener('change',preference); field.remove(); },
  };
}
