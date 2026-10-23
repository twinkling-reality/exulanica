// The follow view's frame for a talking scene (F8, DESIGN's aha item 11): while the scene shows, the camera
// keeps its speaker in view, and the listener where both fit, with nothing between it and the speaker and no
// wall across much of the frame. It is History's moment framing (moment-framing.mjs framingInSight: the one
// speaking most prominent, a side where no bystander stands nearer and larger, the foreground's share bounded,
// stepping back within the band) at the live camera's own lens. contextual-world.ts's framePair eases to it
// as it eases to a pair, and back when the scene closes. It is asked again when the speaker or the one spoken
// to changes, and when the speaker is no longer seen or has left the frame (checked every `checkMs`).
import { MOMENT_FRAMING, foregroundShare, framingInSight } from './moment-framing.mjs';
import { sceneHit, sceneSight } from './scene-sight.ts';

/** How often a framed speaker is checked, ms, and how far from them another person counts as a bystander, metres. */
export const SCENE_FOLLOW = Object.freeze({ checkMs: 500, nearMetres: 20 });

type Point = { x: number; y: number; z: number };
type Pose = Point & { yaw: number; pitch: number };
/** What the talking scene shows (talk-scene.mjs shown()): whether it shows, and its line's speaker and listener. */
type Shown = { readonly showing: boolean; readonly now: { readonly speaker: string; readonly to?: string | null } | null } | null | undefined;

/** Where someone stands as the crowd draws them (render space), with their drawn height and heading; null where not drawn. */
function anchorOf(society: any, id: string): (Point & { height: number; heading: number }) | null {
  const at = { x: 0, y: 0, z: 0, set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; } };
  if (!society?.groundOf?.(id, at)) return null;
  return { x: at.x, y: at.y, z: at.z, height: society.heightOf?.(id) ?? Number.NaN, heading: society.headingOf?.(id) ?? Number.NaN };
}

/**
 * One world view's scene framing. `saw(shown)` hands it what the scene shows each frame; `pose(now)` answers
 * the pose (the controls' frame, as pairFraming's) to hold while it shows, or null: no scene, nobody drawn,
 * or no side that sees the speaker, where the follow view keeps its own frame.
 */
export function createSceneFollow(binding: any, recipe: typeof MOMENT_FRAMING = MOMENT_FRAMING, rule = SCENE_FOLLOW) {
  let shown: Shown = null, key: string | null = null, pose: Pose | null = null, checkedAt = Number.NEGATIVE_INFINITY;
  let hit: ReturnType<typeof sceneHit> | null = null;

  /** The live lens: the recipe's framing at the world camera's field of view and the window's shape. */
  const live = () => ({ ...recipe, fov_deg: binding.camera?.camera?.fov ?? recipe.fov_deg, size_px: [innerWidth, innerHeight] });

  function frame(speaker: string, listener: string | null): Pose | null {
    const society = binding.authoredSociety;
    const first = anchorOf(society, speaker);
    if (first === null) return null;
    const second = listener ? anchorOf(society, listener) : null;
    const subjects = second ? [first, second] : [first];
    const bystanders = ((society?.visibleInhabitantIds ?? []) as readonly string[])
      .filter((id) => id !== speaker && id !== listener)
      .map((id) => anchorOf(society, id))
      .filter((one): one is NonNullable<typeof one> => one !== null && Math.hypot(one.x - first.x, one.z - first.z) <= rule.nearMetres);
    const lens = live();
    hit = sceneHit(binding.app);
    const scene = hit;
    const sighted = framingInSight(subjects, sceneSight(scene, recipe.sight.own_m), lens as typeof recipe,
      (at: Pose, framed: readonly object[]) => foregroundShare(at, framed, scene, lens as typeof recipe), bystanders) as Pose | null;
    if (sighted === null) return null;
    // The framing is in render space, which starts where the world was last re-centred; the controls'
    // pose and the camera's position say by how much.
    const eye = binding.camera.getPosition(), held = binding.controls.state;
    return { ...sighted, x: sighted.x + held.x - eye.x, y: sighted.y + held.y - eye.y, z: sighted.z + held.z - eye.z };
  }

  /** Whether the speaker's head is in the frame and nothing the scene draws stands between it and the camera. */
  function stillSeen(speaker: string): boolean {
    const at = anchorOf(binding.authoredSociety, speaker);
    if (at === null || hit === null) return false;
    const head = { x: at.x, y: at.y + (Number.isFinite(at.height) ? at.height : recipe.subject_height_m), z: at.z };
    const seen = binding.camera?.camera?.worldToScreen?.({ x: head.x, y: head.y, z: head.z, clone() { return this; } });
    const inFrame = !seen || (seen.z > 0 && seen.x >= 0 && seen.x <= innerWidth && seen.y >= 0 && seen.y <= innerHeight);
    const eye = binding.camera.getPosition();
    return inFrame && sceneSight(hit, recipe.sight.own_m)({ x: eye.x, y: eye.y, z: eye.z }, head);
  }

  return {
    saw(next: Shown): void { shown = next; },
    pose(now: number): Pose | null {
      const line = shown?.showing ? shown.now : null;
      if (!line) { key = null; pose = null; hit = null; return null; }
      const asked = `${line.speaker}|${line.to ?? ''}`;
      if (asked !== key) {
        key = asked; checkedAt = now; pose = frame(line.speaker, line.to ?? null);
      } else if (now - checkedAt >= rule.checkMs) {
        checkedAt = now;
        if (!stillSeen(line.speaker)) pose = frame(line.speaker, line.to ?? null) ?? pose;
      }
      return pose;
    },
  };
}
