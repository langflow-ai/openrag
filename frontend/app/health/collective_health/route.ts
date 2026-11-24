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

interface PodHealth {
  alive: boolean;
  body?: unknown;
}

interface BackendHealthResponse {
  langflow_enabled?: boolean;
}

async function checkPodHealth(url: string, timeout = 3000): Promise<PodHealth> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await axios.get<unknown>(url, {
      signal: controller.signal,
      timeout,
      proxy: false,
      validateStatus: () => true,
    });
    return {
      alive: response.status < 500,
      body: response.data,
    };
  } catch {
    return { alive: false };
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

  const backend = await checkPodHealth(backendUrl);
  // Preserve the existing safe default during a staggered deployment with a
  // backend that does not yet report the capability.
  const langflowEnabled =
    (backend.body as BackendHealthResponse)?.langflow_enabled !== false;
  const langflow = langflowEnabled
    ? await checkPodHealth(langflowUrl)
    : { alive: true };

  const allPodsAlive = backend.alive && langflow.alive;

  const response: HealthCheckResponse = {
    status: allPodsAlive ? "ok" : "not_ok",
    pods: {
      backend: { alive: backend.alive },
      langflow: { alive: langflow.alive },
    },
    timestamp: new Date().toISOString(),
  };

  return NextResponse.json(response, {
    status: allPodsAlive ? 200 : 503,
  });
}
