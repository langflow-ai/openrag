"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Cloud,
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
import { useTask } from "@/contexts/task-context";
import {
  duplicateCheck,
  uploadFile as uploadFileUtil,
  uploadFiles,
} from "@/lib/upload-utils";
import { cn } from "@/lib/utils";

// Supported file extensions - single source of truth
// If modified, please also update the list in the documentation (openrag/docs/docs)
export const SUPPORTED_FILE_TYPES = {
  "image/*": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"],
  "application/pdf": [".pdf"],
  "application/msword": [".doc"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.ms-powerpoint": [".ppt"],
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
  "application/vnd.ms-excel": [".xls"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "text/csv": [".csv"],
  "text/plain": [".txt"],
  "text/markdown": [".md"],
  "text/html": [".html", ".htm"],
  "application/rtf": [".rtf"],
  "application/vnd.oasis.opendocument.text": [".odt"],
  "text/asciidoc": [".adoc", ".asciidoc"]
}

export const SUPPORTED_EXTENSIONS = Object.values(SUPPORTED_FILE_TYPES).flat();

export function KnowledgeDropdown() {
  const { addTask } = useTask();
  const { refetch: refetchTasks } = useGetTasksQuery();
  const queryClient = useQueryClient();
  const router = useRouter();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showFolderDialog, setShowFolderDialog] = useState(false);
  const [showS3Dialog, setShowS3Dialog] = useState(false);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [awsEnabled, setAwsEnabled] = useState(false);
  const [uploadBatchSize, setUploadBatchSize] = useState(25);
  const [folderPath, setFolderPath] = useState("");
  const [bucketUrl, setBucketUrl] = useState("s3://");
  const [folderLoading, setFolderLoading] = useState(false);
  const [s3Loading, setS3Loading] = useState(false);
  const [fileUploading, setFileUploading] = useState(false);
  const [isNavigatingToCloud, setIsNavigatingToCloud] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [duplicateFilename, setDuplicateFilename] = useState<string>("");
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

  // Check AWS availability and cloud connectors on mount
  useEffect(() => {
    const checkAvailability = async () => {
      try {
        // Check AWS and upload batch size
        const awsRes = await fetch("/api/upload_options");
        if (awsRes.ok) {
          const awsData = await awsRes.json();
          setAwsEnabled(Boolean(awsData.aws));
          if (
            typeof awsData.upload_batch_size === "number" &&
            awsData.upload_batch_size > 0
          ) {
            setUploadBatchSize(awsData.upload_batch_size);
          }
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
        const checkData = await duplicateCheck(file);
        console.log("[Duplicate Check] Result:", checkData);

        if (checkData.exists) {
          console.log("[Duplicate Check] Duplicate detected, showing dialog");
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

  const handleOverwriteFile = async () => {
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

      setPendingFile(null);
      setDuplicateFilename("");
    }
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
            const checkData = await duplicateCheck(file);
            return { file, isDuplicate: checkData.exists };
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
      const skippedCount = duplicateResults.filter((r) => r.isDuplicate).length;

      if (skippedCount > 0) {
        console.log(
          `[Folder Upload] Skipping ${skippedCount} duplicate file(s)`,
        );
      }

      if (nonDuplicateFiles.length === 0) {
        toast.info("All files already exist, nothing to upload.");
        return;
      }

      // Chunk non-duplicate files into batches
      const batches: File[][] = [];
      for (let i = 0; i < nonDuplicateFiles.length; i += uploadBatchSize) {
        batches.push(nonDuplicateFiles.slice(i, i + uploadBatchSize));
      }

      console.log(
        `[Folder Upload] Uploading ${nonDuplicateFiles.length} file(s) in ${batches.length} batch(es)`,
      );

      // Upload each batch as a single task
      for (const batch of batches) {
        try {
          const result = await uploadFiles(batch, false);
          addTask(result.taskId);
          console.log(
            `[Folder Upload] Batch uploaded: taskId=${result.taskId}, files=${result.fileCount}`,
          );
        } catch (error) {
          console.error("[Folder Upload] Batch upload failed:", error);
          toast.error("Batch upload failed", {
            description:
              error instanceof Error ? error.message : "Unknown error",
          });
        }
      }

      refetchTasks();

      const processedCount = nonDuplicateFiles.length;
      const message =
        skippedCount > 0
          ? `Processed ${processedCount} file(s), skipped ${skippedCount} duplicate(s)`
          : `Successfully processed ${processedCount} file(s)`;
      toast.success(message);
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

  const handleS3Upload = async () => {
    if (!bucketUrl.trim()) return;

    setS3Loading(true);
    setShowS3Dialog(false);

    try {
      const response = await fetch("/api/upload_bucket", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ s3_url: bucketUrl }),
      });

      const result = await response.json();

      if (response.status === 201) {
        const taskId = result.task_id || result.id;

        if (!taskId) {
          throw new Error("No task ID received from server");
        }

        addTask(taskId);
        setBucketUrl("s3://");
        // Refetch tasks to show the new task
        refetchTasks();
      } else {
        console.error("S3 upload failed:", result.error);
        if (response.status === 400) {
          toast.error("Upload failed", {
            description: result.error || "Bad request",
          });
        }
      }
    } catch (error) {
      console.error("S3 upload error:", error);
    } finally {
      setS3Loading(false);
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
      icon: ({ className }: { className?: string }) => (
        <FileIcon className={cn(className, "text-muted-foreground")} />
      ),
      onClick: handleFileUpload,
    },
    {
      label: "Folder",
      icon: ({ className }: { className?: string }) => (
        <Folder className={cn(className, "text-muted-foreground")} />
      ),
      onClick: () => folderInputRef.current?.click(),
    },
    ...(awsEnabled
      ? [
          {
            label: "Amazon S3",
            icon: AwsIcon,
            onClick: () => setShowS3Dialog(true),
          },
        ]
      : []),
    ...cloudConnectorItems,
  ];

  // Comprehensive loading state
  const isLoading =
    fileUploading || folderLoading || s3Loading || isNavigatingToCloud;

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
                    : s3Loading
                      ? "Processing S3..."
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

      {/* Process S3 Bucket Dialog */}
      <Dialog open={showS3Dialog} onOpenChange={setShowS3Dialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Cloud className="h-5 w-5" />
              Process S3 Bucket
            </DialogTitle>
            <DialogDescription>
              Process all documents from an S3 bucket. AWS credentials must be
              configured.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="bucket-url">S3 URL</Label>
              <Input
                id="bucket-url"
                type="text"
                placeholder="s3://bucket/path"
                value={bucketUrl}
                onChange={(e) => setBucketUrl(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowS3Dialog(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleS3Upload}
                disabled={!bucketUrl.trim() || s3Loading}
              >
                {s3Loading ? "Processing..." : "Process Bucket"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Duplicate Handling Dialog */}
      <DuplicateHandlingDialog
        open={showDuplicateDialog}
        onOpenChange={setShowDuplicateDialog}
        onOverwrite={handleOverwriteFile}
        isLoading={fileUploading}
      />
    </>
  );
}
