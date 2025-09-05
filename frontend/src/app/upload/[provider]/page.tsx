"use client"

import { useState, useEffect } from "react"
import { useParams, useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, AlertCircle } from "lucide-react"
import { GoogleDrivePicker } from "@/components/google-drive-picker"
import { OneDrivePicker } from "@/components/onedrive-picker"
import { useTask } from "@/contexts/task-context"

interface GoogleDriveFile {
  id: string
  name: string
  mimeType: string
  webViewLink?: string
  iconLink?: string
}

interface OneDriveFile {
  id: string
  name: string
  mimeType?: string
  webUrl?: string
  driveItem?: {
    file?: { mimeType: string }
    folder?: object
  }
}

interface CloudConnector {
  id: string
  name: string
  description: string
  status: "not_connected" | "connecting" | "connected" | "error"
  type: string
  connectionId?: string
  hasAccessToken: boolean
  accessTokenError?: string
}

export default function UploadProviderPage() {
  const params = useParams()
  const router = useRouter()
  const provider = params.provider as string
  const { addTask } = useTask()

  const [connector, setConnector] = useState<CloudConnector | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<GoogleDriveFile[] | OneDriveFile[]>([])
  const [isSyncing, setIsSyncing] = useState<boolean>(false)
  const [syncResult, setSyncResult] = useState<any>(null)

  useEffect(() => {
    const fetchConnectorInfo = async () => {
      setIsLoading(true)
      setError(null)

      try {
        // Fetch available connectors to validate the provider
        const connectorsResponse = await fetch('/api/connectors')
        if (!connectorsResponse.ok) {
          throw new Error('Failed to load connectors')
        }

        const connectorsResult = await connectorsResponse.json()
        const providerInfo = connectorsResult.connectors[provider]

        if (!providerInfo || !providerInfo.available) {
          setError(`Cloud provider "${provider}" is not available or configured.`)
          return
        }

        // Check connector status
        const statusResponse = await fetch(`/api/connectors/${provider}/status`)
        if (!statusResponse.ok) {
          throw new Error(`Failed to check ${provider} status`)
        }

        const statusData = await statusResponse.json()
        const connections = statusData.connections || []
        const activeConnection = connections.find((conn: {is_active: boolean, connection_id: string}) => conn.is_active)
        const isConnected = activeConnection !== undefined

        let hasAccessToken = false
        let accessTokenError: string | undefined = undefined

        // Try to get access token for connected connectors
        if (isConnected && activeConnection) {
          try {
            const tokenResponse = await fetch(`/api/connectors/${provider}/token?connection_id=${activeConnection.connection_id}`)
            if (tokenResponse.ok) {
              const tokenData = await tokenResponse.json()
              if (tokenData.access_token) {
                hasAccessToken = true
                setAccessToken(tokenData.access_token)
              }
            } else {
              const errorData = await tokenResponse.json().catch(() => ({ error: 'Token unavailable' }))
              accessTokenError = errorData.error || 'Access token unavailable'
            }
          } catch {
            accessTokenError = 'Failed to fetch access token'
          }
        }

        setConnector({
          id: provider,
          name: providerInfo.name,
          description: providerInfo.description,
          status: isConnected ? "connected" : "not_connected",
          type: provider,
          connectionId: activeConnection?.connection_id,
          hasAccessToken,
          accessTokenError
        })

      } catch (error) {
        console.error('Failed to load connector info:', error)
        setError(error instanceof Error ? error.message : 'Failed to load connector information')
      } finally {
        setIsLoading(false)
      }
    }

    if (provider) {
      fetchConnectorInfo()
    }
  }, [provider])

  const handleFileSelected = (files: GoogleDriveFile[] | OneDriveFile[]) => {
    setSelectedFiles(files)
    console.log(`Selected ${files.length} files from ${provider}:`, files)
    // You can add additional handling here like triggering sync, etc.
  }

  const handleSync = async (connector: CloudConnector) => {
    if (!connector.connectionId || selectedFiles.length === 0) return
    
    setIsSyncing(true)
    setSyncResult(null)
    
    try {
      const syncBody: {
        connection_id: string;
        max_files?: number;
        selected_files?: string[];
      } = {
        connection_id: connector.connectionId,
        selected_files: selectedFiles.map(file => file.id)
      }
      
      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(syncBody),
      })
      
      const result = await response.json()
      
      if (response.status === 201) {
        const taskId = result.task_id
        if (taskId) {
          addTask(taskId)
          setSyncResult({ 
            processed: 0, 
            total: selectedFiles.length,
            status: 'started'
          })
        }
      } else if (response.ok) {
        setSyncResult(result)
      } else {
        console.error('Sync failed:', result.error)
        setSyncResult({ error: result.error || 'Sync failed' })
      }
    } catch (error) {
      console.error('Sync error:', error)
      setSyncResult({ error: 'Network error occurred' })
    } finally {
      setIsSyncing(false)
    }
  }

  const getProviderDisplayName = () => {
    const nameMap: { [key: string]: string } = {
      'google_drive': 'Google Drive',
      'onedrive': 'OneDrive',
      'sharepoint': 'SharePoint'
    }
    return nameMap[provider] || provider
  }

  if (isLoading) {
    return (
      <div className="container mx-auto p-6">
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4"></div>
            <p>Loading {getProviderDisplayName()} connector...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error || !connector) {
    return (
      <div className="container mx-auto p-6">
        <div className="mb-6">
          <Button 
            variant="ghost" 
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>
        
        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">Provider Not Available</h2>
            <p className="text-muted-foreground mb-4">{error}</p>
            <Button onClick={() => router.push('/settings')}>
              Configure Connectors
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (connector.status !== "connected") {
    return (
      <div className="container mx-auto p-6">
        <div className="mb-6">
          <Button 
            variant="ghost" 
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>
        
        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-yellow-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">{connector.name} Not Connected</h2>
            <p className="text-muted-foreground mb-4">
              You need to connect your {connector.name} account before you can select files.
            </p>
            <Button onClick={() => router.push('/settings')}>
              Connect {connector.name}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (!connector.hasAccessToken) {
    return (
      <div className="container mx-auto p-6">
        <div className="mb-6">
          <Button 
            variant="ghost" 
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>
        
        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">Access Token Required</h2>
            <p className="text-muted-foreground mb-4">
              {connector.accessTokenError || `Unable to get access token for ${connector.name}. Try reconnecting your account.`}
            </p>
            <Button onClick={() => router.push('/settings')}>
              Reconnect {connector.name}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6">
        <Button 
          variant="ghost" 
          onClick={() => router.back()}
          className="mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back
        </Button>
        
        <div className="mb-6 max-w-4xl mx-auto">
          <h1 className="text-2xl font-bold mb-2">Select Files from {connector.name}</h1>
          <p className="text-muted-foreground">
            Choose specific files from your {connector.name} account to add to your knowledge base.
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto">
        {connector.type === "google_drive" && (
          <GoogleDrivePicker
            onFileSelected={handleFileSelected}
            selectedFiles={selectedFiles as GoogleDriveFile[]}
            isAuthenticated={true}
            accessToken={accessToken || undefined}
          />
        )}
        
        {(connector.type === "onedrive" || connector.type === "sharepoint") && (
          <OneDrivePicker
            onFileSelected={handleFileSelected}
            selectedFiles={selectedFiles as OneDriveFile[]}
            isAuthenticated={true}
            accessToken={accessToken || undefined}
            connectorType={connector.type as "onedrive" | "sharepoint"}
          />
        )}
      </div>

      {selectedFiles.length > 0 && (
        <div className="max-w-4xl mx-auto mt-8">
          <div className="flex justify-center gap-3 mb-4">
            <Button 
              onClick={() => handleSync(connector)}
              disabled={selectedFiles.length === 0 || isSyncing}
            >
              {isSyncing ? (
                <>Syncing {selectedFiles.length} Selected Files...</>
              ) : (
                <>Sync Selected Files ({selectedFiles.length})</>
              )}
            </Button>
            <Button 
              variant="outline"
              onClick={() => setSelectedFiles([])}>
              Clear Selection
            </Button>
          </div>
          
          {syncResult && (
            <div className="p-3 bg-gray-100 rounded text-sm text-center">
              {syncResult.error ? (
                <div className="text-red-600">Error: {syncResult.error}</div>
              ) : syncResult.status === 'started' ? (
                <div className="text-blue-600">
                  Sync started for {syncResult.total} files. Check the task notification for progress.
                </div>
              ) : (
                <div className="text-green-600">
                  <div>Processed: {syncResult.processed || 0}</div>
                  <div>Added: {syncResult.added || 0}</div>
                  {syncResult.errors && <div>Errors: {syncResult.errors}</div>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}