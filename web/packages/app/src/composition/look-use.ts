/**
 * What pressing Use on a card of the Look sheet asks the host for, and what the sheet calls it.
 *
 * A pack offered at a later version than the one a world wears has two cards in the sheet: the
 * world's own, "Now · version k", and the offered "Version N". They name the same pack, so the
 * card pressed decides, not the pack:
 *
 * - the Now card can only be used to save a changed setting, and keeps exactly the version the
 *   world names, an earlier one included: a person changing the hour is not moved to a version
 *   they did not ask for;
 * - any other card asks for the pack as the host lists it now, which for the offered version of
 *   the world's own pack is the move to that version, said by its number.
 *
 * The parts chosen go with the pack for the host to compose for it; none asks for the pack as it
 * states. A world wearing its workspace's own look names that look, never a library version, so
 * its Now card asks for the listed pack like any other.
 */

import type { WorldStylePackBinding } from '../world-style-api.js';

export interface LookUse {
  /** The pack, version and digest to ask for, with the parts of the setting chosen, if any. */
  readonly binding: WorldStylePackBinding;
  /** What the sheet calls the look once it is saved, after "drawn in". */
  readonly named: string;
  /** Whether this keeps the look the world wears and changes only its setting. */
  readonly settingOnly: boolean;
}

export function lookToUse(pressed: {
  readonly option: { readonly packId: string; readonly title: string };
  /** The card pressed is the one the world is drawn in now. */
  readonly isNow: boolean;
  /** The part chosen for each axis that has one; undefined from a sheet that shows no setting. */
  readonly setting: Readonly<Record<string, string>> | undefined;
  /** What the world names now, or null for none. */
  readonly worn: WorldStylePackBinding | null;
  /** The pressed pack as the host lists it now. */
  readonly listed: WorldStylePackBinding;
  /** The pack the world wears an earlier version of, or null where it wears none. */
  readonly earlierPackId: string | null;
}): LookUse {
  const { option, setting, worn } = pressed;
  const settingOnly = pressed.isNow && setting !== undefined && worn !== null && worn.own === undefined
    && worn.packId === option.packId;
  const pack: WorldStylePackBinding = settingOnly
    ? { packId: worn.packId, version: worn.version, manifestSha256: worn.manifestSha256 }
    : { packId: pressed.listed.packId, version: pressed.listed.version, manifestSha256: pressed.listed.manifestSha256 };
  const binding: WorldStylePackBinding = setting === undefined || Object.keys(setting).length === 0
    ? pack : { ...pack, settingParts: setting };
  const named = settingOnly ? `${option.title}, in its new setting`
    : pressed.earlierPackId === option.packId ? `version ${binding.version} of ${option.title}` : option.title;
  return { binding, named, settingOnly };
}
