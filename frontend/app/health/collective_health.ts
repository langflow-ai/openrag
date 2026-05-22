import { NextResponse } from "next/server";

interface PodStatus {
  alive: boolean;
}
interface CollectiveHealthResponse {
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
    const response = await fetch(url, {
      signal: controller.signal,
      method: "GET",
    });
    clearTimeout(timeoutId);
    return response.status < 500;
  } catch {
    clearTimeout(timeoutId);
    return false;
  }
}
export async function GET() {
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "openrag-be";
  const langflowHost = process.env.OPENRAG_LANGFLOW_HOST || "openrag-lf";
  const [backendAlive, langflowAlive] = await Promise.all([
    checkPodLiveness(`http://${backendHost}:8000/health`),
    checkPodLiveness(`http://${langflowHost}:7860/health`),
  ]);
  const allPodsAlive = backendAlive && langflowAlive;
  const response: CollectiveHealthResponse = {
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
