"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Upload, FolderOpen, Loader2, Cloud } from "lucide-react";
import { ProtectedRoute } from "@/components/protected-route";
import { useTask } from "@/contexts/task-context";

function AdminPage() {
  console.log("AdminPage component rendered!");
  const [fileUploadLoading, setFileUploadLoading] = useState(false);
  const [pathUploadLoading, setPathUploadLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [folderPath, setFolderPath] = useState("/app/documents/");
  const [bucketUploadLoading, setBucketUploadLoading] = useState(false);
  const [bucketUrl, setBucketUrl] = useState("s3://");
  const [uploadStatus, setUploadStatus] = useState<string>("");
  const [awsEnabled, setAwsEnabled] = useState(false);
  const { addTask } = useTask();

  useEffect(() => {
    console.log("AdminPage useEffect running - checking AWS availability");
    const checkAws = async () => {
      try {
        console.log("Making request to /api/upload_options");
        const res = await fetch("/api/upload_options");
        console.log("Response status:", res.status, "OK:", res.ok);
        if (res.ok) {
          const data = await res.json();
          console.log("Response data:", data);
          setAwsEnabled(Boolean(data.aws));
        }
      } catch (err) {
        console.error("Failed to check AWS availability", err);
      }
    };
    checkAws();
  }, []);

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    setFileUploadLoading(true);
    setUploadStatus("");

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch("/api/router/upload_ingest", {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (response.ok) {
        setUploadStatus(`File uploaded successfully! ID: ${result.id}`);
        setSelectedFile(null);
        // Reset the file input
        const fileInput = document.getElementById(
          "file-input",
        ) as HTMLInputElement;
        if (fileInput) fileInput.value = "";
      } else {
        setUploadStatus(`Error: ${result.error || "Upload failed"}`);
      }
    } catch (error) {
      setUploadStatus(
        `Error: ${error instanceof Error ? error.message : "Upload failed"}`,
      );
    } finally {
      setFileUploadLoading(false);
    }
  };

  const handleBucketUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bucketUrl.trim()) return;

    setBucketUploadLoading(true);
    setUploadStatus("");

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
        const totalFiles = result.total_files || 0;

        if (!taskId) {
          throw new Error("No task ID received from server");
        }

        addTask(taskId);
        setUploadStatus(
          `🔄 Processing started for ${totalFiles} files. Check the task notification panel for real-time progress. (Task ID: ${taskId})`,
        );
        setBucketUrl("");
      } else {
        setUploadStatus(`Error: ${result.error || "Bucket processing failed"}`);
      }
    } catch (error) {
      setUploadStatus(
        `Error: ${error instanceof Error ? error.message : "Bucket processing failed"}`,
      );
    } finally {
      setBucketUploadLoading(false);
    }
  };

  const handlePathUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!folderPath.trim()) return;

    setPathUploadLoading(true);
    setUploadStatus("");

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
        // New flow: Got task ID, use centralized tracking
        const taskId = result.task_id || result.id;
        const totalFiles = result.total_files || 0;

        if (!taskId) {
          throw new Error("No task ID received from server");
        }

        // Add task to centralized tracking
        addTask(taskId);

        setUploadStatus(
          `🔄 Processing started for ${totalFiles} files. Check the task notification panel for real-time progress. (Task ID: ${taskId})`,
        );
        setFolderPath("");
        setPathUploadLoading(false);
      } else if (response.ok) {
        // Original flow: Direct response with results
        const successful =
          result.results?.filter(
            (r: { status: string }) => r.status === "indexed",
          ).length || 0;
        const total = result.results?.length || 0;
        setUploadStatus(
          `Path processed successfully! ${successful}/${total} files indexed.`,
        );
        setFolderPath("");
        setPathUploadLoading(false);
      } else {
        setUploadStatus(`Error: ${result.error || "Path upload failed"}`);
        setPathUploadLoading(false);
      }
    } catch (error) {
      setUploadStatus(
        `Error: ${error instanceof Error ? error.message : "Path upload failed"}`,
      );
      setPathUploadLoading(false);
    }
  };

  // Remove the old pollPathTaskStatus function since we're using centralized system

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Ingest</h1>
        <p className="text-muted-foreground">
          Upload and manage documents in your database
        </p>
      </div>

      {uploadStatus && (
        <Card
          className={
            uploadStatus.includes("Error")
              ? "border-destructive"
              : "border-green-500"
          }
        >
          <CardContent className="pt-6">
            <p
              className={
                uploadStatus.includes("Error")
                  ? "text-destructive"
                  : "text-green-600"
              }
            >
              {uploadStatus}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5" />
              Upload File
            </CardTitle>
            <CardDescription>
              Upload a single document to be indexed and searchable
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleFileUpload} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="file-input">Select File</Label>
                <Input
                  id="file-input"
                  type="file"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  accept=".pdf,.doc,.docx,.txt,.md"
                  className="cursor-pointer"
                />
              </div>
              <Button
                type="submit"
                disabled={!selectedFile || fileUploadLoading}
                className="w-full"
              >
                {fileUploadLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="mr-2 h-4 w-4" />
                    Upload File
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              Upload Folder
            </CardTitle>
            <CardDescription>
              Process all documents in a folder path on the server
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handlePathUpload} className="space-y-4">
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
              <Button
                type="submit"
                disabled={!folderPath.trim() || pathUploadLoading}
                className="w-full"
              >
                {pathUploadLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <FolderOpen className="mr-2 h-4 w-4" />
                    Process Folder
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
        {awsEnabled && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Cloud className="h-5 w-5" />
                Process Bucket
              </CardTitle>
              <CardDescription>
                Process all documents from an S3 bucket. AWS credentials must be
                set as environment variables.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleBucketUpload} className="space-y-4">
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
                <Button
                  type="submit"
                  disabled={!bucketUrl.trim() || bucketUploadLoading}
                  className="w-full"
                >
                  {bucketUploadLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <Cloud className="mr-2 h-4 w-4" />
                      Process Bucket
                    </>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function ProtectedAdminPage() {
  return (
    <ProtectedRoute>
      <AdminPage />
    </ProtectedRoute>
  );
}
