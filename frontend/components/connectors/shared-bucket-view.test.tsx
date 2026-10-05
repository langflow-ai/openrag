import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import {
  fireEvent,
  renderWithProviders,
  screen,
  waitFor,
} from "@/test-utils/render";
import { SharedBucketView } from "./shared-bucket-view";

const CHECK_DUPLICATES = "/api/connectors/ibm_cos/check-duplicates";

/**
 * A failed duplicate check must not fall through to the ingest.
 *
 * Proceeding silently takes the "skip duplicates" path: the sync runs, every
 * colliding file is skipped with "a file with this name already exists", and
 * the user never gets the choice the check exists to offer. From the outside
 * that is indistinguishable from "there were no duplicates" — which is how it
 * reaches us, reported as the duplicate dialog not appearing.
 */

const mutate = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/lib/analytics", () => ({
  trackStartProcess: vi.fn(),
  trackProcessFailure: vi.fn(),
}));

vi.mock("@/app/api/queries/useGetSettingsQuery", () => ({
  useGetSettingsQuery: () => ({
    data: { show_provider_ingest_settings: false },
  }),
}));

vi.mock("@/hooks/useSessionIngestSettings", () => ({
  useSessionIngestSettings: () => [
    {
      chunkSize: 1000,
      chunkOverlap: 200,
      ocr: false,
      pictureDescriptions: false,
      embeddingModel: "prod-embed",
    },
    vi.fn(),
  ],
}));

function renderView() {
  return renderWithProviders(
    <SharedBucketView
      connector={{ type: "ibm_cos", name: "IBM COS", connectionId: "conn-1" }}
      buckets={[{ name: "docs", ingested_count: 0 }]}
      isLoading={false}
      onRefetch={vi.fn()}
      invalidateQueryKey={["connectors"]}
      syncMutation={{ mutate, isPending: false } as never}
      addTask={vi.fn()}
      onBack={vi.fn()}
      onDone={vi.fn()}
      resourceLabel="bucket"
      resourceLabelPlural="buckets"
    />,
    { providers: ["auth"] },
  );
}

function selectBucketAndIngest() {
  renderView();
  fireEvent.click(screen.getByRole("checkbox", { name: "docs" }));
  fireEvent.click(screen.getByRole("button", { name: /Ingest 1 Bucket/ }));
}

describe("SharedBucketView duplicate-check failures", () => {
  beforeEach(() => {
    mutate.mockReset();
    vi.mocked(toast.error).mockClear();
  });

  it("ingests nothing and says so when the check request rejects", async () => {
    server.use(http.post(CHECK_DUPLICATES, () => HttpResponse.error()));

    selectBucketAndIngest();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Could not check for existing files",
        expect.objectContaining({
          description: expect.stringContaining("Nothing was ingested"),
        }),
      ),
    );
    expect(mutate).not.toHaveBeenCalled();
  });

  it("offers an escape hatch that ingests (skipping duplicates) when the check keeps failing", async () => {
    server.use(http.post(CHECK_DUPLICATES, () => HttpResponse.error()));

    selectBucketAndIngest();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mutate).not.toHaveBeenCalled();

    const [, options] = vi.mocked(toast.error).mock.calls[0];
    const action = options?.action as unknown as { onClick: () => void };
    action.onClick();

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({ replace_duplicates: false }),
      }),
      expect.anything(),
    );
  });

  it("ingests nothing and says so when the check times out upstream", async () => {
    server.use(
      http.post(CHECK_DUPLICATES, () =>
        HttpResponse.json({ error: "timeout" }, { status: 504 }),
      ),
    );

    selectBucketAndIngest();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mutate).not.toHaveBeenCalled();
  });

  it("still ingests when the check succeeds and finds nothing", async () => {
    server.use(
      http.post(CHECK_DUPLICATES, () =>
        HttpResponse.json({ duplicate_names: [], duplicate_count: 0 }),
      ),
    );

    selectBucketAndIngest();

    await waitFor(() => expect(mutate).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("opens the dialog instead of ingesting when duplicates are found", async () => {
    server.use(
      http.post(CHECK_DUPLICATES, () =>
        HttpResponse.json({
          duplicate_names: ["report.pdf"],
          duplicate_count: 1,
          duplicate_files: [
            { id: "docs::report.pdf", name: "report.pdf", mimeType: "" },
          ],
          non_duplicate_files: [],
        }),
      ),
    );

    selectBucketAndIngest();

    await waitFor(() => expect(screen.getByText(/report\.pdf/)).toBeTruthy());
    expect(mutate).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
