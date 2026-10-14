import axios from "axios";
import { NextResponse } from "next/server";

interface PodStatus {
  alive: boolean;
}

interface HealthCheckResponse {
  status: "ok" | "not_ok";
  pods: {
    backend: PodStatus;
    langflow: PodStatus;
  };
  timestamp: string;
}

async function checkPodLiveness(url: string, timeout = 3000): Promise<boolean> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await axios.get(url, {
      signal: controller.signal,
      timeout,
      proxy: false,
      responseType: "stream",
      validateStatus: () => true,
    });
    // Liveness depends only on the status line. Do not wait for a pod that
    // keeps the response body open indefinitely.
    if (response.data && typeof response.data.destroy === "function") {
      response.data.destroy();
    }
    // Pod is alive if it responds (any status code means it's running)
    return response.status < 500;
  } catch {
    return false;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function GET() {
  // Backend configuration
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "openrag-backend";
  const backendPort = process.env.OPENRAG_BACKEND_PORT || "8000";
  const backendScheme = process.env.OPENRAG_BACKEND_SCHEME || "http";
  const backendHealthPath =
    process.env.OPENRAG_BACKEND_HEALTH_PATH || "/health";

  // Langflow configuration
  const langflowHost = process.env.LANGFLOW_HOST || "openrag-langflow";
  const langflowPort = process.env.LANGFLOW_PORT || "7860";
  const langflowScheme = process.env.LANGFLOW_SCHEME || "http";
  const langflowHealthPath = process.env.LANGFLOW_HEALTH_PATH || "/health";

  // Build health check URLs
  const backendUrl = `${backendScheme}://${backendHost}:${backendPort}${backendHealthPath}`;
  const langflowUrl = `${langflowScheme}://${langflowHost}:${langflowPort}${langflowHealthPath}`;

  // Check liveness of backend and langflow pods in parallel
  const [backendAlive, langflowAlive] = await Promise.all([
    checkPodLiveness(backendUrl),
    checkPodLiveness(langflowUrl),
  ]);

  const allPodsAlive = backendAlive && langflowAlive;

  const response: HealthCheckResponse = {
    status: allPodsAlive ? "ok" : "not_ok",
    pods: {
      backend: { alive: backendAlive },
      langflow: { alive: langflowAlive },
    },
    timestamp: new Date().toISOString(),
  };

  return NextResponse.json(response, {
    status: allPodsAlive ? 200 : 503,
  });
}
