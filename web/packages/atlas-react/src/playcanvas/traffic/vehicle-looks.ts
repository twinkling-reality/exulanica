/**
 * VEHICLE LOOKS, VERSION 3: how the page draws each body family and colour the traffic catalog
 * names (`assets/catalogs/traffic/vehicle-class.v1.json`), as data.
 *
 * A figure of parts proportioned to the record's own length, width and height, so a body is
 * exactly the size the simulation drove, and nothing the record does not state (lamps, doors,
 * occupants) is drawn. Each part is placed along the body from its rear bumper, up from the road
 * and across its width, in thousandths of the record's dimensions, and drawn inside that box by its
 * shape: a box (the default), a disc filling the box's along and up sides and as thick as it is
 * across (a wheel), a rod from its first along and up point to its second, as thick as the box is
 * across (a frame's tube, rising or falling as its points say), a dome (a rounded part filling its
 * box: a helmet) or a ring (a tyre: a ring filling the box's along and up sides, as thick as the box
 * is across, its tube the share of its size it states, open in the middle), set off the centre line
 * across by its offset. A family may state a rider, parts drawn only while the vehicle is not parked.
 * Version 2 added the shapes, the offset and the rider; version 3 adds the dome and the ring, and draws
 * the bicycle's tyres as rings round a hub and its rider's helmet as a dome; every other family is as
 * version 2 drew it. Presentation only; the simulation reads none of
 * it. `test/traffic-looks.test.ts` holds its keys to the traffic catalog's, both ways.
 */

export interface LookBox {
  readonly role: string;
  /** How the part is drawn inside its box; a box where it states none. */
  readonly shape?: 'box' | 'disc' | 'rod' | 'dome' | 'ring';
  /** A ring's tube, thousandths of its box's along size (the ring's outer diameter); every ring states one. */
  readonly tube_permille?: number;
  /** How far the part's centre stands off the body's centre line across, thousandths of its width, the sign its side; none is 0. */
  readonly across_offset_permille?: number;
  /** A rod's two ends where it states a rod; otherwise the box's extent, the first the lower. */
  readonly along_permille: readonly [number, number];
  readonly up_permille: readonly [number, number];
  readonly across_permille: number;
}

export interface VehicleLooks {
  readonly profile: string;
  readonly reason: string;
  readonly roles: Readonly<Record<string, { readonly colour: string; readonly reason: string }>>;
  readonly colours: Readonly<Record<string, string>>;
  readonly body_families: Readonly<Record<string, {
    readonly boxes: readonly LookBox[];
    /** Parts drawn only while the vehicle is not parked (a bicycle's rider); none where it states none. */
    readonly rider?: { readonly boxes: readonly LookBox[]; readonly reason: string };
    readonly reason: string;
  }>>;
}

