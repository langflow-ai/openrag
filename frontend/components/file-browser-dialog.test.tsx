import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IngestSettings } from "@/components/cloud-picker/types";
import {
  fireEvent,
  renderWithProviders,
  screen,
  waitFor,
} from "@/test-utils/render";
import { FileBrowserDialog } from "./file-browser-dialog";

/**
 * A failed duplicate check must not fall through to the ingest. Proceeding
 * silently takes the "skip duplicates" path: the sync runs, every colliding
 * file is skipped with "a file with this name already exists", and the user
 * never gets the choice the check exists to offer — indistinguishable from
 * "there were no duplicates", and reported as the dialog not appearing.
 */

const mutateAsync = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/app/api/mutations/useSyncConnector", () => ({
  useSyncConnector: () => ({ mutateAsync, isPending: false }),
}));

vi.mock("@/app/api/queries/useBrowseConnectionFiles", () => ({
  useBrowseConnectionFiles: () => ({
    data: { files: [{ id: "f1", name: "report.pdf", size: 1024 }] },
    isLoading: false,
    error: null,
  }),
}));

const baseSettings: IngestSettings = {
  chunkSize: 1000,
  chunkOverlap: 200,
  ocr: false,
  pictureDescriptions: false,
  embeddingModel: "prod-embed",
};

function renderDialog(ingestSettings: IngestSettings) {
  return renderWithProviders(
    <FileBrowserDialog
      open
      onOpenChange={vi.fn()}
      connectorType="ibm_cos"
      connectionId="conn-1"
      ingestSettings={ingestSettings}
    />,
  );
}

describe("FileBrowserDialog duplicate-check failures", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
    vi.mocked(toast.error).mockClear();
  });

  function ingest() {
    renderDialog(baseSettings);
    fireEvent.click(screen.getByText("report.pdf"));
    fireEvent.click(screen.getByRole("button", { name: /Ingest 1 file/ }));
  }

  it("ingests nothing and says so when the check request rejects", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    ingest();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Could not check for existing files",
        {
          description: "Nothing was ingested. Try again.",
        },
      ),
    );
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("ingests nothing and says so when the check returns an error status", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: false, statusText: "Gateway Timeout" });

    ingest();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("still ingests when the check succeeds and finds nothing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ duplicate_names: [], duplicate_count: 0 }),
    });

    ingest();

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });
});
