/**
 * Extract / sanitize provider stream errors for chat display.
 */

function tryParseJsonMessage(text: string): string | null {
  try {
    const data = JSON.parse(text) as Record<string, unknown>;
    if (!data || typeof data !== "object") {
      return null;
    }

    const errors = data.errors;
    if (Array.isArray(errors) && errors[0] && typeof errors[0] === "object") {
      const first = errors[0] as { message?: unknown; code?: unknown };
      if (typeof first.message === "string" && first.message.trim()) {
        return first.message;
      }
      if (typeof first.code === "string" && first.code.trim()) {
        return `Error: ${first.code}`;
      }
    }

    const errorObj = data.error;
    if (errorObj && typeof errorObj === "object") {
      const message = (errorObj as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) {
        return message;
      }
    }

    if (typeof data.message === "string" && data.message.trim()) {
      return data.message;
    }
    if (typeof data.errorMessage === "string" && data.errorMessage.trim()) {
      return data.errorMessage;
    }
    if (typeof data.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Strip embedded provider JSON payloads so chat never shows raw error objects.
 */
export function formatProviderErrorMessage(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) {
    return "An error occurred while generating a response.";
  }

  const direct = tryParseJsonMessage(trimmed);
  if (direct) {
    return direct;
  }

  const jsonStart = trimmed.indexOf("{");
  if (jsonStart >= 0) {
    const nested = tryParseJsonMessage(trimmed.slice(jsonStart));
    if (nested) {
      const prefix = trimmed
        .slice(0, jsonStart)
        .replace(/[:\s]+$/, "")
        .trim();
      return prefix ? `${prefix}: ${nested}` : nested;
    }
    // Unparseable JSON residue — keep the human-readable prefix only.
    const prefix = trimmed
      .slice(0, jsonStart)
      .replace(/[:\s]+$/, "")
      .trim();
    if (prefix) {
      return prefix;
    }
  }

  return trimmed;
}

/**
 * Extract a user-facing provider/stream error message from an NDJSON chunk.
 * Returns null when the chunk is not a failed/error terminal event.
 */
export function extractStreamProviderError(chunk: unknown): string | null {
  if (!chunk || typeof chunk !== "object") {
    return null;
  }

  const c = chunk as {
    finish_reason?: unknown;
    status?: unknown;
    error?: unknown;
    message?: unknown;
  };

  if (c.finish_reason !== "error" && c.status !== "failed") {
    return null;
  }

  let raw: string | null = null;

  if (typeof c.error === "string" && c.error.trim()) {
    raw = c.error;
  } else if (c.error && typeof c.error === "object") {
    const message = (c.error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      raw = message;
    }
  } else if (typeof c.message === "string" && c.message.trim()) {
    raw = c.message;
  }

  if (!raw) {
    return "An error occurred while generating a response.";
  }

  return formatProviderErrorMessage(raw);
}
