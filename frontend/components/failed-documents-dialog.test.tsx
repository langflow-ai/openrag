/**
 * Tests for FailedDocumentsDialog: the list of documents that failed
 * ingestion, with per-file Retry, Retry all and the loading / empty / error
 * states.
 */
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { FailedDocumentsDialog } from "./failed-documents-dialog";

const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMocks }));

const makeFailure = (overrides: Record<string, unknown> = {}) => ({
  connector_type: "aws_s3",
  file_id: "bucket::docs/broken.docx",
  filename: "broken.docx",
  last_error: "The file 'broken.docx' has an incompatible type.",
  attempt_count: 3,
  skipped: true,
  first_failed_at: "2026-01-01T00:00:00+00:00",
  last_failed_at: "2026-01-02T00:00:00+00:00",
  ...overrides,
});

const listHandler = (failures: unknown[], maxAttempts = 3) =>
  http.get("/api/connectors/failed-ingestions", () =>
    HttpResponse.json({ max_attempts: maxAttempts, failures }),
  );

const renderDialog = (
  failures: unknown[],
  props: { open?: boolean; onOpenChange?: (open: boolean) => void } = {},
) =>
  renderWithProviders(
    <FailedDocumentsDialog
      open={props.open ?? true}
      onOpenChange={props.onOpenChange ?? vi.fn()}
    />,
    { handlers: [listHandler(failures)] },
  );

describe("FailedDocumentsDialog", () => {
  it("shows a spinner while the list is loading", () => {
    const { container } = renderDialog([]);

    expect(document.querySelector(".animate-spin")).not.toBeNull();
    expect(container).toBeTruthy();
  });

  it("says so when nothing has failed", async () => {
    renderDialog([]);

    expect(await screen.findByText("No failed documents.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("lists each failure with its error, connector and attempt state", async () => {
    renderDialog([
      makeFailure(),
      makeFailure({
        file_id: "bucket::docs/flaky.pdf",
        filename: "flaky.pdf",
        last_error: "timeout",
        attempt_count: 1,
        skipped: false,
      }),
    ]);

    expect(await screen.findByText("broken.docx")).toBeInTheDocument();
    expect(
      screen.getByText("The file 'broken.docx' has an incompatible type."),
    ).toBeInTheDocument();
    expect(screen.getByText("Skipped")).toBeInTheDocument();

    expect(screen.getByText("flaky.pdf")).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
    expect(screen.getByText("Attempt 1 of 3")).toBeInTheDocument();
  });

  it("explains the retry budget in the description", async () => {
    renderDialog([makeFailure()]);

    expect(
      await screen.findByText(/After 3 failed attempts a document is skipped/),
    ).toBeInTheDocument();
  });

  it("falls back to the file id when the filename is unknown", async () => {
    renderDialog([makeFailure({ filename: null, last_error: null })]);

    expect(
      await screen.findByText("bucket::docs/broken.docx"),
    ).toBeInTheDocument();
  });

  it("falls back to the raw connector type when it has no label", async () => {
    renderDialog([makeFailure({ connector_type: "mystery_store" })]);

    expect(await screen.findByText("mystery_store")).toBeInTheDocument();
  });

  it("shows the backend error when the list cannot be loaded", async () => {
    renderWithProviders(<FailedDocumentsDialog open onOpenChange={vi.fn()} />, {
      handlers: [
        http.get("/api/connectors/failed-ingestions", () =>
          HttpResponse.json(
            { error: "Could not list failed documents" },
            { status: 500 },
          ),
        ),
      ],
    });

    expect(
      await screen.findByText("Could not list failed documents"),
    ).toBeInTheDocument();
  });

  it("retries one file with its connector type and id", async () => {
    let body: unknown;
    toastMocks.success.mockClear();
    renderWithProviders(<FailedDocumentsDialog open onOpenChange={vi.fn()} />, {
      handlers: [
        listHandler([makeFailure()]),
        http.post(
          "/api/connectors/failed-ingestions/clear",
          async ({ request }) => {
            body = await request.json();
            return HttpResponse.json({ cleared: 1 });
          },
        ),
      ],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /^retry$/i }),
    );

    await waitFor(() =>
      expect(toastMocks.success).toHaveBeenCalledWith(
        "Cleared 1 failed document. Run a sync to retry it.",
      ),
    );
    expect(body).toEqual({
      connector_type: "aws_s3",
      file_id: "bucket::docs/broken.docx",
    });
  });

  it("offers Retry all only for several failures and clears them all", async () => {
    let body: unknown;
    toastMocks.success.mockClear();
    renderWithProviders(<FailedDocumentsDialog open onOpenChange={vi.fn()} />, {
      handlers: [
        listHandler([
          makeFailure(),
          makeFailure({ file_id: "bucket::b.pdf", filename: "b.pdf" }),
        ]),
        http.post(
          "/api/connectors/failed-ingestions/clear",
          async ({ request }) => {
            body = await request.json();
            return HttpResponse.json({ cleared: 2 });
          },
        ),
      ],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /retry all/i }),
    );

    await waitFor(() =>
      expect(toastMocks.success).toHaveBeenCalledWith(
        "Cleared 2 failed documents. Run a sync to retry them.",
      ),
    );
    expect(body).toEqual({});
  });

  it("hides Retry all when there is a single failure", async () => {
    renderDialog([makeFailure()]);

    await screen.findByText("broken.docx");
    expect(screen.queryByRole("button", { name: /retry all/i })).toBeNull();
  });

  it("reports an error toast when clearing fails", async () => {
    toastMocks.error.mockClear();
    renderWithProviders(<FailedDocumentsDialog open onOpenChange={vi.fn()} />, {
      handlers: [
        listHandler([makeFailure()]),
        http.post("/api/connectors/failed-ingestions/clear", () =>
          HttpResponse.json(
            { error: "Could not clear failed documents" },
            { status: 500 },
          ),
        ),
      ],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /^retry$/i }),
    );

    await waitFor(() =>
      expect(toastMocks.error).toHaveBeenCalledWith(
        "Could not clear failed documents",
      ),
    );
  });

  it("closes through the Close button", async () => {
    const onOpenChange = vi.fn();
    renderDialog([], { onOpenChange });

    // The dialog has two "Close" buttons: the footer one and the corner X.
    const closeButtons = await screen.findAllByRole("button", {
      name: /^close$/i,
    });
    expect(closeButtons).toHaveLength(2);
    // The footer button is the one with visible text; the X is icon-only.
    const footerClose = closeButtons.find((b) => b.textContent === "Close");
    expect(footerClose).toBeDefined();
    await userEvent.click(footerClose as HTMLElement);

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not request the list while closed", async () => {
    let requests = 0;
    renderWithProviders(
      <FailedDocumentsDialog open={false} onOpenChange={vi.fn()} />,
      {
        handlers: [
          http.get("/api/connectors/failed-ingestions", () => {
            requests += 1;
            return HttpResponse.json({ max_attempts: 3, failures: [] });
          }),
        ],
      },
    );

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(requests).toBe(0);
  });
});
