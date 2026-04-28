"use client";

import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { IngestSettings } from "@/components/cloud-picker/types";
import { useAuth } from "@/contexts/auth-context";
import { knowledgeToIngestSettings } from "@/lib/ingest-settings-knowledge";

/**
 * Ingest form state: hydrate once from GET /api/settings `knowledge`, then session-owned.
 */
export function useSessionIngestSettings(): readonly [
  IngestSettings,
  Dispatch<SetStateAction<IngestSettings>>,
] {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const { data, isSuccess } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const [ingestSettings, setIngestSettings] = useState<IngestSettings>(() =>
    knowledgeToIngestSettings(undefined),
  );
  const hydrated = useRef(false);

  useEffect(() => {
    if (!isSuccess || !data || hydrated.current) return;
    setIngestSettings(knowledgeToIngestSettings(data.knowledge));
    hydrated.current = true;
  }, [isSuccess, data]);

  return [ingestSettings, setIngestSettings] as const;
}
