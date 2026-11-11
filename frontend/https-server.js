// Container entrypoint wrapper for the Next.js standalone server.
//
// Serves over HTTPS when TLS_CERT_PATH and TLS_KEY_PATH are both set (e.g. a
// certificate mounted by the operator so the ingress proxy can reach the
// frontend over TLS); otherwise it behaves exactly like `node server.js`.
//
// Next's `startServer` only accepts a certificate in `next dev`, and the
// standalone `server.js` is generated at build time, so rather than replacing
// it this wrapper makes the `http.createServer` call it performs return an
// HTTPS server, then loads the generated file unchanged.
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

const certPath = process.env.TLS_CERT_PATH;
const keyPath = process.env.TLS_KEY_PATH;

if (Boolean(certPath) !== Boolean(keyPath)) {
  console.error(
    "TLS_CERT_PATH and TLS_KEY_PATH must be set together to enable HTTPS",
  );
  process.exit(1);
}

if (certPath && keyPath) {
  const tlsOptions = {
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
  };
  const createHttpServer = http.createServer;
  http.createServer = (...args) => {
    // Only the first server (Next's listener) is upgraded; restore the original
    // so any later http.createServer caller is unaffected.
    http.createServer = createHttpServer;
    const listener = args.find((arg) => typeof arg === "function");
    return https.createServer(tlsOptions, listener);
  };
}

require(path.join(__dirname, "server.js"));
