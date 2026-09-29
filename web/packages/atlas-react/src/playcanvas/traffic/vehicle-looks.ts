/**
 * VEHICLE LOOKS, VERSION 1: how the page draws each body family and colour the traffic catalog
 * names (`assets/catalogs/traffic/vehicle-class.v1.json`), as data.
 *
 * A figure of boxes proportioned to the record's own length, width and height, so a body is
 * exactly the size the simulation drove, and nothing the record does not state (lamps, doors,
 * occupants) is drawn. Each box is placed along the body from its rear bumper, up from the road and
 * across its width, in thousandths of the record's dimensions. Presentation only; the simulation
 * reads none of it. `test/traffic-layer.test.ts` holds its keys to the traffic catalog's, both ways.
 */

export interface LookBox {
  readonly role: string;
  readonly along_permille: readonly [number, number];
  readonly up_permille: readonly [number, number];
  readonly across_permille: number;
}

export interface VehicleLooks {
  readonly profile: string;
  readonly reason: string;
  readonly roles: Readonly<Record<string, { readonly colour: string; readonly reason: string }>>;
  readonly colours: Readonly<Record<string, string>>;
  readonly body_families: Readonly<Record<string, { readonly boxes: readonly LookBox[]; readonly reason: string }>>;
}

export const VEHICLE_LOOKS_V1: VehicleLooks = {
  "profile": "exulanica.vehicle-looks/v1",
  "reason": "How the page draws each body family and colour the traffic catalog names (assets/catalogs/traffic/vehicle-class.v1.json): a figure of boxes proportioned to the record's own length, width and height, so a body is exactly the size the simulation drove, and nothing the record does not state (lamps, doors, occupants) is drawn. Each box is placed along the body from its rear bumper, up from the road and across its width, in thousandths of the record's dimensions. Presentation only; the simulation reads none of it.",
  "roles": {
    "body": {
      "colour": "vehicle",
      "reason": "The body takes the vehicle's colour."
    },
    "glass": {
      "colour": "#1f262e",
      "reason": "Glazing is drawn as one dark tint, since the record states no interior."
    },
    "wheel": {
      "colour": "#16171a",
      "reason": "Tyres are drawn dark; the record states no wheel angle, so they do not turn."
    },
    "frame": {
      "colour": "vehicle",
      "reason": "A bicycle's frame takes the vehicle's colour."
    }
  },
  "colours": {
    "black": "#1c1d21",
    "blue": "#2f5ca8",
    "grey": "#7d8288",
    "red": "#b3302b",
    "silver": "#b9bdc2",
    "white": "#e9eaec"
  },
  "body_families": {
    "hatchback": {
      "boxes": [
        {
          "role": "body",
          "along_permille": [
            0,
            1000
          ],
          "up_permille": [
            180,
            560
          ],
          "across_permille": 1000
        },
        {
          "role": "glass",
          "along_permille": [
            180,
            820
          ],
          "up_permille": [
            560,
            920
          ],
          "across_permille": 900
        },
        {
          "role": "wheel",
          "along_permille": [
            100,
            260
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        },
        {
          "role": "wheel",
          "along_permille": [
            740,
            900
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        }
      ],
      "reason": "A body the full length to the waist, and a cabin over most of it, the hatch its rear."
    },
    "sedan": {
      "boxes": [
        {
          "role": "body",
          "along_permille": [
            0,
            1000
          ],
          "up_permille": [
            180,
            560
          ],
          "across_permille": 1000
        },
        {
          "role": "glass",
          "along_permille": [
            260,
            740
          ],
          "up_permille": [
            560,
            920
          ],
          "across_permille": 900
        },
        {
          "role": "wheel",
          "along_permille": [
            100,
            260
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        },
        {
          "role": "wheel",
          "along_permille": [
            740,
            900
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        }
      ],
      "reason": "A body the full length to the waist, and a cabin over its middle, with a bonnet and a boot."
    },
    "minivan": {
      "boxes": [
        {
          "role": "body",
          "along_permille": [
            0,
            1000
          ],
          "up_permille": [
            180,
            600
          ],
          "across_permille": 1000
        },
        {
          "role": "glass",
          "along_permille": [
            120,
            880
          ],
          "up_permille": [
            600,
            960
          ],
          "across_permille": 920
        },
        {
          "role": "wheel",
          "along_permille": [
            100,
            260
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        },
        {
          "role": "wheel",
          "along_permille": [
            740,
            900
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        }
      ],
      "reason": "A tall body with a cabin over nearly its whole length."
    },
    "panel_van": {
      "boxes": [
        {
          "role": "body",
          "along_permille": [
            0,
            1000
          ],
          "up_permille": [
            180,
            1000
          ],
          "across_permille": 1000
        },
        {
          "role": "glass",
          "along_permille": [
            780,
            900
          ],
          "up_permille": [
            560,
            880
          ],
          "across_permille": 940
        },
        {
          "role": "wheel",
          "along_permille": [
            100,
            260
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        },
        {
          "role": "wheel",
          "along_permille": [
            740,
            900
          ],
          "up_permille": [
            0,
            250
          ],
          "across_permille": 1020
        }
      ],
      "reason": "A box body to the roof, glazed only at the cab."
    },
    "rigid_city_bus": {
      "boxes": [
        {
          "role": "body",
          "along_permille": [
            0,
            1000
          ],
          "up_permille": [
            120,
            1000
          ],
          "across_permille": 1000
        },
        {
          "role": "glass",
          "along_permille": [
            40,
            980
          ],
          "up_permille": [
            480,
            860
          ],
          "across_permille": 1010
        },
        {
          "role": "wheel",
          "along_permille": [
            140,
            240
          ],
          "up_permille": [
            0,
            180
          ],
          "across_permille": 1020
        },
        {
          "role": "wheel",
          "along_permille": [
            700,
            800
          ],
          "up_permille": [
            0,
            180
          ],
          "across_permille": 1020
        }
      ],
      "reason": "A box body to the roof with a band of windows along both sides."
    },
    "upright_bicycle": {
      "boxes": [
        {
          "role": "wheel",
          "along_permille": [
            0,
            380
          ],
          "up_permille": [
            0,
            380
          ],
          "across_permille": 60
        },
        {
          "role": "wheel",
          "along_permille": [
            620,
            1000
          ],
          "up_permille": [
            0,
            380
          ],
          "across_permille": 60
        },
        {
          "role": "frame",
          "along_permille": [
            200,
            800
          ],
          "up_permille": [
            330,
            560
          ],
          "across_permille": 120
        },
        {
          "role": "frame",
          "along_permille": [
            640,
            700
          ],
          "up_permille": [
            560,
            1000
          ],
          "across_permille": 700
        }
      ],
      "reason": "Two wheels, a frame between them and the handlebar at the front; no rider, since the record states none."
    }
  }
};
