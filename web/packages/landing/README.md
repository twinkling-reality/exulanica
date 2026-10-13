# @exulanica/landing

The public Exulanica website and documentation.
This package owns the signed-out landing experience. Product scope and delivery order live in
[product direction](../../../docs/product-direction.md).

## Run and build

From the repository root, with workspace dependencies installed:

```bash
pnpm --dir web landing
pnpm --dir web landing:build
```

[DEPLOYING.md](DEPLOYING.md) owns hosting configuration and deployment checks.
The Vite production preview serves built Markdown exports as plain text, matching the published
`public/_headers` rules so View Markdown and Download Markdown retain their distinct behavior.

## Navigation and invitation

The home page places a short product description inside two counter-rotating loops of circular image planes viewed in perspective.
Twelve featured forms use application captures: three town configurations, each in Cozy town,
Finished town, and Toon town, plus Apartment District, Loft Quarter, and Shophouse Quarter. Their
receipts, creation values, appearance bindings, and image hashes live in `public/worlds/sources.json`
on the rows marked featured. `node scripts/generate-world-catalog.mjs` validates the image bytes
and derives the display catalog from those records. Names come from saved-world titles. Appearance
comes from the captured style title. The captures show generated towns. They are not evidence that
a model invented the town. There is no separately authored preview description.

Hover, keyboard focus and tap replace the center invitation with the world's name and appearance.
The center retains the invitation's type scale. Escape, an outside press, or tapping the selected
world again restores the invitation. The underlined entry link carries recipe, configuration and
exact appearance to the application's creation form for review; following it does not create a
world. Without an application destination, the link opens installation instructions.

Product, Use Cases and Documentation have independent
landing links and adjacent colored-marker menu controls. Their shaped gradient menus open on mouse
hover or marker activation. Arrow Down enters the links, Escape restores focus, and modified clicks
retain browser behavior. Each dropdown has one reactive companion. Use Cases links to distinct project
categories: Worldbuilding, Agent Experiments and Agent Development. Documentation links directly to guides and interfaces.
The GitHub and Twinkling Reality utility icons remain independent links.

The homepage invitation opens the configured application, or Installation when no destination is
configured. The homepage is a single viewport containing the orbit, central description and application
invitation. Product information and guides live on their own pages. Product explains the world, model decisions, recorded history and integrations through Overview and Capabilities. Use Cases connects those features to concrete projects. Documentation owns setup and operating instructions.

Navigation and category headings use noun-based labels in Title Case. A use-case page heading matches its navigation label; action links use verbs. Body copy uses sentence case. Product and Use Cases share layout and image treatment through `feature-pages.css`, and ambient motion through `ui/ambient-field.ts`. Site colors and typography inherit the theme and reading tokens. Dropdowns share panel padding,
row height and gaps; section-specific rules supply palette, shape and horizontal anchoring.
The site does not publish a blog index. `JOURNAL` in `src/content/journal.ts` is empty, and
`/blog`, `/research`, `/journal`, and `/roadmap` redirect to `/product#purpose`. Former article
paths listed in `src/router.ts` redirect there as well. Do not invent publication dates, results,
or endorsements.

Public paths that render a page are `/`, `/product`, `/product/capabilities`, `/use-cases` and its
category pages, and the documentation routes from `src/ui/docs/catalog.ts`.
The endpoint catalog generates operation navigation, routes, search entries and Markdown exports.
Old API section URLs redirect to their corresponding operation pages.
About redirects to `/product#purpose`, and its model, comparison, and source anchors go to the
capabilities page. Worlds redirects to `/product/capabilities#configurations`. Developers redirects
to `/docs`. `/waitlist` and `/site-information` redirect to Installation (`/docs/self-hosting`) and
to `/product#purpose` respectively. Query context survives redirects. Legacy world recipe paths
retain their configured application handoff. Unknown paths show a missing-page message. Hidden
surfaces are inert.

