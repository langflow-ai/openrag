/**
 * The gate every authenticated page sits behind. A mistake here either locks
 * users out of a working install or renders protected content to someone who
 * is not signed in, so all four auth shapes are pinned.
 *
 * Exercises the harness end to end: the real `AuthProvider` resolving from MSW,
 * and the shared `next/navigation` double for the redirect assertions.
 */
import { describe, expect, it } from "vitest";
import { ProtectedRoute } from "@/components/protected-route";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { mockRouter, setMockLocation } from "@/test-utils/router";

function renderGate(auth: (typeof authPresets)[keyof typeof authPresets]) {
  return renderWithProviders(
    <ProtectedRoute>
      <p>Secret dashboard</p>
    </ProtectedRoute>,
    { providers: ["auth"], auth },
  );
}

describe("ProtectedRoute", () => {
  it("shows a loading state before auth resolves", () => {
    renderGate(authPresets.admin);

    // Asserted synchronously, before the boot fetches settle.
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("Secret dashboard")).not.toBeInTheDocument();
  });

  it("renders children for a signed-in user", async () => {
    renderGate(authPresets.admin);

    expect(await screen.findByText("Secret dashboard")).toBeInTheDocument();
    expect(mockRouter.push).not.toHaveBeenCalled();
  });

  it("renders children in no-auth mode even though nobody is signed in", async () => {
    // OPENRAG_AUTH_ENABLED=false. Treating "no user" as "not allowed" here
    // would lock every page of an auth-disabled install.
    renderGate(authPresets.noAuthMode);

    expect(await screen.findByText("Secret dashboard")).toBeInTheDocument();
    expect(mockRouter.push).not.toHaveBeenCalled();
  });

  it("redirects to login with the current path so the user comes back", async () => {
    setMockLocation({ pathname: "/knowledge/chunks" });

    renderGate(authPresets.unauthenticated);

    await waitFor(() => {
      expect(mockRouter.push).toHaveBeenCalledWith(
        "/login?redirect=%2Fknowledge%2Fchunks",
      );
    });
    expect(screen.queryByText("Secret dashboard")).not.toBeInTheDocument();
  });

  it("sends an unauthenticated IBM tenant to /unauthorized, not /login", async () => {
    // IBM auth has no local login form to land on.
    renderGate({
      ...authPresets.ibmAuthMode,
      me: { ibm_auth_mode: true, authenticated: false, user: null },
    });

    await waitFor(() => {
      expect(mockRouter.push).toHaveBeenCalledWith("/unauthorized");
    });
    expect(screen.queryByText("Secret dashboard")).not.toBeInTheDocument();
  });
});
