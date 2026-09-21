import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { IngestSettingsSection } from "@/app/settings/_components/ingest-settings-section";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";

describe("IngestSettingsSection OCR languages", () => {
  it("shows English last when an existing selection was saved English-first", async () => {
    renderWithProviders(<IngestSettingsSection />, {
      providers: ["tooltip", "auth", "brand", "unsavedChanges"],
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              knowledge: { ocr: true, ocr_languages: ["en", "ja"] },
            }),
          ),
        ),
        http.get("/api/models/catalog", () =>
          HttpResponse.json({ providers: [] }),
        ),
        http.get("/api/models/providers", () => HttpResponse.json({})),
      ],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /advanced ocr settings/i }),
    );
    expect(await screen.findByText("Japanese, English")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /save ingest settings/i }),
    ).toBeDisabled();
  });

  it("saves a newly added Japanese selection before English", async () => {
    const save = vi.fn(() => HttpResponse.json({}));
    renderWithProviders(<IngestSettingsSection />, {
      providers: ["tooltip", "auth", "brand", "unsavedChanges"],
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({ knowledge: { ocr: true, ocr_languages: ["en"] } }),
          ),
        ),
        http.get("/api/models/catalog", () =>
          HttpResponse.json({ providers: [] }),
        ),
        http.get("/api/models/providers", () => HttpResponse.json({})),
        http.post("/api/settings", async ({ request }) => {
          const body = await request.json();
          expect(body).toMatchObject({ ocr_languages: ["ja", "en"] });
          return save();
        }),
      ],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /advanced ocr settings/i }),
    );
    await userEvent.click(await screen.findByText("English"));
    await userEvent.click(await screen.findByText("Japanese"));
    expect(await screen.findByText("Japanese, English")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /save ingest settings/i }),
    );
    expect(save).toHaveBeenCalledOnce();
  });
});
