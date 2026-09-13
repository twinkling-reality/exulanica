export type Triple = readonly [number, number, number];
export type Matrix4 = readonly [
  number, number, number, number,
  number, number, number, number,
  number, number, number, number,
  number, number, number, number,
];

export interface GoogleLocalFrame {
  readonly name: 'wgs84-ecef-to-local-east-up-south-metres';
  readonly ecefOrigin: Triple;
  readonly east: Triple;
  readonly up: Triple;
  readonly south: Triple;
}

const WGS84_A = 6378137;
const WGS84_E2 = 6.6943799901413165e-3;

export function wgs84ToEcef(longitude: number, latitude: number, altitude: number): Triple {
  if (![longitude, latitude, altitude].every(Number.isFinite) ||
      longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    throw new RangeError('Invalid Google reference origin');
  }
  const lon = longitude * Math.PI / 180;
  const lat = latitude * Math.PI / 180;
  const sinLat = Math.sin(lat);
  const radius = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat);
  return [
    (radius + altitude) * Math.cos(lat) * Math.cos(lon),
    (radius + altitude) * Math.cos(lat) * Math.sin(lon),
    (radius * (1 - WGS84_E2) + altitude) * sinLat,
  ];
}

export function googleLocalFrame(longitude: number, latitude: number, altitude = 0): GoogleLocalFrame {
  const lon = longitude * Math.PI / 180;
  const lat = latitude * Math.PI / 180;
  return Object.freeze({
    name: 'wgs84-ecef-to-local-east-up-south-metres',
    ecefOrigin: wgs84ToEcef(longitude, latitude, altitude),
    east: [-Math.sin(lon), Math.cos(lon), 0] as Triple,
    up: [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)] as Triple,
    south: [Math.sin(lat) * Math.cos(lon), Math.sin(lat) * Math.sin(lon), -Math.cos(lat)] as Triple,
  });
}

export function ecefToGoogleLocal(frame: GoogleLocalFrame, point: Triple): Triple {
  const delta: Triple = [
    point[0] - frame.ecefOrigin[0],
    point[1] - frame.ecefOrigin[1],
    point[2] - frame.ecefOrigin[2],
  ];
  const dot = (basis: Triple): number =>
    basis[0] * delta[0] + basis[1] * delta[1] + basis[2] * delta[2];
  return [dot(frame.east), dot(frame.up), dot(frame.south)];
}

export function googleLocalToEcef(frame: GoogleLocalFrame, point: Triple): Triple {
  return [0, 1, 2].map((index) =>
    frame.ecefOrigin[index]! +
    frame.east[index]! * point[0] +
    frame.up[index]! * point[1] +
    frame.south[index]! * point[2],
  ) as unknown as Triple;
}

export const IDENTITY_MATRIX: Matrix4 = [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
];

export function multiplyMatrices(left: Matrix4, right: Matrix4): Matrix4 {
  const result = Array<number>(16).fill(0);
  for (let column = 0; column < 4; column++) {
    for (let row = 0; row < 4; row++) {
      let value = 0;
      for (let index = 0; index < 4; index++) {
        value += left[index * 4 + row]! * right[column * 4 + index]!;
      }
      result[column * 4 + row] = value;
    }
  }
  return result as unknown as Matrix4;
}

/**
 * Convert an ECEF tile transform into a small local metre transform before it
 * enters PlayCanvas float storage. The render origin is transient renderer state.
 */
export function localTileTransform(
  frame: GoogleLocalFrame,
  tileTransform: readonly number[] | undefined,
  renderOrigin: Triple = [0, 0, 0],
): Matrix4 {
  const source = tileTransform ?? IDENTITY_MATRIX;
  if (source.length !== 16 || !source.every(Number.isFinite) || !renderOrigin.every(Number.isFinite)) {
    throw new Error('Invalid Google tile transform');
  }
  const [east, up, south] = [frame.east, frame.up, frame.south];
  const ecefToLocal = [
    east[0], up[0], south[0], 0,
    east[1], up[1], south[1], 0,
    east[2], up[2], south[2], 0,
    -(east[0] * frame.ecefOrigin[0] + east[1] * frame.ecefOrigin[1] + east[2] * frame.ecefOrigin[2]) - renderOrigin[0],
    -(up[0] * frame.ecefOrigin[0] + up[1] * frame.ecefOrigin[1] + up[2] * frame.ecefOrigin[2]) - renderOrigin[1],
    -(south[0] * frame.ecefOrigin[0] + south[1] * frame.ecefOrigin[1] + south[2] * frame.ecefOrigin[2]) - renderOrigin[2],
    1,
  ] as Matrix4;
  return multiplyMatrices(ecefToLocal, source as Matrix4);
}

export function googleRenderOrigin(camera: Triple, previous: Triple, threshold = 512): Triple {
  if (![...camera, ...previous, threshold].every(Number.isFinite) || threshold <= 0) {
    throw new Error('Invalid Google render origin');
  }
  if (Math.hypot(
    camera[0] - previous[0],
    camera[1] - previous[1],
    camera[2] - previous[2],
  ) < threshold) return previous;
  return [
    Math.round(camera[0] / 256) * 256,
    Math.round(camera[1] / 256) * 256,
    Math.round(camera[2] / 256) * 256,
  ];
}
