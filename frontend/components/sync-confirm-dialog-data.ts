import type { OrphanFile } from "@/app/api/mutations/useSyncConnector";

/** What a sync will do, shaped for the confirmation dialog.
 *
 * Kept out of the .tsx so the part that can actually be wrong — deciding what
 * the user is told — is plain logic with its own tests.
 */
export interface SyncPreviewSummary {
  /** Deletions grouped by connector_type (single-mode collapses to one entry). */
  orphansByType: Record<string, OrphanFile[]>;
  /** Known updates grouped by connector_type. */
  updatesByType: Record<string, OrphanFile[]>;
  /** Synced totals for connectors that can't predict updates, by connector_type. */
  recheckedByType: Record<string, number>;
  /** Connectors whose orphan detection couldn't complete. */
  unavailableConnectors: string[];
  totalOrphans: number;
  totalUpdates: number;
  totalRechecked: number;
}

export interface SyncPreviewInput {
  orphans?: OrphanFile[];
  orphansByType?: Record<string, OrphanFile[]>;
  orphansAvailableByType?: Record<string, boolean>;
  updates?: OrphanFile[];
  updatesByType?: Record<string, OrphanFile[]>;
  updatesAvailableByType?: Record<string, boolean>;
  syncedCount?: number;
  syncedCountByType?: Record<string, number>;
  connectorType?: string;
  isSyncAll?: boolean;
}

const sumLengths = (lists: OrphanFile[][]): number =>
  lists.reduce((sum, list) => sum + list.length, 0);

/** Fold the single-connector and sync-all response shapes into one structure.
 *
 * The distinction that matters here is between a connector reporting *no*
 * updates and one that cannot predict them: connectors on `replace_always`
 * change detection re-read every file and decide during ingest, so their synced
 * total is surfaced as "re-checked" instead of being presented as a count of
 * files that will change.
 */
export const summarizeSyncPreview = (
  props: SyncPreviewInput,
): SyncPreviewSummary => {
  const {
    orphans,
    orphansByType,
    orphansAvailableByType,
    updates,
    updatesByType,
    updatesAvailableByType,
    syncedCount,
    syncedCountByType,
    connectorType,
    isSyncAll,
  } = props;

  const byConnector = (
    grouped: Record<string, OrphanFile[]> | undefined,
    single: OrphanFile[] | undefined,
  ): Record<string, OrphanFile[]> =>
    isSyncAll
      ? Object.fromEntries(
          Object.entries(grouped ?? {}).filter(([, list]) => list.length > 0),
        )
      : single && single.length > 0 && connectorType
        ? { [connectorType]: single }
        : {};

  const normalizedOrphans = byConnector(orphansByType, orphans);
  const normalizedUpdates = byConnector(updatesByType, updates);

  const recheckedByType: Record<string, number> = {};
  const syncedTotals: Record<string, number> = isSyncAll
    ? (syncedCountByType ?? {})
    : connectorType && syncedCount
      ? { [connectorType]: syncedCount }
      : {};
  for (const [type, count] of Object.entries(syncedTotals)) {
    if (count > 0 && (updatesAvailableByType ?? {})[type] === false) {
      recheckedByType[type] = count;
    }
  }

  const unavailableConnectors = Object.entries(orphansAvailableByType ?? {})
    .filter(([, available]) => !available)
    .map(([type]) => type);

  return {
    orphansByType: normalizedOrphans,
    updatesByType: normalizedUpdates,
    recheckedByType,
    unavailableConnectors,
    totalOrphans: sumLengths(Object.values(normalizedOrphans)),
    totalUpdates: sumLengths(Object.values(normalizedUpdates)),
    totalRechecked: Object.values(recheckedByType).reduce((s, n) => s + n, 0),
  };
};
