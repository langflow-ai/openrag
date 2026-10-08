/**
 * Tests for useUpdateSettingsMutation: POSTs /api/settings, invalidates the
 * settings cache, and refetches the current provider's model list. The hook
 * mounts useGetCurrentProviderModelsQuery internally, so /api/settings (GET)
 * and the relevant /api/models/* endpoint must both be mocked even though
 * this file is only testing the mutation.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import { useGetModelCatalogQuery } from "../queries/useGetModelsQuery";
import {
  isEmbeddingProviderInUseError,
  useUpdateSettingsMutation,
} from "./useUpdateSettingsMutation";

describe("useUpdateSettingsMutation", () => {
  it("posts the settings payload and triggers a settings refetch on success", async () => {
    let settingsFetchCount = 0;
    let capturedBody: unknown;
    server.use(
      http.get("/api/settings", () => {
        settingsFetchCount += 1;
        return HttpResponse.json({ agent: { llm_provider: "openai" } });
      }),
      http.post("/api/settings", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({
          message: "saved",
          settings: { agent: { llm_provider: "openai" } },
        });
      }),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
    );

    const { result } = renderHook(() => useUpdateSettingsMutation(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(settingsFetchCount).toBe(1));

    act(() => result.current.mutate({ llm_model: "gpt-5.4" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({ llm_model: "gpt-5.4" });
    // invalidateQueries refetches the mounted useGetSettingsQuery observer.
    await waitFor(() => expect(settingsFetchCount).toBe(2));
  });

  it("refreshes the model catalogue so pickers see a re-configured cluster's models", async () => {
    // Settings → Providers saves credentials only; the Agent and Ingestion
    // pickers read the catalogue, which lists a cluster with saved credentials.
    let catalogFetchCount = 0;
    server.use(
      http.get("/api/settings", () => HttpResponse.json({})),
      http.post("/api/settings", () =>
        HttpResponse.json({ message: "saved", settings: {} }),
      ),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
      http.get("/api/models/catalog", () => {
        catalogFetchCount += 1;
        const model =
          catalogFetchCount === 1 ? "granite-3.3-2b-instruct" : "gpt-oss-120b";
        return HttpResponse.json({
          providers: [
            {
              key: "rhoai",
              name: "Red Hat OpenShift AI",
              credential_fields: [],
              model_placeholder: null,
              models: [{ model, mode: "chat" }],
              embedding_models: [],
            },
          ],
        });
      }),
    );

    const { result } = renderHook(
      () => ({
        catalog: useGetModelCatalogQuery(),
        mutation: useUpdateSettingsMutation(),
      }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() =>
      expect(result.current.catalog.data?.providers[0].models[0].model).toBe(
        "granite-3.3-2b-instruct",
      ),
    );

    act(() =>
      result.current.mutation.mutate({
        provider_credentials: { rhoai: { api_key: "token" } },
      }),
    );

    await waitFor(() =>
      expect(result.current.catalog.data?.providers[0].models[0].model).toBe(
        "gpt-oss-120b",
      ),
    );
  });

  it("calls the caller's onSuccess in addition to the hook's own side effects", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({})),
      http.post("/api/settings", () =>
        HttpResponse.json({ message: "saved", settings: {} }),
      ),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
    );

    let onSuccessCalled = false;
    const { result } = renderHook(
      () =>
        useUpdateSettingsMutation({
          onSuccess: () => {
            onSuccessCalled = true;
          },
        }),
      { wrapper: createQueryWrapper() },
    );

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(onSuccessCalled).toBe(true);
  });

  it("throws an UpdateSettingsError carrying the structured 409 payload", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({})),
      http.post("/api/settings", () =>
        HttpResponse.json(
          {
            error: "Embedding provider still in use",
            code: "embedding_provider_in_use",
            affected_provider: "openai",
            affected_models: [
              { model: "text-embedding-3-small", doc_count: 4 },
            ],
          },
          { status: 409 },
        ),
      ),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
    );

    const { result } = renderHook(() => useUpdateSettingsMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({ remove_openai_config: true }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(isEmbeddingProviderInUseError(result.current.error)).toBe(true);
    if (isEmbeddingProviderInUseError(result.current.error)) {
      expect(result.current.error.affectedProvider).toBe("openai");
      expect(result.current.error.affectedModels).toEqual([
        { model: "text-embedding-3-small", doc_count: 4 },
      ]);
    }
  });

  it("does not classify a plain 500 as the embedding-provider-in-use error", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({})),
      http.post("/api/settings", () =>
        HttpResponse.json({ error: "database unavailable" }, { status: 500 }),
      ),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
    );

    const { result } = renderHook(() => useUpdateSettingsMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(isEmbeddingProviderInUseError(result.current.error)).toBe(false);
    expect(result.current.error?.message).toBe("database unavailable");
  });
});
