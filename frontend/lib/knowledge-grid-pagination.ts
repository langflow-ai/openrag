import type { IRowNode } from "ag-grid-community";
import type { AgGridReact } from "ag-grid-react";
import type { TaskFile } from "@/contexts/task-context";
import {
  getKnowledgeFileAliasKeys,
  getKnowledgeFileIdentity,
} from "@/lib/knowledge-table-state";

type GridApi = NonNullable<AgGridReact<unknown>["api"]>;

type GridRowLike = {
  filename?: string;
  source_url?: string;
  status?: string;
};

export type IngestFocusMode = "existing" | "new";

/**
 * Maps an upload overwrite flag to grid pagination focus mode.
 *
 * Intentionally `replace ? "existing" : "new"` — not inverted:
 * - Overwrite: file is already indexed; jump to its current row (first match).
 * - New ingest: processing overlay is appended after indexed rows (last page).
 */
export function ingestFocusModeFromReplace(replace: boolean): IngestFocusMode {
  return replace ? "existing" : "new";
}

export const KNOWLEDGE_INGEST_FOCUS_EVENT = "knowledgeIngestFocus";

const INGEST_FOCUS_STORAGE_KEY = "openrag:knowledge-ingest-focus";

export type KnowledgeIngestFocusTarget = {
  filename: string;
  replace: boolean;
};

function readPersistedIngestFocusTargets(): KnowledgeIngestFocusTarget[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = sessionStorage.getItem(INGEST_FOCUS_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is KnowledgeIngestFocusTarget =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as KnowledgeIngestFocusTarget).filename === "string" &&
        typeof (item as KnowledgeIngestFocusTarget).replace === "boolean",
    );
  } catch {
    return [];
  }
}

/** Persist focus targets across route changes (e.g. cloud upload → /knowledge). */
export function persistKnowledgeIngestFocus(
  targets: KnowledgeIngestFocusTarget[],
): void {
  if (typeof window === "undefined" || targets.length === 0) {
    return;
  }
  const merged = [...readPersistedIngestFocusTargets(), ...targets];
  sessionStorage.setItem(INGEST_FOCUS_STORAGE_KEY, JSON.stringify(merged));
}

export function consumePersistedKnowledgeIngestFocus(): KnowledgeIngestFocusTarget[] {
  if (typeof window === "undefined") {
    return [];
  }
  const targets = readPersistedIngestFocusTargets();
  sessionStorage.removeItem(INGEST_FOCUS_STORAGE_KEY);
  return targets;
}

export function dispatchKnowledgeIngestFocus(
  filename: string,
  replace: boolean,
): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent(KNOWLEDGE_INGEST_FOCUS_EVENT, {
      detail: { filename, replace },
    }),
  );
}

export function queueKnowledgeIngestFocusForCloudFiles(
  files: Array<{ name: string }>,
  replace: boolean,
): void {
  if (files.length === 0) {
    return;
  }
  persistKnowledgeIngestFocus(
    files.map((file) => ({ filename: file.name, replace })),
  );
}

type VisibleRowTarget = {
  displayIndex: number;
  node: IRowNode | null;
};

function rowMatchesIdentitySet(
  row: GridRowLike,
  identitySet: Set<string>,
): boolean {
  return getKnowledgeFileAliasKeys(row).some((key) => identitySet.has(key));
}

/** Infer focus mode from current grid rows (task-poll path). */
export function inferIngestFocusMode(
  identity: string,
  rowData: GridRowLike[],
): IngestFocusMode {
  const identitySet = new Set([identity]);
  const hasMatch = rowData.some((row) =>
    rowMatchesIdentitySet(row, identitySet),
  );
  return hasMatch ? "existing" : "new";
}

function hasActiveColumnSort(api: GridApi): boolean {
  return api.getColumnState().some((column) => column.sort != null);
}

function findRowDataIndex(
  identitySet: Set<string>,
  rowData: GridRowLike[],
  pick: "first" | "last",
): number {
  let targetIndex = -1;
  rowData.forEach((row, index) => {
    if (!rowMatchesIdentitySet(row, identitySet)) {
      return;
    }
    if (targetIndex < 0) {
      targetIndex = index;
      return;
    }
    if (pick === "first") {
      targetIndex = Math.min(targetIndex, index);
    } else {
      targetIndex = Math.max(targetIndex, index);
    }
  });
  return targetIndex;
}

