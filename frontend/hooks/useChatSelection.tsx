import { useCallback, useState } from "react";

export function useChatSelection({
  onChange,
}: {
  onChange?: (isSelecting: boolean) => void;
} = {}) {
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const enter = useCallback(() => {
    setIsSelecting(true);
    onChange?.(true);
  }, []);
  const clear = useCallback(() => setSelectedIds(new Set()), []);
  const exit = useCallback(() => {
    setIsSelecting(false);
    setSelectedIds(new Set());
    onChange?.(false);
  }, []);
  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);

      return next;
    });
  }, []);

  const isAllSelected = useCallback(
    (ids: string[]) => ids.length > 0 && ids.every((id) => selectedIds.has(id)),
    [selectedIds],
  );
  const toggleAll = useCallback((ids: string[]) => {
    setSelectedIds((prev) => {
      const allSelected = ids.length > 0 && ids.every((id) => prev.has(id));

      return allSelected ? new Set() : new Set(ids);
    });
  }, []);

  return {
    isSelecting,
    selectedIds,
    count: selectedIds.size,
    enter,
    exit,
    toggle,
    toggleAll,
    clear,
    isAllSelected,
  };
}
