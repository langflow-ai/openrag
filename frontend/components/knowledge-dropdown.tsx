"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Cloud,
  FolderOpen,
  Loader2,
  PlugZap,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useUploadIngest } from "@/app/api/mutations/useUploadIngest";
import { useUploadPath } from "@/app/api/mutations/useUploadPath";
import { useUploadBucket } from "@/app/api/mutations/useUploadBucket";
import { DuplicateHandlingDialog } from "@/components/duplicate-handling-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTask } from "@/contexts/task-context";
import { cn } from "@/lib/utils";
import type { File as SearchFile } from "@/src/app/api/queries/useGetSearchQuery";

export function KnowledgeDropdown() {
  const { addTask } = useTask();
  const queryClient = useQueryClient();
  const uploadIngestMutation = useUploadIngest();
  const uploadPathMutation = useUploadPath();
  const uploadBucketMutation = useUploadBucket();
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [showFolderDialog, setShowFolderDialog] = useState(false);
  const [showS3Dialog, setShowS3Dialog] = useState(false);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [awsEnabled, setAwsEnabled] = useState(false);
  const [folderPath, setFolderPath] = useState("/app/documents/");
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
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Check AWS availability and cloud connectors on mount
  useEffect(() => {
    const checkAvailability = async () => {
      try {
        // Check AWS
        const awsRes = await fetch("/api/upload_options");
        if (awsRes.ok) {
          const awsData = await awsRes.json();
          setAwsEnabled(Boolean(awsData.aws));
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
                      conn.is_active
                  );
                  const isConnected = activeConnection !== undefined;

                  if (isConnected && activeConnection) {
                    connectorInfo[type].connected = true;

                    // Check token availability
                    try {
                      const tokenRes = await fetch(
                        `/api/connectors/${type}/token?connection_id=${activeConnection.connection_id}`
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

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  const handleFileUpload = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const file = files[0];

      // Close dropdown immediately after file selection
      setIsOpen(false);

      try {
        // Check if filename already exists (using ORIGINAL filename)
        console.log("[Duplicate Check] Checking file:", file.name);
        const checkResponse = await fetch(
          `/api/documents/check-filename?filename=${encodeURIComponent(
            file.name
          )}`
        );

        console.log("[Duplicate Check] Response status:", checkResponse.status);

        if (!checkResponse.ok) {
          const errorText = await checkResponse.text();
          console.error("[Duplicate Check] Error response:", errorText);
          throw new Error(
            `Failed to check duplicates: ${checkResponse.statusText}`
          );
        }

        const checkData = await checkResponse.json();
        console.log("[Duplicate Check] Result:", checkData);

        if (checkData.exists) {
          // Show duplicate handling dialog
          console.log("[Duplicate Check] Duplicate detected, showing dialog");
          setPendingFile(file);
          setDuplicateFilename(file.name);
          setShowDuplicateDialog(true);
          // Reset file input
          if (fileInputRef.current) {
            fileInputRef.current.value = "";
          }
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

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const uploadFile = async (file: File, replace: boolean) => {
    setFileUploading(true);

    // Trigger the same file upload event as the chat page
    window.dispatchEvent(
      new CustomEvent("fileUploadStart", {
        detail: { filename: file.name },
      })
    );

    try {
      const result = await uploadIngestMutation.mutateAsync({
        file,
        replaceDuplicates: replace,
      });

      // Extract results from the response - handle both unified and simple formats
      const fileId =
        result?.upload?.id ||
        result?.id ||
        result?.task_id;
      const filePath =
        result?.upload?.path || result?.path || "uploaded";
      const runJson = result?.ingestion;
      const deleteResult = result?.deletion;
      console.log("c", result);

      // Notify UI
      window.dispatchEvent(
        new CustomEvent("fileUploaded", {
          detail: {
            file: file,
            result: {
              file_id: fileId,
              file_path: filePath,
              run: runJson,
              deletion: deleteResult,
              unified: true,
            },
          },
        })
      );
    } catch (error) {
      window.dispatchEvent(
        new CustomEvent("fileUploadError", {
          detail: {
            filename: file.name,
            error: error instanceof Error ? error.message : "Upload failed",
          },
        })
      );
    } finally {
      window.dispatchEvent(new CustomEvent("fileUploadComplete"));
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
          (file: SearchFile) => file.filename !== pendingFile.name
        );
      });

      await uploadFile(pendingFile, true);
      setPendingFile(null);
      setDuplicateFilename("");
    }
  };

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return;

    setFolderLoading(true);
    setShowFolderDialog(false);

    try {
      const result = await uploadPathMutation.mutateAsync({
        path: folderPath,
      });

      if (result.status === 201) {
        const taskId = result.task_id || result.id;
        if (taskId) {
          addTask(taskId);
        }
      }

      setFolderPath("");
    } catch (error) {
      console.error("Folder upload error:", error);
      toast.error("Upload failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setFolderLoading(false);
    }
  };

  const handleS3Upload = async () => {
    if (!bucketUrl.trim()) return;

    setS3Loading(true);
    setShowS3Dialog(false);

    try {
      const result = await uploadBucketMutation.mutateAsync({
        s3Url: bucketUrl,
      });

      if (result.status === 201) {
        const taskId = result.task_id || result.id;
        if (taskId) {
          addTask(taskId);
        }
      }

      setBucketUrl("s3://");
    } catch (error) {
      console.error("S3 upload error:", error);
      toast.error("Upload failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setS3Loading(false);
    }
  };

  const cloudConnectorItems = Object.entries(cloudConnectors)
    .filter(([, info]) => info.available)
    .map(([type, info]) => ({
      label: info.name,
      icon: PlugZap,
      onClick: async () => {
        setIsOpen(false);
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
      tooltip: !info.connected
        ? `Connect ${info.name} in Settings first`
        : !info.hasToken
        ? `Reconnect ${info.name} - access token required`
        : undefined,
    }));

  const menuItems = [
    {
      label: "Add File",
      icon: Upload,
      onClick: handleFileUpload,
    },
    {
      label: "Process Folder",
      icon: FolderOpen,
      onClick: () => {
        setIsOpen(false);
        setShowFolderDialog(true);
      },
    },
    ...(awsEnabled
      ? [
          {
            label: "Process S3 Bucket",
            icon: Cloud,
            onClick: () => {
              setIsOpen(false);
              setShowS3Dialog(true);
            },
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
      <div ref={dropdownRef} className="relative">
        <Button
          type="button"
          onClick={() => !isLoading && setIsOpen(!isOpen)}
          disabled={isLoading}
        >
          <>
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
                  "h-4 w-4 transition-transform",
                  isOpen && "rotate-180"
                )}
              />
            )}
          </>
        </Button>

        {isOpen && !isLoading && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-md z-50">
            <div className="py-1">
              {menuItems.map((item, index) => (
                <button
                  key={`${item.label}-${index}`}
                  type="button"
                  onClick={item.onClick}
                  disabled={"disabled" in item ? item.disabled : false}
                  title={"tooltip" in item ? item.tooltip : undefined}
                  className={cn(
                    "w-full px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                    "disabled" in item &&
                      item.disabled &&
                      "opacity-50 cursor-not-allowed hover:bg-transparent hover:text-current"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          onChange={handleFileChange}
          className="hidden"
          accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
        />
      </div>

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
                onChange={e => setFolderPath(e.target.value)}
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
                onChange={e => setBucketUrl(e.target.value)}
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
