"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  File as FileIcon,
  Folder,
  FolderOpen,
  Loader2,
  PlugZap,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { File as SearchFile } from "@/app/api/queries/useGetSearchQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { DuplicateHandlingDialog } from "@/components/duplicate-handling-dialog";
import AwsIcon from "@/components/icons/aws-logo";
import GoogleDriveIcon from "@/components/icons/google-drive-logo";
import IBMCOSIcon from "@/components/icons/ibm-cos-icon";
import OneDriveIcon from "@/components/icons/one-drive-logo";
import SharePointIcon from "@/components/icons/share-point-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/auth-context";
import { useTask } from "@/contexts/task-context";
import {
  duplicateCheck,
  uploadFiles,
  uploadFile as uploadFileUtil,
} from "@/lib/upload-utils";
import { cn } from "@/lib/utils";

/**
 * Local / chat file picker + folder ingest filter — single source of truth.
 * Only extensions verified to ingest successfully in the Langflow pipeline.
 * If modified, update docs (docs/docs/core-components/ingestion.mdx).
 *
 * documents: txt, md, html, htm, adoc, asciidoc, asc, pdf, docx
 * spreadsheets: csv
 *
 * TODO: Re-add other MIME/extension groups (images, xlsx/xls/ppt, rtf/odt, etc.)
 * once ingestion is verified end-to-end in Langflow; keep this list and ingestion.mdx in sync.
 */
export const SUPPORTED_FILE_TYPES = {
  "text/plain": [".txt"],
  "text/markdown": [".md"],
  "text/html": [".html", ".htm"],
  "text/asciidoc": [".adoc", ".asciidoc", ".asc"],
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
    ".docx",
  ],
  "text/csv": [".csv"],
};

export const SUPPORTED_EXTENSIONS = Object.values(SUPPORTED_FILE_TYPES).flat();

const getFilenameVariants = (filename: string): string[] => {
  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex === -1) return [filename];

  const baseName = filename.slice(0, dotIndex);
  const extension = filename.slice(dotIndex).toLowerCase();

  if (extension === ".txt") return [filename, `${baseName}.md`];
  if (extension === ".md") return [filename, `${baseName}.txt`];

  return [filename];
};

const isDuplicateFile = async (file: File): Promise<boolean> => {
  const variants = getFilenameVariants(file.name);
  const checks = await Promise.all(
    variants.map(async (variantName) => {
      const variantFile =
        variantName === file.name
          ? file
          : new File([file], variantName, {
              type: file.type,
              lastModified: file.lastModified,
            });
      const checkData = await duplicateCheck(variantFile);
      return checkData.exists;
    }),
  );
  return checks.some(Boolean);
};

const FileIconWithColor = ({ className }: { className?: string }) => (
  <FileIcon className={cn(className, "text-muted-foreground")} />
);

const FolderIconWithColor = ({ className }: { className?: string }) => (
  <Folder className={cn(className, "text-muted-foreground")} />
);

