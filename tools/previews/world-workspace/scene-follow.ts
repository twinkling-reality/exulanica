// The follow view's frame for a talking scene (F8, DESIGN's aha item 11): while the scene shows, the camera
// keeps its speaker in view, and the listener where both fit, with nothing between it and the speaker and no
// wall across much of the frame. It is History's moment framing (moment-framing.mjs framingInSight: the one
// speaking most prominent, a side where no bystander stands nearer and larger, the foreground's share bounded,
// stepping back within the band) at the live camera's own lens. contextual-world.ts's framePair eases to it
// as it eases to a pair, and back when the scene closes. It is asked again when the speaker or the one spoken
// to changes. (F8b) A pair walking on is followed: between askings the frame is carried with the speaker as
// they walk (at the world's pace a walker crosses a frame within a second or two), and it is asked again when
// the speaker is no longer seen, or the speaker or a listener framed with them has drifted out of the middle
// of the width, at most once every `reaskLeastMs`. A frame asked again mid-scene is eased to from the pose the
// camera holds, never jumped to. (T1) It is asked again too when a passer-by has stood in front of the speaker,
// nearer and larger than them from the frame held (the framing's own band) and drawn over the speaker or the one
// spoken to (their boxes widened by `besideShare` of the frame's width), at `crowdedChecks` checks in a row:
// someone who stops or walks along the line, never one crossing it within a check nor one at the edge clear of both.
// The one spoken to counts too where they stand nearer than the speaker over the speaker's head.
import { easePose } from './character-view.mjs';
import { MOMENT_FRAMING, foregroundShare, framingInSight, lensOf, standsInBand } from './moment-framing.mjs';
import { sceneHit, sceneSight } from './scene-sight.ts';
import { TALK_FRAMING } from './talk-pops.mjs';

/**
 * How often a framed scene is checked, ms; how far from the speaker another person counts as a bystander,
 * metres; the middle share of the width the speaker (and a listener framed with them) is kept inside; the
 * least time between two frames asked in one scene, ms; how long the camera eases to a new one, ms; and at how
 * many checks in a row a passer-by in front of the speaker asks for a new frame (two: about a second); how wide a
 * person is drawn for that, metres; by what share of the frame's width the line's people's boxes are widened; and
 * how far down from the top of the speaker their head reaches, metres.
 */
