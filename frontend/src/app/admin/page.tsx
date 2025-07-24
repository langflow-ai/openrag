"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Upload, FolderOpen, Loader2 } from "lucide-react"

export default function AdminPage() {
  const [fileUploadLoading, setFileUploadLoading] = useState(false)
  const [pathUploadLoading, setPathUploadLoading] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [folderPath, setFolderPath] = useState("/app/documents/")
  const [uploadStatus, setUploadStatus] = useState<string>("")

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFile) return

    setFileUploadLoading(true)
    setUploadStatus("")

    try {
      const formData = new FormData()
      formData.append("file", selectedFile)

      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      })

      const result = await response.json()
      
      if (response.ok) {
        setUploadStatus(`File uploaded successfully! ID: ${result.id}`)
        setSelectedFile(null)
        // Reset the file input
        const fileInput = document.getElementById("file-input") as HTMLInputElement
        if (fileInput) fileInput.value = ""
      } else {
        setUploadStatus(`Error: ${result.error || "Upload failed"}`)
      }
    } catch (error) {
      setUploadStatus(`Error: ${error instanceof Error ? error.message : "Upload failed"}`)
    } finally {
      setFileUploadLoading(false)
    }
  }

  const handlePathUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!folderPath.trim()) return

    setPathUploadLoading(true)
    setUploadStatus("")

    try {
      const response = await fetch("/api/upload_path", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: folderPath }),
      })

      const result = await response.json()
      
      if (response.status === 201) {
        // New flow: Got task ID, start polling
        const taskId = result.task_id || result.id
        const totalFiles = result.total_files || 0
        
        if (!taskId) {
          throw new Error("No task ID received from server")
        }
        
        setUploadStatus(`🔄 Processing started for ${totalFiles} files... (Task ID: ${taskId})`)
        
        // Start polling the task status
        await pollPathTaskStatus(taskId, totalFiles)
        
      } else if (response.ok) {
        // Original flow: Direct response with results
        const successful = result.results?.filter((r: {status: string}) => r.status === "indexed").length || 0
        const total = result.results?.length || 0
        setUploadStatus(`Path processed successfully! ${successful}/${total} files indexed.`)
        setFolderPath("")
      } else {
        setUploadStatus(`Error: ${result.error || "Path upload failed"}`)
      }
    } catch (error) {
      setUploadStatus(`Error: ${error instanceof Error ? error.message : "Path upload failed"}`)
    } finally {
      setPathUploadLoading(false)
    }
  }

  const pollPathTaskStatus = async (taskId: string, totalFiles: number) => {
    const maxAttempts = 120 // Poll for up to 10 minutes (120 * 5s intervals) for large batches
    let attempts = 0
    
    const poll = async (): Promise<void> => {
      try {
        attempts++
        
        const response = await fetch(`/api/tasks/${taskId}`)
        
        if (!response.ok) {
          throw new Error(`Failed to check task status: ${response.status}`)
        }
        
        const task = await response.json()
        
        if (task.status === 'completed') {
          setUploadStatus(`✅ Path processing completed! ${task.successful_files}/${task.total_files} files processed successfully.`)
          setFolderPath("")
          setPathUploadLoading(false)
          
        } else if (task.status === 'failed' || task.status === 'error') {
          setUploadStatus(`❌ Path processing failed: ${task.error || 'Unknown error occurred'}`)
          setPathUploadLoading(false)
          
        } else if (task.status === 'pending' || task.status === 'running') {
          // Still in progress, update status and continue polling
          const processed = task.processed_files || 0
          const successful = task.successful_files || 0
          const failed = task.failed_files || 0
          
          setUploadStatus(`⏳ Processing files... ${processed}/${totalFiles} processed (${successful} successful, ${failed} failed)`)
          
          // Continue polling if we haven't exceeded max attempts
          if (attempts < maxAttempts) {
            setTimeout(poll, 5000) // Poll every 5 seconds
          } else {
            setUploadStatus(`⚠️ Processing timeout after ${attempts} attempts. The task may still be running in the background.`)
            setPathUploadLoading(false)
          }
          
        } else {
          setUploadStatus(`❓ Unknown task status: ${task.status}`)
          setPathUploadLoading(false)
        }
        
      } catch (error) {
        console.error('Task polling error:', error)
        setUploadStatus(`❌ Failed to check processing status: ${error instanceof Error ? error.message : 'Unknown error'}`)
        setPathUploadLoading(false)
      }
    }
    
    // Start polling immediately
    poll()
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Ingest</h1>
        <p className="text-muted-foreground">Upload and manage documents in your database</p>
      </div>

      {uploadStatus && (
        <Card className={uploadStatus.includes("Error") ? "border-destructive" : "border-green-500"}>
          <CardContent className="pt-6">
            <p className={uploadStatus.includes("Error") ? "text-destructive" : "text-green-600"}>
              {uploadStatus}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
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
      </div>
    </div>
  )
}