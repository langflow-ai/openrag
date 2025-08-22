"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter } from "next/navigation"
import { ChevronDown, Upload, FolderOpen, Cloud, PlugZap, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { useTask } from "@/contexts/task-context"

interface KnowledgeDropdownProps {
  active?: boolean
  variant?: 'navigation' | 'button'
}

export function KnowledgeDropdown({ active, variant = 'navigation' }: KnowledgeDropdownProps) {
  const router = useRouter()
  const { addTask } = useTask()
  const [isOpen, setIsOpen] = useState(false)
  const [showFolderDialog, setShowFolderDialog] = useState(false)
  const [showS3Dialog, setShowS3Dialog] = useState(false)
  const [awsEnabled, setAwsEnabled] = useState(false)
  const [folderPath, setFolderPath] = useState("/app/documents/")
  const [bucketUrl, setBucketUrl] = useState("s3://")
  const [folderLoading, setFolderLoading] = useState(false)
  const [s3Loading, setS3Loading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Check AWS availability on mount
  useEffect(() => {
    const checkAws = async () => {
      try {
        const res = await fetch("/api/upload_options")
        if (res.ok) {
          const data = await res.json()
          setAwsEnabled(Boolean(data.aws))
        }
      } catch (err) {
        console.error("Failed to check AWS availability", err)
      }
    }
    checkAws()
  }, [])

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside)
      return () => document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [isOpen])

  const handleFileUpload = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      // Trigger the same file upload event as the chat page
      window.dispatchEvent(new CustomEvent('fileUploadStart', { 
        detail: { filename: files[0].name } 
      }))
      
      try {
        const formData = new FormData()
        formData.append('file', files[0])
        
        const response = await fetch('/api/upload', {
          method: 'POST',
          body: formData,
        })

        const result = await response.json()
        
        if (response.ok) {
          window.dispatchEvent(new CustomEvent('fileUploaded', { 
            detail: { file: files[0], result } 
          }))
        } else {
          window.dispatchEvent(new CustomEvent('fileUploadError', { 
            detail: { filename: files[0].name, error: result.error || 'Upload failed' } 
          }))
        }
      } catch (error) {
        window.dispatchEvent(new CustomEvent('fileUploadError', { 
          detail: { filename: files[0].name, error: error instanceof Error ? error.message : 'Upload failed' } 
        }))
      } finally {
        window.dispatchEvent(new CustomEvent('fileUploadComplete'))
      }
    }
    
    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
    setIsOpen(false)
  }

  const handleFolderUpload = async () => {
    if (!folderPath.trim()) return

    setFolderLoading(true)

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
        const taskId = result.task_id || result.id
        
        if (!taskId) {
          throw new Error("No task ID received from server")
        }
        
        addTask(taskId)
        setFolderPath("")
        setShowFolderDialog(false)
        
      } else if (response.ok) {
        setFolderPath("")
        setShowFolderDialog(false)
      } else {
        console.error("Folder upload failed:", result.error)
      }
    } catch (error) {
      console.error("Folder upload error:", error)
    } finally {
      setFolderLoading(false)
    }
  }

  const handleS3Upload = async () => {
    if (!bucketUrl.trim()) return

    setS3Loading(true)

    try {
      const response = await fetch("/api/upload_bucket", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ s3_url: bucketUrl }),
      })

      const result = await response.json()

      if (response.status === 201) {
        const taskId = result.task_id || result.id

        if (!taskId) {
          throw new Error("No task ID received from server")
        }

        addTask(taskId)
        setBucketUrl("s3://")
        setShowS3Dialog(false)
      } else {
        console.error("S3 upload failed:", result.error)
      }
    } catch (error) {
      console.error("S3 upload error:", error)
    } finally {
      setS3Loading(false)
    }
  }

  const menuItems = [
    {
      label: "Add File",
      icon: Upload,
      onClick: handleFileUpload
    },
    {
      label: "Process Folder", 
      icon: FolderOpen,
      onClick: () => {
        setIsOpen(false)
        setShowFolderDialog(true)
      }
    },
    ...(awsEnabled ? [{
      label: "Process S3 Bucket",
      icon: Cloud,
      onClick: () => {
        setIsOpen(false)
        setShowS3Dialog(true)
      }
    }] : []),
    {
      label: "Cloud Connectors",
      icon: PlugZap,
      onClick: () => {
        setIsOpen(false)
        router.push("/settings")
      }
    }
  ]

  return (
    <>
      <div ref={dropdownRef} className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={cn(
            variant === 'button' 
              ? "rounded-lg h-12 px-4 flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              : "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
            variant === 'navigation' && active 
              ? "bg-accent text-accent-foreground shadow-sm" 
              : variant === 'navigation' ? "text-foreground hover:text-accent-foreground" : "",
          )}
        >
          {variant === 'button' ? (
            <>
              <Plus className="h-4 w-4" />
              <span>Add Knowledge</span>
              <ChevronDown className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")} />
            </>
          ) : (
            <>
              <div className="flex items-center flex-1">
                <Upload className={cn("h-4 w-4 mr-3 shrink-0", active ? "text-accent-foreground" : "text-muted-foreground group-hover:text-foreground")} />
                Knowledge
              </div>
              <ChevronDown className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")} />
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
                  className="w-full px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
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
              Process all documents from an S3 bucket. AWS credentials must be configured.
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
              <Button
                variant="outline"
                onClick={() => setShowS3Dialog(false)}
              >
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
  )
}