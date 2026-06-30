/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

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
