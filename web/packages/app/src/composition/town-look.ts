/**
 * The look a town not made yet will be made in, in Create a world: the Look row above Create this
 * town, the Look sheet Change look opens to choose only, and what the making names.
 *
 * Three things can have chosen the look, and the row says which:
 *
 * - nobody: the host's default, and the making names no pack, so the host binds its own default;
 * - the person, in the Look sheet: the making names that pack as the host lists it;
 * - the person's words, through a draft whose look offer they took with its values
 *   (`docs/style-pack-contract.md` section 10.1): the making names exactly the pack, version and
 *   manifest digest the offer named, so the town is made in what was offered and shown.
 *
 * The look follows the draft that is taken, unless the person chose the look themselves (`take`).
 * A draft that offers a look brings it; a draft whose words ask for no look returns a look that
 * came with an earlier draft to the host's default, so the row never quotes words of a sentence
 * the town is no longer drafted from. A look the person chose is never replaced by a draft: one
 * chosen in the sheet stays, the description panel offers the other with one press
 * (`takeInstead`), and a look taken by that press is theirs too. A draft whose look step did not
 * answer, or that carries no offer, changes nothing. An offered look is named by the title the
 * host's own list gives its pack; one the list does not hold cannot be named, so it is neither
 * shown nor taken. Nothing here is saved: the look is sent with the making (`style_pack` on
 * `POST /worlds/generated`), and a version the host no longer holds is refused there in the
 * making's own words, with the draft left as it is.
 */

import { fill, say } from '../ui/copy.js';
import { buildLookRow, buildLookSheet, type LookOption } from '../ui/look-sheet.js';
import type { DraftLook } from '../ui/world-description.js';
import type { OfferedLook } from '../world-draft-api.js';
import type { WorldStylePackBinding } from '../world-style-api.js';
import type { LookLibrary } from './look-library.js';

export interface TownLook {
  /** The row above Create this town: the look, why it is this one, and Change look. */
  readonly row: HTMLElement;
  /**
   * What the making names: the exact pack, or null for none, which the host makes in its default.
   */
  binding(): WorldStylePackBinding | null;
  /** The description panel's side: a draft's offered look, shown and taken. */
  readonly drafted: DraftLook;
}

/**
 * Who chose the town's look: the person in the sheet, or their words through a draft. A look from
 * their words came with the draft they took, or (`pressed`) by their own press in place of a look
 * they had chosen, which makes it theirs: only the first follows the next draft taken.
 */
type Chosen =
  | { readonly by: 'person'; readonly packId: string }
  | { readonly by: 'words'; readonly offer: OfferedLook; readonly pressed: boolean };

export function buildTownLook(options: {
  /** The host's looks; a list that cannot be read leaves the row hidden and every offer unnamed. */
  readonly library: Promise<LookLibrary>;
  /** Where the Look sheet opens, over Create a world. */
  readonly host: HTMLElement;
}): TownLook {
  let looks: LookLibrary | null = null;
  // Null until someone chooses: the host's default, which the making names no pack for.
  let chosen: Chosen | null = null;
  const watchers: (() => void)[] = [];

  const listed = (packId: string | null): LookOption | undefined => (
    packId === null ? undefined : looks?.options.find((option) => option.packId === packId));
  const packId = (): string | null => (
    chosen === null ? looks?.defaultId ?? null : chosen.by === 'person' ? chosen.packId : chosen.offer.packId);

  const show = (): void => {
    const option = listed(packId());
    if (option === undefined) return;
    const line = chosen === null ? say('worldRecipes.look.default')
      : chosen.by === 'person' ? say('worldRecipes.look.chosen')
        : fill('worldRecipes.look.fromWords', {
          phrases: chosen.offer.lookWords.map((phrase) => fill('worldDescription.quoted', { phrase })).join(', '),
        });
    row.show(option, line);
  };
  const changed = (): void => {
    show();
    for (const watcher of watchers) watcher();
  };

  const row = buildLookRow(() => {
    if (looks === null) return;
    const library = looks;
    const focusBack = (): void => {
      row.root.querySelector<HTMLElement>('.look-row-change')?.focus({ preventScroll: true });
    };
    options.host.querySelector('section.look-sheet')?.remove();
    const sheet = buildLookSheet({
      worldTitle: 'A new town',
      choosing: { use: 'Choose this look', now: 'Chosen' },
      onUse: async (option) => {
        chosen = { by: 'person', packId: option.packId };
        changed();
        sheet.root.remove();
        focusBack();
        return '';
      },
      onClose: () => {
        sheet.root.remove();
        focusBack();
      },
    });
    options.host.append(sheet.root);
    sheet.show(library.options, packId());
    sheet.focus();
  });

  void options.library.then((library) => {
    looks = library;
    changed();
  }, () => undefined);

  /** Make an offered look the town's; false, and nothing changes, for one the host does not list. */
  const wear = (offer: OfferedLook, pressed: boolean): boolean => {
    if (listed(offer.packId) === undefined) return false;
    chosen = { by: 'words', offer, pressed };
    changed();
    return true;
  };

  return {
    row: row.root,
    binding() {
      if (chosen === null) return null;
      if (chosen.by === 'person') return looks?.binding(chosen.packId) ?? null;
      const offer = chosen.offer;
      return { packId: offer.packId, version: offer.version, manifestSha256: offer.manifestSha256 };
    },
    drafted: {
      offered(offer) {
        const option = listed(offer.packId);
        if (option === undefined) return null;
        const own = chosen !== null && chosen.by === 'person' && chosen.packId !== offer.packId
          ? listed(chosen.packId) : undefined;
        return { title: option.title, kept: own?.title ?? null };
      },
      take(offer) {
        // No offer, or a look step that did not answer: the look shown is kept.
        if (offer === null || offer.state === 'unavailable') return false;
        if (offer.state === 'none') {
          // The words of the draft taken ask for no look, so a look that came with an earlier
          // draft goes back to the host's default. A look the person chose themselves stays.
          if (chosen !== null && chosen.by === 'words' && !chosen.pressed) {
            chosen = null;
            changed();
          }
          return false;
        }
        if (chosen !== null && chosen.by === 'person') return false;
        // A look the person's own press took stays theirs when the draft that offers it is taken.
        const pressed = chosen !== null && chosen.by === 'words' && chosen.pressed
          && chosen.offer.packId === offer.packId;
        return wear(offer, pressed);
      },
      takeInstead: (offer) => wear(offer, true),
      watch(watcher) {
        watchers.push(watcher);
      },
    },
  };
}
