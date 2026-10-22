/**
 * A made town's own things by name: the street furniture and street trees its tiles draw, named as
 * the shipped catalogs the town was made from name them (street-furniture.v2.json's labels,
 * tree-species.v2.json's common names), read here as data. Build mode says these over a town's own
 * bench, bin or tree, which came with the world and cannot be changed in it (ruling W13 T3).
 */
import furniture from '../../../assets/catalogs/street-furniture.v2.json' with { type: 'json' };
import trees from '../../../assets/catalogs/tree-species.v2.json' with { type: 'json' };

const FURNITURE = new Map(furniture.entries.map((entry) => [entry.key, entry.label]));
const TREES = new Map(trees.entries.map((entry) => [entry.key, entry.common_name]));

/** How each kind of record a town draws as one of its things is named from its fields. */
const NAMED = Object.freeze({
  'city.street_furniture': (fields) => FURNITURE.get(fields.furniture_class) ?? 'Street furniture',
  'city.street_tree': (fields) => TREES.get(fields.species) ?? 'Street tree',
});

/**
 * The name of a town's own thing from its tile record (`kind`, `fields`), or null for a record that
 * is not one of its things (a building, a street, the ground).
 */
export function townThingName(record) {
  const named = NAMED[record?.kind];
  return named ? named(record.fields ?? {}) : null;
}
