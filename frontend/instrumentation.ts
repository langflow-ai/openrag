export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const { createServer } = await import("node:http");
  const { metricsRegistry } = await import("./lib/metrics");

  const port = Number(process.env.METRICS_PORT) || 9090;

  const server = createServer(async (req, res) => {
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

  server.listen(port, () => {
    console.log(`Metrics server listening on port ${port}`);
  });
}