export function KnowledgeDropdown() {
  const { isIbmAuthMode } = useAuth();
  const { addTask } = useTask();
  const { refetch: refetchTasks } = useGetTasksQuery();
  const queryClient = useQueryClient();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showFolderDialog, setShowFolderDialog] = useState(false);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [uploadBatchSize, setUploadBatchSize] = useState(25);
  const [folderPath, setFolderPath] = useState("");
  const [folderLoading, setFolderLoading] = useState(false);
  const [fileUploading, setFileUploading] = useState(false);
  const [isNavigatingToCloud, setIsNavigatingToCloud] = useState(false);
  const [ibmCosConfigured, setIbmCosConfigured] = useState(false);
  const [s3Configured, setS3Configured] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [duplicateFilename, setDuplicateFilename] = useState<string>("");
  const [pendingFolderUpload, setPendingFolderUpload] = useState<{
    allFiles: File[];
    nonDuplicateFiles: File[];
    duplicateCount: number;
    unsupportedCount: number;
  } | null>(null);
  const isFolderOverwriteConfirmedRef = useRef(false);
  const [cloudConnectors, setCloudConnectors] = useState<{
    [key: string]: {
      name: string;
      available: boolean;
      connected: boolean;
      hasToken: boolean;
    };
  }>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const resetDuplicateDialogState = () => {
    setPendingFolderUpload(null);
    setPendingFile(null);
    setDuplicateFilename("");
  };

  // Check AWS availability and cloud connectors on mount
  useEffect(() => {
    const checkAvailability = async () => {
      try {
        // Check upload batch size and bucket connector availability in parallel
        const [uploadOptionsRes, ibmCosRes, s3Res] = await Promise.all([
          fetch("/api/upload_options"),
          fetch("/api/connectors/ibm_cos/defaults"),
          fetch("/api/connectors/aws_s3/defaults"),
        ]);

        if (uploadOptionsRes.ok) {
          const uploadOptionsData = await uploadOptionsRes.json();
          if (
            typeof uploadOptionsData.upload_batch_size === "number" &&
            uploadOptionsData.upload_batch_size > 0
          ) {
            setUploadBatchSize(uploadOptionsData.upload_batch_size);
          }
        }

        if (ibmCosRes.ok) {
          const ibmCosData = await ibmCosRes.json();
          setIbmCosConfigured(
            Boolean(
              ibmCosData.connection_id ||
                ibmCosData.api_key_set ||
                ibmCosData.hmac_access_key_set,
            ),
          );
        }

        if (s3Res.ok) {
          const s3Data = await s3Res.json();
          setS3Configured(
            Boolean(s3Data.connection_id || s3Data.access_key_set),
          );
        }

        // Check cloud connectors
        const connectorsRes = await fetch("/api/connectors");
        if (connectorsRes.ok) {
          const connectorsResult = await connectorsRes.json();
          const cloudConnectorTypes = [
            "google_drive",
            "onedrive",
            "sharepoint",
          ];
          const connectorInfo: {
            [key: string]: {
              name: string;
              available: boolean;
              connected: boolean;
              hasToken: boolean;
            };
          } = {};

          for (const type of cloudConnectorTypes) {
            if (connectorsResult.connectors[type]) {
              connectorInfo[type] = {
                name: connectorsResult.connectors[type].name,
                available: connectorsResult.connectors[type].available,
                connected: false,
                hasToken: false,
              };

              // Check connection status
              try {
                const statusRes = await fetch(`/api/connectors/${type}/status`);
                if (statusRes.ok) {
                  const statusData = await statusRes.json();
                  const connections = statusData.connections || [];
                  const activeConnection = connections.find(
                    (conn: { is_active: boolean; connection_id: string }) =>
                      conn.is_active,
                  );
                  const isConnected = activeConnection !== undefined;

                  if (isConnected && activeConnection) {
                    connectorInfo[type].connected = true;

                    // Check token availability
                    try {
                      const tokenRes = await fetch(
                        `/api/connectors/${type}/token?connection_id=${activeConnection.connection_id}`,
                      );
                      if (tokenRes.ok) {
                        const tokenData = await tokenRes.json();
                        if (tokenData.access_token) {
                          connectorInfo[type].hasToken = true;
                        }
                      }
                    } catch {
                      // Token check failed
                    }
                  }
                }
              } catch {
                // Status check failed
              }
            }
          }

          setCloudConnectors(connectorInfo);
        }
      } catch (err) {
        console.error("Failed to check availability", err);
      }
    };
    checkAvailability();
  }, []);

  useEffect(() => {
    setMounted(true);
  }, []);

  const handleFileUpload = () => {
    fileInputRef.current?.click();
  };

  const resetFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = event.target.files;

    if (files && files.length > 0) {
      const file = files[0];

      // File selection will close dropdown automatically

      try {
        console.log("[Duplicate Check] Checking file:", file.name);
        const exists = await isDuplicateFile(file);

        if (exists) {
          console.log("[Duplicate Check] Duplicate detected, showing dialog");
          resetDuplicateDialogState();
          setPendingFile(file);
          setDuplicateFilename(file.name);
          setShowDuplicateDialog(true);
          resetFileInput();
          return;
        }

        // No duplicate, proceed with upload
        console.log("[Duplicate Check] No duplicate, proceeding with upload");
        await uploadFile(file, false);
      } catch (error) {
        console.error("[Duplicate Check] Exception:", error);
        toast.error("Failed to check for duplicates", {
          description: error instanceof Error ? error.message : "Unknown error",
        });
      }
    }

    resetFileInput();
  };

  const uploadFile = async (file: File, replace: boolean) => {
    setFileUploading(true);

    try {
      await uploadFileUtil(file, replace);
      refetchTasks();
    } catch (error) {
      // Dispatch event that chat context can listen to
      // This avoids circular dependency issues
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("ingestionFailed", {
            detail: { source: "knowledge-dropdown" },
          }),
        );
      }
      toast.error("Upload failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setFileUploading(false);
    }
  };

  const uploadFolderBatches = async (
    filesToUpload: File[],
    replace: boolean,
  ) => {
    const batches: File[][] = [];
    for (let i = 0; i < filesToUpload.length; i += uploadBatchSize) {
      batches.push(filesToUpload.slice(i, i + uploadBatchSize));
    }

    console.log(
      `[Folder Upload] Uploading ${filesToUpload.length} file(s) in ${batches.length} batch(es), replace=${replace}`,
    );

    for (const batch of batches) {
      try {
        const result = await uploadFiles(batch, replace);
        addTask(result.taskId);
      } catch (error) {
        console.error("[Folder Upload] Batch upload failed:", error);
        toast.error("Batch upload failed", {
          description: error instanceof Error ? error.message : "Unknown error",
        });
      }
    }

    refetchTasks();
  };

  const handleOverwriteFile = async () => {
    if (pendingFolderUpload) {
      isFolderOverwriteConfirmedRef.current = true;
      const { allFiles, duplicateCount, unsupportedCount } =
        pendingFolderUpload;
      await uploadFolderBatches(allFiles, true);
      const unsupportedMessage =
        unsupportedCount > 0 ? `, skipped ${unsupportedCount} unsupported` : "";
      toast.success(
        `Processed ${allFiles.length} file(s), including ${duplicateCount} overwrite(s)${unsupportedMessage}`,
      );
      resetDuplicateDialogState();
      return;
    }

    if (pendingFile) {
      // Remove the old file from all search query caches before overwriting
      queryClient.setQueriesData({ queryKey: ["search"] }, (oldData: []) => {
        if (!oldData) return oldData;
        // Filter out the file that's being overwritten
        return oldData.filter(
          (file: SearchFile) => file.filename !== pendingFile.name,
        );
      });

      await uploadFile(pendingFile, true);

      resetDuplicateDialogState();
    }
  };

  const handleDuplicateDialogOpenChange = async (open: boolean) => {
    if (!open && pendingFolderUpload) {
      if (isFolderOverwriteConfirmedRef.current) {
        isFolderOverwriteConfirmedRef.current = false;
      } else {
        const { nonDuplicateFiles, duplicateCount, unsupportedCount } =
          pendingFolderUpload;
        if (nonDuplicateFiles.length > 0) {
          await uploadFolderBatches(nonDuplicateFiles, false);
          const extraParts: string[] = [];
          if (duplicateCount > 0) {
            extraParts.push(`skipped ${duplicateCount} duplicate(s)`);
          }
          if (unsupportedCount > 0) {
            extraParts.push(`skipped ${unsupportedCount} unsupported`);
          }
          const suffix =
            extraParts.length > 0 ? `, ${extraParts.join(", ")}` : "";
          toast.success(
            `Processed ${nonDuplicateFiles.length} file(s)${suffix}`,
          );
        } else {
          toast.info(
            "Skipped duplicate files. All selected files were duplicates, so nothing was uploaded.",
          );
        }
      }

      resetDuplicateDialogState();
    }

    setShowDuplicateDialog(open);
  };

  const handleFolderSelect = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setFolderLoading(true);

    try {
      const fileList = Array.from(files);

      const filteredFiles = fileList.filter((file) => {
        const ext = file.name
          .substring(file.name.lastIndexOf("."))
          .toLowerCase();
        return SUPPORTED_EXTENSIONS.includes(ext);
      });
      const unsupportedCount = fileList.length - filteredFiles.length;

      if (filteredFiles.length === 0) {
        toast.error("No supported files found", {
          description:
            "Please select a folder containing supported document files (PDF, DOCX, PPTX, XLSX, CSV, HTML, images, etc.).",
        });
        return;
      }

      toast.info(`Processing ${filteredFiles.length} file(s)...`);

      // Create clean File objects (strip folder path from names)
      const cleanFiles = filteredFiles.map((originalFile) => {
        const fileName =
          originalFile.name.split("/").pop() || originalFile.name;
        return new File([originalFile], fileName, {
          type: originalFile.type,
          lastModified: originalFile.lastModified,
        });
      });

      // Check all files for duplicates in parallel
      const duplicateResults = await Promise.all(
        cleanFiles.map(async (file) => {
          try {
            const exists = await isDuplicateFile(file);
            return { file, isDuplicate: exists };
          } catch (error) {
            console.error(
              `[Folder Upload] Duplicate check failed for ${file.name}:`,
              error,
            );
            // On error, include the file (let the server handle it)
            return { file, isDuplicate: false };
          }
        }),
      );

      const nonDuplicateFiles = duplicateResults
        .filter((r) => !r.isDuplicate)
        .map((r) => r.file);
      const duplicateCount = duplicateResults.filter(
        (r) => r.isDuplicate,
      ).length;

      if (unsupportedCount > 0) {
        toast.error(
          `Unsupported files detected: only ${filteredFiles.length} of ${fileList.length} file(s) will be ingested.`,
          {
            description: `${unsupportedCount} file(s) have unsupported types and will be skipped.`,
          },
        );
      }

      if (duplicateCount > 0) {
        console.log(
          `[Folder Upload] Found ${duplicateCount} duplicate file(s), showing overwrite dialog`,
        );
        resetDuplicateDialogState();
        setPendingFolderUpload({
          allFiles: cleanFiles,
          nonDuplicateFiles,
          duplicateCount,
          unsupportedCount,
        });
        setShowDuplicateDialog(true);
        return;
      }

      if (nonDuplicateFiles.length === 0) {
        toast.info("All files already exist, nothing to upload.");
        return;
      }

      await uploadFolderBatches(nonDuplicateFiles, false);
      const unsupportedMessage =
        unsupportedCount > 0 ? `, skipped ${unsupportedCount} unsupported` : "";
      toast.success(
        `Successfully processed ${nonDuplicateFiles.length} file(s)${unsupportedMessage}`,
      );
    } catch (error) {
      console.error("Folder upload error:", error);
      toast.error("Folder upload failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setFolderLoading(false);
      if (folderInputRef.current) {
        folderInputRef.current.value = "";
      }
    }
  };

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return;

    setFolderLoading(true);
    setShowFolderDialog(false);

    try {
      const response = await fetch("/api/upload_path", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: folderPath }),
      });

      const result = await response.json();

      if (response.status === 201) {
        const taskId = result.task_id || result.id;

        if (!taskId) {
          throw new Error("No task ID received from server");
        }

        addTask(taskId);
        setFolderPath("");
        // Refetch tasks to show the new task
        refetchTasks();
      } else if (response.ok) {
        setFolderPath("");
        // Refetch tasks even for direct uploads in case tasks were created
        refetchTasks();
      } else {
        console.error("Folder upload failed:", result.error);
        if (response.status === 400) {
          toast.error("Upload failed", {
            description: result.error || "Bad request",
          });
        }
      }
    } catch (error) {
      console.error("Folder upload error:", error);
    } finally {
      setFolderLoading(false);
    }
  };

  // Icon mapping for cloud connectors
  const connectorIconMap = {
    google_drive: GoogleDriveIcon,
    onedrive: OneDriveIcon,
    sharepoint: SharePointIcon,
  };

  const cloudConnectorItems = Object.entries(cloudConnectors)
    .filter(([, info]) => info.available)
    .map(([type, info]) => ({
      label: info.name,
      icon: connectorIconMap[type as keyof typeof connectorIconMap] || PlugZap,
      onClick: async () => {
        if (info.connected && info.hasToken) {
          setIsNavigatingToCloud(true);
          try {
            router.push(`/upload/${type}`);
            // Keep loading state for a short time to show feedback
            setTimeout(() => setIsNavigatingToCloud(false), 1000);
          } catch {
            setIsNavigatingToCloud(false);
          }
        } else {
          router.push("/settings");
        }
      },
      disabled: !info.connected || !info.hasToken,
    }));

  const menuItems = [
    {
      label: "File",
      icon: FileIconWithColor,
      onClick: handleFileUpload,
    },
    {
      label: "Folder",
      icon: FolderIconWithColor,
      onClick: () => folderInputRef.current?.click(),
    },
    ...(isIbmAuthMode && s3Configured
      ? [
          {
            label: "Amazon S3",
            icon: AwsIcon,
            onClick: () => router.push("/upload/aws_s3"),
          },
        ]
      : []),
    ...(isIbmAuthMode && ibmCosConfigured
      ? [
          {
            label: "IBM Cloud Object Storage",
            icon: IBMCOSIcon,
            onClick: () => router.push("/upload/ibm_cos"),
          },
        ]
      : []),
    ...cloudConnectorItems,
  ];

  // Comprehensive loading state
  const isLoading = fileUploading || folderLoading || isNavigatingToCloud;

  if (!mounted) {
    return (
      <Button disabled variant="outline" className="opacity-50">
        <span>Add Knowledge</span>
        <ChevronDown className="h-4 w-4 ml-2" />
      </Button>
    );
  }

  return (
    <>
      <DropdownMenu onOpenChange={setIsMenuOpen}>
        <DropdownMenuTrigger asChild>
          <Button disabled={isLoading}>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>
              {isLoading
                ? fileUploading
                  ? "Uploading..."
                  : folderLoading
                    ? "Processing Folder..."
                    : isNavigatingToCloud
                      ? "Loading..."
                      : "Processing..."
                : "Add Knowledge"}
            </span>
            {!isLoading && (
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform duration-200",
                  isMenuOpen && "rotate-180",
                )}
              />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {menuItems.map((item, index) => (
            <DropdownMenuItem
              key={`${item.label}-${index}`}
              onClick={item.onClick}
              disabled={"disabled" in item ? item.disabled : false}
            >
              <item.icon className="mr-2 h-4 w-4" />
              {item.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileChange}
        className="hidden"
        accept={SUPPORTED_EXTENSIONS.join(",")}
      />

      <input
        ref={folderInputRef}
        type="file"
        // @ts-ignore - webkitdirectory is not in TypeScript types but is widely supported
        webkitdirectory=""
        // @ts-ignore
        directory=""
        multiple
        onChange={handleFolderSelect}
        className="hidden"
      />

      {/* Process Folder Dialog */}
      <Dialog open={showFolderDialog} onOpenChange={setShowFolderDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              Process Folder
            </DialogTitle>
            <DialogDescription>
              Process all documents in a folder path
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="folder-path">Folder Path</Label>
              <Input
                id="folder-path"
                type="text"
                placeholder="/path/to/documents"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setShowFolderDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleFolderUpload}
                disabled={!folderPath.trim() || folderLoading}
              >
                {folderLoading ? "Processing..." : "Process Folder"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Duplicate Handling Dialog */}
      <DuplicateHandlingDialog
        open={showDuplicateDialog}
        onOpenChange={handleDuplicateDialogOpenChange}
        onOverwrite={handleOverwriteFile}
        isLoading={fileUploading || folderLoading}
        duplicateLabel={duplicateFilename}
        duplicateCount={pendingFolderUpload?.duplicateCount}
      />
    </>
  );
}
