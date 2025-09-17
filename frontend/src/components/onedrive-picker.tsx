"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { FileText, Folder, Plus, Trash2, ArrowLeft } from "lucide-react"

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

  const navigateBack = () => {
    if (breadcrumbs.length > 1) {
      const newBreadcrumbs = breadcrumbs.slice(0, -1)
      setBreadcrumbs(newBreadcrumbs)
      
      if (newBreadcrumbs.length === 1) {
        setCurrentPath('me/drive/root/children')
        fetchFiles('me/drive/root/children')
      } else {
        const parentCrumb = newBreadcrumbs[newBreadcrumbs.length - 1]
        const newPath = `me/drive/items/${parentCrumb.id}/children`
        setCurrentPath(newPath)
        fetchFiles(newPath)
      }
    }
  }

  const removeFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId)
    onFileSelected(updatedFiles)
  }

  const getFileIcon = (file: OneDriveFile) => {
    if (file.driveItem?.folder) {
      return <Folder className="h-4 w-4 text-blue-600" />
    }
    return <FileText className="h-4 w-4 text-gray-600" />
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
      <Card>
        <CardContent className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600">
            Please connect to {serviceName} first to select specific files.
          </p>
        </CardContent>
      </Card>
    )
  }

  if (!accessToken) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600 mb-2">
            Access token unavailable
          </p>
          <p className="text-xs text-amber-600">
            Try disconnecting and reconnecting your {serviceName} account.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {!isPickerOpen ? (
        <Card>
          <CardContent className="flex flex-col items-center text-center p-6">
            <p className="text-sm text-gray-600 mb-4">
              Select files from {serviceName} to ingest.
            </p>
            <Button
              onClick={openPicker}
              className="bg-black text-white hover:bg-gray-800"
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Files
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Select Files from {serviceName}</h3>
              <Button onClick={closePicker} size="sm" variant="outline">
                Done
              </Button>
            </div>
            
            {/* Navigation */}
            <div className="flex items-center space-x-2 mb-4">
              {breadcrumbs.length > 1 && (
                <Button
                  onClick={navigateBack}
                  size="sm"
                  variant="ghost"
                  className="p-1"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Button>
              )}
              <div className="text-sm text-gray-600">
                {breadcrumbs.map((crumb, index) => (
                  <span key={crumb.id}>
                    {index > 0 && <span className="mx-1">/</span>}
                    {crumb.name}
                  </span>
                ))}
              </div>
            </div>

            {/* File List */}
            <div className="border rounded-md max-h-96 overflow-y-auto">
              {isLoading ? (
                <div className="p-4 text-center text-gray-600">Loading...</div>
              ) : files.length === 0 ? (
                <div className="p-4 text-center text-gray-600">No files found</div>
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
                        <Badge className="text-xs bg-green-100 text-green-800">Selected</Badge>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-600">
              Added files
            </p>
            <Button
              onClick={() => onFileSelected([])}
              size="sm"
              variant="ghost"
              className="text-xs h-6"
            >
              Clear all
            </Button>
          </div>
          <div className="max-h-64 overflow-y-auto space-y-1">
            {selectedFiles.map((file) => (
              <div
                key={file.id}
                className="flex items-center justify-between p-2 bg-gray-100 rounded-md text-xs"
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
        </div>
      )}
    </div>
  )
}
