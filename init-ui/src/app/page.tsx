"use client";
import { useEffect, useRef, useState } from "react";

type FormState = {
  OPENSEARCH_PASSWORD: string;
  LANGFLOW_SECRET_KEY: string;
  OPENAI_API_KEY: string;
  GOOGLE_OAUTH_CLIENT_ID?: string;
  GOOGLE_OAUTH_CLIENT_SECRET?: string;
  MICROSOFT_GRAPH_OAUTH_CLIENT_ID?: string;
  MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET?: string;
  WEBHOOK_BASE_URL?: string;
  AWS_ACCESS_KEY_ID?: string;
  AWS_SECRET_ACCESS_KEY?: string;
  LANGFLOW_PUBLIC_URL?: string;
  LANGFLOW_SUPERUSER?: string;
  LANGFLOW_SUPERUSER_PASSWORD?: string;
};

export default function Page() {
  const [form, setForm] = useState<FormState>({
    OPENSEARCH_PASSWORD: "",
    LANGFLOW_SECRET_KEY: "",
    OPENAI_API_KEY: "",
  });
  const [starting, setStarting] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<string>("");
  const [raw, setRaw] = useState<string>("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const update = (k: keyof FormState, v: string) =>
    setForm((s) => ({ ...s, [k]: v }));

  async function saveConfig() {
    setErr("");
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const j = await r.json();
    if (!r.ok || !j.ok)
      throw new Error(j?.error || "Falha ao salvar configurações");
  }

  async function startStack() {
    try {
      setStarting(true);
      await saveConfig();
      timerRef.current = setInterval(async () => {
        const s = await fetch("/api/status");
        const sj = await s.json();
        setProgress(sj.progress);
        setRaw(JSON.stringify(sj, null, 2));
      }, 1500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setStarting(false);
    }
  }

  useEffect(
    () => () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    },
    [],
  );

  return (
    <main className="mx-auto max-w-3xl py-10 px-6">
      <h1 className="text-3xl font-semibold">OpenRAG • Setup inicial</h1>
      <p className="text-sm text-gray-600 mt-1">
        Preencha os campos mínimos e inicie o stack.
      </p>

      <div className="mt-8 grid grid-cols-1 gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">
            OpenSearch admin password *
          </span>
          <input
            className="input input-bordered border rounded-lg px-3 py-2"
            type="password"
            placeholder="OPENSEARCH_PASSWORD"
            value={form.OPENSEARCH_PASSWORD}
            onChange={(e) => update("OPENSEARCH_PASSWORD", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Langflow Secret Key *</span>
          <input
            className="input input-bordered border rounded-lg px-3 py-2"
            type="password"
            placeholder="LANGFLOW_SECRET_KEY"
            value={form.LANGFLOW_SECRET_KEY}
            onChange={(e) => update("LANGFLOW_SECRET_KEY", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">OpenAI API Key *</span>
          <input
            className="input input-bordered border rounded-lg px-3 py-2"
            type="password"
            placeholder="OPENAI_API_KEY"
            value={form.OPENAI_API_KEY}
            onChange={(e) => update("OPENAI_API_KEY", e.target.value)}
          />
        </label>

        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-gray-700">
            Opções avançadas
          </summary>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            {[
              ["GOOGLE_OAUTH_CLIENT_ID", "Google OAuth Client ID"],
              ["GOOGLE_OAUTH_CLIENT_SECRET", "Google OAuth Client Secret"],
              ["MICROSOFT_GRAPH_OAUTH_CLIENT_ID", "MS Graph Client ID"],
              ["MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET", "MS Graph Client Secret"],
              ["WEBHOOK_BASE_URL", "Webhook Base URL"],
              ["AWS_ACCESS_KEY_ID", "AWS Access Key"],
              ["AWS_SECRET_ACCESS_KEY", "AWS Secret Key"],
              ["LANGFLOW_PUBLIC_URL", "Langflow Public URL"],
              ["LANGFLOW_SUPERUSER", "Langflow Superuser"],
              ["LANGFLOW_SUPERUSER_PASSWORD", "Langflow Superuser Password"],
            ].map(([k, label]) => (
              <label key={k} className="flex flex-col gap-1">
                <span className="text-xs font-medium">{label}</span>
                <input
                  className="border rounded-lg px-3 py-2"
                  placeholder={k}
                  type={
                    k.toLowerCase().includes("password") ||
                    k.toLowerCase().includes("secret")
                      ? "password"
                      : "text"
                  }
                  value={form[k as keyof FormState] || ""}
                  onChange={(e) => update(k as keyof FormState, e.target.value)}
                />
              </label>
            ))}
          </div>
        </details>

        <button
          type="button"
          onClick={startStack}
          disabled={starting}
          className="mt-4 inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {starting ? "Iniciando…" : "Salvar & Iniciar"}
        </button>

        {!!err && <div className="text-red-600 text-sm">{err}</div>}

        {progress !== null && (
          <div className="mt-6">
            <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="text-sm text-gray-700 mt-1">
              Progresso: {progress}%
            </div>
          </div>
        )}

        <pre className="mt-4 text-xs bg-gray-50 border rounded-lg p-3 whitespace-pre-wrap">
          {raw}
        </pre>
      </div>
    </main>
  );
}
