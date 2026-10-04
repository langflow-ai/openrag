import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { KnowledgeDropdown } from "./knowledge-dropdown";

describe("Add Knowledge connector menu", () => {
  it("opens a connected flat customer connector from the runtime catalog", async () => {
    renderWithProviders(<KnowledgeDropdown />, {
      providers: ["auth", "brand", "task"],
      auth: authPresets.rbacDisabled,
      handlers: [
        http.get("/api/upload_options", () =>
          HttpResponse.json({ upload_batch_size: 25 }),
        ),
        http.get("/api/connectors/:type/defaults", () =>
          HttpResponse.json({ connection_id: null }),
        ),
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              acme_flat: {
                name: "Acme Files",
                available: true,
                browse_capability: "flat",
              },
            },
          }),
        ),
        http.get("/api/connectors/acme_flat/status", () =>
          HttpResponse.json({
            connections: [
              {
                connection_id: "owned-flat",
                is_active: true,
                is_authenticated: true,
              },
            ],
          }),
        ),
      ],
    });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Add Knowledge" }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: "Acme Files" }),
    );
    await waitFor(() =>
      expect(mockRouter.push).toHaveBeenCalledWith("/upload/acme_flat"),
    );
  });
});