export const SCENE_FOLLOW = Object.freeze({
  checkMs: 500, nearMetres: 20, middleShare: 0.8, reaskLeastMs: 2000, easeMs: TALK_FRAMING.easeMs,
  crowdedChecks: 2, bodyWidthMetres: 0.5, besideShare: 0.1, headMetres: 0.3,
});

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
  // The frame eased from when one is asked mid-scene, and when; when this scene's frame was last asked;
  // whether the listener stood in the middle at the last check (only a listener held there can drift out).
  let easedFrom: Pose | null = null, easedAt = 0, framedAt = 0, listenerIn = false;
  // Where the speaker stood when the frame was asked: the frame is carried by how far they have walked since.
  let speakerAt: Point | null = null;
  // At how many checks in a row a passer-by has stood in front of the speaker.
  let crowded = 0;

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
    const framing = (who: readonly object[]) => framingInSight(who, sceneSight(scene, recipe.sight.own_m), lens as typeof recipe,
      (at: Pose, framed: readonly object[]) => foregroundShare(at, framed, scene, lens as typeof recipe), bystanders) as Pose | null;
    // The listener only where both fit: a frame of the two that leaves the speaker outside the middle of the
    // width gives way to one of the speaker alone.
    const both = framing(subjects);
    const sighted = both !== null && (subjects.length === 1 || centred(both, first, lens)) ? both : framing([first]);
    if (sighted === null) return null;
    // The framing is in render space, which starts where the world was last re-centred; the controls'
    // pose and the camera's position say by how much.
    const eye = binding.camera.getPosition(), held = binding.controls.state;
    return { ...sighted, x: sighted.x + held.x - eye.x, y: sighted.y + held.y - eye.y, z: sighted.z + held.z - eye.z };
  }

  /** Whether a point stands before a pose within the middle `middleShare` of the lens's width. */
  function centred(at: Pose, point: Point, lens: ReturnType<typeof live>): boolean {
    const dx = point.x - at.x, dz = point.z - at.z;
    const depth = -dx * Math.sin(at.yaw) - dz * Math.cos(at.yaw), across = dx * Math.cos(at.yaw) - dz * Math.sin(at.yaw);
    return depth > 0 && Math.abs(across / depth) <= Math.tan(lensOf(lens as typeof recipe).horizontal) * rule.middleShare;
  }

  /** Someone's drawn head (render space), or null where the crowd does not draw them. */
  function headOf(id: string): Point | null {
    const at = anchorOf(binding.authoredSociety, id);
    return at === null ? null : { x: at.x, y: at.y + (Number.isFinite(at.height) ? at.height : recipe.subject_height_m), z: at.z };
  }

  /** Where a point falls on the screen, or null where the camera cannot say (then it is taken as in frame). */
  function onScreen(point: Point): { x: number; y: number; z: number } | null {
    return binding.camera?.camera?.worldToScreen?.({ x: point.x, y: point.y, z: point.z, clone() { return this; } }) ?? null;
  }

  /** Whether a head stands in front of the camera within the middle `middleShare` of the width. */
  function inMiddle(head: Point): boolean {
    const seen = onScreen(head);
    const margin = innerWidth * (1 - rule.middleShare) / 2;
    return !seen || (seen.z > 0 && seen.x >= margin && seen.x <= innerWidth - margin);
  }

  /** Whether the speaker's head is in the frame and nothing the scene draws stands between it and the camera. */
  function stillSeen(speaker: string): boolean {
    const head = headOf(speaker);
    if (head === null || hit === null) return false;
    const seen = onScreen(head);
    const inFrame = !seen || (seen.z > 0 && seen.x >= 0 && seen.x <= innerWidth && seen.y >= 0 && seen.y <= innerHeight);
    const eye = binding.camera.getPosition();
    return inFrame && sceneSight(hit, recipe.sight.own_m)({ x: eye.x, y: eye.y, z: eye.z }, head);
  }

  /**
   * Whether the pair has walked on: the speaker out of the middle, or a listener who has stood in it since the
   * frame was asked now out of it (one the frame left out is not followed).
   */
  function drifted(speaker: string, listener: string | null): boolean {
    const mine = headOf(speaker);
    if (mine !== null && !inMiddle(mine)) return true;
    const theirs = listener ? headOf(listener) : null;
    const middle = theirs !== null && inMiddle(theirs);
    listenerIn ||= middle;
    return listenerIn && !middle;
  }

  /**
   * Whether anyone but the line's people stands out of the frame's band from `at` (the controls' frame): nearer
   * and larger than the speaker, as the framing judges a bystander (standsInBand), so in front of them.
   */
  function crowdedFrom(at: Pose, speaker: string, listener: string | null): boolean {
    const society = binding.authoredSociety;
    const first = anchorOf(society, speaker);
    if (first === null) return false;
    // The frame is held in the controls' frame; the people stand in render space.
    const eye = binding.camera.getPosition(), state = binding.controls.state;
    const seen = { ...at, x: at.x - state.x + eye.x, y: at.y - state.y + eye.y, z: at.z - state.z + eye.z };
    const lens = live() as typeof recipe;
    const second = listener ? anchorOf(society, listener) : null;
    // The line's people as drawn, each box widened by a share of the frame's width (2 across, edge to edge).
    const widen = rule.besideShare * 2;
    const framed = [first, second].flatMap((one) => {
      const box = one === null ? null : boxOf(seen, one, lens);
      return box === null ? [] : [{ ...box, left: box.left - widen, right: box.right + widen }];
    });
    if (second !== null && coversHead(seen, second, first, lens)) return true;
    return ((society?.visibleInhabitantIds ?? []) as readonly string[]).some((id) => {
      if (id === speaker || id === listener) return false;
      const one = anchorOf(society, id);
      if (one === null || Math.hypot(one.x - first.x, one.z - first.z) > rule.nearMetres || standsInBand(seen, one, lens, first)) return false;
      const box = boxOf(seen, one, lens);
      return box !== null && framed.some((other) => box.left < other.right && box.right > other.left && box.bottom < other.top && box.top > other.bottom);
    });
  }

  /** Whether `cover` stands nearer than the speaker from `at` (render space) with their box over the speaker's head. */
  function coversHead(at: Pose, cover: Point & { height: number }, speaker: Point & { height: number }, lens: typeof recipe): boolean {
    const tall = Number.isFinite(speaker.height) && speaker.height > 0 ? speaker.height : recipe.subject_height_m;
    const head = boxOf(at, { ...speaker, y: speaker.y + tall - rule.headMetres, height: rule.headMetres }, lens);
    const box = boxOf(at, cover, lens);
    return head !== null && box !== null && box.depth < head.depth
      && box.left < head.right && box.right > head.left && box.bottom < head.top && box.top > head.bottom;
  }

  /**
   * Where a person (feet to head, `bodyWidthMetres` wide) falls in the frame from `at`, render space: across and up,
   * each from -1 to 1 edge to edge; null for one behind the camera.
   */
  function boxOf(at: Pose, one: Point & { height: number }, lens: typeof recipe) {
    const { horizontal, vertical } = lensOf(lens);
    const cy = Math.cos(at.yaw), sy = Math.sin(at.yaw), cp = Math.cos(at.pitch), sp = Math.sin(at.pitch);
    const tall = Number.isFinite(one.height) && one.height > 0 ? one.height : recipe.subject_height_m;
    const ends = [one.y, one.y + tall].map((y) => {
      const v = [one.x - at.x, y - at.y, one.z - at.z] as const;
      const depth = -sy * cp * v[0] + sp * v[1] - cy * cp * v[2];
      return depth <= 0 ? null : {
        depth,
        across: (cy * v[0] - sy * v[2]) / (depth * Math.tan(horizontal)),
        high: (sy * sp * v[0] + cp * v[1] + cy * sp * v[2]) / (depth * Math.tan(vertical)),
      };
    });
    const [feet, head] = ends;
    if (!feet || !head) return null;
    const half = rule.bodyWidthMetres / 2 / (Math.min(feet.depth, head.depth) * Math.tan(horizontal));
    const across = (feet.across + head.across) / 2;
    return { left: across - half, right: across + half, bottom: Math.min(feet.high, head.high), top: Math.max(feet.high, head.high), depth: Math.min(feet.depth, head.depth) };
  }

  /** The frame (eased to from the one before where it was asked mid-scene), carried by the speaker's walk since. */
  function held(now: number, speaker: string): Pose | null {
    if (pose === null) return null;
    let at: Pose = pose;
    if (easedFrom !== null) {
      const t = (now - easedAt) / rule.easeMs;
      if (t >= 1) easedFrom = null;
      else at = easePose(easedFrom, pose, t) as Pose;
    }
    const ground = speakerAt && anchorOf(binding.authoredSociety, speaker);
    if (!ground || !speakerAt) return at;
    const dx = ground.x - speakerAt.x, dy = ground.y - speakerAt.y, dz = ground.z - speakerAt.z;
    return dx === 0 && dy === 0 && dz === 0 ? at : { ...at, x: at.x + dx, y: at.y + dy, z: at.z + dz };
  }

  /** The speaker's ground where they stand now (render space), for carrying the frame just asked. */
  function groundOf(speaker: string): Point | null {
    const at = anchorOf(binding.authoredSociety, speaker);
    return at === null ? null : { x: at.x, y: at.y, z: at.z };
  }

  return {
    saw(next: Shown): void { shown = next; },
    pose(now: number): Pose | null {
      const line = shown?.showing ? shown.now : null;
      if (!line) { key = null; pose = null; hit = null; easedFrom = null; listenerIn = false; speakerAt = null; crowded = 0; return null; }
      const asked = `${line.speaker}|${line.to ?? ''}`, listener = line.to ?? null;
      if (asked !== key) {
        // A new line's people: framePair eases to the first frame from where the camera stands.
        key = asked; checkedAt = now; framedAt = now; easedFrom = null; listenerIn = false; crowded = 0;
        pose = frame(line.speaker, listener); speakerAt = groundOf(line.speaker);
      } else if (now - checkedAt >= rule.checkMs) {
        checkedAt = now;
        const lost = !stillSeen(line.speaker), walkedOn = drifted(line.speaker, listener);
        const holding = held(now, line.speaker);
        crowded = holding !== null && crowdedFrom(holding, line.speaker, listener) ? crowded + 1 : 0;
        if ((lost || walkedOn || crowded >= rule.crowdedChecks) && now - framedAt >= rule.reaskLeastMs) {
          const from = held(now, line.speaker), next = frame(line.speaker, listener);
          framedAt = now;
          if (next !== null) {
            // With no frame held before, framePair eases to this one from where the camera stands.
            if (from !== null) { easedFrom = from; easedAt = now; }
            pose = next; listenerIn = false; speakerAt = groundOf(line.speaker); crowded = 0;
          }
        }
      }
      return held(now, line.speaker);
    },
  };
}
