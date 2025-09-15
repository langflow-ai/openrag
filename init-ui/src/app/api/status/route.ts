// init-ui/src/app/api/status/route.ts
import { NextResponse } from "next/server";
import { listProjectContainers, progressFromHealth } from "@/docker";

const PROJECT = process.env.COMPOSE_PROJECT_NAME || "mystack";

export async function GET() {
  const items = await listProjectContainers(PROJECT);
  const progress = progressFromHealth(items);
  return NextResponse.json({ items, progress });
}
