/**
 * What the flight route hands a renderer: a window of steps of a saved world's flight.
 *
 * The server computes every step with the flight movement module
 * (`exulanica/movement/flight.py`); a page draws what it is handed. Positions are integer
 * millimetres in the authored region's frame (east, up, south), velocities millimetres a second,
 * and the turning acceleration millimetres a second squared, positive to the left.
 */

/** The states a flyer is in, in the order the route's state codes index. */
export type FlightState = 'perching' | 'taking_off' | 'flying' | 'landing';

/** One flyer's steps in a window, flattened: three entries a step for a vector, one otherwise. */
export interface FlightSamples {
  readonly flyerId: string;
  readonly kind: string;
  readonly positionMm: readonly number[];
  readonly velocityMmS: readonly number[];
  readonly turnMmS2: readonly number[];
  readonly state: readonly number[];
  readonly flap: readonly number[];
}

/** A window of consecutive steps of one flight, as the route serves it. */
export interface FlightWindow {
  /** The digest of everything the flight was computed from; a new one is a new flight. */
  readonly inputSha256: string;
  /** The elevation of the ground the positions stand over, in millimetres. */
  readonly groundMm: number;
  readonly stepMs: number;
  readonly fromStep: number;
  readonly steps: number;
  readonly states: readonly FlightState[];
  readonly flyers: readonly FlightSamples[];
}

/** How a flying kind is drawn: where its wings join its body and how it banks and beats them. */
export interface FlightKindLook {
  readonly key: string;
  /**
   * The right wing's root in the catalog's part frame, millimetres: across the body, toward its
   * front, and up. The left wing's is its mirror across the body.
   */
  readonly wingHingeMm: readonly [number, number, number];
  readonly maxBankMrad: number;
  readonly flapCycleMs: number;
}

/** Builds a flying kind's drawn parts: its body once, and a wing for each side. */
export interface FlightPartFactory {
  body(): import('playcanvas').Entity;
  wing(): import('playcanvas').Entity;
}
