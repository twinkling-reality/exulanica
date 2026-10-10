/**
 * The setting a town not made yet will be made in, in Create a world: the Setting row under the
 * Look row, and what the making names.
 *
 * A town is made as its look has it unless the person took a setting a draft's words asked for
 * (`docs/style-pack-contract.md` section 12.1). An offered setting is shown under Describe it with
 * the words it came from and is taken only by the person's own press on it, never with the
 * draft's values: an offer may carry a part no word asked for, and a town is not made in one the
 * person did not choose. Once taken it is theirs: it stays through later drafts until they press
 * "Draw it as the look has it" or take another. The making then names the parts
 * (`style_pack.setting_parts` on `POST /worlds/generated`), and the host composes them into the
 * setting for the look the town is made in and holds it to the setting's own rules. A setting is
 * asked for with a pack, so where the person chose no look the making names the host's default
 * exactly as the host lists it; a host that lists no look has nothing to draw a setting over, and
 * says none. A part is named by the title the host's own list gives it; parts the list does not
 * hold cannot be named, so they are neither shown nor taken. Nothing here is saved: once the town
 * is made, its setting is changed in the Look sheet like any world's.
 */

import { fill, say } from '../ui/copy.js';
import { el, setText } from '../ui/dom.js';
import type { DraftSetting } from '../ui/world-description.js';
import type { OfferedSetting } from '../world-draft-api.js';
import type { WorldStylePackBinding } from '../world-style-api.js';
import type { LookLibrary } from './look-library.js';

export interface TownSetting {
  /** The row under the Look row: the setting, why it is this one, and a way back to the look's own. */
  readonly row: HTMLElement;
  /** What the making names: a part for an axis, or null for none, which is the look as it states. */
  parts(): Readonly<Record<string, string>> | null;
  /**
   * What the making names, given the look's own (`pack`, null for the host's default): the pack
   * with the taken parts, the host's default named exactly where `pack` is null; with no part
   * taken, `pack` as it is.
   */
  madeIn(pack: WorldStylePackBinding | null): WorldStylePackBinding | null;
  /** The description panel's side: a draft's offered setting, shown, and taken by its own press. */
  readonly drafted: DraftSetting;
}

export function buildTownSetting(options: {
  /** The host's looks and named parts; a list that cannot be read leaves the row hidden and every offer unnamed. */
  readonly library: Promise<LookLibrary>;
}): TownSetting {
  let looks: LookLibrary | null = null;
  // Null until the person takes an offered setting: the look as it states.
  let taken: OfferedSetting | null = null;
  const watchers: (() => void)[] = [];

  /** The host's named parts; null until its list is read, and from a host with no look to draw them over. */
  const listed = (): LookLibrary['settings'] => (looks === null || looks.defaultId === null ? null : looks.settings);
  /** The parts of `offer` the host lists, in the axes' order, each with its title. */
  const known = (offer: OfferedSetting): readonly { readonly axis: string; readonly key: string; readonly title: string }[] => {
    const settings = listed();
    if (settings === null) return [];
    return settings.axes.flatMap((axis) => {
      const part = settings.parts.find((one) => one.axis === axis.key && one.key === offer.parts[axis.key]);
      return part === undefined ? [] : [{ axis: axis.key, key: part.key, title: part.title }];
    });
  };

  const words = el('span', { class: 'look-row-line' });
  const clear = el('button', { type: 'button', class: 'look-row-change', 'data-action': 'setting.clear', text: say('worldRecipes.setting.clear'), hidden: true }) as HTMLButtonElement;
  const row = el('section', { class: 'look-row town-setting-row', 'aria-label': say('worldRecipes.setting.label'), hidden: true }, [
    el('p', { class: 'look-row-label', text: say('worldRecipes.setting.label') }),
    el('div', { class: 'look-row-body' }, [el('span', { class: 'look-row-words' }, [words]), clear]),
  ]);
  const show = (): void => {
    // Said only once the host's parts are read: a host that lists none has no setting to say.
    row.hidden = listed() === null;
    const parts = taken === null ? [] : known(taken);
    clear.hidden = parts.length === 0;
    setText(words, taken === null || parts.length === 0 ? say('worldRecipes.setting.none') : fill('worldRecipes.setting.fromWords', {
      titles: parts.map((part) => part.title).join(', '),
      phrases: taken.settingWords.map((phrase) => fill('worldDescription.quoted', { phrase })).join(', '),
    }));
  };
  const changed = (): void => {
    show();
    for (const watcher of watchers) watcher();
  };
  clear.addEventListener('click', () => {
    taken = null;
    changed();
  });

  void options.library.then((library) => {
    looks = library;
    changed();
  }, () => undefined);

  const parts = (): Readonly<Record<string, string>> | null => {
    if (taken === null) return null;
    const named = known(taken);
    return named.length === 0 ? null : Object.fromEntries(named.map((part) => [part.axis, part.key]));
  };

  return {
    row,
    parts,
    madeIn(pack) {
      const settingParts = parts();
      if (settingParts === null) return pack;
      // Parts are known only once the list is read and holds a default, so this names a pack.
      const named = pack ?? (looks === null || looks.defaultId === null ? null : looks.binding(looks.defaultId));
      return named === null ? pack : { ...named, settingParts };
    },
    drafted: {
      offered(offer) {
        const parts = known(offer);
        return parts.length === 0 ? null : parts.map((part) => part.title);
      },
      take(offer) {
        // Parts the host does not list cannot be named, so they are not taken.
        if (known(offer).length === 0) return false;
        taken = offer;
        changed();
        return true;
      },
      holds(offer) {
        if (taken === null) return false;
        const now = known(taken).map((part) => `${part.axis}=${part.key}`).join(' ');
        const asked = known(offer).map((part) => `${part.axis}=${part.key}`).join(' ');
        return asked !== '' && now === asked;
      },
      watch(watcher) {
        watchers.push(watcher);
      },
    },
  };
}
