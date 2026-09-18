/**
 * The Companion's appearance, for a surface that must not pay for the world.
 *
 * `index.ts` is the whole presentation contract and it is not safe to import for its Companion
 * symbols alone. It re-exports `world-profiles.js`, which constructs the world style registry at
 * module scope, and a constructor call at module scope cannot be dropped as unused: a bundler that
 * sees one named import from the barrel still ships and runs the registry and the five modules
 * behind it. Measured on the public landing page, that was 25,600 of 55,898 attributed bundle
 * bytes executing on every cold load, with `world-style-model.ts` larger than any module the page
 * itself had written, to draw one small avatar in the corner of a signed-out screen.
 *
 * So this entry exists for consumers that want the avatar and not the vocabulary. The two modules
 * behind it import nothing at runtime, which is the property that makes the narrow entry worth
 * having, and `landing/test/bundle-boundary.test.ts` fails if the page's build ever carries a world
 * style module again. The composition root keeps importing the barrel, because it does want both.
 */
export * from './companion-appearance.js';
export * from './companion-avatar-blueprint.js';