The [interface system](../../../docs/interface-system.md#public-reading-and-controls) owns the
public design rules. `reading-system.css` supplies semantic reading roles and shared control,
page-action and disclosure treatments. Font stacks come from presentation's `--ui-font-brand` and
`--ui-font-code`; reading motion aliases the navigation timing and shared quick duration.
Use existing tokens before adding a component value. Keep layout rules in `documentation.css`
and search layout in `documentation-search.css`; remove superseded declarations when revising a
component. Do not append a corrective style layer.

Use the shared `action` helper for public secondary destinations. Documentation's `routeLink`
delegates to it; paging uses the same helper with a directional arrow. The visible label names the
destination once. Previous and Next remain in accessible names and `rel` attributes. Inline prose
links retain their underline. Primary application entry keeps its existing treatment.

The secondary action has a 30px face with 4px corners inside a 44px target. Compact controls share
presentation's 13px `--ui-text-compact` and 44px `--ui-control-target`; light hover and press reuse
`--ui-light-action-hover` and `--ui-light-action-pressed`. Documentation utilities use 8px corners,
content/code/table frames use 12px and search uses 16px. Small metadata tags use capsules; reading
rows use 4px corners. Tags identify real categories, HTTP methods and response status. Do not add
Guide, API or Source labels to ordinary destinations. Rails use ink and weight for selection, search
uses a neutral selection wash, and reading surfaces follow the public light/dark preference.

Copy and export actions pair text with small functional icons. Desktop menu rows use 36px
targets; mobile rows retain 44px. Menu focus stays inset within each row. Search and disclosure icons communicate function and inherit
ink and accessible names from their controls. All standalone controls have 44px targets and
visible focus. Native disclosures preserve their semantics. Menus, disclosure content and request
panels have brief state-driven reveals; reduced motion removes them. `ui/copy-feedback.ts` binds
page and code copy feedback to clipboard completion, including pending and failure states. Code
uses one inset surface in the selected scheme, with aligned label/text edges and a 44px toolbar.
Copy reuses the secondary action with a quiet face at rest; its glyph and label confirm success.
The live success message is visually hidden to avoid repeating that confirmation. Failure guidance
stays visible in its own row without covering the example. Request tabs use stronger selected text
and a fine lower rule, sharing the copy toolbar's target and hover proportions. Decorative tags are excluded from search text and Markdown labels.

Pages share the navigation's outer gutter. Text shares its heading's left edge; documentation
retains separate navigation and section rails. The orbit and shaped menus own the
abstract visual identity, while inner pages use actual application imagery and text.

Documentation follows four responsibilities: Getting Started, Worlds, Models and Agents, and
Developer Tools. World structure, creation, assets, rules, model decisions and comparisons have
focused guides. Content inputs sit within world-building workflows. Future mechanisms are described
at their contract boundary without presenting them as installed operations.

The shell uses the shared white canvas and IBM Plex typography, with a navigation rail, constrained
article measure, page outline and sidebar search. Navigation and outlines become native disclosures
on narrow screens. Search remains available above those disclosures. Page copying uses a split control with Markdown viewing
and download actions in its keyboard-accessible dropdown. Documentation adds no second site header or
site footer. Search opens a shared modal dialog with suggested guides, ranked section and API results,
matching text and an explicit empty state. Arrow keys select results while focus stays in the search
field; Enter opens the selection and Escape closes the dialog and restores launcher focus.
Command/Ctrl K opens search on the active documentation page.

`src/ui/docs/catalog.ts` owns guide membership, grouping, labels, descriptions, routes and reading
order. Each content builder identifies its technical source in `sourcePath`. Builders supply the
browser article, section search, copied Markdown and published exports; commands and examples must
not be maintained in a separate Markdown copy. `documentation-contracts.test.ts` checks every internal
document link, section target, source path, route and export, and the complete API operation inventory.
Guide pagination and API example pagination remain separate. Moved section addresses redirect to
their owners. The production build emits route-specific HTML metadata and a sitemap; page content
is rendered by the browser.

## Application destination

World preview links open the canonical application in `@exulanica/app`. Its destination belongs
to the deployment and has no development default:

```bash
VITE_ATLAS_URL=https://atlas.example.com pnpm --dir web landing:build
```

A same-origin path such as `/atlas` is also supported. An absent or invalid value sends world previews to the
documentation. The homepage invitation opens the configured application, or the installation guide when no application is configured. A local development handoff can be configured explicitly:

```bash
VITE_ATLAS_URL='http://127.0.0.1:5175/?preview=1' pnpm --dir web landing
```

The application's preview query is honored only by its development server.

## Access information

The site has no email collection form, signup request or provider endpoint. Existing `/waitlist`
bookmarks redirect to `/docs/self-hosting`. `/site-information` redirects to Product’s purpose section.

## Artwork and motion

The daylight palette is green `#cefa96`, yellow `#f4ff91` and blue `#c6e1ff` on a near-white
`#fcfdf9` canvas. Bundled IBM Plex Sans provides display and reading type; IBM Plex Mono is reserved
for code and small utility text. No remote fonts, images or rendering dependencies are required.

The loops use a shared perspective projection for the rendered circles and native world buttons.
Forms maintain equal angular spacing and travel in opposite directions over an 84-second period.
A small WebGL surface renders the image planes across the full page. Nearby forms join the actual
viewport boundary, with chromatic dispersion and softened sampling limited to their outer edges
and connecting neck. There is no invisible inner clipping boundary. Worlds far from the viewport
edge stay crisp. The shader and projection use no rendering framework.
Hover or keyboard focus on a selectable world pauses the loops. Three smaller abstract forms remain
decorative. The nine world controls keep equal angular spacing on the outer track. The selected
world's text appears in the open center on desktop and mobile. There is no pointer-tracking camera.
Page changes cross-fade without moving text. Reduced motion holds a static composition and suppresses
spatial reveal and hover travel. Rendering pauses while hidden or on another route. If WebGL is
unavailable, tilted native forms retain the world controls without the optical effect. Forced colors
uses native controls instead of the rendered surface.
The reusable vector forms module remains available independently but is not mounted by the site.

## Package boundary and verification

The only workspace dependency is `@exulanica/presentation`, used for shared CSS tokens.
The landing bundle excludes the application renderer, world-style registry, formation replay,
graph client and Companion runtime. Dependency rules and the production sourcemap test cover
that boundary. No application state is constructed to render the public introduction.

```bash
pnpm --dir web typecheck
pnpm --dir web boundaries
pnpm --dir web exec vitest run packages/landing
pnpm --dir web landing:build
```

Browser review should cover desktop and narrow layouts, menu keyboard behavior, page routes and legacy hash
navigation, the configured application destination and the absence of email collection. Unit tests
cover routing transitions, artwork invariants, disclosure behavior, documentation search and access information;
they do not establish visual quality or verify a deployed application.

## Reading exports

Documentation and articles provide Copy page and Markdown links. The same content builders produce
the browser content and the static `.md` files. `/llms.txt` indexes these pages; `/llms-full.txt`
contains their full text. `/openapi.json` publishes the checked-in API contract. The schema on an
installed server remains authoritative for that installation. No reading tools contact an AI service.

The guided World API reference derives field types and constraints from a selected subset of
`tests/snapshots/api-openapi.json`. After that contract changes, regenerate the reference with
`node web/packages/landing/scripts/sync-api-reference.mjs` from the repository root. The same generator derives the complete operation catalog from that schema and
`tests/snapshots/api-routes.json`, preserving each route’s authorization rule. Tests check both
outputs and the complete agent example against their underlying sources. A contract definition
is labelled separately from sample or live response data.
