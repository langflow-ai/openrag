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
    };
  }
  return g[GLOBAL_KEY];
}

const metrics = getOrCreateMetrics();

export const metricsRegistry = metrics.registry;
export const backendProxyDuration = metrics.backendProxyDuration;
export const backendProxyTotal = metrics.backendProxyTotal;
export const backendProxyErrors = metrics.backendProxyErrors;

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
