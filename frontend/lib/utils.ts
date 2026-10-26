import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Mirror the custom `@theme` keys in app/globals.css. Without this,
// tailwind-merge reads `text-mmd` as a text color and drops it when a later
// `text-foreground` appears.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["xxs", "mmd"],
      radius: ["mmd"],
      spacing: [
        "mmd",
        "task-dialog-error-indent",
        "task-dialog-error-indent-cloud",
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function isChunkLoadError(error: Error): boolean {
  return (
    error.name === "ChunkLoadError" ||
    error.message?.includes("Loading chunk") ||
    error.message?.includes("Failed to fetch")
  );
}

export function encodeBase64(str: string): string {
  return Buffer.from(str).toString("base64");
}

export function decodeBase64(str: string): string {
  return Buffer.from(str, "base64").toString("utf-8");
}

export function formatFlowName(type: string): string {
  if (type === "url_ingest") return "URL Ingest";
  return type.charAt(0).toUpperCase() + type.slice(1).replace(/_/g, " ");
}
