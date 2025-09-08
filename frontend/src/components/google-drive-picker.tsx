"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { FileText, Folder, Plus, Trash2 } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"

interface GoogleDrivePickerProps {
  onFileSelected: (files: GoogleDriveFile[]) => void
  selectedFiles?: GoogleDriveFile[]
  isAuthenticated: boolean
  accessToken?: string
  onPickerStateChange?: (isOpen: boolean) => void
}

interface GoogleDriveFile {
  id: string
  name: string
  mimeType: string
  webViewLink?: string
  iconLink?: string
  size?: number
  modifiedTime?: string
  isFolder?: boolean
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
  accessToken,
  onPickerStateChange
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
      onPickerStateChange?.(true)

      // Create picker with higher z-index and focus handling
      const picker = new window.google.picker.PickerBuilder()
        .addView(window.google.picker.ViewId.DOCS)
        .addView(window.google.picker.ViewId.FOLDERS)
        .setOAuthToken(accessToken)
        .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
        .setTitle('Select files from Google Drive')
        .setCallback(pickerCallback)
        .build()

      picker.setVisible(true)

      // Apply z-index fix after a short delay to ensure picker is rendered
      setTimeout(() => {
        const pickerElements = document.querySelectorAll('.picker-dialog, .goog-modalpopup')
        pickerElements.forEach(el => {
          (el as HTMLElement).style.zIndex = '10000'
        })
        const bgElements = document.querySelectorAll('.picker-dialog-bg, .goog-modalpopup-bg')
        bgElements.forEach(el => {
          (el as HTMLElement).style.zIndex = '9999'
        })
      }, 100)
      
    } catch (error) {
      console.error('Error creating picker:', error)
      setIsPickerOpen(false)
      onPickerStateChange?.(false)
    }
  }

  const pickerCallback = async (data: GooglePickerData) => {
    if (data.action === window.google.picker.Action.PICKED) {
      const files: GoogleDriveFile[] = data.docs.map((doc: GooglePickerDocument) => ({
        id: doc[window.google.picker.Document.ID],
        name: doc[window.google.picker.Document.NAME],
        mimeType: doc[window.google.picker.Document.MIME_TYPE],
        webViewLink: doc[window.google.picker.Document.URL],
        iconLink: doc[window.google.picker.Document.ICON_URL],
        size: doc['sizeBytes'] ? parseInt(doc['sizeBytes']) : undefined,
        modifiedTime: doc['lastEditedUtc'],
        isFolder: doc[window.google.picker.Document.MIME_TYPE] === 'application/vnd.google-apps.folder'
      }))
      
      // If size is still missing, try to fetch it via Google Drive API
      if (accessToken && files.some(f => !f.size && !f.isFolder)) {
        try {
          const enrichedFiles = await Promise.all(files.map(async (file) => {
            if (!file.size && !file.isFolder) {
              try {
                const response = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}?fields=size,modifiedTime`, {
                  headers: {
                    'Authorization': `Bearer ${accessToken}`
                  }
                })
                if (response.ok) {
                  const fileDetails = await response.json()
                  return {
                    ...file,
                    size: fileDetails.size ? parseInt(fileDetails.size) : undefined,
                    modifiedTime: fileDetails.modifiedTime || file.modifiedTime
                  }
                }
              } catch (error) {
                console.warn('Failed to fetch file details:', error)
              }
            }
            return file
          }))
          onFileSelected(enrichedFiles)
        } catch (error) {
          console.warn('Failed to enrich file data:', error)
          onFileSelected(files)
        }
      } else {
        onFileSelected(files)
      }
    }
    
    setIsPickerOpen(false)
    onPickerStateChange?.(false)
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

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return ''
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    if (bytes === 0) return '0 B'
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`
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
      <Card>
        <CardContent className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-muted-foreground mb-4">
            Select files from Google Drive to ingest.
          </p>
          <Button
            onClick={openPicker}
            disabled={!isPickerLoaded || isPickerOpen || !accessToken}
            className="bg-foreground text-background hover:bg-foreground/90"
          >
            <Plus className="h-4 w-4" />
            {isPickerOpen ? 'Opening Picker...' : 'Add Files'}
          </Button>
        </CardContent>
      </Card>

      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
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
                className="flex items-center justify-between p-2 bg-muted/30 rounded-md text-xs"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {getFileIcon(file.mimeType)}
                  <span className="truncate font-medium">{file.name}</span>
                  <Badge variant="secondary" className="text-xs px-1 py-0.5 h-auto">
                    {getMimeTypeLabel(file.mimeType)}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">{formatFileSize(file.size)}</span>
                  <Button
                    onClick={() => removeFile(file.id)}
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
          
        </div>
      )}
    </div>
  )
}
