"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Plus } from "lucide-react";
import { CloudProvider } from "./types";

interface PickerHeaderProps {
  provider: CloudProvider;
  onAddFiles: () => void;
  isPickerLoaded: boolean;
  isPickerOpen: boolean;
  accessToken?: string;
  isAuthenticated: boolean;
}

const getProviderName = (provider: CloudProvider): string => {
  switch (provider) {
    case "google_drive":
      return "Google Drive";
    case "onedrive":
      return "OneDrive";
    case "sharepoint":
      return "SharePoint";
    default:
      return "Cloud Storage";
  }
};

export const PickerHeader = ({
  provider,
  onAddFiles,
  isPickerLoaded,
  isPickerOpen,
  accessToken,
  isAuthenticated,
}: PickerHeaderProps) => {
  if (!isAuthenticated) {
    return (
      <div className="text-sm text-muted-foreground p-4 bg-muted/20 rounded-md">
        Please connect to {getProviderName(provider)} first to select specific
        files or folders.
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col items-center text-center py-8">
        <p className="text-sm text-primary mb-4">
          Select files or folders from {getProviderName(provider)} to ingest.
        </p>
        <Button
          onClick={onAddFiles}
          disabled={!isPickerLoaded || isPickerOpen || !accessToken}
          className="bg-foreground text-background hover:bg-foreground/90 font-semibold"
        >
          <Plus className="h-4 w-4" />
          {isPickerOpen ? "Opening picker..." : "Add files or folders"}
        </Button>
      </CardContent>
    </Card>
  );
};
