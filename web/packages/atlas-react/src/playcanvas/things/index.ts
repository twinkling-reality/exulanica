/**
 * @exulanica/atlas-react/things
 *
 * Drawing the things a world holds by their looks: the library they are read from, one dispatch by
 * look kind, the skeleton and motion of any body plan, the layer that stands a version's placed
 * things where it puts them, and the marks of who runs each being with the lines it says. A
 * separate entry from `./playcanvas`, as the generated site's is.
 */

export type {
  ContainerReference,
  DocumentReference,
  Grip,
  KindDrawing,
  LibraryKind,
  LibraryLook,
  LookDrawing,
  LookKind,
  SkinnedRig,
  ThingDocumentRefusal,
  ThingLibraryList,
} from './documents.js';
export {
  LOOK_KINDS,
  LOOK_PROFILE,
  THING_KIND_PROFILE,
  THING_LIBRARY_PROFILE,
  ThingDocumentRefused,
  drawnHeightMm,
  readBodyPlans,
  readKindDrawing,
  readLookDrawing,
  readThingLibrary,
} from './documents.js';
export type { LibraryBytes, LibraryRefusal, Named } from './library.js';
export { LibraryRefused, ThingLibrary } from './library.js';
export type { FigureRefusal, FigureRequest, InstancedContainer } from './dispatch.js';
export { CatalogPersonFigure, FigureRefused, makeFigure } from './dispatch.js';
export type { PickVolume, ThingFigure, ThingPose } from './figures.js';
export { FLOAT_HEIGHT, LookRoleFigure, NoFigure, PresenceFigure, StaticFigure, facingOfYaw } from './figures.js';
export { RigidOnBonesFigure } from './rigid-on-bones.js';
export type { SkinnedMiss } from './skinned.js';
export { CLIP_SPEED_LIMIT, SkinnedFigure } from './skinned.js';
export type { BodyPlanEntry, DressedSkeleton, Limb, LimbRole, PlanBone, PlanSocket, SkeletonRefusal, Vec3 } from './skeleton.js';
export { SkeletonRefused, dressSkeleton } from './skeleton.js';
export type { JointPose, MotionInput, Pose, Quat } from './motion.js';
export { DUTY, gaitOf, solvePose } from './motion.js';
export { PickRing, rayMeets, ringRadius } from './ring.js';
export type { DrawnThing, PlacedThingRecord, ThingLayerOptions, ThingMiss, ThingPick } from './thing-layer.js';
export { ThingLayer } from './thing-layer.js';
export type { FigureMade, FigureMakerOptions } from './figure-maker.js';
export { ThingFigureMaker } from './figure-maker.js';
export type { ThingCrowdFiguresOptions, ThingFigureMiss } from './crowd-figures.js';
export { ThingCrowdFigures, ThingCrowdRenderable } from './crowd-figures.js';
export type { AttachedMarksOptions, MarkAnchors, MarkedSubject, ThingLine, ThingMark } from './marks.js';
export { AttachedMarks, LINES_MAXIMUM, MARKS_MAXIMUM, MARK_RANGE_METRES, NAMED_NEAREST, NAME_RANGE_METRES, ThingMarks, lineSeconds } from './marks.js';
