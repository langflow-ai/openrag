import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ALL_PERMISSIONS,
  authPresets,
  withAuth,
} from "@/test-utils/fixtures/auth";
import { parseMultipart } from "@/test-utils/msw/multipart";
import { fireEvent, renderWithProviders, waitFor } from "@/test-utils/render";
import { KnowledgeDropdown } from "./knowledge-dropdown";

/**
 * The size guards added for the "413 Request Entity Too Large" failure.
 *
 * A proxy in front of docling-serve caps the request body, and because
 * ingestion is asynchronous the rejection used to land minutes later on a
 * failed task with no mention of size. These tests pin the two places the UI
 * now stops that from happening: refusing a file it knows is over the bound,
 * and keeping each folder batch under it.
 *
 * The bound is whatever `/api/upload_options` reports, so every test here
 * serves 1 MB — well under the 100 MB client default, which means a passing
 * assertion can only come from the server value being read.
 *
 * Requests are asserted by file *count*, not name: jsdom's File crosses the
 * undici boundary unnamed. See test-utils/msw/multipart.ts.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const MB = 1024 * 1024;

// The dropdown renders nothing at all without `knowledge:upload`, which the
// shared `admin` preset does not list.
const UPLOADER = withAuth(authPresets.admin, {
  usersMe: { permissions: [...ALL_PERMISSIONS, "knowledge:upload"] },
});

function sized(name: string, bytes: number, type = "application/pdf") {
  return new File(["x".repeat(bytes)], name, { type });
}

/** Records the number of files in every multipart upload the page sends. */
function trackUploads() {
  const fileCounts: number[] = [];
  return {
    fileCounts,
    handler: http.post("/api/router/upload_ingest", async ({ request }) => {
      fileCounts.push(parseMultipart(await request.text()).fileCount);
      return HttpResponse.json({ task_id: `t-${fileCounts.length}` });
    }),
  };
}

function baseHandlers(maxUploadSizeMb: number | undefined) {
  return [
    http.get("/api/upload_options", () =>
      HttpResponse.json({
        aws: false,
        upload_batch_size: 25,
        max_upload_size_mb: maxUploadSizeMb,
      }),
    ),
    http.get("/api/connectors", () => HttpResponse.json({ connectors: {} })),
    http.get("/api/connectors/:type/defaults", () => HttpResponse.json({})),
    http.get("/api/documents/check-filename", () =>
      HttpResponse.json({ exists: false }),
    ),
  ];
}

/**
 * Both file inputs are always in the tree and carry no accessible name, so
 * they are selected by the attribute that distinguishes them: the folder input
 * is the one with `webkitdirectory`.
 */
async function mountDropdown(
  maxUploadSizeMb: number | undefined,
  extra: ReturnType<typeof http.post>[] = [],
) {
  const { container } = renderWithProviders(<KnowledgeDropdown />, {
    providers: ["auth", "brand", "task"],
    auth: UPLOADER,
    handlers: [...baseHandlers(maxUploadSizeMb), ...extra],
  });

  const inputs = await waitFor(() => {
    const found =
      container.querySelectorAll<HTMLInputElement>('input[type="file"]');
    if (found.length < 2) throw new Error("file inputs not mounted yet");
    return Array.from(found);
  });

  const file = inputs.find((i) => !i.hasAttribute("webkitdirectory"));
  const folder = inputs.find((i) => i.hasAttribute("webkitdirectory"));

  // The limit arrives from /api/upload_options after mount; selecting a file
  // before it lands would be measured against the client default.
  await waitFor(() => {
    expect(file?.accept).toContain(".pdf");
  });

  if (!file || !folder) throw new Error("file inputs not found");
  return { file, folder };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("single file selection", () => {
  it("refuses a file over the reported limit without contacting the server", async () => {
    const uploads = trackUploads();
    const { file } = await mountDropdown(1, [uploads.handler]);

    fireEvent.change(file, { target: { files: [sized("big.pdf", 2 * MB)] } });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "File too large",
        expect.objectContaining({
          description: expect.stringContaining("big.pdf is 2.0 MB"),
        }),
      );
    });
    expect(toast.error).toHaveBeenCalledWith(
      "File too large",
      expect.objectContaining({
        description: expect.stringContaining("maximum is 1 MB"),
      }),
    );
    expect(uploads.fileCounts).toEqual([]);
  });

  it("uploads a file under the limit", async () => {
    const uploads = trackUploads();
    const { file } = await mountDropdown(1, [uploads.handler]);

    fireEvent.change(file, { target: { files: [sized("small.pdf", 1000)] } });

    await waitFor(() => {
      expect(uploads.fileCounts).toEqual([1]);
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("falls back to the client default when the server reports no limit", async () => {
    const uploads = trackUploads();
    const { file } = await mountDropdown(undefined, [uploads.handler]);

    fireEvent.change(file, { target: { files: [sized("mid.pdf", 2 * MB)] } });

    await waitFor(() => {
      expect(uploads.fileCounts).toEqual([1]);
    });
  });
});

describe("folder selection", () => {
  it("skips oversized files and uploads the rest", async () => {
    const uploads = trackUploads();
    const { folder } = await mountDropdown(1, [uploads.handler]);

    fireEvent.change(folder, {
      target: { files: [sized("ok.pdf", 1000), sized("huge.pdf", 3 * MB)] },
    });

    await waitFor(() => {
      expect(uploads.fileCounts).toEqual([1]);
    });
    expect(toast.error).toHaveBeenCalledWith(
      "Skipping 1 file(s) over the 1 MB limit",
      expect.objectContaining({
        description: expect.stringContaining("huge.pdf (3.0 MB)"),
      }),
    );
  });

  it("splits a folder upload so no request exceeds the limit", async () => {
    const uploads = trackUploads();
    const { folder } = await mountDropdown(1, [uploads.handler]);

    // Four files well inside the per-file bound: batching on count alone
    // would send all four as a single 2.4 MB body the proxy rejects.
    fireEvent.change(folder, {
      target: {
        files: [1, 2, 3, 4].map((n) => sized(`part${n}.pdf`, 600 * 1024)),
      },
    });

    await waitFor(() => {
      expect(uploads.fileCounts.reduce((a, b) => a + b, 0)).toBe(4);
    });
    expect(uploads.fileCounts).toEqual([1, 1, 1, 1]);
  });

  it("reports when every file in the folder is oversized", async () => {
    const uploads = trackUploads();
    const { folder } = await mountDropdown(1, [uploads.handler]);

    fireEvent.change(folder, {
      target: { files: [sized("huge.pdf", 3 * MB)] },
    });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Skipping 1 file(s) over the 1 MB limit",
        expect.objectContaining({
          description: expect.stringContaining("huge.pdf (3.0 MB)"),
        }),
      );
    });
    expect(toast.error).not.toHaveBeenCalledWith(
      "No supported files found",
      expect.anything(),
    );
    expect(uploads.fileCounts).toEqual([]);
  });
});
