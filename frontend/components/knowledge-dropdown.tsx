"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Cloud,
  File,
  Folder,
  FolderOpen,
  Loader2,
  PlugZap,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { DuplicateHandlingDialog } from "@/components/duplicate-handling-dialog";
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
import { cn } from "@/lib/utils";
import {
  duplicateCheck,
  uploadFile as uploadFileUtil,
} from "@/lib/upload-utils";
import type { File as SearchFile } from "@/src/app/api/queries/useGetSearchQuery";
import GoogleDriveIcon from "@/app/settings/icons/google-drive-icon";
import OneDriveIcon from "@/app/settings/icons/one-drive-icon";
import SharePointIcon from "@/app/settings/icons/share-point-icon";
import AwsIcon from "@/app/settings/icons/aws-icon";

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
        <File className={cn(className, "text-muted-foreground")} />
      ),
      onClick: handleFileUpload,
    },
    {
      label: "Folder",
      icon: ({ className }: { className?: string }) => (
        <Folder className={cn(className, "text-muted-foreground")} />
      ),
      onClick: () => setShowFolderDialog(true),
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
        accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
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
