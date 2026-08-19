/** Return a safe downloadable source URL when the source is supported. */
export function getDownloadSourceUrl(sourceUrl?: string): string | undefined {
  const url = sourceUrl?.trim();
  if (!url) return undefined;

  try {
    const parsed = new URL(url, "http://openrag.local");
    if (!["http:", "https:"].includes(parsed.protocol)) return undefined;
    if (parsed.username || parsed.password) return undefined;

    const isManagedLocalSource =
      url.startsWith("/api/source-files/") &&
      parsed.pathname.startsWith("/api/source-files/");
    const isAbsoluteHttpUrl = /^https?:\/\//i.test(url);
    if (!isAbsoluteHttpUrl && !isManagedLocalSource) return undefined;
    return url;
  } catch {
    return undefined;
  }
}
