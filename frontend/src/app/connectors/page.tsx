"use client"

import { useState, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, PlugZap, CheckCircle, XCircle, RefreshCw, FileText, Download, AlertCircle } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"
import { ProtectedRoute } from "@/components/protected-route"

interface Connector {
  id: string
  name: string
  description: string
  icon: React.ReactNode
  status: "not_connected" | "connecting" | "connected" | "error"
  type: string
  connectionId?: string  // Store the active connection ID for syncing
}

interface ConnectorStatus {
  authenticated: boolean
  status: string
  connections: Array<{
    connection_id: string
    name: string
    is_active: boolean
    created_at: string
    last_sync?: string
  }>
}

function ConnectorsPage() {
  const { user, isAuthenticated } = useAuth()
  const searchParams = useSearchParams()
  const [connectors, setConnectors] = useState<Connector[]>([
    {
      id: "google_drive",
      name: "Google Drive",
      description: "Connect your Google Drive to automatically sync documents",
      icon: <div className="w-8 h-8 bg-blue-500 rounded flex items-center justify-center text-white font-bold">G</div>,
      status: "not_connected",
      type: "google_drive"
    },
    // Future connectors can be added here
    // {
    //   id: "dropbox",
    //   name: "Dropbox", 
    //   description: "Connect your Dropbox to automatically sync documents",
    //   icon: <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold">D</div>,
    //   status: "not_connected",
    //   type: "dropbox"
    // }
  ])
  
  const [isConnecting, setIsConnecting] = useState<string | null>(null)
  const [isSyncing, setIsSyncing] = useState<string | null>(null)
  const [syncResults, setSyncResults] = useState<{ [key: string]: any }>({})
  const [syncProgress, setSyncProgress] = useState<{ [key: string]: any }>({})
  const [maxFiles, setMaxFiles] = useState<number>(10)

  // Function definitions first
  const checkConnectorStatuses = async () => {
    for (const connector of connectors) {
      try {
        const response = await fetch(`/api/connectors/status/${connector.type}`)
        if (response.ok) {
          const status: ConnectorStatus = await response.json()
          const isConnected = status.authenticated
          
          // Find the first active connection to use for syncing
          const activeConnection = status.connections?.find(conn => conn.is_active)
          
          setConnectors(prev => prev.map(c => 
            c.id === connector.id 
              ? { 
                  ...c, 
                  status: isConnected ? "connected" : "not_connected",
                  connectionId: activeConnection?.connection_id 
                } 
              : c
          ))
        }
      } catch (error) {
        console.error(`Failed to check status for ${connector.name}:`, error)
      }
    }
  }

  const refreshConnectorStatus = async (connectorId: string) => {
    const connector = connectors.find(c => c.id === connectorId)
    if (!connector) return

    try {
      const response = await fetch(`/api/connectors/status/${connector.type}`)
      if (response.ok) {
        const status: ConnectorStatus = await response.json()
        const isConnected = status.authenticated
        
        // Find the first active connection to use for syncing
        const activeConnection = status.connections?.find(conn => conn.is_active)
        
        setConnectors(prev => prev.map(c => 
          c.id === connectorId 
            ? { 
                ...c, 
                status: isConnected ? "connected" : "not_connected",
                connectionId: activeConnection?.connection_id 
              } 
            : c
        ))
      }
    } catch (error) {
      console.error(`Failed to refresh status for ${connector.name}:`, error)
    }
  }

  const handleConnect = async (connector: Connector) => {
    setIsConnecting(connector.id)
    setConnectors(prev => prev.map(c => 
      c.id === connector.id ? { ...c, status: "connecting" } : c
    ))
    
    try {
      // Frontend determines the correct redirect URI using its own origin
      const redirectUri = `${window.location.origin}/connectors/callback`
      
      const response = await fetch('/api/auth/init', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider: connector.type.replace('_drive', ''), // "google_drive" -> "google"
          purpose: "data_source",
          name: `${connector.name} Connection`,
          redirect_uri: redirectUri
        }),
      })

      const result = await response.json()
      
      if (response.ok) {
        // Store connector ID for callback
        localStorage.setItem('connecting_connector_id', result.connection_id)
        localStorage.setItem('connecting_connector_type', connector.type)
        
        // Handle client-side OAuth with Google's library
        if (result.oauth_config) {
          // Use the redirect URI provided by the backend
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
        throw new Error(result.error || 'Failed to initialize OAuth')
      }
    } catch (error) {
      console.error('OAuth initialization failed:', error)
      setConnectors(prev => prev.map(c => 
        c.id === connector.id ? { ...c, status: "error" } : c
      ))
    } finally {
      setIsConnecting(null)
    }
  }

  const pollTaskStatus = async (taskId: string, connectorId: string) => {
    const maxAttempts = 120 // Poll for up to 10 minutes (120 * 5s intervals)
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
          // Task completed successfully
          setSyncResults(prev => ({ 
            ...prev, 
            [connectorId]: {
              processed: task.total_files || 0,
              added: task.successful_files || 0,
              skipped: (task.total_files || 0) - (task.successful_files || 0),
              errors: task.failed_files || 0
            }
          }))
          setSyncProgress(prev => ({ ...prev, [connectorId]: null }))
          setIsSyncing(null)
          
        } else if (task.status === 'failed' || task.status === 'error') {
          // Task failed
          setSyncResults(prev => ({ 
            ...prev, 
            [connectorId]: { 
              error: task.error || 'Sync failed'
            } 
          }))
          setSyncProgress(prev => ({ ...prev, [connectorId]: null }))
          setIsSyncing(null)
          
        } else if (task.status === 'pending' || task.status === 'running') {
          // Still in progress, update progress and continue polling
          const processed = task.processed_files || 0
          const total = task.total_files || 0
          const successful = task.successful_files || 0
          const failed = task.failed_files || 0
          
          setSyncProgress(prev => ({ 
            ...prev, 
            [connectorId]: {
              status: task.status,
              processed,
              total,
              successful,
              failed
            }
          }))
          
          // Continue polling if we haven't exceeded max attempts
          if (attempts < maxAttempts) {
            setTimeout(poll, 5000) // Poll every 5 seconds
          } else {
            setSyncResults(prev => ({ 
              ...prev, 
              [connectorId]: { 
                error: `Sync timeout after ${attempts} attempts. The task may still be running in the background.`
              } 
            }))
            setSyncProgress(prev => ({ ...prev, [connectorId]: null }))
            setIsSyncing(null)
          }
          
        } else {
          // Unknown status
          setSyncResults(prev => ({ 
            ...prev, 
            [connectorId]: { 
              error: `Unknown task status: ${task.status}`
            } 
          }))
          setSyncProgress(prev => ({ ...prev, [connectorId]: null }))
          setIsSyncing(null)
        }
        
      } catch (error) {
        console.error('Task polling error:', error)
        setSyncResults(prev => ({ 
          ...prev, 
          [connectorId]: { 
            error: error instanceof Error ? error.message : 'Failed to check sync status'
          } 
        }))
        setSyncProgress(prev => ({ ...prev, [connectorId]: null }))
        setIsSyncing(null)
      }
    }
    
    // Start polling
    await poll()
  }

  const handleSync = async (connector: Connector) => {
    setIsSyncing(connector.id)
    setSyncResults(prev => ({ ...prev, [connector.id]: null }))
    setSyncProgress(prev => ({ ...prev, [connector.id]: null }))
    
    if (!connector.connectionId) {
      console.error('No connection ID available for syncing')
      setSyncResults(prev => ({ 
        ...prev, 
        [connector.id]: { 
          error: 'No active connection found. Please reconnect and try again.' 
        } 
      }))
      setIsSyncing(null)
      return
    }
    
    try {
      const response = await fetch('/api/connectors/sync', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          connection_id: connector.connectionId,
          max_files: maxFiles
        }),
      })

      const result = await response.json()
      
      if (response.status === 201 && result.task_id) {
        // Async sync started, begin polling for status
        setSyncProgress(prev => ({ 
          ...prev, 
          [connector.id]: {
            status: 'pending',
            processed: 0,
            total: 0,
            successful: 0,
            failed: 0
          }
        }))
        
        // Start polling for task status
        await pollTaskStatus(result.task_id, connector.id)
        
      } else if (response.ok) {
        // Legacy synchronous response (fallback)
        setSyncResults(prev => ({ ...prev, [connector.id]: result }))
        setIsSyncing(null)
      } else {
        throw new Error(result.error || 'Failed to sync')
      }
    } catch (error) {
      console.error('Sync failed:', error)
      setSyncResults(prev => ({ 
        ...prev, 
        [connector.id]: { 
          error: error instanceof Error ? error.message : 'Sync failed' 
        } 
      }))
      setIsSyncing(null)
    }
  }

  const handleDisconnect = async (connector: Connector) => {
    // This would call a disconnect endpoint when implemented
    setConnectors(prev => prev.map(c => 
      c.id === connector.id ? { ...c, status: "not_connected", connectionId: undefined } : c
    ))
    setSyncResults(prev => ({ ...prev, [connector.id]: null }))
  }

  const getStatusIcon = (status: Connector['status']) => {
    switch (status) {
      case "connected":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case "connecting":
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      case "error":
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <XCircle className="h-4 w-4 text-gray-400" />
    }
  }

  const getStatusBadge = (status: Connector['status']) => {
    switch (status) {
      case "connected":
        return <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">Connected</Badge>
      case "connecting":
        return <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">Connecting...</Badge>
      case "error":
        return <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">Error</Badge>
      default:
        return <Badge variant="outline" className="bg-gray-500/10 text-gray-500 border-gray-500/20">Not Connected</Badge>
    }
  }

  // Check connector status on mount and when returning from OAuth
  useEffect(() => {
    if (isAuthenticated) {
      checkConnectorStatuses()
    }
    
    // If we just returned from OAuth, clear the URL parameter
    if (searchParams.get('oauth_success') === 'true') {
      // Clear the URL parameter without causing a page reload
      const url = new URL(window.location.href)
      url.searchParams.delete('oauth_success')
      window.history.replaceState({}, '', url.toString())
    }
  }, [searchParams, isAuthenticated])

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Connectors</h1>
        <p className="text-muted-foreground mt-2">
          Connect external services to automatically sync and index your documents
        </p>
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
            <div className="flex items-center space-x-4">
              <Label htmlFor="maxFiles" className="text-sm font-medium">
                Max files per sync:
              </Label>
              <Input
                id="maxFiles"
                type="number"
                value={maxFiles}
                onChange={(e) => setMaxFiles(parseInt(e.target.value) || 10)}
                className="w-24"
                min="1"
                max="100"
              />
              <span className="text-sm text-muted-foreground">
                (Leave blank or set to 0 for unlimited)
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Connectors Grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {connectors.map((connector) => (
          <Card key={connector.id} className="relative">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {connector.icon}
                  <div>
                    <CardTitle className="text-lg">{connector.name}</CardTitle>
                    <div className="flex items-center gap-2 mt-1">
                      {getStatusIcon(connector.status)}
                      {getStatusBadge(connector.status)}
                    </div>
                  </div>
                </div>
              </div>
              <CardDescription className="mt-2">
                {connector.description}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-col gap-2">
                {connector.status === "not_connected" && (
                  <Button
                    onClick={() => handleConnect(connector)}
                    disabled={isConnecting === connector.id}
                    className="w-full"
                  >
                    {isConnecting === connector.id ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Connecting...
                      </>
                    ) : (
                      <>
                        <PlugZap className="h-4 w-4 mr-2" />
                        Connect
                      </>
                    )}
                  </Button>
                )}
                
                {connector.status === "connected" && (
                  <>
                    <Button
                      onClick={() => handleSync(connector)}
                      disabled={isSyncing === connector.id}
                      variant="default"
                      className="w-full"
                    >
                      {isSyncing === connector.id ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Syncing...
                        </>
                      ) : (
                        <>
                          <RefreshCw className="h-4 w-4 mr-2" />
                          Sync Files
                        </>
                      )}
                    </Button>
                    <Button
                      onClick={() => handleDisconnect(connector)}
                      variant="outline"
                      size="sm"
                      className="w-full"
                    >
                      Disconnect
                    </Button>
                  </>
                )}
                
                {connector.status === "error" && (
                  <Button
                    onClick={() => handleConnect(connector)}
                    disabled={isConnecting === connector.id}
                    variant="destructive"
                    className="w-full"
                  >
                    <AlertCircle className="h-4 w-4 mr-2" />
                    Retry Connection
                  </Button>
                )}
              </div>
              
              {/* Sync Results and Progress */}
              {(syncResults[connector.id] || syncProgress[connector.id]) && (
                <div className="mt-4 p-3 bg-muted/50 rounded-lg">
                  {syncProgress[connector.id] && (
                    <div className="text-sm">
                      <div className="font-medium text-blue-600 mb-1">
                        <RefreshCw className="inline h-3 w-3 mr-1 animate-spin" />
                        Sync in Progress
                      </div>
                      <div className="space-y-1 text-muted-foreground">
                        <div>Status: {syncProgress[connector.id].status}</div>
                        {syncProgress[connector.id].total > 0 && (
                          <>
                            <div>Progress: {syncProgress[connector.id].processed}/{syncProgress[connector.id].total} files</div>
                            <div>Successful: {syncProgress[connector.id].successful}</div>
                            {syncProgress[connector.id].failed > 0 && (
                              <div className="text-red-500">
                                Failed: {syncProgress[connector.id].failed}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  )}
                  
                  {syncResults[connector.id] && !syncProgress[connector.id] && (
                    <>
                      {syncResults[connector.id].error ? (
                        <div className="text-sm text-red-500">
                          <div className="font-medium">Sync Failed</div>
                          <div>{syncResults[connector.id].error}</div>
                        </div>
                      ) : (
                        <div className="text-sm">
                          <div className="font-medium text-green-600 mb-1">
                            <FileText className="inline h-3 w-3 mr-1" />
                            Sync Completed
                          </div>
                          <div className="space-y-1 text-muted-foreground">
                            <div>Processed: {syncResults[connector.id].processed || 0} files</div>
                            <div>Added: {syncResults[connector.id].added || 0} documents</div>
                            <div>Skipped: {syncResults[connector.id].skipped || 0} files</div>
                            {syncResults[connector.id].errors > 0 && (
                              <div className="text-red-500">
                                Errors: {syncResults[connector.id].errors}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
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
              <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold">D</div>
              <div>
                <div className="font-medium">Dropbox</div>
                <div className="text-sm text-muted-foreground">File storage</div>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 rounded-lg border border-dashed">
              <div className="w-8 h-8 bg-purple-600 rounded flex items-center justify-center text-white font-bold">O</div>
              <div>
                <div className="font-medium">OneDrive</div>
                <div className="text-sm text-muted-foreground">Microsoft cloud storage</div>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 rounded-lg border border-dashed">
              <div className="w-8 h-8 bg-orange-600 rounded flex items-center justify-center text-white font-bold">B</div>
              <div>
                <div className="font-medium">Box</div>
                <div className="text-sm text-muted-foreground">Enterprise file sharing</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function ProtectedConnectorsPage() {
  return (
    <ProtectedRoute>
      <ConnectorsPage />
    </ProtectedRoute>
  )
} 