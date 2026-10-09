/**
 * Make a creature from the open world (CREATURE C6c): the sheet over the world, the creature routes,
 * and the placement of what was made, by its kind's digest alone, in front of the person.
 *
 * Opening reads the offer (whether creatures are made here, why not by code, how long one takes)
 * and any draft of this person's still running, so a reload never loses one. Make sends the words
 * (`POST /things/creatures`) and reads the draft every second, at most twice the drafter's
 * timeout and a margin. A kept creature is placed by the page's own edit path for a planned thing
 * (`place`, the Companion's `things.place`: the version's compare-and-swap, the saved entry's
 * advance, the objects and people told), at the pose the objects panel offers in front of the
 * person, facing them, or, in a saved world drawn from a recipe or a world kind, ahead of them in
 * that world's region (`placementInGeneratedRegion`). A refusal shows its code's fixed sentence and
 * keeps the words; a failure or
 * an erased creature says so in one sentence. Nothing here decides what the creature is: the
 * server's drafter and checks do.
 */

import { atlasVec3, type CameraPose } from '@exulanica/atlas-core';
import {
  DEFAULT_PLACEMENT_DISTANCE_MM,
  generatedRegionName,
  placementPoseBeforeVisitor,
  yawMicroradiansOf,
} from '@exulanica/atlas-react/playcanvas';
import { ApiError } from '@exulanica/graph-client';
import { draftEnded, type CreatureDraft, type CreatureDraftsClient, type CreatureOffer } from '../creature-drafts-api.js';
import type { CreatureSheet } from '../ui/creature-sheet.js';

/** Where a made creature is put: a region and a pose in front of the person, as the objects panel offers one. */
export interface CreaturePlacement {
  readonly region_id: string;
  readonly transform: { readonly x_mm: number; readonly y_mm: number; readonly z_mm: number; readonly yaw_microradians: number };
}

export interface CreatureMakerDeps {
  readonly client: CreatureDraftsClient;
  readonly sheet: CreatureSheet;
  /**
   * The open version and its state, and the saved entry an edit advances with it (`saved_entry`, as
   * object edits and the Companion's steps send it), or null when no world is open to change.
   */
  readonly version: () => {
    readonly versionId: string;
    readonly stateSha256: string;
    readonly savedEntry: {
      readonly entry_id: string;
      readonly base_revision: number;
      readonly authored_state_sha256: string;
      readonly authored_edit_seq: number;
    };
  } | null;
  /** Where to put it now, or null when the page cannot say where the person stands. */
  readonly placement: () => CreaturePlacement | null;
  /** Send the placement through the page's edit path for a planned thing; answers its status. */
  readonly place: (versionId: string, body: Readonly<Record<string, unknown>>) => Promise<{ readonly status: number }>;
  readonly wait?: (ms: number) => Promise<void>;
}

/** Why a world may not ask, in words, by the offer's code. */
const UNAVAILABLE: Readonly<Record<string, string>> = Object.freeze({
  creatures_not_run_here: 'Creatures are not made on this server yet.',
  models_not_configured: 'No model is set up on this server yet, so no creature can be made.',
});
/** Why an ask was refused before anything was queued, in words, by the route's code. */
const ASK_REFUSED: Readonly<Record<string, string>> = Object.freeze({
  words_refused: 'Describe it in one plain line.',
  words_too_long: 'That is longer than one creature\'s description can be.',
  creature_limit_reached: 'A creature of yours is still being made, or you have made as many as one may this hour.',
  creatures_not_run_here: UNAVAILABLE['creatures_not_run_here']!,
  tombstoned: 'This world\'s workspace is being erased, so nothing more is made in it.',
});
/** Why a draft ended without a creature, in words, by its failure code. */
const FAILED: Readonly<Record<string, string>> = Object.freeze({
  drafter_unavailable: 'The model that drafts creatures did not answer. Try again in a moment.',
  spending_refused: 'This world has no allowance left for drafting a creature.',
  request_refused: 'The words could not be sent to the model as they are.',
  expired: 'Nobody took the request in time. Try again.',
  stranded: 'The request stopped part way. Try again.',
  not_served: 'Creatures are no longer made on this server.',
  workspace_deleted: 'This world\'s workspace was erased.',
});

const sleep = (ms: number): Promise<void> => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * The yaw that turns a creature put ahead of the person round to face them. A place ahead carries
 * the person's own heading, and a thing's front is turned by its yaw (`facingOfYaw`), so without a
 * half turn the creature would stand with its back to them.
 */
export function facingThePerson(aheadYawMicroradians: number): number {
  return yawMicroradiansOf(aheadYawMicroradians / 1_000_000 + Math.PI);
}

/**
 * Where a made creature stands in a saved world drawn from a recipe or a world kind, where the
 * objects panel offers no placement: the ground ahead of the person, as far as the panel puts a
 * thing, facing the way they face, in the one region that world's people live in. That region's
 * frame is the city's, raised to the height where a person arrives (`hostGeneratedSociety`), so a
 * point in it is the person's atlas position less that height, on the plane its people stand on.
 * Null unless that region is the one drawn here (`drawnRegion`, the entity its people and things
 * hang from), so a creature is never placed where this page would not show it.
 */