export const VEHICLE_LOOKS_V3: VehicleLooks = {
  "profile": "exulanica.vehicle-looks/v3",
  "reason": "How the page draws each body family and colour the traffic catalog names (assets/catalogs/traffic/vehicle-class.v1.json): a figure of parts proportioned to the record's own length, width and height, so a body is exactly the size the simulation drove, and nothing the record does not state (lamps, doors, occupants) is drawn. Each part is placed along the body from its rear bumper, up from the road and across its width, in thousandths of the record's dimensions, and drawn in that box as a box, a disc (a wheel), a rod between two of its points, a dome (a helmet) or a ring (a tyre, open in the middle). Presentation only; the simulation reads none of it.",
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
    "hub": {
      "colour": "#7d838b",
      "reason": "A bicycle wheel's hub is drawn in a plain metal grey where the frame meets it, so the wheel reads open round it."
    },
    "seat": {
      "colour": "#16171a",
      "reason": "A bicycle's saddle is drawn dark."
    },
    "handlebar": {
      "colour": "#16171a",
      "reason": "A bicycle's handlebar is drawn dark across the head of its frame."
    },
    "rider": {
      "colour": "#5b6b60",
      "reason": "A riding bicycle's rider is drawn in one plain clothing colour, a muted grey green that is no vehicle colour, so the rider reads apart from the frame."
    },
    "rider_head": {
      "colour": "#2b2d33",
      "reason": "A rider's head is drawn as a dark rounded helmet; the record states no person, so no face or skin is drawn."
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
          "shape": "ring",
          "tube_permille": 90,
          "along_permille": [
            0,
            371
          ],
          "up_permille": [
            0,
            440
          ],
          "across_permille": 60
        },
        {
          "role": "wheel",
          "shape": "ring",
          "tube_permille": 90,
          "along_permille": [
            629,
            1000
          ],
          "up_permille": [
            0,
            440
          ],
          "across_permille": 60
        },
        {
          "role": "hub",
          "shape": "disc",
          "along_permille": [
            163,
            208
          ],
          "up_permille": [
            193,
            247
          ],
          "across_permille": 145
        },
        {
          "role": "hub",
          "shape": "disc",
          "along_permille": [
            792,
            837
          ],
          "up_permille": [
            193,
            247
          ],
          "across_permille": 145
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            185,
            450
          ],
          "up_permille": [
            220,
            200
          ],
          "across_permille": 50
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            185,
            390
          ],
          "up_permille": [
            220,
            560
          ],
          "across_permille": 50
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            450,
            390
          ],
          "up_permille": [
            200,
            560
          ],
          "across_permille": 50
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            450,
            735
          ],
          "up_permille": [
            200,
            540
          ],
          "across_permille": 50
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            390,
            720
          ],
          "up_permille": [
            560,
            620
          ],
          "across_permille": 50
        },
        {
          "role": "frame",
          "shape": "rod",
          "along_permille": [
            720,
            815
          ],
          "up_permille": [
            620,
            220
          ],
          "across_permille": 50
        },
        {
          "role": "seat",
          "along_permille": [
            345,
            445
          ],
          "up_permille": [
            560,
            580
          ],
          "across_permille": 200
        },
        {
          "role": "frame",
          "along_permille": [
            710,
            740
          ],
          "up_permille": [
            620,
            666
          ],
          "across_permille": 60
        },
        {
          "role": "handlebar",
          "along_permille": [
            715,
            735
          ],
          "up_permille": [
            640,
            666
          ],
          "across_permille": 700
        }
      ],
      "rider": {
        "boxes": [
          {
            "role": "rider",
            "along_permille": [
              340,
              450
            ],
            "up_permille": [
              575,
              640
            ],
            "across_permille": 420
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              395,
              530
            ],
            "up_permille": [
              600,
              870
            ],
            "across_permille": 380
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              530,
              725
            ],
            "up_permille": [
              870,
              655
            ],
            "across_permille": 110,
            "across_offset_permille": 170
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              530,
              725
            ],
            "up_permille": [
              870,
              655
            ],
            "across_permille": 110,
            "across_offset_permille": -170
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              395,
              540
            ],
            "up_permille": [
              600,
              420
            ],
            "across_permille": 150,
            "across_offset_permille": 120
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              540,
              470
            ],
            "up_permille": [
              420,
              200
            ],
            "across_permille": 130,
            "across_offset_permille": 120
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              395,
              540
            ],
            "up_permille": [
              600,
              420
            ],
            "across_permille": 150,
            "across_offset_permille": -120
          },
          {
            "role": "rider",
            "shape": "rod",
            "along_permille": [
              540,
              430
            ],
            "up_permille": [
              420,
              200
            ],
            "across_permille": 130,
            "across_offset_permille": -120
          },
          {
            "role": "rider_head",
            "shape": "dome",
            "along_permille": [
              530,
              610
            ],
            "up_permille": [
              880,
              1000
            ],
            "across_permille": 260
          }
        ],
        "reason": "A rider drawn only while the bicycle is on the move (any mode but parked): seated on the saddle, the hands on the bar, the feet on the cranks, the head's top at the class's envelope (a rider's eye height of 1,500 mm), in plain parts: one clothing colour that is no frame's, a dark rounded helmet."
      },
      "reason": "Two wheels drawn as tyre rings, open round a hub, a frame of rods between the hubs, the saddle and the handlebar near a metre up, nothing of the bicycle above it; its height is a rider's eye envelope, which the rider fills while it moves."
    }
  }
};
