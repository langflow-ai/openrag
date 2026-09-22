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

  it("persists the filter ID and calls the caller's onSuccess", async () => {
    let stateBody: unknown;
    let releaseSave!: () => void;
    const saveBlocked = new Promise<void>((resolve) => {
      releaseSave = resolve;
    });
    const onSuccess = vi.fn();
    const response = {
      message: "done",
      edited: true,
      openrag_docs_filter_id: "filter-123",
    };
    server.use(
      http.post("/api/onboarding", () => HttpResponse.json(response)),
      http.post("/api/onboarding/state", async ({ request }) => {
        stateBody = await request.json();
        await saveBlocked;
        return HttpResponse.json({ success: true });
      }),
    );

    const { result } = renderHook(() => useOnboardingMutation({ onSuccess }), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() =>
      expect(stateBody).toEqual({ openrag_docs_filter_id: "filter-123" }),
    );
    expect(onSuccess).not.toHaveBeenCalled();
    expect(result.current.isSuccess).toBe(false);
    releaseSave();

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

  it("reports a failed filter ID save without completing onboarding", async () => {
    const onSuccess = vi.fn();
    const onError = vi.fn();
    server.use(
      http.post("/api/onboarding", () =>
        HttpResponse.json({
          message: "done",
          edited: true,
          openrag_docs_filter_id: "filter-123",
        }),
      ),
      http.post("/api/onboarding/state", () =>
        HttpResponse.json(
          { error: "Could not save filter ID" },
          { status: 500 },
        ),
      ),
    );

    const { result } = renderHook(
      () => useOnboardingMutation({ onSuccess, onError }),
      { wrapper: createQueryWrapper() },
    );

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Could not save filter ID");
    expect(onError).toHaveBeenCalledOnce();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("invalidates settings and calls the caller's onSettled", async () => {
    const response = { message: "done", edited: true };
    const onSettled = vi.fn();
    server.use(http.post("/api/onboarding", () => HttpResponse.json(response)));

    const queryClient = createTestQueryClient();
    queryClient.setQueryDefaults(["settings"], { gcTime: 60_000 });
    queryClient.setQueryData(["settings"], { edited: false });
    const { result } = renderHook(() => useOnboardingMutation({ onSettled }), {
      wrapper: createQueryWrapper({ queryClient }),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(onSettled).toHaveBeenCalledOnce();
    expect(onSettled).toHaveBeenCalledWith(
      response,
      null,
      {},
      undefined,
      expect.anything(),
    );
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
