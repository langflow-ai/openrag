"use client"

import { useState, useEffect, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Upload, FolderOpen, Loader2, PlugZap, RefreshCw, Download, Cloud } from "lucide-react"
import { ProtectedRoute } from "@/components/protected-route"
import { useTask } from "@/contexts/task-context"
import { useAuth } from "@/contexts/auth-context"
import { FileUploadArea } from "@/components/file-upload-area"

type FacetBucket = { key: string; count: number }

interface Connector {
  id: string
  name: string
  description: string
  icon: React.ReactNode
  status: "not_connected" | "connecting" | "connected" | "error"
  type: string
  connectionId?: string
  access_token?: string
}

interface SyncResult {
  processed?: number;
  added?: number;
  errors?: number;
  skipped?: number;
  total?: number;
}

interface Connection {
  connection_id: string
  is_active: boolean
  created_at: string
  last_sync?: string
}

function KnowledgeSourcesPage() {
  const { isAuthenticated } = useAuth()
  const { addTask, tasks } = useTask()
  const searchParams = useSearchParams()
  
  // File upload state
  const [fileUploadLoading, setFileUploadLoading] = useState(false)
  const [pathUploadLoading, setPathUploadLoading] = useState(false)
  const [folderPath, setFolderPath] = useState("/app/documents/")
  const [bucketUploadLoading, setBucketUploadLoading] = useState(false)
  const [bucketUrl, setBucketUrl] = useState("s3://")
  const [uploadStatus, setUploadStatus] = useState<string>("")
  const [awsEnabled, setAwsEnabled] = useState(false)
  
  // Connectors state
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [isConnecting, setIsConnecting] = useState<string | null>(null)
  const [isSyncing, setIsSyncing] = useState<string | null>(null)
  const [syncResults, setSyncResults] = useState<{[key: string]: SyncResult | null}>({})
  const [maxFiles, setMaxFiles] = useState<number>(10)


  // File upload handlers
  const handleDirectFileUpload = async (file: File) => {
    setFileUploadLoading(true)
    setUploadStatus("")

    try {
      const formData = new FormData()
      formData.append("file", file)

      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      })

      const result = await response.json()
      
      if (response.ok) {
        setUploadStatus(`File processed successfully! ID: ${result.id}`)
        
      } else {
        setUploadStatus(`Error: ${result.error || "Processing failed"}`)
      }
    } catch (error) {
      setUploadStatus(`Error: ${error instanceof Error ? error.message : "Processing failed"}`)
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
        const taskId = result.task_id || result.id
        const totalFiles = result.total_files || 0
        
        if (!taskId) {
          throw new Error("No task ID received from server")
        }
        
        addTask(taskId)
        
        setUploadStatus(`🔄 Processing started for ${totalFiles} files. Check the task notification panel for real-time progress. (Task ID: ${taskId})`)
        setFolderPath("")
        setPathUploadLoading(false)
        
      } else if (response.ok) {
        const successful = result.results?.filter((r: {status: string}) => r.status === "indexed").length || 0
        const total = result.results?.length || 0
        setUploadStatus(`Path processed successfully! ${successful}/${total} files indexed.`)
        setFolderPath("")
        setPathUploadLoading(false)
      } else {
        setUploadStatus(`Error: ${result.error || "Path upload failed"}`)
        setPathUploadLoading(false)
      }
    } catch (error) {
      setUploadStatus(`Error: ${error instanceof Error ? error.message : "Path upload failed"}`)
      setPathUploadLoading(false)
    }
  }

  const handleBucketUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!bucketUrl.trim()) return

    setBucketUploadLoading(true)
    setUploadStatus("")

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
        const totalFiles = result.total_files || 0

        if (!taskId) {
          throw new Error("No task ID received from server")
        }

        addTask(taskId)
        setUploadStatus(`🔄 Processing started for ${totalFiles} files. Check the task notification panel for real-time progress. (Task ID: ${taskId})`)
        setBucketUrl("s3://")
      } else {
        setUploadStatus(`Error: ${result.error || "Bucket processing failed"}`)
      }
    } catch (error) {
      setUploadStatus(
        `Error: ${error instanceof Error ? error.message : "Bucket processing failed"}`,
      )
    } finally {
      setBucketUploadLoading(false)
    }
  }

  // Helper function to get connector icon
  const getConnectorIcon = (iconName: string) => {
    const iconMap: { [key: string]: React.ReactElement } = {
      'google-drive': (
        <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          G
        </div>
      ),
      'sharepoint': (
        <div className="w-8 h-8 bg-blue-700 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          SP
        </div>
      ),
      'onedrive': (
        <div className="w-8 h-8 bg-blue-400 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          OD
        </div>
      ),
    }
    return iconMap[iconName] || (
      <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
        ?
      </div>
    )
  }

  // Connector functions
  const checkConnectorStatuses = useCallback(async () => {
    try {
      // Fetch available connectors from backend
      const connectorsResponse = await fetch('/api/connectors')
      if (!connectorsResponse.ok) {
        throw new Error('Failed to load connectors')
      }
      
      const connectorsResult = await connectorsResponse.json()
      const connectorTypes = Object.keys(connectorsResult.connectors)
      
      // Initialize connectors list with metadata from backend
      const initialConnectors = connectorTypes
        .filter(type => connectorsResult.connectors[type].available) // Only show available connectors
        .map(type => ({
          id: type,
          name: connectorsResult.connectors[type].name,
          description: connectorsResult.connectors[type].description,
          icon: getConnectorIcon(connectorsResult.connectors[type].icon),
          status: "not_connected" as const,
          type: type
        }))
      
      setConnectors(initialConnectors)

      // Check status for each connector type
      
      for (const connectorType of connectorTypes) {
        const response = await fetch(`/api/connectors/${connectorType}/status`)
        if (response.ok) {
          const data = await response.json()
          const connections = data.connections || []
          const activeConnection = connections.find((conn: Connection) => conn.is_active)
          const isConnected = activeConnection !== undefined
          
          setConnectors(prev => prev.map(c => 
            c.type === connectorType 
              ? { 
                  ...c, 
                  status: isConnected ? "connected" : "not_connected",
                  connectionId: activeConnection?.connection_id
                } 
              : c
          ))
        }
      }
    } catch (error) {
      console.error('Failed to check connector statuses:', error)
    }
  }, [])

  const handleConnect = async (connector: Connector) => {
    setIsConnecting(connector.id)
    setSyncResults(prev => ({ ...prev, [connector.id]: null }))
    
    try {
      // Use the shared auth callback URL, same as connectors page
      const redirectUri = `${window.location.origin}/auth/callback`
      
      const response = await fetch('/api/auth/init', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          connector_type: connector.type,
          purpose: "data_source",
          name: `${connector.name} Connection`,
          redirect_uri: redirectUri
        }),
      })
      
      if (response.ok) {
        const result = await response.json()
        
        if (result.oauth_config) {
          localStorage.setItem('connecting_connector_id', result.connection_id)
          localStorage.setItem('connecting_connector_type', connector.type)
          
          const authUrl = `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(' ')}&` +
            `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
            `access_type=offline&` +
            `prompt=consent&` +
            `state=${result.connection_id}`
          
          window.location.href = authUrl
        }
      } else {
        console.error('Failed to initiate connection')
        setIsConnecting(null)
      }
    } catch (error) {
      console.error('Connection error:', error)
      setIsConnecting(null)
    }
  }

  const handleSync = async (connector: Connector) => {
    if (!connector.connectionId) return
    
    setIsSyncing(connector.id)
    setSyncResults(prev => ({ ...prev, [connector.id]: null }))
    
    try {
      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          connection_id: connector.connectionId,
          max_files: maxFiles || undefined
        }),
      })
      
      const result = await response.json()
      
      if (response.status === 201) {
        const taskId = result.task_id
        if (taskId) {
          addTask(taskId)
          setSyncResults(prev => ({ 
            ...prev, 
            [connector.id]: { 
              processed: 0, 
              total: result.total_files || 0 
            }
          }))
        }
      } else if (response.ok) {
        setSyncResults(prev => ({ ...prev, [connector.id]: result }))
        // Note: Stats will auto-refresh via task completion watcher for async syncs
      } else {
        console.error('Sync failed:', result.error)
      }
    } catch (error) {
      console.error('Sync error:', error)
    } finally {
      setIsSyncing(null)
    }
  }

  const getStatusBadge = (status: Connector["status"]) => {
    switch (status) {
      case "connected":
        return <Badge variant="default" className="bg-green-500/20 text-green-400 border-green-500/30">Connected</Badge>
      case "connecting":
        return <Badge variant="secondary" className="bg-yellow-500/20 text-yellow-400 border-yellow-500/30">Connecting...</Badge>
      case "error":
        return <Badge variant="destructive">Error</Badge>
      default:
        return <Badge variant="outline" className="bg-muted/20 text-muted-foreground border-muted whitespace-nowrap">Not Connected</Badge>
    }
  }

  // Check connector status on mount and when returning from OAuth
  useEffect(() => {
    if (isAuthenticated) {
      checkConnectorStatuses()
    }
    
    if (searchParams.get('oauth_success') === 'true') {
      const url = new URL(window.location.href)
      url.searchParams.delete('oauth_success')
      window.history.replaceState({}, '', url.toString())
    }
  }, [searchParams, isAuthenticated, checkConnectorStatuses])


  // Check AWS availability
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


  // Track previous tasks to detect new completions
  const [prevTasks, setPrevTasks] = useState<typeof tasks>([])
  
  // Watch for task completions and refresh stats
  useEffect(() => {
    // Find newly completed tasks by comparing with previous state
    const newlyCompletedTasks = tasks.filter(task => {
      const wasCompleted = prevTasks.find(prev => prev.task_id === task.task_id)?.status === 'completed'
      return task.status === 'completed' && !wasCompleted
    })
    
    if (newlyCompletedTasks.length > 0) {
      // Task completed - could refresh data here if needed
      const timeoutId = setTimeout(() => {
        // Stats refresh removed
      }, 1000)
      
      // Update previous tasks state
      setPrevTasks(tasks)
      
      return () => clearTimeout(timeoutId)
    } else {
      // Always update previous tasks state
      setPrevTasks(tasks)
    }
  }, [tasks, prevTasks])

  return (
    <div className="space-y-8">
      {/* Upload Section */}
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2">Import</h2>
        </div>
        
        <div className={`grid gap-6 ${awsEnabled ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
          {/* File Upload Card */}
          <Card className="flex flex-col">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Upload className="h-5 w-5" />
                Add File
              </CardTitle>
              <CardDescription>
                Import a single document to be processed and indexed
              </CardDescription>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col justify-end">
              <FileUploadArea
                onFileSelected={handleDirectFileUpload}
                isLoading={fileUploadLoading}
              />
            </CardContent>
          </Card>

          {/* Folder Upload Card */}
          <Card className="flex flex-col">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FolderOpen className="h-5 w-5" />
                Process Folder
              </CardTitle>
              <CardDescription>
                Process all documents in a folder path
              </CardDescription>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col justify-end">
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

          {/* S3 Bucket Upload Card - only show if AWS is enabled */}
          {awsEnabled && (
            <Card className="flex flex-col">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Cloud className="h-5 w-5" />
                  Process S3 Bucket
                </CardTitle>
                <CardDescription>
                  Process all documents from an S3 bucket. AWS credentials must be configured.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end">
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

        {/* Upload Status */}
        {uploadStatus && (
          <Card className="bg-muted/20">
            <CardContent className="pt-6">
              <p className="text-sm">{uploadStatus}</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Connectors Section */}
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2">Cloud Connectors</h2>
        </div>

        {/* Sync Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Download className="h-5 w-5" />
              Sync Settings
            </CardTitle>
            <CardDescription>
              Configure how many files to sync when manually triggering a sync
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center text-sm">
                <div className="flex items-center gap-3">
                  <Label htmlFor="maxFiles" className="font-medium whitespace-nowrap">
                    Max files per sync:
                  </Label>
                  <Input
                    id="maxFiles"
                    type="number"
                    value={maxFiles}
                    onChange={(e) => setMaxFiles(parseInt(e.target.value) || 10)}
                    className="w-16 min-w-16 max-w-16 flex-shrink-0"
                    min="1"
                    max="100"
                  />
                  <span className="text-muted-foreground whitespace-nowrap">
                    (Leave blank or set to 0 for unlimited)
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Connectors Grid */}
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {connectors.map((connector) => (
            <Card key={connector.id} className="relative flex flex-col">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {connector.icon}
                    <div>
                      <CardTitle className="text-lg">{connector.name}</CardTitle>
                      <CardDescription className="text-sm">
                        {connector.description}
                      </CardDescription>
                    </div>
                  </div>
                  {getStatusBadge(connector.status)}
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                {connector.status === "connected" ? (
                  <div className="space-y-3">
                    <Button
                      onClick={() => handleSync(connector)}
                      disabled={isSyncing === connector.id}
                      className="w-full"
                      variant="outline"
                    >
                      {isSyncing === connector.id ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Syncing...
                        </>
                      ) : (
                        <>
                          <RefreshCw className="mr-2 h-4 w-4" />
                          Sync Now
                        </>
                      )}
                    </Button>
                    
                    {syncResults[connector.id] && (
                      <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded">
                        <div>Processed: {syncResults[connector.id]?.processed || 0}</div>
                        <div>Added: {syncResults[connector.id]?.added || 0}</div>
                        {syncResults[connector.id]?.errors && (
                          <div>Errors: {syncResults[connector.id]?.errors}</div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <Button
                    onClick={() => handleConnect(connector)}
                    disabled={isConnecting === connector.id}
                    className="w-full"
                  >
                    {isConnecting === connector.id ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Connecting...
                      </>
                    ) : (
                      <>
                        <PlugZap className="mr-2 h-4 w-4" />
                        Connect
                      </>
                    )}
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Coming Soon Section */}
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle className="text-lg text-muted-foreground">Coming Soon</CardTitle>
            <CardDescription>
              Additional connectors are in development
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 opacity-50">
              <div className="flex items-center gap-3 p-3 rounded-lg border border-dashed">
                <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold leading-none">D</div>
                <div>
                  <div className="font-medium">Dropbox</div>
                  <div className="text-sm text-muted-foreground">File storage</div>
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg border border-dashed">
                <div className="w-8 h-8 bg-orange-600 rounded flex items-center justify-center text-white font-bold leading-none">B</div>
                <div>
                  <div className="font-medium">Box</div>
                  <div className="text-sm text-muted-foreground">Enterprise file sharing</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default function ProtectedKnowledgeSourcesPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading knowledge sources...</div>}>
        <KnowledgeSourcesPage />
      </Suspense>
    </ProtectedRoute>
  )
}
