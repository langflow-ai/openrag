import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { IngestionTab } from "@/app/settings/_components/ingestion-tab";
import { readIngestPreviewSettings } from "@/hooks/use-ingest-preview-settings";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderTab() {
  return renderWithProviders(<IngestionTab />, {
    providers: ["tooltip", "auth", "unsavedChanges", "task"],
    auth: withAuth(authPresets.admin, { me: { run_mode: "oss" } }),
    handlers: [
      http.get("/api/settings", () =>
        HttpResponse.json(
          makeSettings({
            knowledge: { chunk_size: 1024, chunk_overlap: 50 },
            show_vlm_settings: false,
          }),
        ),
      ),
      http.get("/api/models/catalog", () =>
        HttpResponse.json({ providers: [] }),
      ),
      http.get("/api/models/providers", () => HttpResponse.json({})),
    ],
  });
}

describe("IngestPreviewSettingsSection", () => {
  it("persists the auto-open choice when Save changes is clicked", async () => {
    const user = userEvent.setup();
    renderTab();

    expect(readIngestPreviewSettings().autoOpen).toBe("never");

    await user.click(await screen.findByRole("tab", { name: /every upload/i }));

    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(readIngestPreviewSettings().autoOpen).toBe("every"),
    );
  });
});
