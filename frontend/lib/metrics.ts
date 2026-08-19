import {
  Counter,
  collectDefaultMetrics,
  Histogram,
  Registry,
} from "prom-client";

interface Metrics {
  registry: Registry;
  backendProxyDuration: Histogram;
  backendProxyTotal: Counter;
  backendProxyErrors: Counter;
  httpRequestDuration: Histogram;
  httpRequestsTotal: Counter;
}

const GLOBAL_KEY = Symbol.for("openrag.metrics");

function getOrCreateMetrics(): Metrics {
  const g = globalThis as Record<symbol, Metrics>;
  if (!g[GLOBAL_KEY]) {
    const registry = new Registry();
    collectDefaultMetrics({
      register: registry,
      prefix: "nodejs_",
      gcDurationBuckets: [0.001, 0.01, 0.1, 1, 2, 5],
    });

    g[GLOBAL_KEY] = {
      registry,
      backendProxyDuration: new Histogram({
        name: "backend_proxy_duration_seconds",
        help: "Duration of backend proxy requests in seconds",
        labelNames: ["method", "path", "status_code"],
        buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60],
        registers: [registry],
      }),
      backendProxyTotal: new Counter({
        name: "backend_proxy_requests_total",
        help: "Total number of backend proxy requests",
        labelNames: ["method", "path", "status_code"],
        registers: [registry],
      }),
      backendProxyErrors: new Counter({
        name: "backend_proxy_errors_total",
        help: "Total number of backend proxy errors",
        labelNames: ["method", "path", "error_type"],
        registers: [registry],
      }),
      httpRequestDuration: new Histogram({
        name: "http_request_duration_seconds",
        help: "Duration of inbound HTTP requests in seconds",
        labelNames: ["method", "route", "status_code"],
        buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
        registers: [registry],
      }),
      httpRequestsTotal: new Counter({
        name: "http_requests_total",
        help: "Total inbound HTTP requests",
        labelNames: ["method", "route", "status_code"],
        registers: [registry],
      }),
    };
  }
  return g[GLOBAL_KEY];
}

const metrics = getOrCreateMetrics();

export const metricsRegistry = metrics.registry;
export const backendProxyDuration = metrics.backendProxyDuration;
export const backendProxyTotal = metrics.backendProxyTotal;
export const backendProxyErrors = metrics.backendProxyErrors;
export const httpRequestDuration = metrics.httpRequestDuration;
export const httpRequestsTotal = metrics.httpRequestsTotal;

export function normalizePath(raw: string): string {
  return raw
    .split("/")
    .map((seg) => {
      if (
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          seg,
        )
      )
        return ":id";
      if (/^[0-9a-f]{24}$/i.test(seg)) return ":id";
      if (/^\d+$/.test(seg)) return ":id";
      return seg;
    })
    .join("/");
}

const KNOWN_PREFIXES = new Set([
  "api",
  "auth",
  "chat",
  "connectors",
  "health",
  "knowledge",
  "login",
  "mcp",
  "settings",
  "unauthorized",
  "upload",
]);

export function normalizeRoute(raw: string): string {
  if (raw === "/") return "/";
  if (raw.startsWith("/_next/")) return "/_next/*";

  const firstSeg = raw.split("/", 2)[1];
  if (!firstSeg || !KNOWN_PREFIXES.has(firstSeg)) return "unmatched";

  return normalizePath(raw);
}
