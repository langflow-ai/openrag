import express from "express";
import { register } from "./lib/metrics";

const app = express();
const PORT = process.env.METRICS_PORT || 9090;

// Health check endpoint
app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

// Metrics endpoint
app.get("/metrics", async (req, res) => {
  try {
    res.set("Content-Type", register.contentType);
    res.end(await register.metrics());
  } catch (error) {
    console.error("Error generating metrics:", error);
    res.status(500).json({ error: "Failed to generate metrics" });
  }
});

app.listen(PORT, () => {
  console.log(`Metrics server listening on port ${PORT}`);
  console.log(`Metrics available at http://localhost:${PORT}/metrics`);
});
