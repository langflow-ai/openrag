import {
  Counter,
  collectDefaultMetrics,
  Histogram,
  Registry,
} from "prom-client";

// Create a Registry
export const register = new Registry();

// Collect default Node.js metrics (CPU, memory, event loop lag, etc.)
collectDefaultMetrics({
  register,
  prefix: "nodejs_",
  gcDurationBuckets: [0.001, 0.01, 0.1, 1, 2, 5],
});

// Custom HTTP metrics
export const httpRequestDuration = new Histogram({
  name: "http_request_duration_seconds",
  help: "Duration of HTTP requests in seconds",
  labelNames: ["method", "route", "status_code"],
  buckets: [0.1, 0.3, 0.5, 1, 2, 5, 10],
  registers: [register],
});

export const httpRequestTotal = new Counter({
  name: "http_requests_total",
  help: "Total number of HTTP requests",
  labelNames: ["method", "route", "status_code"],
  registers: [register],
});

// Backend proxy metrics
export const backendProxyDuration = new Histogram({
  name: "backend_proxy_duration_seconds",
  help: "Duration of backend proxy requests in seconds",
  labelNames: ["method", "path", "status_code"],
  buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60],
  registers: [register],
});

export const backendProxyTotal = new Counter({
  name: "backend_proxy_requests_total",
  help: "Total number of backend proxy requests",
  labelNames: ["method", "path", "status_code"],
  registers: [register],
});

export const backendProxyErrors = new Counter({
  name: "backend_proxy_errors_total",
  help: "Total number of backend proxy errors",
  labelNames: ["method", "path", "error_type"],
  registers: [register],
});
