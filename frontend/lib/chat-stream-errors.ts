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

  if (typeof c.error === "string" && c.error.trim()) {
    return c.error;
  }

  if (c.error && typeof c.error === "object") {
    const message = (c.error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }

  if (typeof c.message === "string" && c.message.trim()) {
    return c.message;
  }

  return "An error occurred while generating a response.";
}
