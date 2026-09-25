/**
 * Tests for useGetModelsQuery.ts: the four per-provider model queries, the
 * provider-switching dispatcher, and the static model catalogue query.
 */
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import {
  useGetAnthropicModelsQuery,
  useGetCurrentProviderModelsQuery,
  useGetIBMModelsQuery,
  useGetModelCatalogQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "./useGetModelsQuery";

const models = {
  language_models: [{ value: "gpt-5.4", label: "GPT-5.4", default: true }],
  embedding_models: [{ value: "text-embedding-3-small", label: "Small" }],
};

describe("useGetOpenAIModelsQuery", () => {
  it("omits api_key from the body when useEnvKey is true", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/models/openai", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(
      () => useGetOpenAIModelsQuery({ apiKey: "sk-ignored", useEnvKey: true }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({});
    expect(result.current.data).toEqual(models);
  });

  it("sends the api_key in the body when provided and not using env key", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/models/openai", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(
      () => useGetOpenAIModelsQuery({ apiKey: "sk-real" }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({ api_key: "sk-real" });
  });

  it("formats the backend error message on failure", async () => {
    server.use(
      http.post("/api/models/openai", () =>
        HttpResponse.json({ error: "Invalid API key" }, { status: 401 }),
      ),
    );

    const { result } = renderHook(() => useGetOpenAIModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Invalid API key");
  });

  it("falls back to a default message when the error body has no error field", async () => {
    server.use(
      http.post("/api/models/openai", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useGetOpenAIModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to fetch OpenAI models");
  });
});

describe("useGetAnthropicModelsQuery", () => {
  it("resolves the model list on success", async () => {
    server.use(
      http.post("/api/models/anthropic", () => HttpResponse.json(models)),
    );

    const { result } = renderHook(() => useGetAnthropicModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(models);
  });

  it("surfaces the backend error message on failure", async () => {
    server.use(
      http.post("/api/models/anthropic", () =>
        HttpResponse.json({ error: "rate limited" }, { status: 429 }),
      ),
    );

    const { result } = renderHook(() => useGetAnthropicModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("rate limited");
  });
});

describe("useGetOllamaModelsQuery", () => {
  it("appends the endpoint as a query param when given", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/models/ollama", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(
      () => useGetOllamaModelsQuery({ endpoint: "http://localhost:11434" }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("endpoint=http%3A%2F%2Flocalhost%3A11434");
  });

  it("omits the query param when no endpoint is given", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/models/ollama", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(() => useGetOllamaModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).not.toContain("endpoint=");
  });
});

describe("useGetIBMModelsQuery", () => {
  it("sends endpoint and project_id, omitting api_key when useEnvKey is true", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/models/ibm", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(
      () =>
        useGetIBMModelsQuery({
          endpoint: "https://ibm.example.com",
          projectId: "proj-1",
          apiKey: "ignored",
          useEnvKey: true,
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({
      endpoint: "https://ibm.example.com",
      project_id: "proj-1",
    });
  });

  it("surfaces the backend error message on failure", async () => {
    server.use(
      http.post("/api/models/ibm", () =>
        HttpResponse.json({ error: "endpoint unreachable" }, { status: 502 }),
      ),
    );

    const { result } = renderHook(() => useGetIBMModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("endpoint unreachable");
  });
});

describe("useGetCurrentProviderModelsQuery", () => {
  it("dispatches to the anthropic query when settings.agent.llm_provider is anthropic", async () => {
    let anthropicCalled = false;
    let openaiCalled = false;
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json({ agent: { llm_provider: "anthropic" } }),
      ),
      http.post("/api/models/anthropic", () => {
        anthropicCalled = true;
        return HttpResponse.json(models);
      }),
      http.post("/api/models/openai", () => {
        openaiCalled = true;
        return HttpResponse.json(models);
      }),
    );

    const { result } = renderHook(() => useGetCurrentProviderModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(anthropicCalled).toBe(true);
    expect(openaiCalled).toBe(false);
  });

  it("dispatches to the ollama query only once its endpoint is configured", async () => {
    let ollamaCalled = false;
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json({
          agent: { llm_provider: "ollama" },
          providers: { ollama: { endpoint: "http://localhost:11434" } },
        }),
      ),
      http.get("/api/models/ollama", () => {
        ollamaCalled = true;
        return HttpResponse.json(models);
      }),
      http.post("/api/models/openai", () => HttpResponse.json(models)),
    );

    const { result } = renderHook(() => useGetCurrentProviderModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(ollamaCalled).toBe(true);
  });

  it("defaults to the openai query when no provider is configured yet", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({ agent: {} })),
      http.post("/api/models/openai", () => HttpResponse.json(models)),
    );

    const { result } = renderHook(() => useGetCurrentProviderModelsQuery(), {
      wrapper: createQueryWrapper(),
    });

    // Falls through to the openai branch, but stays disabled because
    // currentProvider !== "openai" — data never resolves.
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toBeUndefined();
  });
});

describe("useGetModelCatalogQuery", () => {
  it("resolves the provider catalogue on success", async () => {
    server.use(
      http.get("/api/models/catalog", () =>
        HttpResponse.json({
          providers: [
            {
              key: "openai",
              name: "OpenAI",
              credential_fields: [],
              model_placeholder: null,
              models: [],
              embedding_models: [],
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useGetModelCatalogQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.providers[0].key).toBe("openai");
  });

  it("formats the backend error message on failure", async () => {
    server.use(
      http.get(
        "/api/models/catalog",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useGetModelCatalogQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Failed to fetch the model catalogue",
    );
  });
});
