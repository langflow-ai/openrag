/**
 * What the sync confirmation dialog tells the user.
 *
 * The dialog used to derive "N files will be updated" from the *total synced
 * count*, which claimed every indexed file would be updated no matter how many
 * had actually changed. Updates now come from the preview's own list.
 *
 * The case worth pinning is the third state: a connector that re-reads every
 * file and decides during ingest can't predict updates at all. That must read
 * as "re-checked", never as a confident count and never as "nothing changed".
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { summarizeSyncPreview } from "./sync-confirm-dialog-data";

const file = (id: string, name: string) => ({
  document_id: id,
  filename: name,
});

describe("summarizeSyncPreview — single connector", () => {
  it("reports the changed files, not the synced total", () => {
    const summary = summarizeSyncPreview({
      connectorType: "ibm_cos",
      updates: [file("c::b", "b.pdf")],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 40,
    });

    assert.equal(summary.totalUpdates, 1);
    assert.deepEqual(summary.updatesByType, {
      ibm_cos: [file("c::b", "b.pdf")],
    });
    // The other 39 synced files are untouched and must not be counted.
    assert.equal(summary.totalRechecked, 0);
  });

  it("reports nothing when a predicting connector has no changes", () => {
    const summary = summarizeSyncPreview({
      connectorType: "ibm_cos",
      updates: [],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 40,
    });

    assert.equal(summary.totalUpdates, 0);
    assert.equal(summary.totalRechecked, 0);
  });

  it("falls back to re-checked when the connector can't predict updates", () => {
    const summary = summarizeSyncPreview({
      connectorType: "google_drive",
      updates: [],
      updatesAvailableByType: { google_drive: false },
      syncedCount: 7,
    });

    assert.equal(summary.totalUpdates, 0);
    assert.equal(summary.totalRechecked, 7);
    assert.deepEqual(summary.recheckedByType, { google_drive: 7 });
  });

  it("keeps deletions separate from updates", () => {
    const summary = summarizeSyncPreview({
      connectorType: "ibm_cos",
      orphans: [file("c::gone", "gone.pdf")],
      orphansAvailableByType: { ibm_cos: true },
      updates: [file("c::b", "b.pdf")],
      updatesAvailableByType: { ibm_cos: true },
      syncedCount: 2,
    });

    assert.equal(summary.totalOrphans, 1);
    assert.equal(summary.totalUpdates, 1);
    assert.deepEqual(summary.unavailableConnectors, []);
  });
});

describe("summarizeSyncPreview — sync all", () => {
  it("groups updates by connector and drops empty groups", () => {
    const summary = summarizeSyncPreview({
      isSyncAll: true,
      updatesByType: {
        ibm_cos: [file("c::b", "b.pdf"), file("c::c", "c.pdf")],
        aws_s3: [],
      },
      updatesAvailableByType: { ibm_cos: true, aws_s3: true },
      syncedCountByType: { ibm_cos: 10, aws_s3: 4 },
    });

    assert.equal(summary.totalUpdates, 2);
    assert.deepEqual(Object.keys(summary.updatesByType), ["ibm_cos"]);
  });

  it("mixes predicting and non-predicting connectors without conflating them", () => {
    const summary = summarizeSyncPreview({
      isSyncAll: true,
      updatesByType: { ibm_cos: [file("c::b", "b.pdf")], google_drive: [] },
      updatesAvailableByType: { ibm_cos: true, google_drive: false },
      syncedCountByType: { ibm_cos: 10, google_drive: 5 },
    });

    assert.equal(summary.totalUpdates, 1);
    assert.deepEqual(summary.recheckedByType, { google_drive: 5 });
    // ibm_cos predicted its updates, so its synced total is not re-checked too.
    assert.equal(summary.totalRechecked, 5);
  });

  it("surfaces connectors whose deletion check couldn't complete", () => {
    const summary = summarizeSyncPreview({
      isSyncAll: true,
      orphansByType: { ibm_cos: [] },
      orphansAvailableByType: { ibm_cos: false, aws_s3: true },
      syncedCountByType: { ibm_cos: 3 },
    });

    assert.deepEqual(summary.unavailableConnectors, ["ibm_cos"]);
    assert.equal(summary.totalOrphans, 0);
  });

  it("is empty for an empty preview", () => {
    const summary = summarizeSyncPreview({ isSyncAll: true });

    assert.equal(summary.totalOrphans, 0);
    assert.equal(summary.totalUpdates, 0);
    assert.equal(summary.totalRechecked, 0);
    assert.deepEqual(summary.unavailableConnectors, []);
  });
});
