/**
 * The digest a route names its document by in its entity tag (RFC 9110 section 8.8.3), as the page reads it after any
 * edge in between: the tag's opaque value without its quotes, without a weak `W/` prefix, and without the content
 * coding an edge appends when it compresses the body on its way (Caddy's `encode` turns `"<sha256>"` into
 * `"<sha256>-zstd"`; others append `-gzip`, `-br` or `-deflate`). The browser hands the page the document itself, so
 * what the route named is still what the body's own digest is compared with; a tag that names another document is
 * still refused there. Pure; nothing here reads a response.
 */

/** The content codings an edge may append to a tag when it compresses a body. */
const CODING = /-(?:zstd|gzip|br|deflate)$/u;

/** The digest `etag` names, or null where there is no tag. */
export function entityTagDigest(etag: string | null | undefined): string | null {
  if (etag == null) return null;
  const bare = etag.trim().replace(/^W\//u, '').replace(/^"/u, '').replace(/"$/u, '').replace(CODING, '');
  return bare === '' ? null : bare;
}
