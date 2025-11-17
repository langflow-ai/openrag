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

export const UnifiedCloudPicker = ({
  provider,
  onFileSelected,
  selectedFiles = [],
  isAuthenticated,
  isIngesting,
  accessToken,
  onPickerStateChange,
  clientId,
  baseUrl,
  onSettingsChange,
}: UnifiedCloudPickerProps) => {
  const [isPickerLoaded, setIsPickerLoaded] = useState(false);
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [isIngestSettingsOpen, setIsIngestSettingsOpen] = useState(false);
  const [isLoadingBaseUrl, setIsLoadingBaseUrl] = useState(false);
  const [autoBaseUrl, setAutoBaseUrl] = useState<string | undefined>(undefined);

  // Settings state with defaults
  const [ingestSettings, setIngestSettings] = useState<IngestSettingsType>({
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: "text-embedding-3-small",
  });

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
          effectiveBaseUrl,
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
        (isOpen) => {
          setIsPickerOpen(isOpen);
          onPickerStateChange?.(isOpen);
        },
        clientId,
        effectiveBaseUrl,
      );

      handler.openPicker((files: CloudFile[]) => {
        // Merge new files with existing ones, avoiding duplicates
        const existingIds = new Set(selectedFiles.map((f) => f.id));
        const newFiles = files.filter((f) => !existingIds.has(f.id));
        onFileSelected([...selectedFiles, ...newFiles]);
      });
    } catch (error) {
      console.error("Error opening picker:", error);
      setIsPickerOpen(false);
      onPickerStateChange?.(false);
    }
  };

  const handleRemoveFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter((file) => file.id !== fileId);
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
    <div>
      <div className="mb-6">
        <PickerHeader
          provider={provider}
          onAddFiles={handleAddFiles}
          isPickerLoaded={isPickerLoaded}
          isPickerOpen={isPickerOpen}
          accessToken={accessToken}
          isAuthenticated={isAuthenticated}
        />
      </div>

      <FileList
        provider={provider}
        files={selectedFiles}
        onClearAll={handleClearAll}
        onRemoveFile={handleRemoveFile}
        shouldDisableActions={isIngesting}
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
