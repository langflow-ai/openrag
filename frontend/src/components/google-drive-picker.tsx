"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { FileText, Folder, X } from "lucide-react"

interface GoogleDrivePickerProps {
  onFileSelected: (files: GoogleDriveFile[]) => void
  selectedFiles?: GoogleDriveFile[]
  isAuthenticated: boolean
  accessToken?: string
}

interface GoogleDriveFile {
  id: string
  name: string
  mimeType: string
  webViewLink?: string
  iconLink?: string
}

interface GoogleAPI {
  load: (api: string, options: { callback: () => void; onerror?: () => void }) => void
}

interface GooglePickerData {
  action: string
  docs: GooglePickerDocument[]
}

interface GooglePickerDocument {
  [key: string]: string
}

declare global {
  interface Window {
    gapi: GoogleAPI
    google: {
      picker: {
        api: {
          load: (callback: () => void) => void
        }
        PickerBuilder: new () => GooglePickerBuilder
        ViewId: {
          DOCS: string
          FOLDERS: string
          DOCS_IMAGES_AND_VIDEOS: string
          DOCUMENTS: string
          PRESENTATIONS: string
          SPREADSHEETS: string
        }
        Feature: {
          MULTISELECT_ENABLED: string
          NAV_HIDDEN: string
          SIMPLE_UPLOAD_ENABLED: string
        }
        Action: {
          PICKED: string
          CANCEL: string
        }
        Document: {
          ID: string
          NAME: string
          MIME_TYPE: string
          URL: string
          ICON_URL: string
        }
      }
    }
  }
}

interface GooglePickerBuilder {
  addView: (view: string) => GooglePickerBuilder
  setOAuthToken: (token: string) => GooglePickerBuilder
  setCallback: (callback: (data: GooglePickerData) => void) => GooglePickerBuilder
  enableFeature: (feature: string) => GooglePickerBuilder
  setTitle: (title: string) => GooglePickerBuilder
  build: () => GooglePicker
}

interface GooglePicker {
  setVisible: (visible: boolean) => void
}

export function GoogleDrivePicker({ 
  onFileSelected, 
  selectedFiles = [], 
  isAuthenticated, 
  accessToken 
}: GoogleDrivePickerProps) {
  const [isPickerLoaded, setIsPickerLoaded] = useState(false)
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  
  useEffect(() => {
    const loadPickerApi = () => {
      if (typeof window !== 'undefined' && window.gapi) {
        window.gapi.load('picker', {
          callback: () => {
            setIsPickerLoaded(true)
          },
          onerror: () => {
            console.error('Failed to load Google Picker API')
          }
        })
      }
    }

    // Load Google API script if not already loaded
    if (typeof window !== 'undefined') {
      if (!window.gapi) {
        const script = document.createElement('script')
        script.src = 'https://apis.google.com/js/api.js'
        script.async = true
        script.defer = true
        script.onload = loadPickerApi
        script.onerror = () => {
          console.error('Failed to load Google API script')
        }
        document.head.appendChild(script)
        
        return () => {
          if (document.head.contains(script)) {
            document.head.removeChild(script)
          }
        }
      } else {
        loadPickerApi()
      }
    }
  }, [])

  const openPicker = () => {
    if (!isPickerLoaded || !accessToken || !window.google?.picker) {
      return
    }

    try {
      setIsPickerOpen(true)

      const picker = new window.google.picker.PickerBuilder()
        .addView(window.google.picker.ViewId.DOCS)
        .addView(window.google.picker.ViewId.FOLDERS)
        .setOAuthToken(accessToken)
        .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
        .setTitle('Select files from Google Drive')
        .setCallback(pickerCallback)
        .build()

      picker.setVisible(true)
    } catch (error) {
      console.error('Error creating picker:', error)
      setIsPickerOpen(false)
    }
  }

  const pickerCallback = (data: GooglePickerData) => {
    if (data.action === window.google.picker.Action.PICKED) {
      const files: GoogleDriveFile[] = data.docs.map((doc: GooglePickerDocument) => ({
        id: doc[window.google.picker.Document.ID],
        name: doc[window.google.picker.Document.NAME],
        mimeType: doc[window.google.picker.Document.MIME_TYPE],
        webViewLink: doc[window.google.picker.Document.URL],
        iconLink: doc[window.google.picker.Document.ICON_URL]
      }))
      
      onFileSelected(files)
    }
    
    setIsPickerOpen(false)
  }

  const removeFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId)
    onFileSelected(updatedFiles)
  }

  const getFileIcon = (mimeType: string) => {
    if (mimeType.includes('folder')) {
      return <Folder className="h-4 w-4" />
    }
    return <FileText className="h-4 w-4" />
  }

  const getMimeTypeLabel = (mimeType: string) => {
    const typeMap: { [key: string]: string } = {
      'application/vnd.google-apps.document': 'Google Doc',
      'application/vnd.google-apps.spreadsheet': 'Google Sheet',
      'application/vnd.google-apps.presentation': 'Google Slides',
      'application/vnd.google-apps.folder': 'Folder',
      'application/pdf': 'PDF',
      'text/plain': 'Text',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word Doc',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint'
    }
    
    return typeMap[mimeType] || 'Document'
  }

  if (!isAuthenticated) {
    return (
      <div className="text-sm text-muted-foreground p-4 bg-muted/20 rounded-md">
        Please connect to Google Drive first to select specific files.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium">File Selection</h4>
          <p className="text-xs text-muted-foreground">
            Choose specific files to sync instead of syncing everything
          </p>
        </div>
        <Button
          onClick={openPicker}
          disabled={!isPickerLoaded || isPickerOpen || !accessToken}
          size="sm"
          variant="outline"
        >
          {isPickerOpen ? 'Opening Picker...' : 'Select Files'}
        </Button>
      </div>

      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Selected files ({selectedFiles.length}):
          </p>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {selectedFiles.map((file) => (
              <div
                key={file.id}
                className="flex items-center justify-between p-2 bg-muted/30 rounded-md text-xs"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {getFileIcon(file.mimeType)}
                  <span className="truncate font-medium">{file.name}</span>
                  <Badge variant="secondary" className="text-xs px-1 py-0.5 h-auto">
                    {getMimeTypeLabel(file.mimeType)}
                  </Badge>
                </div>
                <Button
                  onClick={() => removeFile(file.id)}
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                >
                  <X className="h-3 w-3" />
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