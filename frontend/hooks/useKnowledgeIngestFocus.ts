"use client";

import type { AgGridReact } from "ag-grid-react";
import { type RefObject, useCallback, useEffect, useMemo, useRef } from "react";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import type { TaskFile } from "@/contexts/task-context";
import {
  buildGridRowsSelectionKey,
  collectNewIngestFocusIdentities,
  collectProcessingFocusIdentities,
  consumePersistedKnowledgeIngestFocus,
  focusPendingIngestRows,
  type IngestFocusMode,
  inferIngestFocusMode,
  ingestFocusModeFromReplace,
  KNOWLEDGE_INGEST_FOCUS_EVENT,
} from "@/lib/knowledge-grid-pagination";

export function useKnowledgeIngestFocus(
  gridRef: RefObject<AgGridReact<File> | null>,
  gridRows: File[],
  taskFiles: TaskFile[],
) {
  const paginationSnapshotRef = useRef({
    initialized: false,
    taskFiles: [] as TaskFile[],
    gridRows: [] as File[],
  });

  const pendingFocusRef = useRef({
    identities: new Set<string>(),
    modes: new Map<string, IngestFocusMode>(),
  });

  const tryFocusPendingIngestRows = useCallback(
    (rows: File[]) => {
      const run = () => {
        const api = gridRef.current?.api;
        if (!api) {
          return;
        }
        const pending = pendingFocusRef.current;
        const resolved = focusPendingIngestRows(
          api,
          pending.identities,
          rows,
          pending.modes,
        );
        for (const identity of resolved) {
          pending.identities.delete(identity);
          pending.modes.delete(identity);
        }
      };
      requestAnimationFrame(() => requestAnimationFrame(run));
    },
    [gridRef],
  );

  const queueIngestFocusIdentities = useCallback(
    (identities: string[], mode?: IngestFocusMode, rows: File[] = gridRows) => {
      if (identities.length === 0) {
        return;
      }
      const pending = pendingFocusRef.current;
      for (const identity of identities) {
        pending.identities.add(identity);
        pending.modes.set(
          identity,
          mode ??
            pending.modes.get(identity) ??
            inferIngestFocusMode(identity, rows),
        );
      }
      tryFocusPendingIngestRows(rows);
    },
    [gridRows, tryFocusPendingIngestRows],
  );

  useEffect(() => {
    const stored = consumePersistedKnowledgeIngestFocus();
    for (const target of stored) {
      queueIngestFocusIdentities(
        [target.filename],
        ingestFocusModeFromReplace(target.replace),
      );
    }
  }, [queueIngestFocusIdentities]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (
        event as CustomEvent<{ filename: string; replace: boolean }>
      ).detail;
      if (!detail?.filename) {
        return;
      }
      queueIngestFocusIdentities(
        [detail.filename],
        ingestFocusModeFromReplace(detail.replace),
      );
    };
    window.addEventListener(KNOWLEDGE_INGEST_FOCUS_EVENT, handler);
    return () =>
      window.removeEventListener(KNOWLEDGE_INGEST_FOCUS_EVENT, handler);
  }, [queueIngestFocusIdentities]);

  useEffect(() => {
    const snapshot = paginationSnapshotRef.current;
    if (!snapshot.initialized) {
      snapshot.taskFiles = taskFiles;
      snapshot.gridRows = gridRows;
      snapshot.initialized = true;
      return;
    }

    const fromTasks = collectNewIngestFocusIdentities(
      snapshot.taskFiles,
      taskFiles,
    );
    const fromGrid = collectProcessingFocusIdentities(
      snapshot.gridRows,
      gridRows,
    );
    snapshot.taskFiles = taskFiles;
    snapshot.gridRows = gridRows;

    queueIngestFocusIdentities([...new Set([...fromTasks, ...fromGrid])]);
  }, [taskFiles, gridRows, queueIngestFocusIdentities]);

  const gridRowsSelectionKey = useMemo(
    () => buildGridRowsSelectionKey(gridRows),
    [gridRows],
  );

  useEffect(() => {
    tryFocusPendingIngestRows(gridRows);
  }, [gridRows, gridRowsSelectionKey, tryFocusPendingIngestRows]);

  const onKnowledgeGridReady = useCallback(() => {
    tryFocusPendingIngestRows(gridRows);
  }, [gridRows, tryFocusPendingIngestRows]);

  const onKnowledgeRowDataUpdated = useCallback(() => {
    tryFocusPendingIngestRows(gridRows);
  }, [gridRows, tryFocusPendingIngestRows]);

  return {
    gridRowsSelectionKey,
    onKnowledgeGridReady,
    onKnowledgeRowDataUpdated,
  };
}
