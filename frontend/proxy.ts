import { type NextRequest, NextResponse } from "next/server";
import {
  httpRequestDuration,
  httpRequestsTotal,
  normalizeRoute,
} from "@/lib/metrics";

// `proxy` is the Next 16 replacement for the deprecated `middleware` file
// convention. It always runs on the Node.js runtime, so it can share the
// prom-client registry created in `lib/metrics.ts`; exporting a `runtime`
// segment config here is an error.
export function proxy(request: NextRequest) {
  const start = performance.now();

  const response = NextResponse.next();

  // This runs ahead of the route handler and does not await it, so the duration
  // covers the proxy hop only and the status is whatever `next()` set (200).
  // Exact per-request latency and status for backend traffic live in
  // `backend_proxy_*`.
  const durationSeconds = (performance.now() - start) / 1000;
  const labels = {
    method: request.method,
    route: normalizeRoute(request.nextUrl.pathname),
    status_code: response.status.toString(),
  };

  httpRequestDuration.observe(labels, durationSeconds);
  httpRequestsTotal.inc(labels);

  return response;
}

export const config = {
  // Every inbound path except the dev-only HMR socket.
  matcher: ["/((?!_next/webpack-hmr).*)"],
};
