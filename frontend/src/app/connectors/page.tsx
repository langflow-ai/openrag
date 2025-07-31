"use client"

import { useState, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, PlugZap, CheckCircle, XCircle, RefreshCw, Download, AlertCircle } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"
import { useTask } from "@/contexts/task-context"
import { ProtectedRoute } from "@/components/protected-route"

interface Connector {
  id: string
  name: string
  description: string
  icon: React.ReactNode
  status: "not_connected" | "connecting" | "connected" | "error"
  type: string
  connectionId?: string  // Store the active connection ID for syncing
  access_token?: string // For connectors that use OAuth
}

interface SyncResult {
  processed?: number;
  added?: number;
  skipped?: number;
  errors?: number;
  error?: string;
  message?: string; // For sync started messages
  isStarted?: boolean; // For sync started state
}

interface Connection {
  connection_id: string
  name: string
  is_active: boolean
  created_at: string
  last_sync?: string
}

function ConnectorsPage() {
  const { isAuthenticated } = useAuth()
  const { addTask, refreshTasks } = useTask()
  const searchParams = useSearchParams()
  const [connectors, setConnectors] = useState<Connector[]>([])
  
  const [isConnecting, setIsConnecting] = useState<string | null>(null)
  const [isSyncing, setIsSyncing] = useState<string | null>(null)
  const [syncResults, setSyncResults] = useState<{[key: string]: SyncResult | null}>({})
  const [maxFiles, setMaxFiles] = useState<number>(10)

  // Function definitions first
  const checkConnectorStatuses = async () => {
    // Initialize connectors list
    setConnectors([
      {
        id: "google_drive",
        name: "Google Drive",
        description: "Connect your Google Drive to automatically sync documents",
        icon: <div className="w-8 h-8 bg-blue-500 rounded flex items-center justify-center text-white font-bold">G</div>,
        status: "not_connected",
        type: "google_drive"
      },
    ])

    try {
      // Check status for each connector type
      const connectorTypes = ["google_drive"]
      
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
  }

  const handleConnect = async (connector: Connector) => {
    setIsConnecting(connector.id)
    setConnectors(prev => prev.map(c => 
      c.id === connector.id ? { ...c, status: "connecting" } : c
    ))
    
    try {
      // Use the shared auth callback URL, not a separate connectors callback
      const redirectUri = `${window.location.origin}/auth/callback`
      
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

  const handleSync = async (connector: Connector) => {
    if (!connector.connectionId) {
      console.error('No connection ID available for connector')
      return
    }

    setIsSyncing(connector.id)
    setSyncResults(prev => ({ ...prev, [connector.id]: null })) // Clear any existing progress

    try {
      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          max_files: maxFiles
        }),
      })

      const result = await response.json()

      if (response.status === 201 && result.task_id) {
        // Task-based sync, use centralized tracking
        addTask(result.task_id)
        console.log(`Sync task ${result.task_id} added to central tracking for connector ${connector.id}`)
        
        // Immediately refresh task notifications to show the new task
        await refreshTasks()
        
        // Show sync started message
        setSyncResults(prev => ({ 
          ...prev, 
          [connector.id]: {
            message: "Check task notification panel for progress",
            isStarted: true
          }
        }))
        setIsSyncing(null)
      } else if (response.ok) {
        // Direct sync result - still show "sync started" message
        setSyncResults(prev => ({ 
          ...prev, 
          [connector.id]: {
            message: "Check task notification panel for progress",
            isStarted: true
          }
        }))
        setIsSyncing(null)
      } else {
        throw new Error(result.error || 'Sync failed')
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
              
              {/* Sync Results */}
              {syncResults[connector.id] && (
                <div className="mt-4 p-3 bg-muted/50 rounded-lg">
                  {syncResults[connector.id]?.isStarted && (
                    <div className="text-sm">
                      <div className="font-medium text-blue-600 mb-1">
                        <RefreshCw className="inline h-3 w-3 mr-1" />
                        Task initiated:
                      </div>
                      <div className="text-blue-600">
                        {syncResults[connector.id]?.message}
                      </div>
                    </div>
                  )}
                  {syncResults[connector.id]?.error && (
                    <div className="text-sm">
                      <div className="font-medium text-red-600 mb-1">
                        <XCircle className="h-4 w-4 inline mr-1" />
                        Sync Failed
                      </div>
                      <div className="text-red-600">
                        {syncResults[connector.id]?.error}
                      </div>
                    </div>
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