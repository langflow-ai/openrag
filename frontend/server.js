// Production entrypoint for the Next.js frontend.
//
// Serves over HTTPS when TLS_CERT_PATH and TLS_KEY_PATH are both set (e.g. a
// certificate mounted by the operator so the ingress proxy can reach the
// frontend over TLS); otherwise serves plain HTTP, same as `next start`.
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const next = require("next");

const port = Number.parseInt(process.env.PORT || "3000", 10);
// Bind on all interfaces by default so the container port is reachable.
const hostname = process.env.HOST || "0.0.0.0";

const certPath = process.env.TLS_CERT_PATH;
const keyPath = process.env.TLS_KEY_PATH;

if (Boolean(certPath) !== Boolean(keyPath)) {
  console.error(
    "TLS_CERT_PATH and TLS_KEY_PATH must be set together to enable HTTPS",
  );
  process.exit(1);
}

const useTls = Boolean(certPath && keyPath);
const app = next({ dev: false, hostname, port });
const handle = app.getRequestHandler();

app
  .prepare()
  .then(() => {
    const onRequest = (req, res) => handle(req, res);
    const server = useTls
      ? https.createServer(
          { cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath) },
          onRequest,
        )
      : http.createServer(onRequest);

    server.listen(port, hostname, () => {
      process.stdout.write(
        `> Ready on ${useTls ? "https" : "http"}://${hostname}:${port}\n`,
      );
    });

    const shutdown = () => server.close(() => process.exit(0));
    process.on("SIGTERM", shutdown);
    process.on("SIGINT", shutdown);
  })
  .catch((err) => {
    console.error("Failed to start server:", err);
    process.exit(1);
  });
