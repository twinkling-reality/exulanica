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
| `VITE_WAITLIST_URL` | `https://app.kit.com/forms/9921855/subscriptions` |
| `VITE_ATLAS_URL` | Unset for the public waitlist deployment |

The form endpoint is public configuration, exposed in the browser bundle. It is not a secret.
Vite reads both values at build time. An ignored `.env.local` file inside this package may
supply them for local previews; explicit build environment variables take precedence.

A build without a valid waitlist endpoint displays a temporary-unavailable message and hides
the form. It cannot collect addresses. A configured application URL connects world previews to their matching recipe in the application.
The primary invitation remains **Join Waitlist**. The [package guide](README.md)
describes navigation, application handoff and form behavior.

Cloudflare Pages serves the index document for unmatched paths. This supports direct loading
of the public page routes, including `/docs/world-api`. The browser router selects the page or
shows a missing-page message. This fallback also means a successful HTTP status alone does not
prove an asset exists: verification must compare file contents.

## Verify and publish

Compare the configured local build against the public origin:

```bash
VITE_WAITLIST_URL=https://app.kit.com/forms/9921855/subscriptions pnpm --dir web landing:verify
```

The command rebuilds the site and reports differences from the deployed files. A difference is
expected for an unpublished change; inspect it before publishing. Shared presentation tokens
and fonts are build inputs as well as files in the landing package.

After release approval, build and deploy:

```bash
VITE_WAITLIST_URL=https://app.kit.com/forms/9921855/subscriptions pnpm --dir web landing:build
npx wrangler pages deploy web/packages/landing/dist --project-name=exulanica --branch=main
```

Use the configured Cloudflare account; `wrangler whoami` identifies it. Publishing changes the
public site. A local preview or passing build does not itself publish anything.

## Check the deployed result

- Open the home page, a direct documentation path and the waitlist path, then refresh each.
- Confirm Back and Forward preserve navigation and that an unknown path shows a missing page.
- Confirm the waitlist field accepts input and no duplicate signup action appears on that page.
- With a designated test address and authorization to subscribe it, verify the provider accepts
  a submission and the page confirms it. Browser form validation and mocked provider tests do
  not establish that the deployed provider's CORS and subscription settings work.
- Inspect desktop and phone layouts, keyboard focus, menus and reduced-motion behavior.

The form sends Kit's `email_address` field and requires an explicit JSON success response.
A timeout, denied cross-origin request, failed status or rejected subscription restores the
form for retry. Success copy assumes the provider's configured automatic confirmation behavior;
recheck that copy if provider confirmation settings change.
