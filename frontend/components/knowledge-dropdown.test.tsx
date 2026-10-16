import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetUploadLimitCache } from "@/lib/upload-utils";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen } from "@/test-utils/render";
import { KnowledgeDropdown } from "./knowledge-dropdown";

function sizedPdf(name: string, size: number) {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

function handlers(maxUploadMb: number, onOptions: () => void) {
  return [
    http.get("/api/upload_options", () => {
      onOptions();
      return HttpResponse.json({
        upload_batch_size: 25,
        max_upload_mb: maxUploadMb,
      });
    }),
    http.get("/api/connectors", () => HttpResponse.json({ connectors: {} })),
    http.get("/api/connectors/:type/defaults", () => HttpResponse.json({})),
    http.get("/api/documents/check-filename", () =>
      HttpResponse.json({ exists: false }),
    ),
    http.post("/api/router/upload_ingest", () =>
      HttpResponse.json({
        task_id: "task-1",
        file_count: 1,
        preview_mode: false,
      }),
    ),
  ];
}

async function chooseFolder(files: File[]) {
  let optionsLoaded = false;
  renderWithProviders(<KnowledgeDropdown />, {
    providers: ["brand", "task"],
    auth: authPresets.rbacDisabled,
    handlers: handlers(1, () => {
      optionsLoaded = true;
    }),
  });

  await screen.findByRole("button", { name: /add knowledge/i });
  await waitFor(() => expect(optionsLoaded).toBe(true));
  const folderInput = document.querySelector(
    "input[webkitdirectory]",
  ) as HTMLInputElement | null;
  if (!folderInput) throw new Error("folder input missing");
  await userEvent.upload(folderInput, files);
}

describe("KnowledgeDropdown folder upload limit", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetUploadLimitCache();
    vi.spyOn(toast, "error").mockReturnValue("toast");
    vi.spyOn(toast, "success").mockReturnValue("toast");
    vi.spyOn(toast, "info").mockReturnValue("toast");
  });

  it("skips a file over the configured limit and uploads the rest", async () => {
    await chooseFolder([
      sizedPdf("notes.pdf", 100),
      sizedPdf("huge.pdf", 2 * 1024 * 1024),
    ]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "File too large",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf"),
        }),
      );
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringContaining("Successfully processed 1 file(s)"),
      );
    });
  });

  it("does not report success when every file is over the limit", async () => {
    await chooseFolder([sizedPdf("huge.pdf", 2 * 1024 * 1024)]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "File too large",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf"),
        }),
      );
    });
    expect(toast.success).not.toHaveBeenCalled();
  });
});
