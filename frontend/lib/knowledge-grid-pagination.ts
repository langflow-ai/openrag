import type { IRowNode } from "ag-grid-community";
import type { AgGridReact } from "ag-grid-react";
import type { TaskFile } from "@/contexts/task-context";
import { getKnowledgeFileIdentity } from "@/lib/knowledge-table-state";

type GridApi = NonNullable<AgGridReact<unknown>["api"]>;

type GridRowLike = {
  filename?: string;
  source_url?: string;
  status?: string;
};

type VisibleRowTarget = {
  displayIndex: number;
  node: IRowNode;
};

/** Earliest visible row (after filter/sort) matching any identity. */
function findFirstVisibleRowTarget(
  api: GridApi,
  identitySet: Set<string>,
): VisibleRowTarget | null {
  let target: VisibleRowTarget | null = null;

  api.forEachNodeAfterFilterAndSort((node, index) => {
    const id = node.id;
    if (id && identitySet.has(id)) {
      if (!target || index < target.displayIndex) {
        target = { displayIndex: index, node };
      }
    }
  });

  return target;
}

/** Identities visible in the grid after filter/sort. */
function collectVisibleIdentities(
  api: GridApi,
  identities: Set<string>,
): Set<string> {
  const visible = new Set<string>();
  api.forEachNodeAfterFilterAndSort((node) => {
    const id = node.id;
    if (id && identities.has(id)) {
      visible.add(id);
    }
  });
  return visible;
}

/** Identities of task overlays that just started ingesting or were retried. */
export function collectNewIngestFocusIdentities(
  previous: TaskFile[],
  current: TaskFile[],
): string[] {
  const prevByIdentity = new Map<string, TaskFile>();
  for (const file of previous) {
    const identity = getKnowledgeFileIdentity(file);
    if (identity) {
      prevByIdentity.set(identity, file);
    }
  }

  const identities: string[] = [];
  for (const file of current) {
    const identity = getKnowledgeFileIdentity(file);
    if (!identity) {
      continue;
    }
    const prev = prevByIdentity.get(identity);
    if (!prev) {
      identities.push(identity);
      continue;
    }
    if (prev.status !== "processing" && file.status === "processing") {
      identities.push(identity);
    }
  }
  return identities;
}

/** Identities of rendered rows that entered the processing state. */
export function collectProcessingFocusIdentities(
  previous: GridRowLike[],
  current: GridRowLike[],
): string[] {
  const prevStatusByIdentity = new Map<string, string>();
  for (const row of previous) {
    const identity = getKnowledgeFileIdentity(row);
    if (identity) {
      prevStatusByIdentity.set(identity, row.status ?? "active");
    }
  }

  const identities: string[] = [];
  for (const row of current) {
    const identity = getKnowledgeFileIdentity(row);
    if (!identity) {
      continue;
    }
    const status = row.status ?? "active";
    if (status !== "processing") {
      continue;
    }
    const prevStatus = prevStatusByIdentity.get(identity);
    if (prevStatus === undefined || prevStatus !== "processing") {
      identities.push(identity);
    }
  }
  return identities;
}

function scrollToRowTarget(
  api: GridApi,
  target: VisibleRowTarget,
  afterPageChange = false,
): void {
  const scroll = () => api.ensureNodeVisible(target.node, "middle");
  if (afterPageChange) {
    requestAnimationFrame(() => requestAnimationFrame(scroll));
  } else {
    requestAnimationFrame(scroll);
  }
}

/** Jump to the first pagination page that contains any of the given row identities. */
export function goToGridRowIdentities(
  api: GridApi,
  identities: Iterable<string>,
): boolean {
  const identitySet = new Set(identities);
  if (identitySet.size === 0) {
    return false;
  }

  const target = findFirstVisibleRowTarget(api, identitySet);
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
): string[] {
  if (pending.size === 0) {
    return [];
  }

  const found = collectVisibleIdentities(api, pending);
  if (found.size === 0) {
    return [];
  }

  const didJump = goToGridRowIdentities(api, found);
  return didJump ? [...found] : [];
}
