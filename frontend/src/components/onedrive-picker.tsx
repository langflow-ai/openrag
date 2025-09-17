"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Plus, Trash2, FileText } from "lucide-react"

interface OneDrivePickerProps {
  onFileSelected: (files: SelectedFile[]) => void
  selectedFiles?: SelectedFile[]
  isAuthenticated: boolean
  accessToken?: string
  connectorType?: "onedrive" | "sharepoint"
  baseUrl?: string // e.g., "https://tenant.sharepoint.com/sites/sitename" or "https://tenant-my.sharepoint.com"
  clientId: string
}

interface SelectedFile {
  id: string
  name: string
  mimeType?: string
  webUrl?: string
  downloadUrl?: string
}

export function OneDrivePicker({ 
  onFileSelected, 
  selectedFiles = [], 
  isAuthenticated, 
  accessToken,
  connectorType = "onedrive",
  baseUrl: providedBaseUrl,
  clientId
}: OneDrivePickerProps) {
  // Debug all props
  console.log('All OneDrivePicker props:', {
    onFileSelected: !!onFileSelected,
    selectedFiles: selectedFiles?.length,
    isAuthenticated,
    accessToken: !!accessToken,
    connectorType,
    providedBaseUrl,
    clientId
  })
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  const [autoBaseUrl, setAutoBaseUrl] = useState<string | null>(null)
  const [isLoadingBaseUrl, setIsLoadingBaseUrl] = useState(false)
  const baseUrl = providedBaseUrl || autoBaseUrl

  useEffect(() => {
    if (providedBaseUrl || !accessToken || autoBaseUrl) return

      const getBaseUrl = async () => {
        setIsLoadingBaseUrl(true)
        try {
          // For personal accounts, use the picker URL directly
          setAutoBaseUrl("https://onedrive.live.com/picker")
        } catch (error) {
          console.error('Auto-detect baseUrl failed:', error)
        } finally {
          setIsLoadingBaseUrl(false)
        }
      }
    
    getBaseUrl()
  }, [accessToken, providedBaseUrl, autoBaseUrl])

  // Add this loading check before your existing checks:
  if (isLoadingBaseUrl) {
    return (
      <div className="border rounded-lg shadow-sm bg-white">
        <div className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  const openPicker = () => {
    if (!accessToken || !clientId) {
      console.error('Access token and client ID required')
      return
    }

    setIsPickerOpen(true)

    const script = document.createElement('script')
    script.src = 'https://js.live.net/v7.2/OneDrive.js'
    script.onload = () => {
      // @ts-ignore
      const OneDrive = window.OneDrive
      
      if (OneDrive) {
        OneDrive.open({
          clientId: clientId,
          action: 'query',
          multiSelect: true,
          advanced: {
            endpointHint: 'api.onedrive.com',
            accessToken: accessToken,
          },
          success: (response: any) => {
            console.log('Raw OneDrive response:', response)
            
            const newFiles: SelectedFile[] = response.value?.map((item: any, index: number) => ({
              id: item.id,
              name: `OneDrive File ${index + 1} (${item.id.slice(-8)})`,
              mimeType: 'application/pdf',
              webUrl: item.webUrl || '',
              downloadUrl: ''
            })) || []
            
            console.log('Mapped files:', newFiles)
            onFileSelected([...selectedFiles, ...newFiles])
            setIsPickerOpen(false)
          },
          cancel: () => {
            console.log('Picker cancelled')
            setIsPickerOpen(false)
          },
          error: (error: any) => {
            console.error('Picker error:', error)
            setIsPickerOpen(false)
          }
        })
      }
    }
    
    document.head.appendChild(script)
  }

  const closePicker = () => {
    setIsPickerOpen(false)
  }

  const removeFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId)
    onFileSelected(updatedFiles)
  }

  const serviceName = connectorType === "sharepoint" ? "SharePoint" : "OneDrive"
  
  if (!isAuthenticated) {
    return (
      <div className="border rounded-lg shadow-sm bg-white">
        <div className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600">
            Please connect to {serviceName} first to select files.
          </p>
        </div>
      </div>
    )
  }

  if (!accessToken || !baseUrl) {
    return (
      <div className="border rounded-lg shadow-sm bg-white">
        <div className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600 mb-2">
            Configuration required
          </p>
          <p className="text-xs text-amber-600">
            {!accessToken && "Access token required. "}
            {!baseUrl && "Base URL required."}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {isPickerOpen ? (
        <div className="border rounded-lg shadow-sm bg-white">
          <div className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">OneDrive Picker is open in popup</h3>
              <Button 
                onClick={closePicker} 
                size="sm" 
                variant="outline"
                className="text-black"
                style={{ color: '#000000' }}
              >
                Cancel
              </Button>
            </div>
            <p className="text-sm text-gray-600">
              Please select your files in the popup window. This window will update when you're done.
            </p>
          </div>
        </div>
      ) : (
        <div className="border rounded-lg shadow-sm bg-white">
          <div className="flex flex-col items-center text-center p-6">
            <p className="text-sm text-gray-600 mb-4">
              Select files from {serviceName} to ingest into OpenRAG.
            </p>
            <Button
              onClick={openPicker}
              className="bg-blue-600 text-white hover:bg-blue-700 border-0"
              style={{ backgroundColor: '#2563eb', color: '#ffffff' }}
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Files
            </Button>
          </div>
        </div>
      )}

      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-600">
              Selected files ({selectedFiles.length})
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
                  <FileText className="h-4 w-4 text-gray-600" />
                  <span className="truncate font-medium text-black" style={{ color: '#000000' }}>{file.name}</span>
                    {file.mimeType && (
                      <Badge variant="secondary" className="text-xs px-1 py-0.5 h-auto">
                        {file.mimeType.split('/').pop() || 'File'}
                      </Badge>
                    )}
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