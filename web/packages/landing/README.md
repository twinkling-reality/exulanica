# @exulanica/landing

The public Exulanica introduction, exploration pages, builder resources, research and waitlist.
This package owns the signed-out landing experience. Product scope and delivery order live in
[product direction](../../../docs/product-direction.md).

## Run and build

From the repository root, with workspace dependencies installed:

```bash
pnpm --dir web landing
pnpm --dir web landing:build
```

[DEPLOYING.md](DEPLOYING.md) owns hosting configuration and deployment checks.

## Navigation and invitation

The home page places a short product description inside two counter-rotating loops of circular image planes viewed in perspective.
Two selectable forms use genuine still captures from the application's `public/your-worlds/` assets,
identified by `recipe-pictures.ts`. They are previews, not live worlds or recorded footage.
Hover and keyboard focus bring a portal forward. Selecting it opens its named capture in a
native modal dialog. Escape or the close button returns focus to the selected world. The preview
links to the configured application with its recipe selected, or to the waitlist.

The compact lowercase home link, three navigation disclosures, and GitHub and Twinkling
Reality links share aligned outer gutters. Platform contains About and Worlds; Developers contains
the overview, World API and agent integration; Resources contains documentation, research and roadmap.
Menus open on pointer hover or activation. Only one disclosure opens at a time. Arrow Down enters its links; Escape closes it and restores
focus. Modified clicks retain normal browser behavior.

The primary invitation is **Join Waitlist**. It appears once at the bottom of the home page,
in the header on reading pages, and only in the form on the waitlist page. Secondary page actions
use compact outlined controls. Navigation markers expand into fading outlines, while dropdown
panels use left, centered and mirrored-right silhouettes with blue, rose and green palettes.

Public paths are `/`, `/about`, `/worlds`, `/developers`, `/research`, `/waitlist`, `/docs`,
`/docs/world-api`, `/docs/agents` and `/roadmap`. The browser-history router preserves native links,
modified clicks, Back and Forward, article anchors and reading positions. Legacy hash URLs resolve
to their corresponding paths. Unknown paths show a missing-page message. Hidden surfaces are inert.

Worlds presents the same captures in a two-item collection. Reading pages use a shared introduction,
sections organized by responsibility and further-reading links. Documentation uses a compact
sidebar, article and section index. On narrow screens the documentation navigation becomes a
wrapping row above the article. Signup preserves its validation, retry and confirmed-success states.

## Application destination

World preview links open the canonical application in `@exulanica/app`. Its destination belongs
to the deployment and has no development default:

```bash
VITE_ATLAS_URL=https://atlas.example.com pnpm --dir web landing:build
```

A same-origin path such as `/atlas` is also supported. An absent or invalid value sends world previews to the
waitlist. The homepage invitation stays Join Waitlist in either configuration. A local development handoff can be configured explicitly:

```bash
VITE_ATLAS_URL='http://127.0.0.1:5175/?preview=1' pnpm --dir web landing
```

The application's preview query is honored only by its development server.

## Waitlist endpoint

The landing package stores no addresses. A deployment provides the form endpoint:

```bash
VITE_WAITLIST_URL=https://forms.example/f/abc pnpm --dir web landing:build
```

Submission sends `email_address=<address>` as `application/x-www-form-urlencoded`. The endpoint must
allow the deployed origin through CORS and return a successful HTTP response with JSON
`status: "success"`. An HTTP success without provider confirmation is not treated as a signup. A failed request keeps the entered address and lets
the visitor retry. Success replaces the form with confirmation.

The endpoint must use HTTPS, with HTTP allowed on a loopback host during development. Without
a valid endpoint, the page displays a temporary-unavailable message instead of a disabled form.
Requests time out after 15 seconds; failed requests preserve the address for retry. There is no
implicit endpoint. Local preview configuration can use an ignored `.env.local` file in this package
with the documented public form endpoint from [DEPLOYING.md](DEPLOYING.md).

## Artwork and motion

The daylight palette is green `#cefa96`, yellow `#f4ff91` and blue `#c6e1ff` on a near-white
`#fcfdf9` canvas. Bundled IBM Plex Sans provides display and reading type; IBM Plex Mono is reserved
for code and small utility text. No remote fonts, images or rendering dependencies are required.

The loops use a shared perspective projection for the rendered circles and native world buttons.
Forms maintain equal angular spacing and travel in opposite directions over an 84-second period.
A small WebGL surface renders the image planes, smoothly joins nearby forms to the boundary, and
refracts their imagery along the resulting contour. Chromatic dispersion and softened sampling are
concentrated at that connection. On wide screens the optical field stays centered and fades into
the page at its boundary. The shader and projection use no rendering framework.
Hover or keyboard focus on a world pauses the loops. A keyboard target outside the viewport returns
along its track before selection. Opening a preview also pauses the loops and reveals the capture
from the selected portal's measured position. There is no pointer-tracking camera.
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
navigation, the configured entry destination and the waitlist's connection state. Unit tests
cover routing transitions, artwork invariants, disclosure behavior and waitlist responses;
they do not establish visual quality or verify a deployed form provider.
