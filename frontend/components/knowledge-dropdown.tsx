"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Cloud,
  FolderOpen,
  PlugZap,
  Plus,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
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

interface KnowledgeDropdownProps {
  active?: boolean;
  variant?: "navigation" | "button";
}

export function KnowledgeDropdown({
  active,
  variant = "navigation",
}: KnowledgeDropdownProps) {
  const { addTask } = useTask();
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [showFolderDialog, setShowFolderDialog] = useState(false);
  const [showS3Dialog, setShowS3Dialog] = useState(false);
  const [awsEnabled, setAwsEnabled] = useState(false);
  const [folderPath, setFolderPath] = useState("/app/documents/");
  const [bucketUrl, setBucketUrl] = useState("s3://");
  const [folderLoading, setFolderLoading] = useState(false);
  const [s3Loading, setS3Loading] = useState(false);
  const [fileUploading, setFileUploading] = useState(false);
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

  const queryClient = useQueryClient();

  const refetchSearch = () => {
    queryClient.invalidateQueries({ queryKey: ["search"] });
  };

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
      // Close dropdown and disable button immediately after file selection
      setIsOpen(false);
      setFileUploading(true);

      // Trigger the same file upload event as the chat page
      window.dispatchEvent(
        new CustomEvent("fileUploadStart", {
          detail: { filename: files[0].name },
        }),
      );

      try {
        const formData = new FormData();
        formData.append("file", files[0]);

        const uploadIngestRes = await fetch('/api/upload', {
          body: formData,
        });
        const uploadIngestJson = await uploadIngestRes.json();
        if (!uploadIngestRes.ok) {
          throw new Error(
            uploadIngestJson?.error || "Upload and ingest failed",
          );
        }

        // Extract results from the unified response
        const fileId = uploadIngestJson?.upload?.id;
        const filePath = uploadIngestJson?.upload?.path;
        const runJson = uploadIngestJson?.ingestion;
        const deleteResult = uploadIngestJson?.deletion;

        if (!fileId || !filePath) {
          throw new Error("Upload successful but no file id/path returned");
        }

        // Log deletion status if provided
        if (deleteResult) {
          if (deleteResult.status === "deleted") {
            console.log(
              "File successfully cleaned up from Langflow:",
              deleteResult.file_id,
            );
          } else if (deleteResult.status === "delete_failed") {
            console.warn(
              "Failed to cleanup file from Langflow:",
              deleteResult.error,
            );
          }
        }

        // Notify UI
        window.dispatchEvent(
          new CustomEvent("fileUploaded", {
            detail: {
              file: files[0],
              result: {
                file_id: fileId,
                file_path: filePath,
                run: runJson,
                deletion: deleteResult,
                unified: true,
              },
            },
          }),
        );
        // Trigger search refresh after successful ingestion
        window.dispatchEvent(new CustomEvent("knowledgeUpdated"));
      } catch (error) {
        window.dispatchEvent(
          new CustomEvent("fileUploadError", {
            detail: {
              filename: files[0].name,
              error: error instanceof Error ? error.message : "Upload failed",
            },
          }),
        );
      } finally {
        window.dispatchEvent(new CustomEvent("fileUploadComplete"));
        setFileUploading(false);
        refetchSearch();
      }
    }

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
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
        // Trigger search refresh after successful folder processing starts
        window.dispatchEvent(new CustomEvent("knowledgeUpdated"));
      } else if (response.ok) {
        setFolderPath("");
        window.dispatchEvent(new CustomEvent("knowledgeUpdated"));
      } else {
        console.error("Folder upload failed:", result.error);
      }
    } catch (error) {
      console.error("Folder upload error:", error);
    } finally {
      setFolderLoading(false);
      refetchSearch();
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
        // Trigger search refresh after successful S3 processing starts
        window.dispatchEvent(new CustomEvent("knowledgeUpdated"));
      } else {
        console.error("S3 upload failed:", result.error);
      }
    } catch (error) {
      console.error("S3 upload error:", error);
    } finally {
      setS3Loading(false);
      refetchSearch();
    }
  };

  const cloudConnectorItems = Object.entries(cloudConnectors)
    .filter(([, info]) => info.available)
    .map(([type, info]) => ({
      label: info.name,
      icon: PlugZap,
      onClick: () => {
        setIsOpen(false);
        if (info.connected && info.hasToken) {
          router.push(`/upload/${type}`);
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

  return (
    <>
      <div ref={dropdownRef} className="relative">
        <button
          onClick={() =>
            !(fileUploading || folderLoading || s3Loading) && setIsOpen(!isOpen)
          }
          disabled={fileUploading || folderLoading || s3Loading}
          className={cn(
            variant === "button"
              ? "rounded-lg h-12 px-4 flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              : "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed",
            variant === "navigation" && active
              ? "bg-accent text-accent-foreground shadow-sm"
              : variant === "navigation"
              ? "text-foreground hover:text-accent-foreground"
              : "",
          )}
        >
          {variant === "button" ? (
            <>
              <Plus className="h-4 w-4" />
              <span>Add Knowledge</span>
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform",
                  isOpen && "rotate-180",
                )}
              />
            </>
          ) : (
            <>
              <div className="flex items-center flex-1">
                <Upload
                  className={cn(
                    "h-4 w-4 mr-3 shrink-0",
                    active
                      ? "text-accent-foreground"
                      : "text-muted-foreground group-hover:text-foreground",
                  )}
                />
                Knowledge
              </div>
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform",
                  isOpen && "rotate-180",
                )}
              />
            </>
          )}
        </button>

        {isOpen && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-md z-50">
            <div className="py-1">
              {menuItems.map((item, index) => (
                <button
                  key={index}
                  onClick={item.onClick}
                  disabled={"disabled" in item ? item.disabled : false}
                  title={"tooltip" in item ? item.tooltip : undefined}
                  className={cn(
                    "w-full px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                    "disabled" in item &&
                      item.disabled &&
                      "opacity-50 cursor-not-allowed hover:bg-transparent hover:text-current",
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
    </>
  );
}
