"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { FileText, Folder, Plus, Trash2, ArrowLeft, Building2 } from "lucide-react"

interface SharePointPickerProps {
  onFileSelected: (files: SharePointFile[]) => void
  selectedFiles?: SharePointFile[]
  isAuthenticated: boolean
  accessToken?: string
  onPickerStateChange?: (isOpen: boolean) => void
}

interface SharePointFile {
  id: string
  name: string
  mimeType?: string
  webUrl?: string
  driveItem?: {
    file?: { mimeType: string }
    folder?: unknown
  }
  parentReference?: {
    siteId?: string
    driveId?: string
  }
}

interface SharePointSite {
  id: string
  displayName: string
  name: string
  webUrl: string
}

interface GraphResponse {
  value: SharePointFile[] | SharePointSite[]
}

export function SharePointPicker({ 
  onFileSelected, 
  selectedFiles = [], 
  isAuthenticated, 
  accessToken,
  onPickerStateChange
}: SharePointPickerProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [files, setFiles] = useState<SharePointFile[]>([])
  const [sites, setSites] = useState<SharePointSite[]>([])
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  const [currentView, setCurrentView] = useState<'sites' | 'drives' | 'files'>('sites')
  const [currentSite, setCurrentSite] = useState<SharePointSite | null>(null)
  const [currentDrive, setCurrentDrive] = useState<string | null>(null)
  const [currentPath, setCurrentPath] = useState<string>('')
  const [breadcrumbs, setBreadcrumbs] = useState<{id: string, name: string, type: 'site' | 'drive' | 'folder'}[]>([
    {id: 'root', name: 'SharePoint Sites', type: 'site'}
  ])

  const fetchSites = async () => {
    if (!accessToken) return
    
    setIsLoading(true)
    try {
      const response = await fetch('https://graph.microsoft.com/v1.0/sites?search=*', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const data: { value: SharePointSite[] } = await response.json()
        setSites(data.value || [])
      } else {
        console.error('Failed to fetch SharePoint sites:', response.statusText)
      }
    } catch (error) {
      console.error('Error fetching SharePoint sites:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const fetchDrives = async (siteId: string) => {
    if (!accessToken) return
    
    setIsLoading(true)
    try {
      const response = await fetch(`https://graph.microsoft.com/v1.0/sites/${siteId}/drives`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const data: GraphResponse = await response.json()
        // Convert drives to file-like objects for display
        const driveFiles: SharePointFile[] = (data.value as any[]).map(drive => ({
          id: drive.id,
          name: drive.name || 'Document Library',
          driveItem: { folder: {} }, // Mark as folder
          webUrl: drive.webUrl
        }))
        setFiles(driveFiles)
      } else {
        console.error('Failed to fetch drives:', response.statusText)
      }
    } catch (error) {
      console.error('Error fetching drives:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const fetchFiles = async (path: string) => {
    if (!accessToken || !currentSite || !currentDrive) return
    
    setIsLoading(true)
    try {
      const url = path || `https://graph.microsoft.com/v1.0/sites/${currentSite.id}/drives/${currentDrive}/root/children`
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const data: GraphResponse = await response.json()
        setFiles(data.value as SharePointFile[] || [])
      } else {
        console.error('Failed to fetch SharePoint files:', response.statusText)
      }
    } catch (error) {
      console.error('Error fetching SharePoint files:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const openPicker = () => {
    if (!accessToken) return
    
    setIsPickerOpen(true)
    onPickerStateChange?.(true)
    setCurrentView('sites')
    fetchSites()
  }

  const closePicker = () => {
    setIsPickerOpen(false)
    onPickerStateChange?.(false)
    setFiles([])
    setSites([])
    setCurrentView('sites')
    setCurrentSite(null)
    setCurrentDrive(null)
    setCurrentPath('')
    setBreadcrumbs([{id: 'root', name: 'SharePoint Sites', type: 'site'}])
  }

  const handleSiteClick = (site: SharePointSite) => {
    setCurrentSite(site)
    setCurrentView('drives')
    setBreadcrumbs([
      {id: 'root', name: 'SharePoint Sites', type: 'site'},
      {id: site.id, name: site.displayName, type: 'site'}
    ])
    fetchDrives(site.id)
  }

  const handleDriveClick = (drive: SharePointFile) => {
    setCurrentDrive(drive.id)
    setCurrentView('files')
    setBreadcrumbs([
      {id: 'root', name: 'SharePoint Sites', type: 'site'},
      {id: currentSite!.id, name: currentSite!.displayName, type: 'site'},
      {id: drive.id, name: drive.name, type: 'drive'}
    ])
    fetchFiles('')
  }

  const handleFileClick = (file: SharePointFile) => {
    if (file.driveItem?.folder) {
      // Navigate to folder
      const newPath = `https://graph.microsoft.com/v1.0/sites/${currentSite!.id}/drives/${currentDrive}/items/${file.id}/children`
      setCurrentPath(newPath)
      setBreadcrumbs([...breadcrumbs, {id: file.id, name: file.name, type: 'folder'}])
      fetchFiles(newPath)
    } else {
      // Select file - allow multiple selections
      const isAlreadySelected = selectedFiles.some(f => f.id === file.id)
      if (isAlreadySelected) {
        // Deselect if already selected
        const updatedFiles = selectedFiles.filter(f => f.id !== file.id)
        onFileSelected(updatedFiles)
      } else {
        // Add to selection
        onFileSelected([...selectedFiles, file])
      }
    }
  }

  const navigateBack = () => {
    if (breadcrumbs.length > 1) {
      const newBreadcrumbs = breadcrumbs.slice(0, -1)
      setBreadcrumbs(newBreadcrumbs)
      const lastCrumb = newBreadcrumbs[newBreadcrumbs.length - 1]
      
      if (lastCrumb.type === 'site' && lastCrumb.id === 'root') {
        // Back to sites
        setCurrentView('sites')
        setCurrentSite(null)
        setCurrentDrive(null)
        fetchSites()
      } else if (lastCrumb.type === 'site') {
        // Back to drives
        setCurrentView('drives')
        setCurrentDrive(null)
        fetchDrives(lastCrumb.id)
      } else if (lastCrumb.type === 'drive') {
        // Back to root of drive
        setCurrentView('files')
        setCurrentPath('')
        fetchFiles('')
      } else {
        // Back to parent folder
        const parentCrumb = newBreadcrumbs[newBreadcrumbs.length - 2]
        if (parentCrumb.type === 'drive') {
          setCurrentPath('')
          fetchFiles('')
        } else {
          const newPath = `https://graph.microsoft.com/v1.0/sites/${currentSite!.id}/drives/${currentDrive}/items/${lastCrumb.id}/children`
          setCurrentPath(newPath)
          fetchFiles(newPath)
        }
      }
    }
  }

  const removeFile = (fileId: string) => {
    const updatedFiles = selectedFiles.filter(file => file.id !== fileId)
    onFileSelected(updatedFiles)
  }

  const getFileIcon = (item: SharePointFile | SharePointSite) => {
    if ('displayName' in item) {
      return <Building2 className="h-4 w-4 text-blue-600" />
    }
    if (item.driveItem?.folder) {
      return <Folder className="h-4 w-4 text-blue-600" />
    }
    return <FileText className="h-4 w-4 text-gray-600" />
  }

  const getMimeTypeLabel = (file: SharePointFile) => {
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

  if (!isAuthenticated) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center text-center p-6">
          <p className="text-sm text-gray-600">
            Please connect to SharePoint first to select specific files.
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
            Try disconnecting and reconnecting your SharePoint account.
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
              Select files from SharePoint to ingest.
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
              <h3 className="text-lg font-semibold">Select Files from SharePoint</h3>
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
                  <span key={`${crumb.type}-${crumb.id}`}>
                    {index > 0 && <span className="mx-1">/</span>}
                    {crumb.name}
                  </span>
                ))}
              </div>
            </div>

            {/* Content List */}
            <div className="border rounded-md max-h-96 overflow-y-auto">
              {isLoading ? (
                <div className="p-4 text-center text-gray-600">Loading...</div>
              ) : currentView === 'sites' ? (
                sites.length === 0 ? (
                  <div className="p-4 text-center text-gray-600">No sites found</div>
                ) : (
                  <div className="divide-y">
                    {sites.map((site) => (
                      <div
                        key={site.id}
                        className="flex items-center p-3 hover:bg-gray-50 cursor-pointer"
                        onClick={() => handleSiteClick(site)}
                      >
                        <div className="flex items-center gap-3 flex-1">
                          {getFileIcon(site)}
                          <span className="font-medium">{site.displayName}</span>
                          <Badge variant="secondary" className="text-xs">
                            Site
                          </Badge>
                        </div>
                        <span className="text-xs text-gray-500">Click to open</span>
                      </div>
                    ))}
                  </div>
                )
              ) : files.length === 0 ? (
                <div className="p-4 text-center text-gray-600">No files found</div>
              ) : (
                <div className="divide-y">
                  {files.map((file) => (
                    <div
                      key={file.id}
                      className="flex items-center p-3 hover:bg-gray-50 cursor-pointer"
                      onClick={() => currentView === 'drives' ? handleDriveClick(file) : handleFileClick(file)}
                    >
                      <div className="flex items-center gap-3 flex-1">
                        {getFileIcon(file)}
                        <span className="font-medium">{file.name}</span>
                        <Badge variant="secondary" className="text-xs">
                          {currentView === 'drives' ? 'Library' : getMimeTypeLabel(file)}
                        </Badge>
                      </div>
                      {currentView === 'files' && selectedFiles.some(f => f.id === file.id) ? (
                        <Badge className="text-xs bg-green-100 text-green-800 border-green-300">Selected</Badge>
                      ) : file.driveItem?.folder || currentView === 'drives' ? (
                        <span className="text-xs text-gray-500">Click to open</span>
                      ) : (
                        <span className="text-xs text-gray-500">Click to select</span>
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
