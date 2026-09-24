/**
 * Tests for useOnboardingMutation: POSTs the onboarding payload and, when the
 * backend ingested sample data, persists the resulting filter ID through
 * useUpdateOnboardingStateMutation.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, createTestQueryClient } from "@/test-utils/render";
import { useOnboardingMutation } from "./useOnboardingMutation";

const toast = vi.hoisted(() => ({
  info: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));

describe("useOnboardingMutation", () => {
  it("posts the onboarding variables and resolves with the response", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/onboarding", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ message: "done", edited: true });
      }),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() =>
      result.current.mutate({
        llm_provider: "openai",
        openai_api_key: "sk-test",
      }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({
      llm_provider: "openai",
      openai_api_key: "sk-test",
    });
  });

  it("persists openrag_docs_filter_id via the onboarding-state endpoint on success", async () => {
    let stateBody: unknown;
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({
          message: "done",
          edited: true,
          openrag_docs_filter_id: "filter-123",
        }),
      ),
      http.post("/api/onboarding/state", async ({ request }) => {
        stateBody = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() =>
      expect(stateBody).toEqual({ openrag_docs_filter_id: "filter-123" }),
    );
  });

  it("explains when watsonx.ai on-prem reduces the ingestion chunk size", async () => {
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({
          message: "done",
          edited: true,
          chunk_size_adjusted_to: 500,
        }),
      ),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() =>
      result.current.mutate({
        embedding_provider: "watsonx_onprem",
        embedding_model: "ibm/slate-30m-english-rtrvr",
      }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.info).toHaveBeenCalledWith("Chunk size reduced to 500", {
      description:
        "OpenRAG adjusted ingestion chunks to stay within watsonx.ai on-prem embedding limits.",
    });
  });

  it("does not show a chunk-size toast when the backend reports no adjustment", async () => {
    toast.info.mockClear();
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({
          message: "done",
          edited: true,
          chunk_size_adjusted_to: null,
        }),
      ),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({ embedding_provider: "watsonx_onprem" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("calls the caller's onSuccess for a completed onboarding request", async () => {
    const onSuccess = vi.fn();
    const response = {
      message: "done",
      edited: true,
    };
    server.use(http.post("/api/onboarding", () => HttpResponse.json(response)));

    const { result } = renderHook(() => useOnboardingMutation({ onSuccess }), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(
        response,
        {},
        undefined,
        expect.anything(),
      ),
    );
    expect(result.current.isSuccess).toBe(true);
  });

  it("calls the caller's onError when onboarding fails", async () => {
    const onError = vi.fn();
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json(
          { error: "Could not complete onboarding" },
          { status: 500 },
        ),
      ),
    );

    const { result } = renderHook(() => useOnboardingMutation({ onError }), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Could not complete onboarding");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Could not complete onboarding" }),
      {},
      undefined,
      expect.anything(),
    );
  });

  it("invalidates settings after onboarding settles", async () => {
    const response = { message: "done", edited: true };
    server.use(http.post("/api/onboarding", () => HttpResponse.json(response)));

    const queryClient = createTestQueryClient();
    queryClient.setQueryDefaults(["settings"], { gcTime: 60_000 });
    queryClient.setQueryData(["settings"], { edited: false });
    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper({ queryClient }),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryState(["settings"])?.isInvalidated).toBe(true);
  });

  it("does not call the onboarding-state endpoint when there is no filter ID", async () => {
    let stateCalled = false;
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({ message: "done", edited: true }),
      ),
      http.post("/api/onboarding/state", () => {
        stateCalled = true;
        return HttpResponse.json({ success: true });
      }),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(stateCalled).toBe(false);
  });

  it("formats the backend error message on failure", async () => {
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json(
          { error: "Invalid provider configuration" },
          {
            status: 500,
          },
        ),
      ),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Invalid provider configuration",
    );
  });

  it("falls back to a default message when the error body has no error field", async () => {
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useOnboardingMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to complete onboarding");
  });
});
