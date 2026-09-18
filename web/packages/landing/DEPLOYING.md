# Deploying the public landing site

`exulanica.com` is this package, built locally and uploaded by hand. There is no deploy workflow in
`.github/workflows`, nothing watches a branch, and no build runs anywhere but on the machine of
whoever types the command. Read this before deploying, because two of the facts below are the kind
that produce a site which looks correct and is not.

## Where it is

| | |
| --- | --- |
| Host | Cloudflare Pages |
| Project | `exulanica` |
| Public origin | `https://exulanica.com` |
| Project origin | `https://exulanica.pages.dev`, serving the same bytes |
| Account | the Cloudflare account belonging to this project's operator; `wrangler whoami` names it |

The domain's nameservers are Cloudflare's and the apex is proxied, so the site is reached through
Cloudflare whichever name is used. Both origins were checked byte for byte against the same build.

## The two build-time values

Neither reaches the bundle from any file in `src/`. Both are read through `import.meta.env` and
substituted by Vite at build time, so **the source alone does not tell you what a deployment does**.
`README.md` explains why each one is deployment-owned; this file records what they are set to.

| Variable | Production value | A build without it |
| --- | --- | --- |
| `VITE_WAITLIST_URL` | `https://app.kit.com/forms/9921855/subscriptions` | The waitlist station and surface are still built, the field is shut, and the page does not explain why |
| `VITE_ATLAS_URL` | unset | No Enter Exulanica station is built, and the waitlist leads the column instead |

The endpoint is not a secret. It is a public form action that the deployed bundle hands to every
visitor, and it is written here because a value that exists only in somebody's shell history is a
value the next deploy will omit.

**`VITE_ATLAS_URL` being unset is a decision, not an oversight.** With it set, Enter Exulanica leads
the column and no waitlist station is built at all, which is `README.md`'s "One way in" rule. So
setting it on a deploy does not add a way in, it replaces the one that is there.

### The failure this arrangement makes easy

A build with no `VITE_WAITLIST_URL` resolves the waitlist destination to nothing. That is a
deliberate refusal, and it is the right one: the alternative is posting somebody's email address to
whatever happened to be listening. But its consequence is that a rebuild by anyone who does not know
the variable exists produces a page that renders normally, offers a waitlist, and collects nothing,
with no error anywhere. Nothing in the source, the build output or the deployed page says the
variable was missing.

`pnpm run landing:verify` exists because of this. It refuses to run at all without the variable
rather than compare a shut build against an open one and report a puzzle.

## Before you deploy

```bash
VITE_WAITLIST_URL=https://app.kit.com/forms/9921855/subscriptions pnpm --dir web landing:verify
```

It rebuilds this tree and compares every file against what the origin serves, then says one of two
things: this tree rebuilds the live site exactly, or it does not and here is which files differ. Run
it first and read the answer, because it converts "am I about to republish what is already there or
change it" from a recollection into a measurement.

It reports a difference in both directions on purpose. Asset filenames carry a content hash, so a
changed file is a path the origin has never heard of, and **this deployment answers an unknown path
with the index page and a `200`** rather than a `404`. Anything reading the status alone concludes
the file is fine. The first version of that script did exactly this and reported a bundle the origin
does not hold as a 2,874 byte content mismatch, which is the size of the index page.

## Deploying

```bash
VITE_WAITLIST_URL=https://app.kit.com/forms/9921855/subscriptions pnpm --dir web landing:build
npx wrangler pages deploy web/packages/landing/dist --project-name=exulanica --branch=main
```

Then load the site and submit an address to the waitlist, because a shut field and an open one look
the same until one is used.

`--commit-dirty=true` suppresses wrangler's warning that the tree has uncommitted changes. Reach for
it only after deciding the warning is wrong, which is rarer than it feels: the one deployment this
project has made used it, and the source of what is live was therefore uncommitted at the moment it
went out.

## What is live

The public site has had exactly one deployment. `pnpm run landing:verify` answers whether this tree
still produces it; that answer is not repeated here, because a sentence naming a commit is a claim
sitting where nothing can check it, and the next deploy makes it false without touching this file.

Two things about that deployment are worth carrying, because neither is recoverable from the site:

- It was uploaded from a working tree that had not been committed, so for fifty minutes the bytes
  serving the public internet existed in no commit anywhere. They were reproduced afterwards, byte
  for byte, from the commit that captured that work.
- The landing package's sources are not the only input, and the other one is larger than it looks.
  `src/ui/chrome.ts` imports the Companion blueprint from `@exulanica/presentation`, whose barrel
  also re-exports `world-profiles.js`, which constructs the world style registry at module scope.
  A constructor call at module scope cannot be dropped as unused, so that module and the five
  behind it are built into this page and run on every load of it. That means
  `@exulanica/presentation` moving changes what the public site ships with nothing in
  `packages/landing` changing at all, which is exactly what happened between the deployed state and
  `main`. `npx vite build --sourcemap` in the package, read against the coverage of a cold load,
  is how to measure how much; do that rather than trust a figure written here, which would rot.
  The page now imports `@exulanica/presentation/companion` rather than the barrel, so the next
  deploy will carry about half the JavaScript this one does. That is a bundle change and not a
  visible one, and `landing:verify` will report it as a difference, correctly.
