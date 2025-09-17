// init-ui/src/app/api/config/route.ts

import fs from "node:fs/promises";
import { NextResponse } from "next/server";
import { z } from "zod";

const ENV_PATH = process.env.APP_ENV_FILE || "/app/.env";
const ENV_PATH_EXAMPLE =
  process.env.APP_ENV_FILE_EXAMPLE || "/app/.env.example";

const schema = z.object({
  OPENSEARCH_PASSWORD: z.string().min(1, "Obrigatório"),
  LANGFLOW_SECRET_KEY: z.string().optional(),
  OPENAI_API_KEY: z.string().min(1, "Obrigatório"),
  GOOGLE_OAUTH_CLIENT_ID: z.string().optional(),
  GOOGLE_OAUTH_CLIENT_SECRET: z.string().optional(),
  MICROSOFT_GRAPH_OAUTH_CLIENT_ID: z.string().optional(),
  MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET: z.string().optional(),
  WEBHOOK_BASE_URL: z.string().optional(),
  AWS_ACCESS_KEY_ID: z.string().optional(),
  AWS_SECRET_ACCESS_KEY: z.string().optional(),
  LANGFLOW_PUBLIC_URL: z.string().optional(),
  LANGFLOW_SUPERUSER: z.string().optional(),
  LANGFLOW_SUPERUSER_PASSWORD: z.string().optional(),
});

function setKV(text: string, key: string, value: string) {
  const re = new RegExp(`^${key}=.*$`, "m");
  const line = `${key}=${value}`;
  return re.test(text)
    ? text.replace(re, line)
    : `${text.replace(/\s*$/, "")}\n${line}\n`;
}

export async function POST(req: Request) {
  const body = await req.json();
  const data = schema.parse(body);

  let envText = "";
  try {
    envText = await fs.readFile(ENV_PATH, "utf8");
  } catch {
    envText = await fs.readFile(ENV_PATH_EXAMPLE, "utf8");
  }

  // grava campos relevantes
  for (const [k, v] of Object.entries(data)) {
    if (v && typeof v === "string") envText = setKV(envText, k, v);
  }
  // troca profile p/ app
  envText = setKV(envText, "COMPOSE_PROFILES", "app");

  await fs.writeFile(ENV_PATH, envText, "utf8");
  return NextResponse.json({ ok: true });
}
