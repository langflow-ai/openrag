import {
  Counter,
  collectDefaultMetrics,
  Gauge,
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

// ===== HTTP Request Metrics =====

// Request duration histogram (RED: Duration)
export const httpRequestDuration = new Histogram({
  name: "http_request_duration_seconds",
  help: "Duration of HTTP requests in seconds",
  labelNames: ["method", "route", "status_code"],
  buckets: [0.1, 0.3, 0.5, 1, 2, 5, 10],
  registers: [register],
});

// Total requests counter (RED: Rate)
export const httpRequestTotal = new Counter({
  name: "http_requests_total",
  help: "Total number of HTTP requests",
  labelNames: ["method", "route", "status_code"],
  registers: [register],
});

// In-flight requests gauge (concurrency monitoring)
export const httpRequestsInFlight = new Gauge({
  name: "http_requests_in_flight",
  help: "Current number of HTTP requests being processed",
  labelNames: ["method", "route"],
  registers: [register],
});

// Request errors counter (RED: Errors)
export const httpRequestErrors = new Counter({
  name: "http_request_errors_total",
  help: "Total HTTP request errors by type",
  labelNames: ["method", "route", "error_type"],
  registers: [register],
});

// Request size histogram (optional, for payload analysis)
export const httpRequestSize = new Histogram({
  name: "http_request_size_bytes",
  help: "Size of HTTP request bodies in bytes",
  labelNames: ["method", "route"],
  buckets: [100, 1000, 10000, 100000, 1000000, 10000000],
  registers: [register],
});

// Response size histogram (optional, for payload analysis)
export const httpResponseSize = new Histogram({
  name: "http_response_size_bytes",
  help: "Size of HTTP response bodies in bytes",
  labelNames: ["method", "route", "status_code"],
  buckets: [100, 1000, 10000, 100000, 1000000, 10000000],
  registers: [register],
});

// ===== Backend Proxy Metrics =====
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
