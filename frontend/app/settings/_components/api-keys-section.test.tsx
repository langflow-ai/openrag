import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { ApiKeysSection } from "./api-keys-section";

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSection(keys: unknown[] = []) {
  let revoked: string | null = null;
  const utils = renderWithProviders(<ApiKeysSection />, {
    providers: ["tooltip", "auth", "brand"],
    auth: authPresets.rbacDisabled,
    handlers: [
      http.get("/api/keys", () => HttpResponse.json({ keys })),
      http.delete("/api/keys/:key_id", ({ params }) => {
        revoked = params.key_id as string;
        return HttpResponse.json({ success: true });
      }),
    ],
  });
  return { ...utils, getRevoked: () => revoked };
}

describe("ApiKeysSection", () => {
  it("opens the create-key dialog from the header button", async () => {
    renderSection([]);

    fireEvent.click(
      await screen.findByRole("button", { name: /^create key$/i }),
    );

    expect(
      await screen.findByRole("heading", { name: /create api key/i }),
    ).toBeInTheDocument();
  });

  it("opens the create-key dialog from the empty state", async () => {
    renderSection([]);

    fireEvent.click(
      await screen.findByRole("button", {
        name: /create your first api key/i,
      }),
    );

    expect(
      await screen.findByRole("heading", { name: /create api key/i }),
    ).toBeInTheDocument();
  });

  it("revokes an existing API key from the list", async () => {
    const { getRevoked } = renderSection([
      {
        key_id: "key-1",
        name: "My Key",
        key_prefix: "sk-abc",
        created_at: "2024-01-01T00:00:00Z",
        last_used_at: null,
      },
    ]);

    const row = (await screen.findByText("My Key")).closest("tr");
    if (!row) throw new Error("row not found");
    fireEvent.click(within(row).getByRole("button"));

    fireEvent.click(await screen.findByRole("button", { name: /^revoke$/i }));

    await waitFor(() => expect(getRevoked()).toBe("key-1"));
  });
});