/** Earliest or latest visible row (after filter/sort) matching any identity. */
function findVisibleRowTarget(
  api: GridApi,
  identitySet: Set<string>,
  rowData: GridRowLike[] | undefined,
  pick: "first" | "last",
): VisibleRowTarget | null {
  let target: VisibleRowTarget | null = null;

  api.forEachNodeAfterFilterAndSort((node, index) => {
    const data = node.data as GridRowLike | undefined;
    const nodeId = node.id;
    const matches =
      (nodeId && identitySet.has(nodeId)) ||
      (data != null && rowMatchesIdentitySet(data, identitySet));
    if (!matches) {
      return;
    }
    if (!target) {
      target = { displayIndex: index, node };
      return;
    }
    if (
      pick === "first"
        ? index < target.displayIndex
        : index > target.displayIndex
    ) {
      target = { displayIndex: index, node };
    }
  });

  if (target) {
    return target;
  }

  for (const id of identitySet) {
    const node = api.getRowNode(id);
    if (!node) {
      continue;
    }
    let displayIndex = -1;
    api.forEachNodeAfterFilterAndSort((current, index) => {
      if (current === node || current.id === id) {
        displayIndex = index;
      }
    });
    if (displayIndex >= 0) {
      return { displayIndex, node };
    }
  }

  if (!rowData?.length || hasActiveColumnSort(api)) {
    return null;
  }

  const displayIndex = findRowDataIndex(identitySet, rowData, pick);
  if (displayIndex < 0) {
    return null;
  }

  for (const id of identitySet) {
    const node = api.getRowNode(id);
    if (node) {
      return { displayIndex, node };
    }
  }

  return { displayIndex, node: null };
}

/** Map row alias hits back to the canonical pending ids that were queued. */
function addResolvablePendingIdsForRowKeys(
  found: Set<string>,
  identities: Set<string>,
  rowKeys: Iterable<string>,
): void {
  const keys = new Set(rowKeys);
  for (const pendingId of identities) {
    for (const alias of getKnowledgeFileAliasKeys({
      filename: pendingId,
      source_url: pendingId,
    })) {
      if (keys.has(alias)) {
        found.add(pendingId);
        break;
      }
    }
  }
}

/** Identities from pending that appear in the grid model and/or current rowData. */
function collectResolvableIdentities(
  api: GridApi,
  identities: Set<string>,
  rowData?: GridRowLike[],
): Set<string> {
  const found = new Set<string>();

  api.forEachNodeAfterFilterAndSort((node) => {
    const data = node.data as GridRowLike | undefined;
    const rowKeys = new Set(getKnowledgeFileAliasKeys(data));
    if (node.id) {
      rowKeys.add(node.id);
    }
    addResolvablePendingIdsForRowKeys(found, identities, rowKeys);
  });

  if (!rowData?.length || hasActiveColumnSort(api)) {
    return found;
  }

  for (const row of rowData) {
    addResolvablePendingIdsForRowKeys(
      found,
      identities,
      getKnowledgeFileAliasKeys(row),
    );
  }

  return found;
}

function resolveFocusMode(
  identitySet: Set<string>,
  modes: Map<string, IngestFocusMode> | undefined,
): IngestFocusMode {
  for (const id of identitySet) {
    const mode = modes?.get(id);
    if (mode) {
      return mode;
    }
  }
  return "existing";
}

/** Identities of task overlays that just started ingesting or were retried. */
export function collectNewIngestFocusIdentities(
  previous: TaskFile[],
  current: TaskFile[],
): string[] {
  const prevByAlias = new Map<string, TaskFile>();
  for (const file of previous) {
    for (const key of getKnowledgeFileAliasKeys(file)) {
      prevByAlias.set(key, file);
    }
  }

  const identities: string[] = [];
  const seen = new Set<string>();

  for (const file of current) {
    const keys = getKnowledgeFileAliasKeys(file);
    const identity = getKnowledgeFileIdentity(file) || keys[0];
    if (!identity || seen.has(identity)) {
      continue;
    }

    const prev = keys.map((key) => prevByAlias.get(key)).find(Boolean);
    if (!prev) {
      if (file.status === "processing") {
        identities.push(identity);
        seen.add(identity);
      }
      continue;
    }
    if (prev.status !== "processing" && file.status === "processing") {
      identities.push(identity);
      seen.add(identity);
    }
  }
  return identities;
}

