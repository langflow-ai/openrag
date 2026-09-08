import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

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
