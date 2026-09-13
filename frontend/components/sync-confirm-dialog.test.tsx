import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils/render";
import { SyncConfirmDialog } from "./sync-confirm-dialog";

/**
 * What the sync confirmation dialog tells the user before they commit.
 *
 * The update count used to come from the *total synced count*, so a sync of 40
 * COS files with one modified announced "40 files will be updated" and then
 * updated one. These pin the three distinct states the dialog now has to keep
 * apart, because conflating any two of them misleads the user about what the
 * button is going to do:
 *
 *   - files that will change (named, from the preview)
 *   - files that can only be re-checked (the connector cannot predict)
 *   - nothing to do
 *
 * The dialog is presentational, but it's driven by radix primitives that need
 * a portal, so it renders through the shared harness rather than being asserted
 * on summarizeSyncPreview's return value alone (that lives in
 * sync-confirm-dialog-data.test.ts).
 */

const noop = () => {};

const file = (id: string, name: string) => ({
  document_id: id,
  filename: name,
});

function renderDialog(props: Partial<Parameters<typeof SyncConfirmDialog>[0]>) {
  return renderWithProviders(
    <SyncConfirmDialog
      open
      onOpenChange={noop}
      onConfirm={vi.fn()}
      {...props}
    />,
  );
}

describe("SyncConfirmDialog — updates", () => {
  it("names the files that changed instead of counting everything synced", async () => {
    renderDialog({
      connectorType: "ibm_cos",
      updates: [file("c::b", "b.pdf")],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 40,
    });

    expect(await screen.findByText("1 file will be updated")).toBeVisible();
    expect(screen.getByText("b.pdf")).toBeVisible();
    // The 39 untouched files must not be presented as updates.
    expect(screen.queryByText("40 files will be updated")).toBeNull();
  });

  it("groups changed files by connector when syncing all", async () => {
    renderDialog({
      isSyncAll: true,
      updatesByType: {
        ibm_cos: [file("c::b", "b.pdf")],
        aws_s3: [file("s::c", "c.pdf")],
      },
      updatesAvailableByType: { ibm_cos: true, aws_s3: true },
      syncedCountByType: { ibm_cos: 5, aws_s3: 5 },
    });

    expect(await screen.findByText("2 files will be updated")).toBeVisible();
    expect(screen.getByText("b.pdf")).toBeVisible();
    expect(screen.getByText("c.pdf")).toBeVisible();
  });
});

describe("SyncConfirmDialog — re-checks", () => {
  it("says re-checked, not updated, when the connector can't predict", async () => {
    renderDialog({
      connectorType: "google_drive",
      updates: [],
      updatesAvailableByType: { google_drive: false },
      syncedCount: 7,
    });

    expect(await screen.findByText("7 files will be re-checked")).toBeVisible();
    expect(
      screen.getByText(
        "Sync re-reads these files and updates the ones whose content changed.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("7 files will be updated")).toBeNull();
  });

  it("breaks the re-check count down per connector when several apply", async () => {
    renderDialog({
      isSyncAll: true,
      updatesByType: { google_drive: [], sharepoint: [] },
      updatesAvailableByType: { google_drive: false, sharepoint: false },
      syncedCountByType: { google_drive: 4, sharepoint: 2 },
    });

    expect(await screen.findByText("6 files will be re-checked")).toBeVisible();
    expect(screen.getByText("4")).toBeVisible();
    expect(screen.getByText("2")).toBeVisible();
  });
});

describe("SyncConfirmDialog — nothing to do", () => {
  it("says so rather than showing a zero count", async () => {
    renderDialog({
      connectorType: "ibm_cos",
      orphans: [],
      updates: [],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 12,
    });

    expect(await screen.findByText("Nothing to change")).toBeVisible();
    expect(
      screen.getByText(
        "No files were added, changed, or removed at the source.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("0 files will be updated")).toBeNull();
  });
});

describe("SyncConfirmDialog — deletions stay dominant", () => {
  it("shows deletions alongside updates and keeps the destructive CTA", async () => {
    renderDialog({
      connectorType: "ibm_cos",
      orphans: [file("c::gone", "gone.pdf")],
      orphansAvailableByType: { ibm_cos: true },
      updates: [file("c::b", "b.pdf")],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 2,
    });

    expect(await screen.findByText("1 file will be deleted")).toBeVisible();
    expect(screen.getByText("1 file will be updated")).toBeVisible();
    expect(screen.getByText("gone.pdf")).toBeVisible();
    expect(screen.getByText("b.pdf")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /delete & sync/i }),
    ).toBeVisible();
  });
});
