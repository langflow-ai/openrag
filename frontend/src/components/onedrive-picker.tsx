"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { FileText, Folder, Trash2, X } from "lucide-react"

interface OneDrivePickerProps {
  onFileSelected: (files: OneDriveFile[]) => void
  selectedFiles?: OneDriveFile[]
  isAuthenticated: boolean
  accessToken?: string
  connectorType?: "onedrive" | "sharepoint"
  onPickerStateChange?: (isOpen: boolean) => void
}

interface OneDriveFile {
  id: string
  name: string
  mimeType?: string
  webUrl?: string
  driveItem?: {
    file?: { mimeType: string }
    folder?: unknown
  }
}

interface GraphResponse {
  value: OneDriveFile[]
}

declare global {
  interface Window {
    mgt?: {
      Providers?: {
        globalProvider?: unknown
      }
    }
  }
}

export function OneDrivePicker({ 
  onFileSelected, 
  selectedFiles = [], 
  isAuthenticated, 
  accessToken,
  connectorType = "onedrive",
  onPickerStateChange
}: OneDrivePickerProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [files, setFiles] = useState<OneDriveFile[]>([])
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  const [currentPath, setCurrentPath] = useState<string>(
    connectorType === "sharepoint" ? 'sites?search=' : 'me/drive/root/children'
  )
  const [breadcrumbs, setBreadcrumbs] = useState<{id: string, name: string}[]>([
    {id: 'root', name: connectorType === "sharepoint" ? 'SharePoint' : 'OneDrive'}
  ])
  
  useEffect(() => {
  const loadMGT = async () => {
    if (typeof window !== 'undefined' && !window.mgt) {
      try {
        await import('@microsoft/mgt-components')
        await import('@microsoft/mgt-msal2-provider')
        
        // For simplicity, we'll use direct Graph API calls instead of MGT components
        // MGT provider initialization would go here if needed
      } catch {
        console.warn('MGT not available, falling back to direct API calls')
      }
    }
  }
    
    loadMGT()
  }, [accessToken])


  const fetchFiles = async (path: string = currentPath) => {
    if (!accessToken) return
    
    setIsLoading(true)
    try {
      const response = await fetch(`https://graph.microsoft.com/v1.0/${path}`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const data: GraphResponse = await response.json()
        setFiles(data.value || [])
      } else {
        console.error('Failed to fetch OneDrive files:', response.statusText)
      }
    } catch (error) {
      console.error('Error fetching OneDrive files:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const openPicker = () => {
    if (!accessToken) return
    
    setIsPickerOpen(true)
    onPickerStateChange?.(true)
    fetchFiles()
  }

  const closePicker = () => {
    setIsPickerOpen(false)
    onPickerStateChange?.(false)
    setFiles([])
    setCurrentPath(
      connectorType === "sharepoint" ? 'sites?search=' : 'me/drive/root/children'
    )
    setBreadcrumbs([
      {id: 'root', name: connectorType === "sharepoint" ? 'SharePoint' : 'OneDrive'}
    ])
  }

  const handleFileClick = (file: OneDriveFile) => {
    if (file.driveItem?.folder) {
      // Navigate to folder
      const newPath = `me/drive/items/${file.id}/children`
      setCurrentPath(newPath)
      setBreadcrumbs([...breadcrumbs, {id: file.id, name: file.name}])
      fetchFiles(newPath)
    } else {
      // Select file
      const isAlreadySelected = selectedFiles.some(f => f.id === file.id)
      if (!isAlreadySelected) {
        onFileSelected([...selectedFiles, file])
      }
    }
  }

  const navigateToBreadcrumb = (index: number) => {
    if (index === 0) {
      setCurrentPath('me/drive/root/children')
      setBreadcrumbs([{id: 'root', name: 'OneDrive'}])
      fetchFiles('me/drive/root/children')
    } else {
      const targetCrumb = breadcrumbs[index]
      const newPath = `me/drive/items/${targetCrumb.id}/children`
      setCurrentPath(newPath)
      setBreadcrumbs(breadcrumbs.slice(0, index + 1))
      fetchFiles(newPath)
    }
  }

  const removeFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId)
    onFileSelected(updatedFiles)
  }

  const getFileIcon = (file: OneDriveFile) => {
    if (file.driveItem?.folder) {
      return <Folder className="h-4 w-4" />
    }
    return <FileText className="h-4 w-4" />
  }

  const getMimeTypeLabel = (file: OneDriveFile) => {
    const mimeType = file.driveItem?.file?.mimeType || file.mimeType || ''
    const typeMap: { [key: string]: string } = {
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word Doc',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint',
      'application/pdf': 'PDF',
      'text/plain': 'Text',
      'image/jpeg': 'Image',
      'image/png': 'Image',
    }
    
    if (file.driveItem?.folder) return 'Folder'
    return typeMap[mimeType] || 'Document'
  }

  const serviceName = connectorType === "sharepoint" ? "SharePoint" : "OneDrive"
  
  if (!isAuthenticated) {
    return (
      <div className="text-sm text-muted-foreground p-4 bg-muted/20 rounded-md">
        Please connect to {serviceName} first to select specific files.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium">{serviceName} File Selection</h4>
          <p className="text-xs text-muted-foreground">
            Choose specific files to sync instead of syncing everything
          </p>
        </div>
        <Button
          onClick={openPicker}
          disabled={!accessToken}
          size="sm"
          variant="outline"
          title={!accessToken ? `Access token required - try disconnecting and reconnecting ${serviceName}` : ""}
        >
          {!accessToken ? "No Access Token" : "Select Files"}
        </Button>
      </div>

      {/* Status message when access token is missing */}
      {isAuthenticated && !accessToken && (
        <div className="text-xs text-amber-600 bg-amber-50 p-3 rounded-md border border-amber-200">
          <div className="font-medium mb-1">Access token unavailable</div>
          <div>The file picker requires an access token. Try disconnecting and reconnecting your {serviceName} account.</div>
        </div>
      )}

      {/* File Picker Modal */}
      {isPickerOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[100]">
          <div className="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Select Files from {serviceName}</h3>
              <Button onClick={closePicker} size="sm" variant="ghost">
                <X className="h-4 w-4" />
              </Button>
            </div>
            
            {/* Breadcrumbs */}
            <div className="flex items-center space-x-2 mb-4 text-sm">
              {breadcrumbs.map((crumb, index) => (
                <div key={crumb.id} className="flex items-center">
                  {index > 0 && <span className="mx-2 text-gray-400">/</span>}
                  <button
                    onClick={() => navigateToBreadcrumb(index)}
                    className="text-blue-600 hover:underline"
                  >
                    {crumb.name}
                  </button>
                </div>
              ))}
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto border rounded-md">
              {isLoading ? (
                <div className="p-4 text-center text-muted-foreground">Loading...</div>
              ) : files.length === 0 ? (
                <div className="p-4 text-center text-muted-foreground">No files found</div>
              ) : (
                <div className="divide-y">
                  {files.map((file) => (
                    <div
                      key={file.id}
                      className="flex items-center p-3 hover:bg-gray-50 cursor-pointer"
                      onClick={() => handleFileClick(file)}
                    >
                      <div className="flex items-center gap-3 flex-1">
                        {getFileIcon(file)}
                        <span className="font-medium">{file.name}</span>
                        <Badge variant="secondary" className="text-xs">
                          {getMimeTypeLabel(file)}
                        </Badge>
                      </div>
                      {selectedFiles.some(f => f.id === file.id) && (
                        <Badge variant="default" className="text-xs">Selected</Badge>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Selected files ({selectedFiles.length}):
          </p>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {selectedFiles.map((file) => (
              <div
                key={file.id}
                className="flex items-center justify-between p-2 bg-muted/30 rounded-md text-xs"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {getFileIcon(file)}
                  <span className="truncate font-medium">{file.name}</span>
                  <Badge variant="secondary" className="text-xs px-1 py-0.5 h-auto">
                    {getMimeTypeLabel(file)}
                  </Badge>
                </div>
                <Button
                  onClick={() => removeFile(file.id)}
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
          <Button
            onClick={() => onFileSelected([])}
            size="sm"
            variant="ghost"
            className="text-xs h-6"
          >
            Clear all
          </Button>
        </div>
      )}
    </div>
  )
}