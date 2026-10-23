import { canonicalJson } from '../../../web/packages/atlas-core/src/style-pack.ts';
import { accessHeaders, type Credentials } from '/src/config.ts';
import { say } from '/src/ui/copy.ts';
import { icon } from '/src/ui/system/icon.ts';
import type { SavedWorldEntry } from '/src/world-entry-api.ts';
import type { ListedStylePack } from '/src/world-look.ts';

// Details: the chosen world's saved facts, read only. Changing a world happens inside it.

function node(tag: string, text = '', className = '') { const n = document.createElement(tag); n.textContent = text; n.className = className; return n; }
const metres = (value: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value / 1000) + ' m';

export function showWorldDetails(entry: SavedWorldEntry, credentials: Credentials): void {
  const dialog = document.createElement('dialog'); dialog.className = 'ux-entry-details ux-noveuis'; dialog.setAttribute('aria-labelledby', 'ux-entry-details-title');
  const previous = document.activeElement as HTMLElement | null;
  const header = node('header'); const heading = node('h2', entry.title); heading.id = 'ux-entry-details-title';
  const close = node('button', '', 'ux-details-close') as HTMLButtonElement; close.type = 'button'; close.setAttribute('aria-label', 'Close details'); close.append(icon('close'));
  header.append(heading, close); dialog.append(header);
  const body = node('div', '', 'ux-details-body'); body.append(node('p', 'Reading this world’s details…')); dialog.append(body);
  const abort = new AbortController();
  const dismiss = () => { abort.abort(); dialog.close(); dialog.remove(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  close.onclick = dismiss; dialog.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
  const read = async (path: string) => { const r = await fetch(credentials.baseUrl + path, { headers: { ...accessHeaders(credentials), Accept: 'application/json' }, credentials: 'same-origin', signal: abort.signal, cache: 'no-store' }); if (!r.ok) throw Error('World details could not be read.'); return r.json(); };
  const fact = (parent: HTMLElement, label: string, value: string) => { const row = node('div', '', 'ux-details-fact'); row.append(node('dt', label), node('dd', value)); parent.append(row); };
  const section = (title: string) => { const s = node('section'); s.append(node('h3', title)); body.append(s); return s; };
  const load = async () => {
    body.replaceChildren(node('p', 'Reading this world’s details…'));
    const world = '?world_id=' + encodeURIComponent(entry.worldId);
    const [site, styles, packs] = await Promise.allSettled([
      read('/world/versions/' + encodeURIComponent(entry.authoredVersionId) + '/site' + world),
      read('/world/styles/versions' + world), read('/world/style-packs'),
    ]);
    if (!dialog.isConnected || abort.signal.aborted) return;
    body.replaceChildren();
    const facts = node('dl'); body.append(facts);
    fact(facts, 'Kind of world', entry.generatedSite?.kindLabel ?? entry.generatedGround?.recipeLabel
      ?? (entry.generatedTerrain ? 'Terrain world' : say(entry.sourceKind === 'personal' ? 'yourWorlds.kind.personal' : 'yourWorlds.kind.authored')));
    const size = section('Size');
    if (site.status === 'fulfilled' && site.value.world_id === entry.worldId && site.value.extent) {
      const dimensions = node('dl'); fact(dimensions, 'Width', metres(site.value.extent.widthMm)); fact(dimensions, 'Depth', metres(site.value.extent.depthMm)); size.append(dimensions);
    } else if (entry.generatedSite) size.append(node('p', 'Its size could not be read.', 'ux-details-note'));
    else if (entry.declaredFloor) { const floor = node('dl'); fact(floor, 'Floor width', metres(entry.declaredFloor.halfExtentMm * 2)); fact(floor, 'Floor elevation', metres(entry.declaredFloor.elevationMm)); size.append(floor); }
    else size.append(node('p', 'No size is saved for this world.', 'ux-details-note'));
    const appearance = section('Appearance');
    if (styles.status === 'fulfilled' && packs.status === 'fulfilled') {
      const versions = Array.isArray(styles.value) ? styles.value : styles.value.versions;
      const version = versions?.find((v: { readonly version_id: string }) => v.version_id === entry.styleVersionId);
      const listed = Array.isArray(packs.value) ? packs.value : packs.value.packs;
      const bound = version?.style_pack;
      let chosen = bound ? listed?.find((p: ListedStylePack) => p.pack_id === bound.pack_id && (p.manifest_sha256 === bound.manifest_sha256 || p.earlier_versions?.some(v => v.manifest_sha256 === bound.manifest_sha256))) : listed?.find((p: ListedStylePack) => p.default === true);
      if (bound?.source === 'workspace') {
        try {
          const held = await read('/workspace-style-packs/' + encodeURIComponent(bound.manifest_sha256));
          if (held.ready === true && held.pack_id === bound.pack_id && held.manifest_sha256 === bound.manifest_sha256 && held.manifest?.version === bound.version) {
            const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalJson(held.manifest))))).map(byte => byte.toString(16).padStart(2, '0')).join('');
            if (digest === bound.manifest_sha256) chosen = held.manifest;
          }
        } catch { /* the look's name stays unknown */ }
      }
      if (abort.signal.aborted) return;
      // A look bound to this world but not found is not known; an unbound world wears the standard look.
      const lookFacts = node('dl'); fact(lookFacts, 'Look', version ? chosen?.title ?? (bound ? 'Not known' : 'The standard look') : 'Not known'); appearance.append(lookFacts);
    } else appearance.append(node('p', 'Its appearance could not be read. Close this and try again.', 'ux-details-note'));
  };
  document.body.append(dialog); dialog.showModal(); close.focus();
  const retryLoad = () => void load().catch(() => { if (!abort.signal.aborted) { body.replaceChildren(node('p', 'This world’s details could not be read.')); const retry = node('button', 'Try again', 'ux-details-action') as HTMLButtonElement; retry.type = 'button'; retry.onclick = retryLoad; body.append(retry); } });
  retryLoad();
}
