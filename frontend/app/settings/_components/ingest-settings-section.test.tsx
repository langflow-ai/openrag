import type { RequestHandler } from "msw";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { IngestSettingsSection } from "@/app/settings/_components/ingest-settings-section";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { server } from "@/test-utils/msw/server";
import {
  act,
  fireEvent,
  renderWithProviders,
  screen,
  waitFor,
} from "@/test-utils/render";

// ── Global mocks ─────────────────────────────────────────────────────────────

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));

// Avoid BrandProvider needing its own auth bootstrap; the component only reads
// isCloudBrand to conditionally show one UI branch.
vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

// Suppress toasts — we're not asserting on them here and they can leak into
// unrelated assertions through aria-live regions.
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Default GET handlers for every test.
 * - /api/settings  → 1024 / 50 chunk settings, VLM disabled so the auto-select
 *                    effect never fires an extra /api/models/catalog request.
 * - /api/models/catalog → empty provider list; prevents unhandled-request error
 *                          from useGetModelCatalogQuery (always enabled for authed users).
 */
function baseHandlers(): RequestHandler[] {
  return [
    http.get("/api/settings", () =>
      HttpResponse.json(
        makeSettings({
          knowledge: { chunk_size: 1024, chunk_overlap: 50 },
          show_vlm_settings: false,
        }),
      ),
    ),
    http.get("/api/models/catalog", () => HttpResponse.json({ providers: [] })),
  ];
}

function renderSection(extraHandlers: RequestHandler[] = []) {
  return renderWithProviders(<IngestSettingsSection />, {
    providers: ["tooltip", "auth", "unsavedChanges"],
    auth: authPresets.admin,
    handlers: [...baseHandlers(), ...extraHandlers],
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("IngestSettingsSection", () => {
  // ── Baseline ──────────────────────────────────────────────────────────────

  describe("initial load", () => {
    it("populates chunk size and overlap from server", async () => {
      renderSection();

      expect(
        await screen.findByRole("spinbutton", { name: /chunk size/i }),
      ).toHaveValue(1024);
      expect(
        screen.getByRole("spinbutton", { name: /chunk overlap/i }),
      ).toHaveValue(50);
    });
  });

  // ── Group 1: Validation error display ─────────────────────────────────────

  describe("validation error display", () => {
    it("shows no error on load with valid settings", async () => {
      renderSection();

      // Wait for the form to fully render after auth + settings load.
      await screen.findByRole("spinbutton", { name: /chunk size/i });
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows 'Chunk size must be at least 1' when chunk size is set to 0", async () => {
      renderSection();

      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      fireEvent.change(input, { target: { value: "0" } });

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Chunk size must be at least 1",
      );
    });

    it("shows 'Chunk overlap must be less than chunk size' when overlap equals chunk size", async () => {
      renderSection();

      await screen.findByRole("spinbutton", { name: /chunk size/i });
      const overlapInput = screen.getByRole("spinbutton", {
        name: /chunk overlap/i,
      });
      fireEvent.change(overlapInput, { target: { value: "1024" } });

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Chunk overlap must be less than chunk size",
      );
    });

    it("clears the error when the user corrects invalid values", async () => {
      renderSection();

      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });

      // Introduce error.
      fireEvent.change(input, { target: { value: "0" } });
      expect(await screen.findByRole("alert")).toBeInTheDocument();

      // Fix it.
      fireEvent.change(input, { target: { value: "512" } });
      await waitFor(() => {
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      });
    });
  });

  // ── Group 2: Save button disabled state ───────────────────────────────────

  describe("save button disabled state", () => {
    it("is disabled when chunk size is 0", async () => {
      renderSection();

      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      fireEvent.change(input, { target: { value: "0" } });

      expect(
        screen.getByRole("button", { name: /save ingest settings/i }),
      ).toBeDisabled();
    });

    it("is disabled when overlap equals chunk size", async () => {
      renderSection();

      await screen.findByRole("spinbutton", { name: /chunk size/i });
      const overlapInput = screen.getByRole("spinbutton", {
        name: /chunk overlap/i,
      });
      fireEvent.change(overlapInput, { target: { value: "1024" } });

      expect(
        screen.getByRole("button", { name: /save ingest settings/i }),
      ).toBeDisabled();
    });

    it("is enabled when settings are valid and dirty (user changed a value)", async () => {
      renderSection();

      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      fireEvent.change(input, { target: { value: "512" } });

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /save ingest settings/i }),
        ).toBeEnabled();
      });
    });

    it("is disabled when form is clean (server values match state)", async () => {
      renderSection();

      // Wait for settings to load — state now matches server (1024 / 50).
      await screen.findByRole("spinbutton", { name: /chunk size/i });

      expect(
        screen.getByRole("button", { name: /save ingest settings/i }),
      ).toBeDisabled();
    });
  });

  // ── Group 3: Save handler blocked ─────────────────────────────────────────

  describe("save handler blocked", () => {
    it("does not POST /api/settings when chunk size is 0 (button is disabled)", async () => {
      let postCalled = false;
      server.use(
        http.post("/api/settings", () => {
          postCalled = true;
          return HttpResponse.json({
            message: "ok",
            settings: makeSettings({ show_vlm_settings: false }),
          });
        }),
      );

      renderSection();

      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      fireEvent.change(input, { target: { value: "0" } });

      const saveButton = screen.getByRole("button", {
        name: /save ingest settings/i,
      });
      expect(saveButton).toBeDisabled();
      expect(postCalled).toBe(false);
    });
  });

  // ── Group 4: userEdited ref prevents background sync overwrite ─────────────

  describe("userEdited ref / background sync", () => {
    it("background refetch does NOT overwrite user-entered chunk size", async () => {
      const { queryClient } = renderSection();

      // Wait for initial load.
      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      expect(input).toHaveValue(1024);

      // User edits the field → userEdited = true.
      fireEvent.change(input, { target: { value: "512" } });
      expect(input).toHaveValue(512);

      // Simulate a background refetch — the handler still returns the original
      // server value of 1024.
      await act(async () => {
        await queryClient.invalidateQueries({ queryKey: ["settings"] });
      });

      // User's edit must be preserved; the sync effect should have been
      // short-circuited by userEditedRef.current === true.
      expect(
        screen.getByRole("spinbutton", { name: /chunk size/i }),
      ).toHaveValue(512);
    });

    it("background sync resumes after a successful save", async () => {
      renderSection();

      // Wait for initial load.
      const input = await screen.findByRole("spinbutton", {
        name: /chunk size/i,
      });
      expect(input).toHaveValue(1024);

      // User edits.
      fireEvent.change(input, { target: { value: "512" } });

      // Override handlers: POST succeeds, then GET returns a different server
      // value (999) to prove sync has resumed after the save.
      server.use(
        http.post("/api/settings", () =>
          HttpResponse.json({
            message: "ok",
            settings: makeSettings({
              knowledge: { chunk_size: 512, chunk_overlap: 50 },
              show_vlm_settings: false,
            }),
          }),
        ),
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              knowledge: { chunk_size: 999, chunk_overlap: 50 },
              show_vlm_settings: false,
            }),
          ),
        ),
      );

      // Trigger the save.
      fireEvent.click(
        screen.getByRole("button", { name: /save ingest settings/i }),
      );

      // After the POST succeeds, userEdited resets to false.  The mutation's
      // own invalidateQueries then fires another GET, which returns 999.  The
      // sync effect (no longer blocked) must update the input.
      await waitFor(() => {
        expect(
          screen.getByRole("spinbutton", { name: /chunk size/i }),
        ).toHaveValue(999);
      });
    });
  });
});
