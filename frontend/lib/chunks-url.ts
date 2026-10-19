export function buildChunksUrl(
  filename: string,
  effectiveSearchText: string,
): string {
  const params = new URLSearchParams({ filename });
  const trimmed = effectiveSearchText.trim();
  if (trimmed && trimmed !== "*") {
    params.set("q", trimmed);
  }
  return `/knowledge/chunks?${params.toString()}`;
}
