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
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [channelId] = useState(() => crypto.randomUUID())

  const [autoBaseUrl, setAutoBaseUrl] = useState<string | null>(null)
  const [isLoadingBaseUrl, setIsLoadingBaseUrl] = useState(false)
  const baseUrl = providedBaseUrl || autoBaseUrl

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Only process messages from Microsoft domains
      if (!event.origin.includes('.sharepoint.com') && 
          !event.origin.includes('onedrive.live.com')) {
        return
      }

      const message = event.data
      
      if (message.type === 'initialize') {
        // Picker is ready
        console.log('Picker initialized')
      } else if (message.type === 'pick') {
        // Files were selected
        const files: SelectedFile[] = message.items?.map((item: any) => ({
          id: item.id,
          name: item.name,
          mimeType: item.mimeType,
          webUrl: item.webUrl,
          downloadUrl: item.downloadUrl
        })) || []
        
        onFileSelected([...selectedFiles, ...files])
        closePicker()
      } else if (message.type === 'cancel') {
        // User cancelled
        closePicker()
      } else if (message.type === 'authenticate') {
        // Picker needs authentication token
        if (accessToken && iframeRef.current?.contentWindow) {
          iframeRef.current.contentWindow.postMessage({
            type: 'token',
            token: accessToken
          }, '*')
        }
      }
    }

    if (isPickerOpen) {
      window.addEventListener('message', handleMessage)
      return () => window.removeEventListener('message', handleMessage)
    }
  }, [isPickerOpen, accessToken, selectedFiles, onFileSelected])

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

  useEffect(() => {
    const handlePopupMessage = (event: MessageEvent) => {
      // Only process messages from Microsoft domains
      if (!event.origin.includes('onedrive.live.com') && 
          !event.origin.includes('.live.com')) {
        return
      }

      const message = event.data
      console.log('Received message from popup:', message) // Debug log
      
      if (message.type === 'pick' && message.items) {
        // Files were selected
        const files: SelectedFile[] = message.items.map((item: any) => ({
          id: item.id,
          name: item.name,
          mimeType: item.mimeType,
          webUrl: item.webUrl,
          downloadUrl: item.downloadUrl || item['@microsoft.graph.downloadUrl']
        }))
        
        console.log('Selected files:', files) // Debug log
        onFileSelected([...selectedFiles, ...files])
        setIsPickerOpen(false)
        
        // Close popup if it's still open
        const popups = window.open('', 'OneDrivePicker')
        if (popups && !popups.closed) {
          popups.close()
        }
      } else if (message.type === 'cancel') {
        // User cancelled
        setIsPickerOpen(false)
      }
    }

    if (isPickerOpen) {
      window.addEventListener('message', handlePopupMessage)
      return () => window.removeEventListener('message', handlePopupMessage)
    }
  }, [isPickerOpen, selectedFiles, onFileSelected])

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

  const [popupRef, setPopupRef] = useState<Window | null>(null) // Add this state

  const openPicker = () => {
    if (!accessToken) {
      console.error('Access token required')
      return
    }

    setIsPickerOpen(true)

    // Use OneDrive.js SDK approach instead of form POST
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
          success: (files: any) => {
            console.log('Files selected:', files)
            const selectedFiles: SelectedFile[] = files.value.map((file: any) => ({
              id: file.id,
              name: file.name,
              mimeType: file.file?.mimeType || 'application/octet-stream',
              webUrl: file.webUrl,
              downloadUrl: file['@microsoft.graph.downloadUrl']
            }))
            
            onFileSelected([...selectedFiles, ...selectedFiles])
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
    
    script.onerror = () => {
      console.error('Failed to load OneDrive SDK')
      setIsPickerOpen(false)
    }
    
    document.head.appendChild(script)
  }

  // Update closePicker to close the popup
  const closePicker = () => {
    setIsPickerOpen(false)
    if (popupRef && !popupRef.closed) {
      popupRef.close()
    }
    setPopupRef(null)
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
              <Button onClick={closePicker} size="sm" variant="outline">
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
                  <span className="truncate font-medium">{file.name}</span>
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