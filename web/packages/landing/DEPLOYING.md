# Deploying the public landing site

This guide owns the public site's hosting configuration and release procedure. The landing
package is built locally and deployed manually to Cloudflare Pages; no repository workflow
publishes it automatically.

## Hosting and build configuration

| Setting | Value |
| --- | --- |
| Cloudflare Pages project | `exulanica` |
| Public origin | `https://exulanica.com` |
| Project origin | `https://exulanica.pages.dev` |
| `VITE_ATLAS_URL` | Unset until a public application is available |

`VITE_ATLAS_URL` is public configuration read by Vite at build time. An ignored `.env.local`
file inside this package may supply it for local previews; explicit build environment variables
take precedence. A configured application URL connects world previews to their matching recipe.
Without it, previews link to the getting-started guide.

The site does not collect email. The old `/waitlist` URL redirects to `/docs/self-hosting`.
There is no signup provider or form endpoint to configure. The [package guide](README.md)
describes navigation and application handoff.

The build emits route-specific index documents and a sitemap. Cloudflare Pages serves the root
index document for unmatched paths. This supports direct loading
of the public page routes, including `/docs/world-api`. The browser router selects the page or
shows a missing-page message. This fallback also means a successful HTTP status alone does not
prove an asset exists: verification must compare file contents.

## Verify and publish

Compare the configured local build against the public origin:

```bash
pnpm --dir web landing:verify
```

The command rebuilds the site and reports differences from the deployed files. A difference is
expected for an unpublished change; inspect it before publishing. Shared presentation tokens
and fonts are build inputs as well as files in the landing package.

After release approval, build and deploy:

```bash
pnpm --dir web landing:build
npx wrangler pages deploy web/packages/landing/dist --project-name=exulanica --branch=main
```

Use the configured Cloudflare account; `wrangler whoami` identifies it. Publishing changes the
public site. A local preview or passing build does not itself publish anything.

## Check the deployed result

- Open the home page, a direct documentation path and the waitlist path, then refresh each.
- Confirm Back and Forward preserve navigation and that an unknown path shows a missing page.
- Confirm `/waitlist` redirects to `/docs/self-hosting`, and confirm `/roadmap` and `/blog` redirect to `/product#purpose`. Confirm no email form or submission request remains.
- Inspect desktop and phone layouts, keyboard focus, menus and reduced-motion behavior.
- Inspect hosting-injected scripts separately from the bundle. Cloudflare Web Analytics and
  request logging are hosting settings; an absence of analytics code here does not establish
  that the public deployment has no analytics or request logs.
