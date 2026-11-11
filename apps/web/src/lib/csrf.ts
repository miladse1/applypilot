const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Cross-site request forgery guard for the API proxy. The session cookie is SameSite=Lax, but
 * every site on localhost (any local dev server) counts as the same site. Browsers send Origin
 * on every POST/PUT/PATCH/DELETE, so a write is accepted only from this app's own pages.
 */
export function isTrustedWrite(method: string, origin: string | null, host: string | null, fetchSite: string | null): boolean {
  if (!UNSAFE_METHODS.has(method.toUpperCase())) return true;
  if (origin) {
    try {
      return new URL(origin).host === host;
    } catch {
      return false;
    }
  }
  // No Origin header: a non-browser client such as curl. A browser always sends Sec-Fetch-Site.
  return fetchSite === null || fetchSite === "same-origin" || fetchSite === "none";
}
