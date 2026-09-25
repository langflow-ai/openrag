import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import type { WebsiteSource } from "./types";

export function useWebsiteSource(sourceId: string) {
  const [source, setSource] = useState<WebsiteSource | null>(null);
  const [sourceLoading, setSourceLoading] = useState(true);

  const reload = useCallback(async () => {
    setSourceLoading(true);
    try {
      const response = await fetch(`/api/connectors/url/sources/${sourceId}`);
      if (!response.ok) {
        throw new Error("Website source was not found");
      }
      setSource(await response.json());
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not load website pages",
      );
    } finally {
      setSourceLoading(false);
    }
  }, [sourceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { source, sourceLoading, reload };
}