export function placementInGeneratedRegion(
  generated: { readonly regionId: string; readonly arrivalMm: readonly number[] } | null | undefined,
  drawnRegion: string | null | undefined,
  pose: CameraPose | undefined,
): CreaturePlacement | null {
  if (generated == null || pose === undefined || drawnRegion !== generatedRegionName(generated.regionId)) return null;
  const ahead = placementPoseBeforeVisitor(
    { position: atlasVec3(0, (generated.arrivalMm[1] ?? 0) / 1000, 0), yaw: 0, scale: 1 },
    pose,
    DEFAULT_PLACEMENT_DISTANCE_MM,
  );
  return {
    region_id: generated.regionId,
    transform: { x_mm: ahead.xMm, y_mm: ahead.yMm, z_mm: ahead.zMm, yaw_microradians: ahead.yawMicroradians },
  };
}

export function offerWords(offer: CreatureOffer): { readonly unavailable: string | null; readonly timing: string } {
  return {
    unavailable: offer.offered ? null : UNAVAILABLE[offer.code ?? ''] ?? 'Creatures are not made here.',
    timing: `Usually about ${offer.timing.typicalSeconds} seconds; at most ${offer.timing.timeoutSeconds}.`,
  };
}

/** The sentence a draft that ended without a creature shows. */
export function endedWords(draft: CreatureDraft): string {
  if (draft.status === 'refused') return draft.refusal?.detail ?? 'The creature could not be made from those words.';
  if (draft.status === 'erased') return 'That creature was erased.';
  return FAILED[draft.failure ?? ''] ?? 'The creature could not be made. Try again.';
}

export function mountCreatureMaker(deps: CreatureMakerDeps): {
  readonly make: (words: string) => Promise<void>;
  readonly open: () => Promise<void>;
} {
  const wait = deps.wait ?? sleep;
  let timeoutSeconds = 50;
  let running = false;

  const follow = async (first: CreatureDraft): Promise<void> => {
    let draft = first;
    // Twice the call's timeout covers a call and its one repair; ten seconds more for the worker.
    const deadline = Date.now() + (2 * timeoutSeconds + 10) * 1000;
    while (!draftEnded(draft) && Date.now() < deadline) {
      await wait(1000);
      draft = await deps.client.draft(draft.draftId);
    }
    if (!draftEnded(draft)) {
      deps.sheet.notMade('It is taking longer than it should. It will be in your drafts when it ends.');
      return;
    }
    if (draft.status !== 'kept' || draft.kind === null) {
      deps.sheet.notMade(endedWords(draft));
      return;
    }
    const version = deps.version();
    const placement = deps.placement();
    if (version === null || placement === null) {
      deps.sheet.notMade('It was made, but this world cannot say where you stand, so it was not placed.');
      return;
    }
    deps.sheet.placing(draft.label);
    const { region_id: regionId, transform } = placement;
    const placed = await deps.place(version.versionId, {
      base_state_sha256: version.stateSha256,
      thing_id: `creature:${draft.draftId.slice(0, 8)}`,
      kind: { source: 'workspace', sha256: draft.kind.sha256 },
      region_id: regionId,
      pose: {
        x_mm: transform.x_mm, y_mm: transform.y_mm, z_mm: transform.z_mm,
        yaw_microradians: facingThePerson(transform.yaw_microradians),
      },
      origin_role: 'fictional',
      // The saved entry moves with the version in the same edit, so the world reopens where it was
      // left rather than asking to reconcile a change "saved elsewhere".
      saved_entry: version.savedEntry,
    });
    if (placed.status !== 201) {
      deps.sheet.notMade('It was made, but could not be placed here. It is kept among your things.');
      return;
    }
    deps.sheet.made(draft.label);
  };

  const guarded = async (step: () => Promise<void>): Promise<void> => {
    if (running) return;
    running = true;
    try {
      await step();
    } catch (error) {
      const code = error instanceof ApiError ? error.code : '';
      deps.sheet.notMade(ASK_REFUSED[code] ?? 'Something went wrong while making it. Try again.');
    } finally {
      running = false;
    }
  };

  return {
    async open() {
      let offer: CreatureOffer;
      try {
        offer = await deps.client.offer();
      } catch {
        deps.sheet.show({ unavailable: 'Creatures cannot be made here right now.', timing: null });
        return;
      }
      timeoutSeconds = offer.timing.timeoutSeconds;
      deps.sheet.show(offerWords(offer));
      deps.sheet.focus();
      const still = (await deps.client.drafts().catch(() => [])).find((draft) => !draftEnded(draft));
      if (still !== undefined) {
        deps.sheet.imagining();
        await guarded(() => follow(still));
      }
    },
    async make(words) {
      deps.sheet.imagining();
      await guarded(async () => follow(await deps.client.ask(words)));
    },
  };
}
