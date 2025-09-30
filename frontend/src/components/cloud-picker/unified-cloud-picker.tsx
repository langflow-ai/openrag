"use client";

import { useState, useEffect } from "react";
import {
  UnifiedCloudPickerProps,
  CloudFile,
  IngestSettings as IngestSettingsType,
} from "./types";
import { PickerHeader } from "./picker-header";
import { FileList } from "./file-list";
import { IngestSettings } from "./ingest-settings";
import { createProviderHandler } from "./provider-handlers";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";

export const UnifiedCloudPicker = ({
  provider,
  onFileSelected,
  selectedFiles = [],
  isAuthenticated,
  accessToken,
  onPickerStateChange,
  clientId,
  baseUrl,
  onSettingsChange,
}: UnifiedCloudPickerProps) => {
  const { isNoAuthMode } = useAuth();
  const [isPickerLoaded, setIsPickerLoaded] = useState(false);
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [isIngestSettingsOpen, setIsIngestSettingsOpen] = useState(true);
  const [isLoadingBaseUrl, setIsLoadingBaseUrl] = useState(false);
  const [autoBaseUrl, setAutoBaseUrl] = useState<string | undefined>(undefined);

  // Fetch settings using React Query
  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  // Settings state with defaults
  const [ingestSettings, setIngestSettings] = useState<IngestSettingsType>({
    chunkSize: DEFAULT_KNOWLEDGE_SETTINGS.chunk_size,
    chunkOverlap: DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap,
    ocr: DEFAULT_KNOWLEDGE_SETTINGS.ocr,
    pictureDescriptions: DEFAULT_KNOWLEDGE_SETTINGS.picture_descriptions,
    embeddingModel: DEFAULT_KNOWLEDGE_SETTINGS.embedding_model,
    tableStructure: DEFAULT_KNOWLEDGE_SETTINGS.table_structure,
  });

  // Sync chunk size with backend settings
  useEffect(() => {
    const chunkSize = settings.knowledge?.chunk_size;
    if (chunkSize !== undefined) {
      setIngestSettings(prev => ({
        ...prev,
        chunkSize: chunkSize,
      }));
    }
  }, [settings.knowledge]);

  // Sync chunk overlap with backend settings
  useEffect(() => {
    const chunkOverlap = settings.knowledge?.chunk_overlap;
    if (chunkOverlap !== undefined) {
      setIngestSettings(prev => ({
        ...prev,
        chunkOverlap: chunkOverlap,
      }));
    }
  }, [settings.knowledge]);

  // Sync processing mode (doclingPresets) with OCR and picture descriptions
  useEffect(() => {
    const mode = settings.knowledge?.doclingPresets;
    if (mode) {
      setIngestSettings(prev => ({
        ...prev,
        ocr: mode === "ocr" || mode === "picture_description" || mode === "VLM",
        pictureDescriptions: mode === "picture_description",
      }));
    }
  }, [settings.knowledge]);

  // Sync embedding model with backend settings
  useEffect(() => {
    const embeddingModel = settings.knowledge?.embedding_model;
    if (embeddingModel) {
      setIngestSettings(prev => ({
        ...prev,
        embeddingModel: embeddingModel,
      }));
    }
  }, [settings.knowledge]);

  // Handle settings changes and notify parent
  const handleSettingsChange = (newSettings: IngestSettingsType) => {
    setIngestSettings(newSettings);
    onSettingsChange?.(newSettings);
  };

  const effectiveBaseUrl = baseUrl || autoBaseUrl;

  // Auto-detect base URL for OneDrive personal accounts
  useEffect(() => {
    if (
      (provider === "onedrive" || provider === "sharepoint") &&
      !baseUrl &&
      accessToken &&
      !autoBaseUrl
    ) {
      const getBaseUrl = async () => {
        setIsLoadingBaseUrl(true);
        try {
          setAutoBaseUrl("https://onedrive.live.com/picker");
        } catch (error) {
          console.error("Auto-detect baseUrl failed:", error);
        } finally {
          setIsLoadingBaseUrl(false);
        }
      };

      getBaseUrl();
    }
  }, [accessToken, baseUrl, autoBaseUrl, provider]);

  // Load picker API
  useEffect(() => {
    if (!accessToken || !isAuthenticated) return;

    const loadApi = async () => {
      try {
        const handler = createProviderHandler(
          provider,
          accessToken,
          onPickerStateChange,
          clientId,
          effectiveBaseUrl
        );
        const loaded = await handler.loadPickerApi();
        setIsPickerLoaded(loaded);
      } catch (error) {
        console.error("Failed to create provider handler:", error);
        setIsPickerLoaded(false);
      }
    };

    loadApi();
  }, [
    accessToken,
    isAuthenticated,
    provider,
    clientId,
    effectiveBaseUrl,
    onPickerStateChange,
  ]);

  const handleAddFiles = () => {
    if (!isPickerLoaded || !accessToken) {
      return;
    }

    if ((provider === "onedrive" || provider === "sharepoint") && !clientId) {
      console.error("Client ID required for OneDrive/SharePoint");
      return;
    }

    try {
      setIsPickerOpen(true);
      onPickerStateChange?.(true);

      const handler = createProviderHandler(
        provider,
        accessToken,
        isOpen => {
          setIsPickerOpen(isOpen);
          onPickerStateChange?.(isOpen);
        },
        clientId,
        effectiveBaseUrl
      );

      handler.openPicker((files: CloudFile[]) => {
        // Merge new files with existing ones, avoiding duplicates
        const existingIds = new Set(selectedFiles.map(f => f.id));
        const newFiles = files.filter(f => !existingIds.has(f.id));
        onFileSelected([...selectedFiles, ...newFiles]);
      });
    } catch (error) {
      console.error("Error opening picker:", error);
      setIsPickerOpen(false);
      onPickerStateChange?.(false);
    }
  };

  const handleRemoveFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId);
    onFileSelected(updatedFiles);
  };

  const handleClearAll = () => {
    onFileSelected([]);
  };

  if (isLoadingBaseUrl) {
    return (
      <div className="text-sm text-muted-foreground p-4 bg-muted/20 rounded-md">
        Loading...
      </div>
    );
  }

  if (
    (provider === "onedrive" || provider === "sharepoint") &&
    !clientId &&
    isAuthenticated
  ) {
    return (
      <div className="text-sm text-muted-foreground p-4 bg-muted/20 rounded-md">
        Configuration required: Client ID missing for{" "}
        {provider === "sharepoint" ? "SharePoint" : "OneDrive"}.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PickerHeader
        provider={provider}
        onAddFiles={handleAddFiles}
        isPickerLoaded={isPickerLoaded}
        isPickerOpen={isPickerOpen}
        accessToken={accessToken}
        isAuthenticated={isAuthenticated}
      />

      <FileList
        files={selectedFiles}
        onClearAll={handleClearAll}
        onRemoveFile={handleRemoveFile}
      />

      <IngestSettings
        isOpen={isIngestSettingsOpen}
        onOpenChange={setIsIngestSettingsOpen}
        settings={ingestSettings}
        onSettingsChange={handleSettingsChange}
      />
    </div>
  );
};
