import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { resetUploadLimitCache } from "@/lib/upload-utils";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { KnowledgeDropdown } from "./knowledge-dropdown";

function sizedPdf(name: string, size: number) {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

function handlers(
  maxUploadMb: number,
  onOptions: () => void,
  defaults: () => Response = () => HttpResponse.json({}),
) {
  return [
    http.get("/api/upload_options", () => {
      onOptions();
      return HttpResponse.json({
        upload_batch_size: 25,
        max_upload_mb: maxUploadMb,
      });
    }),
    http.get("/api/connectors", () => HttpResponse.json({ connectors: {} })),
    http.get("/api/connectors/:type/defaults", () => defaults()),
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
        "1 file is over the upload limit",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf"),
          duration: Number.POSITIVE_INFINITY,
        }),
      );
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringContaining("Successfully processed 1 file(s)"),
      );
    });
  });

  it("lists every skipped file in one toast", async () => {
    await chooseFolder([
      sizedPdf("huge.pdf", 2 * 1024 * 1024),
      sizedPdf("bigger.pdf", 3 * 1024 * 1024),
    ]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "2 files are over the upload limit",
        expect.objectContaining({
          description: expect.stringMatching(/huge\.pdf[\s\S]*bigger\.pdf/),
          duration: Number.POSITIVE_INFINITY,
          closeButton: true,
        }),
      );
    });
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("keeps a split folder on one task and records the skipped files once", async () => {
    const posts: Array<{
      existing: FormDataEntryValue | null;
      rejected: string;
      files: number;
    }> = [];
    vi.spyOn(apiClient, "post").mockImplementation(async (_url, body) => {
      const form = body as FormData;
      const existing = form.get("existing_task_id");
      posts.push({
        existing,
        rejected: String(form.get("rejected_files") ?? ""),
        files: form.getAll("file").length,
      });
      return {
        status: 202,
        data: {
          task_id:
            typeof existing === "string" && existing ? existing : "task-1",
          file_count: form.getAll("file").length,
          preview_mode: false,
        },
      };
    });
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
    await userEvent.upload(folderInput, [
      sizedPdf("first.pdf", 600 * 1024),
      sizedPdf("huge.pdf", 2 * 1024 * 1024),
      sizedPdf("second.pdf", 600 * 1024),
    ]);

    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[0]).toMatchObject({ existing: null, files: 1 });
    expect(posts[0]?.rejected).toContain("huge.pdf");
    expect(posts[1]).toMatchObject({
      existing: "task-1",
      files: 1,
      rejected: "",
    });
  });

  it("does not report success when every file is over the limit", async () => {
    await chooseFolder([sizedPdf("huge.pdf", 2 * 1024 * 1024)]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "1 file is over the upload limit",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf"),
          duration: Number.POSITIVE_INFINITY,
        }),
      );
    });
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("keeps the configured limit when a connector lookup fails", async () => {
    let optionsLoaded = false;
    renderWithProviders(<KnowledgeDropdown />, {
      providers: ["brand", "task"],
      auth: authPresets.rbacDisabled,
      handlers: handlers(
        1,
        () => {
          optionsLoaded = true;
        },
        () => HttpResponse.error(),
      ),
    });

    await screen.findByRole("button", { name: /add knowledge/i });
    await waitFor(() => expect(optionsLoaded).toBe(true));
    const folderInput = document.querySelector(
      "input[webkitdirectory]",
    ) as HTMLInputElement | null;
    if (!folderInput) throw new Error("folder input missing");
    await userEvent.upload(folderInput, [
      sizedPdf("huge.pdf", 2 * 1024 * 1024),
    ]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "1 file is over the upload limit",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf"),
          duration: Number.POSITIVE_INFINITY,
        }),
      );
    });
    expect(toast.success).not.toHaveBeenCalled();
  });
});
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
