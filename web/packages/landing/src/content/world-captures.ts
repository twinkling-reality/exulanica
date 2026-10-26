// Generated from public/worlds/sources.json. Run scripts/generate-world-catalog.mjs.
export interface ShowcaseCapture {
  readonly id: string;
  readonly world: string;
  readonly title: string;
  readonly sentence: string;
  readonly image: string;
  readonly made: Readonly<Record<string, unknown>>;
}
export interface ConfigurationCapture {
  readonly id: string;
  readonly recipe: string;
  readonly values: Readonly<Record<string, string | number>>;
  readonly style_pack: { readonly pack_id: string; readonly version: number; readonly manifest_sha256: string };
  readonly image: string;
  readonly saved_world_title: string;
  readonly style_title: string;
}
export const WORLD_CAPTURES: readonly (ShowcaseCapture | ConfigurationCapture)[] = [
  {
    "id": "mountain-town",
    "world": "mountain-town",
    "title": "A snowy mountain town with a bakery",
    "sentence": "a snowy mountain town with a bakery",
    "image": "showcase-mountain-town.jpg",
    "made": {
      "main": "4a878448e",
      "draft_id": "7faa20c2-4813-51ef-ad07-c4834d634b0e",
      "tool": "town",
      "decisions": 25,
      "creature": "White horned grazer",
      "spend_usd": {
        "draft": "0.00520320",
        "run": "0.00868198",
        "creature": "0.0047"
      },
      "spend_account": "Nebius Token Factory, the user's key, APPROVALS item 36 allocation WORLDS-SHOWCASE-1"
    }
  },
  {
    "id": "fishing-village",
    "world": "fishing-village",
    "title": "Fishing village",
    "sentence": "a fishing village by the sea at sunset",
    "image": "showcase-fishing-village.jpg",
    "made": {
      "main": "4a878448e",
      "draft_id": "d16b2a23-c4a0-5d37-b368-e178e48ec7eb",
      "tool": "place",
      "decisions": 35,
      "creature": "Harbour napper",
      "spend_usd": {
        "draft": "0.00628430",
        "run": "0.01661950",
        "creature": "0.0053"
      },
      "spend_account": "Nebius Token Factory, the user's key, APPROVALS item 36 allocation WORLDS-SHOWCASE-1"
    }
  },
  {
    "id": "night-market",
    "world": "night-market",
    "title": "Night market",
    "sentence": "a rainy night market in the city",
    "image": "showcase-night-market.jpg",
    "made": {
      "main": "4a878448e",
      "draft_id": "089859e9-f12f-5761-ac2b-a317e9ddc175",
      "tool": "place",
      "decisions": 30,
      "creature": "Sleepy stall wanderer",
      "spend_usd": {
        "draft": "0.00420398",
        "run": "0.01078080",
        "creature": "0.0046"
      },
      "spend_account": "Nebius Token Factory, the user's key, APPROVALS item 36 allocation WORLDS-SHOWCASE-1"
    }
  },
  {
    "id": "windmill-village",
    "world": "windmill-village",
    "title": "Farming village",
    "sentence": "a farming village in the hills with an old windmill",
    "image": "showcase-windmill-village.jpg",
    "made": {
      "main": "4a878448e",
      "draft_id": "bf6a6d68-67b7-5b5d-8f07-23449f246b4a",
      "tool": "place",
      "decisions": 38,
      "creature": "Shaggy herd guardian",
      "spend_usd": {
        "draft": "0.00562204",
        "run": "0.01371620",
        "creature": "0.0039"
      },
      "spend_account": "Nebius Token Factory, the user's key, APPROVALS item 36 allocation WORLDS-SHOWCASE-1"
    }
  },
  {
    "id": "lighthouse-island",
    "world": "lighthouse-island",
    "title": "Tiny Island Lighthouse",
    "sentence": "a tiny island with a lighthouse",
    "image": "showcase-lighthouse-island.jpg",
    "made": {
      "main": "4a878448e",
      "draft_id": "6fa10c0e-95ce-5f95-8651-08b4878c71a4",
      "tool": "place",
      "decisions": 30,
      "creature": "Crimson beaked seabird",
      "spend_usd": {
        "draft": "0.01433550",
        "run": "0.01086570",
        "creature": "0.01"
      },
      "spend_account": "Nebius Token Factory, the user's key, APPROVALS item 36 allocation WORLDS-SHOWCASE-1"
    }
  },
  {
    "id": "compact-cozy",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.cozy-town",
      "version": 3,
      "manifest_sha256": "c9f3e58e0c83bd62bf5e58b5a7d44fbca47e9048521c2cfa48d1702d1797a6dc"
    },
    "image": "compact-cozy.jpg",
    "saved_world_title": "Compact Town · Cozy",
    "style_title": "Cozy town"
  },
  {
    "id": "compact-finished",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.finished-town",
      "version": 3,
      "manifest_sha256": "67adb7466c8c82a90800d568db6796eb6569f86ab4487c74909a25b9645d6444"
    },
    "image": "compact-finished.jpg",
    "saved_world_title": "Compact Town · Finished",
    "style_title": "Finished town"
  },
  {
    "id": "compact-toon",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.toon-town",
      "version": 3,
      "manifest_sha256": "af8205f7e379cf5d81b777a298a67c6081b2afb1dd0a07d26515ca393cce4c37"
    },
    "image": "compact-toon.jpg",
    "saved_world_title": "Compact Town · Toon",
    "style_title": "Toon town"
  },
  {
    "id": "rowhouses-cozy",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 3,
      "storey_band_high": 5,
      "high_street_count": 1,
      "cross_street_hierarchy": "narrow_street",
      "typology_weight_apartment_block_permille": 0,
      "typology_weight_loft_building_permille": 0,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 1000,
      "typology_weight_shophouse_permille": 0,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.cozy-town",
      "version": 3,
      "manifest_sha256": "c9f3e58e0c83bd62bf5e58b5a7d44fbca47e9048521c2cfa48d1702d1797a6dc"
    },
    "image": "rowhouses-cozy.jpg",
    "saved_world_title": "Narrow Rowhouses · Cozy",
    "style_title": "Cozy town"
  },
  {
    "id": "rowhouses-finished",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 3,
      "storey_band_high": 5,
      "high_street_count": 1,
      "cross_street_hierarchy": "narrow_street",
      "typology_weight_apartment_block_permille": 0,
      "typology_weight_loft_building_permille": 0,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 1000,
      "typology_weight_shophouse_permille": 0,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.finished-town",
      "version": 3,
      "manifest_sha256": "67adb7466c8c82a90800d568db6796eb6569f86ab4487c74909a25b9645d6444"
    },
    "image": "rowhouses-finished.jpg",
    "saved_world_title": "Narrow Rowhouses · Finished",
    "style_title": "Finished town"
  },
  {
    "id": "rowhouses-toon",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 3,
      "storey_band_high": 5,
      "high_street_count": 1,
      "cross_street_hierarchy": "narrow_street",
      "typology_weight_apartment_block_permille": 0,
      "typology_weight_loft_building_permille": 0,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 1000,
      "typology_weight_shophouse_permille": 0,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.toon-town",
      "version": 3,
      "manifest_sha256": "af8205f7e379cf5d81b777a298a67c6081b2afb1dd0a07d26515ca393cce4c37"
    },
    "image": "rowhouses-toon.jpg",
    "saved_world_title": "Narrow Rowhouses · Toon",
    "style_title": "Toon town"
  },
  {
    "id": "high-streets-cozy",
    "recipe": "market_town",
    "values": {
      "city_extent_x_mm": 384000,
      "block_length_mm": 140000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 3,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.cozy-town",
      "version": 3,
      "manifest_sha256": "c9f3e58e0c83bd62bf5e58b5a7d44fbca47e9048521c2cfa48d1702d1797a6dc"
    },
    "image": "high-streets-cozy.jpg",
    "saved_world_title": "Three High Streets · Cozy",
    "style_title": "Cozy town"
  },
  {
    "id": "high-streets-finished",
    "recipe": "market_town",
    "values": {
      "city_extent_x_mm": 384000,
      "block_length_mm": 140000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 3,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.finished-town",
      "version": 3,
      "manifest_sha256": "67adb7466c8c82a90800d568db6796eb6569f86ab4487c74909a25b9645d6444"
    },
    "image": "high-streets-finished.jpg",
    "saved_world_title": "Three High Streets · Finished",
    "style_title": "Finished town"
  },
  {
    "id": "high-streets-toon",
    "recipe": "market_town",
    "values": {
      "city_extent_x_mm": 384000,
      "block_length_mm": 140000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 3,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 500,
      "typology_weight_loft_building_permille": 500,
      "typology_weight_mansion_block_permille": 500,
      "typology_weight_rowhouse_permille": 500,
      "typology_weight_shophouse_permille": 500,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.toon-town",
      "version": 3,
      "manifest_sha256": "af8205f7e379cf5d81b777a298a67c6081b2afb1dd0a07d26515ca393cce4c37"
    },
    "image": "high-streets-toon.jpg",
    "saved_world_title": "Three High Streets · Toon",
    "style_title": "Toon town"
  },
  {
    "id": "apartment-district",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 1000,
      "typology_weight_loft_building_permille": 0,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 0,
      "typology_weight_shophouse_permille": 0,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.finished-town",
      "version": 3,
      "manifest_sha256": "67adb7466c8c82a90800d568db6796eb6569f86ab4487c74909a25b9645d6444"
    },
    "image": "apartment-district.jpg",
    "saved_world_title": "Apartment District · Finished",
    "style_title": "Finished town"
  },
  {
    "id": "loft-quarter",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 0,
      "typology_weight_loft_building_permille": 1000,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 0,
      "typology_weight_shophouse_permille": 0,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.cozy-town",
      "version": 3,
      "manifest_sha256": "c9f3e58e0c83bd62bf5e58b5a7d44fbca47e9048521c2cfa48d1702d1797a6dc"
    },
    "image": "loft-quarter.jpg",
    "saved_world_title": "Loft Quarter · Cozy",
    "style_title": "Cozy town"
  },
  {
    "id": "shophouse-quarter",
    "recipe": "small_town",
    "values": {
      "city_extent_x_mm": 256000,
      "block_length_mm": 90000,
      "storey_band_low": 2,
      "storey_band_high": 4,
      "high_street_count": 1,
      "cross_street_hierarchy": "local_street",
      "typology_weight_apartment_block_permille": 0,
      "typology_weight_loft_building_permille": 0,
      "typology_weight_mansion_block_permille": 0,
      "typology_weight_rowhouse_permille": 0,
      "typology_weight_shophouse_permille": 1000,
      "ground_floor_use_weight_bakery_permille": 500,
      "ground_floor_use_weight_bookshop_permille": 500,
      "ground_floor_use_weight_cafe_permille": 500,
      "ground_floor_use_weight_grocery_permille": 500,
      "ground_floor_use_weight_office_permille": 500,
      "ground_floor_use_weight_pharmacy_permille": 500,
      "ground_floor_use_weight_restaurant_permille": 500,
      "ground_floor_use_weight_workshop_permille": 500
    },
    "style_pack": {
      "pack_id": "exulanica.toon-town",
      "version": 3,
      "manifest_sha256": "af8205f7e379cf5d81b777a298a67c6081b2afb1dd0a07d26515ca393cce4c37"
    },
    "image": "shophouse-quarter.jpg",
    "saved_world_title": "Shophouse Quarter · Toon",
    "style_title": "Toon town"
  }
];
