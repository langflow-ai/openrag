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

function extractBalancedJsonObject(text: string): string | null {
  const start = text.indexOf("{");
  if (start < 0) {
    return null;
  }
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === "{") {
      depth += 1;
    } else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        return text.slice(start, i + 1);
      }
    }
  }
  return null;
}

/**
 * True when assistant text looks like a provider/auth failure rather than a reply.
 * Marker list aligned with src/api/provider_validation.py (_PROVIDER_ERROR_CONTENT_MARKERS).
 * Ambiguous phrases use tighter patterns so ordinary assistant prose is not flagged.
 */
export function looksLikeProviderErrorContent(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) {
    return false;
  }
  if (trimmed.startsWith("Error:")) {
    return true;
  }
  const lowered = trimmed.toLowerCase();
  const markers = [
    "incorrect api key",
    "invalid api key",
    "invalid_api_key",
    "api key could not be found",
    "api key is invalid",
    "api key has been revoked",
    "api key revoked",
    "revoked api key",
    "provided api key could not be found",
    "authentication_error",
    "failed to authenticate",
    "invalid x-api-key",
    "authentication failed",
    "invalid credentials",
    "could not authenticate",
    "rate limit",
    "rate_limit",
    "provider request failed",
    "insufficient_quota",
  ];
  if (markers.some((marker) => lowered.includes(marker))) {
    return true;
  }
  // Tighter matches for phrases that also appear in ordinary explanations.
  if (
    /(?:^|\berror\b[:\s]*|\b(?:401|403)\b[:\s]*)unauthorized\b/.test(lowered) ||
    /(?:^|\berror\b[:\s]*)permission denied\b/.test(lowered) ||
    /\bpermission denied\s*:/.test(lowered) ||
    /(?:^|\berror\b[:\s]*)quota exceeded\b/.test(lowered) ||
    /\bquota exceeded\s*:/.test(lowered)
  ) {
    return true;
  }
  if (
    trimmed.includes("{") &&
    (lowered.includes('"error"') ||
      lowered.includes('"errormessage"') ||
      lowered.includes('"errorcode"') ||
      lowered.includes('"errors"'))
  ) {
    return true;
  }
  return false;
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

  const jsonBlob = extractBalancedJsonObject(trimmed);
  if (jsonBlob) {
    const nested = tryParseJsonMessage(jsonBlob);
    if (nested) {
      let prefix = trimmed
        .slice(0, trimmed.indexOf(jsonBlob))
        .replace(/[:\s]+$/, "")
        .trim();
      if (/error$/i.test(prefix)) {
        prefix = prefix
          .replace(/error$/i, "")
          .replace(/[:.\s]+$/, "")
          .trim();
      }
      return prefix ? `${prefix}: ${nested}` : nested;
    }
    const prefix = trimmed
      .slice(0, trimmed.indexOf(jsonBlob))
      .replace(/[:\s]+$/, "")
      .trim();
    if (prefix) {
      return prefix;
    }
  }

  // Truncated / unbalanced JSON — keep the readable prefix only.
  const jsonStart = trimmed.indexOf("{");
  if (jsonStart > 0) {
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

  // Empty error payloads are common from Langflow (finish_reason=error with no
  // message). Return null so the client can fall back to accumulated content or
  // a later sanitized error chunk instead of a generic placeholder.
  if (!raw) {
    return null;
  }

  return formatProviderErrorMessage(raw);
}
