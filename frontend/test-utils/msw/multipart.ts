/**
 * Minimal multipart/form-data reader for MSW handlers.
 *
 * Why not `await request.formData()`: under vitest's jsdom environment, jsdom
 * supplies its own `File`/`Blob`, which undici (the fetch implementation MSW
 * intercepts) cannot re-parse. `request.formData()` throws, and MSW turns that
 * into a 500 that surfaces as a confusing "Upload failed" from app code.
 *
 * Reading `request.text()` works, so this parses the raw body instead.
 *
 * LIMITS, and they are environment limits rather than choices:
 *   - Text fields round-trip exactly.
 *   - File parts are COUNTED but their filename and bytes are NOT available —
 *     jsdom's File crosses the boundary as an unnamed, empty blob. Assertions
 *     about uploaded file *content* or *names* belong in Playwright.
 */

export interface ParsedMultipart {
  /** Text field values by name. Repeated fields keep every value. */
  fields: Record<string, string[]>;
  /** Number of parts that carried a `filename` (i.e. file inputs). */
  fileCount: number;
}

export function parseMultipart(body: string): ParsedMultipart {
  const fields: Record<string, string[]> = {};
  let fileCount = 0;

  const boundaryMatch = /^(--[^\r\n]+)\r\n/.exec(body);
  if (!boundaryMatch) {
    return { fields, fileCount };
  }
  const boundary = boundaryMatch[1];

  for (const rawPart of body.split(boundary)) {
    const part = rawPart.replace(/^\r\n/, "");
    if (!part || part.startsWith("--")) continue;

    const split = part.indexOf("\r\n\r\n");
    if (split === -1) continue;

    const headers = part.slice(0, split);
    const value = part.slice(split + 4).replace(/\r\n$/, "");

    const name = /name="([^"]*)"/.exec(headers)?.[1];
    if (!name) continue;

    if (/filename="/.test(headers)) {
      fileCount++;
      continue;
    }

    if (!fields[name]) {
      fields[name] = [];
    }
    fields[name].push(value);
  }

  return { fields, fileCount };
}

/** Convenience: first value of a text field, or undefined when absent. */
export function field(
  parsed: ParsedMultipart,
  name: string,
): string | undefined {
  return parsed.fields[name]?.[0];
}
