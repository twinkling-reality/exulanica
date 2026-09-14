import type { V3 } from './player-sculpt.js';
const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));
export interface Bone {
  readonly a: V3;
  readonly b: V3;
}
const side = (s: number, x: number, y: number, z = 0): V3 => [s * x, y, z];
/** abstract-human/v1 ordered bone semantics. Units: metres, +Y up, -Z forward, X anatomical side. */
export const HUMAN_BONE_NAMES = [
  'pelvis',
  'spine',
  'head',
  'left-thigh',
  'left-shin',
  'left-foot',
  'left-upper-arm',
  'left-forearm',
  'right-thigh',
  'right-shin',
  'right-foot',
  'right-upper-arm',
  'right-forearm',
] as const;
export const HUMAN_LEGS = [
  { thigh: 3, shin: 4, foot: 5 },
  { thigh: 8, shin: 9, foot: 10 },
] as const;
export const PLAYER_BIND_BONES: readonly Bone[] = [
  { a: [0, 0.86, 0], b: [0, 1.16, 0] },
  { a: [0, 1.16, 0], b: [0, 1.43, 0] },
  { a: [0, 1.43, 0], b: [0, 1.8, 0] },
  ...[-1, 1].flatMap((s) => [
    { a: side(s, 0.095, 0.86), b: side(s, 0.108, 0.478, -0.065) },
    { a: side(s, 0.108, 0.478, -0.065), b: side(s, 0.112, 0.105) },
    { a: side(s, 0.112, 0.105), b: side(s, 0.112, 0.105, -0.1) },
    { a: side(s, 0.209, 1.367), b: side(s, 0.274, 1.115) },
    { a: side(s, 0.274, 1.115), b: side(s, 0.3, 0.902, -0.018) },
  ]),
];
function distance(p: V3, b: Bone): number {
  const dx = b.b[0] - b.a[0],
    dy = b.b[1] - b.a[1],
    dz = b.b[2] - b.a[2],
    t = clamp(
      ((p[0] - b.a[0]) * dx + (p[1] - b.a[1]) * dy + (p[2] - b.a[2]) * dz) /
        (dx * dx + dy * dy + dz * dz),
      0,
      1,
    );
  return Math.hypot(
    p[0] - b.a[0] - t * dx,
    p[1] - b.a[1] - t * dy,
    p[2] - b.a[2] - t * dz,
  );
}
export function playerSkinWeights(positions: Float32Array): {
  indices: Uint8Array;
  weights: Float32Array;
} {
  const indices = new Uint8Array((positions.length / 3) * 3),
    weights = new Float32Array(indices.length);
  for (let i = 0; i < positions.length / 3; i++) {
    const p: V3 = [
        positions[i * 3]!,
        positions[i * 3 + 1]!,
        positions[i * 3 + 2]!,
      ],
      offset = p[0] < 0 ? 3 : 8;
    let candidates: number[];
    if (p[1] < 0.15) candidates = [offset + 2];
    else if (p[1] > 1.46) candidates = [1, 2];
    else if (p[1] < 0.77) candidates = [offset, offset + 1, offset + 2, 0];
    else if (Math.abs(p[0]) > 0.175) candidates = [offset + 3, offset + 4, 1];
    else candidates = [0, 1, 2, offset];
    const near = candidates
      .map((id) => ({ id, d: distance(p, PLAYER_BIND_BONES[id]!) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 3);
    const values = near.map((n) => Math.exp(-(n.d - near[0]!.d) * 45));
    const total = values.reduce((a, b) => a + b, 0);
    near.forEach((bone, k) => {
      indices[i * 3 + k] = bone.id;
      weights[i * 3 + k] = values[k]! / total;
    });
  }
  return { indices, weights };
}
/** Rotation and translation mapping a bind bone to a posed bone, without axial stretching. */
function matrix(bind: Bone, pose: Bone): number[] {
  const u = bind.b.map((v, i) => v - bind.a[i]!),
    v = pose.b.map((n, i) => n - pose.a[i]!);
  let n = Math.hypot(...u);
  u.forEach((x, i) => (u[i] = x / n));
  n = Math.hypot(...v);
  v.forEach((x, i) => (v[i] = x / n));
  const cross = [
      u[1]! * v[2]! - u[2]! * v[1]!,
      u[2]! * v[0]! - u[0]! * v[2]!,
      u[0]! * v[1]! - u[1]! * v[0]!,
    ],
    dot = u.reduce((s, x, i) => s + x * v[i]!, 0),
    k = 1 / Math.max(1e-6, 1 + dot),
    [x, y, z] = cross as [number, number, number];
  const r = [
    1 - (y * y + z * z) * k,
    x * y * k - z,
    x * z * k + y,
    x * y * k + z,
    1 - (x * x + z * z) * k,
    y * z * k - x,
    x * z * k - y,
    y * z * k + x,
    1 - (x * x + y * y) * k,
  ];
  return [
    ...r,
    ...pose.a.map(
      (p, i) =>
        p -
        r[i * 3]! * bind.a[0] -
        r[i * 3 + 1]! * bind.a[1] -
        r[i * 3 + 2]! * bind.a[2],
    ),
  ];
}
export function deformPlayer(
  bindPositions: Float32Array,
  bindNormals: Float32Array,
  skin: ReturnType<typeof playerSkinWeights>,
  bones: readonly Bone[],
  positions: Float32Array,
  normals: Float32Array,
  bindBones: readonly Bone[] = PLAYER_BIND_BONES,
): void {
  const transforms = bones.map((b, i) => matrix(bindBones[i]!, b));
  for (let i = 0; i < bindPositions.length / 3; i++) {
    for (let axis = 0; axis < 3; axis++) {
      let p = 0,
        n = 0;
      for (let k = 0; k < 3; k++) {
        const w = skin.weights[i * 3 + k]!;
        if (!w) continue;
        const t = transforms[skin.indices[i * 3 + k]!]!;
        let pp = t[9 + axis]!,
          nn = 0;
        for (let j = 0; j < 3; j++) {
          pp += t[axis * 3 + j]! * bindPositions[i * 3 + j]!;
          nn += t[axis * 3 + j]! * bindNormals[i * 3 + j]!;
        }
        p += pp * w;
        n += nn * w;
      }
      positions[i * 3 + axis] = p;
      normals[i * 3 + axis] = n;
    }
    const length = Math.hypot(
      normals[i * 3]!,
      normals[i * 3 + 1]!,
      normals[i * 3 + 2]!,
    );
    for (let a = 0; a < 3; a++)
      normals[i * 3 + a] = normals[i * 3 + a]! / length;
  }
}
export function solveKnee(hip: V3, ankle: V3, a = 0.389, b = 0.382): V3 {
  const dy = ankle[1] - hip[1],
    dz = ankle[2] - hip[2],
    d = Math.max(0.01, Math.hypot(dy, dz)),
    along = (a * a - b * b + d * d) / (2 * d),
    height = Math.sqrt(Math.max(0, a * a - along * along));
  return [
    (hip[0] + ankle[0]) / 2,
    hip[1] + (along * dy) / d - (height * dz) / d,
    hip[2] + (along * dz) / d + (height * dy) / d,
  ];
}
export interface GaitPose {
  readonly bones: readonly Bone[];
  readonly stance: readonly boolean[];
  readonly feet: readonly V3[];
}
/** Distance-driven gait with knee/elbow articulation and opposing shoulder/hip rotation. */
export function playerGaitPose(
  phase: number,
  amount: number,
  run: number,
): GaitPose {
  const stride = 1.05 + run * 0.55,
    stance = 0.62 - run * 0.12,
    hipY = 0.86 - amount * (0.045 + run * 0.012),
    twist = Math.sin(phase) * amount * 0.055;
  const bones: Bone[] = [
    { a: [0, hipY, 0], b: [0, 1.16 - amount * 0.04, -amount * 0.012] },
    {
      a: [0, 1.16 - amount * 0.04, -amount * 0.012],
      b: [0, 1.43 - amount * 0.035, -amount * (0.015 + run * 0.035)],
    },
    {
      a: [0, 1.43 - amount * 0.035, -amount * (0.015 + run * 0.035)],
      b: [0, 1.8 - amount * 0.035, -amount * 0.015],
    },
  ];
  const feet: V3[] = [],
    contacts: boolean[] = [];
  [-1, 1].forEach((s, index) => {
    const cycle = (((phase / (Math.PI * 2) + index * 0.5) % 1) + 1) % 1,
      isStance = cycle < stance;
    const swing = clamp((cycle - stance) / (1 - stance), 0, 1),
      e = swing * swing * (3 - 2 * swing),
      reach = (stride * stance) / 2;
    const z =
      amount * (isStance ? -reach + stride * cycle : reach * (1 - 2 * e));
    const ankle: V3 = [
      s * 0.112,
      0.105 +
        amount *
          (isStance ? 0 : Math.sin(Math.PI * swing) * (0.085 + run * 0.07)),
      z,
    ];
    const hip: V3 = [s * 0.095, hipY, s * twist];
    const joint = solveKnee(hip, ankle);
    feet.push(ankle);
    contacts.push(isStance);
    const shoulder: V3 = [s * 0.209, 1.367 - amount * 0.035, -s * twist];
    const armAngle =
      Math.sin(phase + index * Math.PI) * amount * (0.42 + run * 0.35);
    const elbow: V3 = [
      s * 0.255,
      shoulder[1] - 0.253 * Math.cos(armAngle),
      shoulder[2] - 0.253 * Math.sin(armAngle),
    ];
    const forearm = armAngle - 0.12 - amount * (0.16 + run * 0.8);
    const wrist: V3 = [
      s * 0.28,
      elbow[1] - 0.211 * Math.cos(forearm),
      elbow[2] - 0.211 * Math.sin(forearm),
    ];
    bones.push(
      { a: hip, b: joint },
      { a: joint, b: ankle },
      { a: ankle, b: [ankle[0], ankle[1], ankle[2] - 0.1] },
      { a: shoulder, b: elbow },
      { a: elbow, b: wrist },
    );
  });
  return { bones, stance: contacts, feet };
}
