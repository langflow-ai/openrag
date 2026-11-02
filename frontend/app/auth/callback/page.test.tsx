import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test-utils/render";
import { mockRouter, setMockLocation } from "@/test-utils/router";
import AuthCallbackPage from "./page";

let callbackRequests = 0;
const callbackHandler = http.post("/api/auth/callback", () => {
  callbackRequests += 1;
  return HttpResponse.json({ purpose: "app_auth" });
});

function setCallbackLocation(code: string) {
  setMockLocation({
    pathname: "/auth/callback",
    searchParams: { code, state: "test-state" },
  });
}

describe("AuthCallbackPage", () => {
  beforeEach(() => {
    callbackRequests = 0;
    localStorage.setItem("auth_purpose", "app_auth");
  });

  // A <StrictMode> inside the provider wrapper doesn't double-invoke effects.
  it("finishes sign-in under StrictMode's effect double-invoke", async () => {
    setCallbackLocation(crypto.randomUUID());

    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [callbackHandler],
      reactStrictMode: true,
    });

    expect(await screen.findByText("Welcome to OpenRAG!")).toBeInTheDocument();
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith("/chat"), {
      timeout: 3000,
    });
    expect(callbackRequests).toBe(1);
  });

  it("reuses a settled exchange when the page remounts with the same code", async () => {
    setCallbackLocation(crypto.randomUUID());

    const first = renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [callbackHandler],
    });
    expect(await screen.findByText("Welcome to OpenRAG!")).toBeInTheDocument();
    first.unmount();

    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [callbackHandler],
    });
    expect(await screen.findByText("Welcome to OpenRAG!")).toBeInTheDocument();
    expect(callbackRequests).toBe(1);
  });

  it("redirects to auth_redirect_to after sign-in", async () => {
    setCallbackLocation(crypto.randomUUID());
    localStorage.setItem("auth_redirect_to", "/knowledge");

    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [callbackHandler],
      reactStrictMode: true,
    });

    await waitFor(
      () => expect(mockRouter.push).toHaveBeenCalledWith("/knowledge"),
      { timeout: 3000 },
    );
    expect(localStorage.getItem("auth_redirect_to")).toBeNull();
  });

  it("shows the backend's error and allows a retry when the exchange fails", async () => {
    const code = crypto.randomUUID();
    setCallbackLocation(code);

    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [
        http.post("/api/auth/callback", () =>
          HttpResponse.json({ error: "invalid_grant" }, { status: 400 }),
        ),
      ],
      reactStrictMode: true,
    });

    expect(await screen.findByText("Sign In Failed")).toBeInTheDocument();
    expect(screen.getByText("invalid_grant")).toBeInTheDocument();
    expect(sessionStorage.getItem(`callback_processed_${code}`)).toBeNull();
  });

  it("clears the dedupe state when the exchange fails after unmount", async () => {
    const code = crypto.randomUUID();
    setCallbackLocation(code);
    let failRequest!: () => void;
    const requestFailed = new Promise<void>((resolve) => {
      failRequest = resolve;
    });

    const view = renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [
        http.post("/api/auth/callback", async () => {
          callbackRequests += 1;
          await requestFailed;
          return HttpResponse.json({ error: "invalid_grant" }, { status: 400 });
        }),
      ],
    });
    await waitFor(() => expect(callbackRequests).toBe(1));
    view.unmount();
    failRequest();

    await waitFor(() =>
      expect(sessionStorage.getItem(`callback_processed_${code}`)).toBeNull(),
    );

    // The rejected exchange isn't reused: a remount reports the backend's error,
    // not "already used".
    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [
        http.post("/api/auth/callback", () =>
          HttpResponse.json({ error: "invalid_grant" }, { status: 400 }),
        ),
      ],
    });
    expect(await screen.findByText("invalid_grant")).toBeInTheDocument();
  });

  it("shows an error instead of spinning when the code was already used", async () => {
    const code = crypto.randomUUID();
    setCallbackLocation(code);
    sessionStorage.setItem(`callback_processed_${code}`, "true");

    renderWithProviders(<AuthCallbackPage />, {
      providers: ["auth"],
      handlers: [callbackHandler],
    });

    expect(await screen.findByText("Sign In Failed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /back to login/i }),
    ).toBeInTheDocument();
    expect(callbackRequests).toBe(0);
  });
});
