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

  // `reactStrictMode` wraps the whole tree, providers included. A <StrictMode>
  // nested inside the provider wrapper does not double-invoke effects, so it
  // would not reproduce the dev-mode mount/unmount/remount.
  it("finishes sign-in under StrictMode's effect double-invoke", async () => {
    // A fresh code per test: the page dedupes exchanges by code for the
    // lifetime of the module, as the browser would within one page load.
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

  it("shows an error instead of spinning when the code was already used", async () => {
    const code = crypto.randomUUID();
    setCallbackLocation(code);
    // A reload of the callback URL: the earlier load marked the code used.
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
