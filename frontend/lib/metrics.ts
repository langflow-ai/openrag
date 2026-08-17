import {
  Counter,
  collectDefaultMetrics,
  Histogram,
  Registry,
} from "prom-client";

const GLOBAL_KEY = Symbol.for("openrag.metricsRegistry");

function getOrCreateRegistry(): Registry {
  const g = globalThis as Record<symbol, Registry>;
  if (!g[GLOBAL_KEY]) {
    const registry = new Registry();
    collectDefaultMetrics({
      register: registry,
      prefix: "nodejs_",
      gcDurationBuckets: [0.001, 0.01, 0.1, 1, 2, 5],
    });
    g[GLOBAL_KEY] = registry;
  }
  return g[GLOBAL_KEY];
}

export const metricsRegistry = getOrCreateRegistry();

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

// ===== Backend Proxy Metrics =====

export const backendProxyDuration = new Histogram({
  name: "backend_proxy_duration_seconds",
  help: "Duration of backend proxy requests in seconds",
  labelNames: ["method", "path", "status_code"],
  buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60],
  registers: [metricsRegistry],
});

export const backendProxyTotal = new Counter({
  name: "backend_proxy_requests_total",
  help: "Total number of backend proxy requests",
  labelNames: ["method", "path", "status_code"],
  registers: [metricsRegistry],
});

export const backendProxyErrors = new Counter({
  name: "backend_proxy_errors_total",
  help: "Total number of backend proxy errors",
  labelNames: ["method", "path", "error_type"],
  registers: [metricsRegistry],
});
