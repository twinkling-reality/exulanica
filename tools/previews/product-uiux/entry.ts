import './entry.css';
import './navigation-material.css';
import previews from './world-previews/catalog.json';
import {createEntryPreview} from './entry-preview';
import {showEntryDetails} from './entry-details';
import {worldEntryDestination, isScenePreview} from './world-handoff.mjs';
import type {SavedWorldEntry} from '../../../web/packages/app/src/world-entry-api';
import { icon, type IconName } from '../../../web/packages/app/src/ui/system/icon';
document.body.classList.add('ux-review');
if (isScenePreview(new URL(location.href))) document.body.classList.add('ux-capture-world');

// Native opening is reconstructed from the same owned saved entry after browser navigation.
window.addEventListener('popstate', () => { if (document.getElementById('shell')) location.reload(); });

export function reviewOpenEntry(entryId:string): void {
  if(document.querySelector('.ux-world-entry')) history.replaceState({...history.state,uxChooserEntryId:entryId},'',location.href);
  location.assign(worldEntryDestination(entryId));
}

export function reviewReturnToChooser(entryId?:string): void {
  const url=new URL('/?workspace=1',location.origin);
  history.replaceState({...history.state,...(entryId?{uxChooserEntryId:entryId}:{})},'',url);
  location.reload();
}

export function reviewWorldPicture(entry): string | null {
  const preview = previews.captures.find(p => p.entry_id === entry.entryId && p.world_id === entry.worldId
    && p.version_id === entry.authoredVersionId && p.authored_state_sha256 === entry.authoredStateSha256
    && p.style_version_id === entry.styleVersionId);
  return preview ? '/review-world-previews/' + preview.file : null;
}

/** Rearrange the native entry's nodes without replacing their actions or availability gates. */
export function mountEntryReview({root, entries}: {root:HTMLElement, entries:readonly SavedWorldEntry[]}): void {
  root.classList.add('ux-world-entry', 'ux-noveuis');
  root.querySelector('.your-worlds-corner').replaceChildren();
  const corner = root.querySelector('.your-worlds-corner');
  const identity = document.createElement('a'); identity.href = '/home'; identity.className = 'ux-entry-brand'; identity.setAttribute('aria-label', 'Exulanica home');
  identity.textContent = 'exulanica';
  corner.append(identity);
  const back = document.createElement('a'); back.href = '/home'; back.className = 'ux-entry-back entry-command'; back.setAttribute('aria-label','Back to Exulanica'); back.append(icon('back'), document.createTextNode('Back'));

  const hero = document.createElement('section'); hero.className = 'ux-entry-hero'; hero.setAttribute('aria-label', 'Selected world');
  const title = document.createElement('h1'); title.className = 'ux-entry-title';
  const lede = root.querySelector('.your-worlds-lede');
  const actions = root.querySelector('.your-worlds-actions');
  actions.prepend(back);
  const createRow = root.querySelector('.your-worlds-create-row');
  for (const [selector, name] of [['.your-worlds-open',null],['.your-worlds-create','add']] as const) {
    const control = root.querySelector(selector);
    if (name) control.prepend(icon(name));
    else {
      control.classList.add('ux-entry-orb');
      const ring=document.createElement('span'); ring.className='ux-orb-icon'; ring.setAttribute('aria-hidden','true'); ring.append(icon('forward')); control.append(ring);
    }
    const shortcut = control.querySelector('kbd');
    if (shortcut) { if (selector === '.your-worlds-open') shortcut.textContent='Enter'; control.append(shortcut); }
  }
  hero.append(title, lede);
  root.insertBefore(hero, root.querySelector('.your-worlds-strip'));
  const preview = createEntryPreview(root);
  const strip = root.querySelector('.your-worlds-strip');
  const arrows = document.createElement('nav'); arrows.className = 'ux-entry-arrows'; arrows.setAttribute('aria-label', 'Choose a world');
  function arrow(label: string, glyph: IconName, step: number) {
    const control = document.createElement('button'); control.type = 'button'; control.append(icon(glyph)); control.setAttribute('aria-label', label);
    control.onclick = () => { const cards = [...strip.querySelectorAll('.your-worlds-card')]; const current = cards.findIndex(c => c.getAttribute('aria-current') === 'true'); cards[Math.max(0, Math.min(cards.length - 1, current + step))]?.focus(); };
    arrows.append(control); return control;
  }
  const previous = arrow('Previous world', 'forward', -1), next = arrow('Next world', 'forward', 1);
  previous.classList.add('ux-entry-previous');
  const playback = document.createElement('button'); playback.type='button';
  const reflectPlayback=()=>{ playback.replaceChildren(icon(preview.enabled?'pause':'play')); playback.setAttribute('aria-label',preview.enabled?'Pause preview motion':'Play preview motion'); };
  playback.onclick=()=>{preview.toggle();reflectPlayback();}; reflectPlayback(); arrows.append(playback, createRow);
  root.insertBefore(arrows, strip);
  let selected:SavedWorldEntry|null=null;
  const details=document.createElement('button'); details.type='button'; details.className='entry-command ux-entry-details-open'; details.textContent='Details'; details.onclick=()=>{if(selected)showEntryDetails(selected);};
  actions.append(details);
  for (const card of strip.querySelectorAll('.your-worlds-card')) {
    const caption = document.createElement('span'); caption.className = 'ux-entry-card-caption'; caption.textContent = 'Saved world';
    card.insertBefore(caption, card.querySelector('.world-entry-choice-title'));
  }
  let currentId = null;
  function reflect() {
    const card = strip.querySelector('.your-worlds-card[aria-current="true"]');
    if (!card || card.dataset.entryId === currentId) return;
    currentId = card.dataset.entryId;
    const entry = entries.find(e => e.entryId === currentId); if (!entry) return;
    selected=entry;
    title.getAnimations().forEach(animation=>animation.cancel());
    title.textContent=entry.title;
    const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(!reduce) title.animate([{opacity:0,filter:'blur(7px)',transform:'translateY(5px)'},{opacity:1,filter:'blur(0px)',transform:'translateY(0px)'}],{duration:420,easing:'cubic-bezier(.25,.46,.45,.94)'});
    const source=reviewWorldPicture(entry) || card.querySelector('img')?.src || null;
    preview.select(entry,source);
    const inset=card.offsetLeft-strip.offsetLeft;
    if(inset<strip.scrollLeft || inset+card.offsetWidth>strip.scrollLeft+strip.clientWidth) strip.scrollTo({left:Math.max(0,inset-4),behavior:reduce?'instant':'smooth'});
    const cards = [...strip.querySelectorAll('.your-worlds-card')], index = cards.indexOf(card);
    previous.disabled = index === 0; next.disabled = index === cards.length - 1;
  }
  const observer=new MutationObserver(()=>reflect());
  observer.observe(strip,{attributes:true,attributeFilter:['aria-current'],subtree:true});
  const lifetime=new MutationObserver(()=>{if(!root.isConnected){observer.disconnect();lifetime.disconnect();preference.removeEventListener('change',reflectPlayback);preview.dispose();title.getAnimations().forEach(animation=>animation.cancel());}});
  lifetime.observe(root.parentElement!,{childList:true});
  const preference=matchMedia('(prefers-reduced-motion: reduce)'); preference.addEventListener('change',reflectPlayback);
  const remembered=history.state?.uxChooserEntryId;
  if(remembered) (Array.from(strip.querySelectorAll<HTMLElement>('.your-worlds-card')).find(card=>card.dataset.entryId===remembered))?.focus({preventScroll:true});
  void reflect();
}