/** Identities of rendered rows that entered the processing state. */
export function collectProcessingFocusIdentities(
  previous: GridRowLike[],
  current: GridRowLike[],
): string[] {
  const prevStatusByAlias = new Map<string, string>();
  for (const row of previous) {
    const status = row.status ?? "active";
    for (const key of getKnowledgeFileAliasKeys(row)) {
      prevStatusByAlias.set(key, status);
    }
  }

  const identities: string[] = [];
  const seen = new Set<string>();

  for (const row of current) {
    const status = row.status ?? "active";
    if (status !== "processing") {
      continue;
    }
    const keys = getKnowledgeFileAliasKeys(row);
    const identity = getKnowledgeFileIdentity(row) || keys[0];
    if (!identity || seen.has(identity)) {
      continue;
    }
    const prevStatus = keys
      .map((key) => prevStatusByAlias.get(key))
      .find((value) => value !== undefined);
    if (prevStatus === undefined || prevStatus !== "processing") {
      identities.push(identity);
      seen.add(identity);
    }
  }
  return identities;
}

function scrollToRowTarget(
  api: GridApi,
  target: VisibleRowTarget,
  afterPageChange = false,
): void {
  const scroll = () => {
    if (target.node) {
      api.ensureNodeVisible(target.node, "middle");
      return;
    }
    api.ensureIndexVisible(target.displayIndex, "middle");
  };
  if (afterPageChange) {
    requestAnimationFrame(() => requestAnimationFrame(scroll));
  } else {
    requestAnimationFrame(scroll);
  }
}

/** Jump to the pagination page that contains the target ingest row. */
export function goToGridRowIdentities(
  api: GridApi,
  identities: Iterable<string>,
  rowData?: GridRowLike[],
  modes?: Map<string, IngestFocusMode>,
): boolean {
  const identitySet = new Set(identities);
  if (identitySet.size === 0) {
    return false;
  }

  const mode = resolveFocusMode(identitySet, modes);
  const pick = mode === "new" ? "last" : "first";
  const target = findVisibleRowTarget(api, identitySet, rowData, pick);

  if (!target && mode === "new") {
    api.paginationGoToLastPage();
    return true;
  }

  if (!target) {
    return false;
  }

  let didChangePage = false;
  const pageSize = api.paginationGetPageSize();
  if (pageSize && pageSize > 0) {
    const targetPage = Math.floor(target.displayIndex / pageSize);
    const currentPage = api.paginationGetCurrentPage();
    if (currentPage !== targetPage) {
      api.paginationGoToPage(targetPage);
      didChangePage = true;
    }
  }

  scrollToRowTarget(api, target, didChangePage);
  return true;
}

/** Focus pending ingest rows once they appear in the grid. Returns resolved identities. */
export function focusPendingIngestRows(
  api: GridApi,
  pending: Set<string>,
  rowData?: GridRowLike[],
  modes?: Map<string, IngestFocusMode>,
): string[] {
  if (pending.size === 0) {
    return [];
  }

  const resolvable = collectResolvableIdentities(api, pending, rowData);
  const hasExistingTarget = resolvable.size > 0;
  const hasNewOnlyPending = [...pending].some(
    (id) => modes?.get(id) === "new" && !resolvable.has(id),
  );

  if (!hasExistingTarget && hasNewOnlyPending) {
    api.paginationGoToLastPage();
    return [];
  }

  if (!hasExistingTarget) {
    return [];
  }

  const didJump = goToGridRowIdentities(api, pending, rowData, modes);
  if (!didJump) {
    return [];
  }

  return [...pending].filter((id) => resolvable.has(id));
}
