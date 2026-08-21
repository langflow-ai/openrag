// Instrumentation runs in the Node.js runtime only. Exporting `runtime`
// tells the Next.js bundler not to analyse this file for Edge compatibility,
// which suppresses the false-positive "node:http not supported in Edge
// Runtime" warning that the dynamic import guard on line 9 already prevents.
export const runtime = "nodejs";

const SERVER_KEY = Symbol.for("openrag.metricsServer");
const START_TIME = Symbol("openrag.requestStart");

export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if ((globalThis as Record<symbol, boolean>)[SERVER_KEY]) return;
  (globalThis as Record<symbol, boolean>)[SERVER_KEY] = true;

  const { createServer } = await import("node:http");
  const { subscribe } = await import("node:diagnostics_channel");
  const {
    metricsRegistry,
    httpRequestDuration,
    httpRequestsTotal,
    normalizeRoute,
  } = await import("./lib/metrics");

  const port = Number(process.env.METRICS_PORT) || 9090;

  const metricsServer = createServer(async (req, res) => {
    if (req.url === "/metrics") {
      try {
        res.setHeader("Content-Type", metricsRegistry.contentType);
        res.end(await metricsRegistry.metrics());
      } catch {
        res.statusCode = 500;
        res.end('{"error":"Failed to generate metrics"}');
      }
    } else if (req.url === "/health") {
      res.setHeader("Content-Type", "application/json");
      res.end('{"status":"ok"}');
    } else {
      res.statusCode = 404;
      res.end();
    }
  });

  subscribe("http.server.request.start", (message: unknown) => {
    const msg = message as Record<string, unknown>;
    if (msg.server === metricsServer) return;
    const req = msg.request as Record<symbol, number>;
    req[START_TIME] = performance.now();
  });

  subscribe("http.server.response.finish", (message: unknown) => {
    const msg = message as Record<string, unknown>;
    if (msg.server === metricsServer) return;
    const req = msg.request as Record<string | symbol, string | number>;
    const startTime = req[START_TIME] as number | undefined;
    if (startTime == null) return;

    const url = (req.url as string) ?? "/";
    const pathname = url.split("?", 1)[0];
    const labels = {
      method: req.method as string,
      route: normalizeRoute(pathname),
      status_code: String((msg.response as Record<string, number>).statusCode),
    };

    httpRequestDuration.observe(labels, (performance.now() - startTime) / 1000);
    httpRequestsTotal.inc(labels);
  });

  metricsServer.on("error", (err) => {
    console.error(`Metrics server failed to start on port ${port}:`, err);
    (globalThis as Record<symbol, boolean>)[SERVER_KEY] = false;
  });

  metricsServer.listen(port, () => {
    console.log(`Metrics server listening on port ${port}`);
  });
}
