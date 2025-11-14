"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CloudConnectorsDialog } from "@/components/cloud-connectors-dialog";
import { Cloud, ChevronDown } from "lucide-react";

interface GoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  webViewLink?: string;
  iconLink?: string;
}

interface OneDriveFile {
  id: string;
  name: string;
  mimeType?: string;
  webUrl?: string;
  driveItem?: {
    file?: { mimeType: string };
    folder?: unknown;
  };
}

interface CloudConnectorsDropdownProps {
  onFileSelected?: (
    files: GoogleDriveFile[] | OneDriveFile[],
    connectorType: string,
  ) => void;
  buttonText?: string;
  variant?:
    | "default"
    | "outline"
    | "secondary"
    | "ghost"
    | "link"
    | "destructive";
  size?: "default" | "sm" | "lg" | "icon";
}

export function CloudConnectorsDropdown({
  onFileSelected,
  buttonText = "Cloud Files",
  variant = "outline",
  size = "default",
}: CloudConnectorsDropdownProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  const handleOpenDialog = () => {
    setIsDialogOpen(true);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant={variant} size={size}>
            <Cloud className="mr-2 h-4 w-4" />
            {buttonText}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuItem
            onClick={handleOpenDialog}
            className="cursor-pointer"
          >
            <Cloud className="mr-2 h-4 w-4" />
            Select Cloud Files
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <CloudConnectorsDialog
        isOpen={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        onFileSelected={onFileSelected}
      />
    </>
  );
}
