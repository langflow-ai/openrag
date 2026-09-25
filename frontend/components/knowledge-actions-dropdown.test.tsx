import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { KnowledgeActionsDropdown } from "./knowledge-actions-dropdown";

describe("KnowledgeActionsDropdown", () => {
  it("syncs a website source and removes it after confirmation", async () => {
    const user = userEvent.setup();
    let syncCalls = 0;
    let deleteCalls = 0;
    renderWithProviders(
      <KnowledgeActionsDropdown
        filename="Docs"
        connectorType="url"
        webSourceId="source-1"
        webChildCount={3}
      />,
      {
        providers: ["task"],
        auth: authPresets.noAuthMode,
        handlers: [
          http.post("/api/connectors/url/sources/source-1/sync", () => {
            syncCalls += 1;
            return HttpResponse.json({ run_id: "run-1" });
          }),
          http.delete("/api/connectors/url/sources/source-1", () => {
            deleteCalls += 1;
            return HttpResponse.json({ success: true });
          }),
        ],
      },
    );

    await user.click(screen.getByRole("button"));
    await user.click(await screen.findByRole("menuitem", { name: "Sync" }));
    await waitFor(() => expect(syncCalls).toBe(1));

    await user.click(screen.getByRole("button"));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByText("Delete website source")).toBeVisible();
    expect(screen.getByText(/3 child pages/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteCalls).toBe(1));
  });

  it("opens chunks for a regular document from the same action menu", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <KnowledgeActionsDropdown filename="Product docs.pdf" />,
      { providers: ["task"], auth: authPresets.noAuthMode },
    );

    await user.click(screen.getByRole("button"));
    await user.click(
      await screen.findByRole("menuitem", { name: "View chunks" }),
    );

    expect(mockRouter.push).toHaveBeenCalledWith(
      "/knowledge/chunks?filename=Product%20docs.pdf",
    );
  });
});
