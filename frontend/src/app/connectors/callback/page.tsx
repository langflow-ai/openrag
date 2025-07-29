"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Loader2, CheckCircle, XCircle, ArrowLeft } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"

export default function ConnectorCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refreshAuth } = useAuth()
  const [status, setStatus] = useState<"processing" | "success" | "error">("processing")
  const [error, setError] = useState<string | null>(null)
  const [connectorType, setConnectorType] = useState<string | null>(null)
  const [isAppAuth, setIsAppAuth] = useState<boolean>(false)

  useEffect(() => {
    const handleCallback = async () => {
      try {
        // Get parameters from URL
        const code = searchParams.get('code')
        const state = searchParams.get('state')
        const errorParam = searchParams.get('error')
        
        // Get stored connector info
        const connectorId = localStorage.getItem('connecting_connector_id')
        const storedConnectorType = localStorage.getItem('connecting_connector_type')
        const authPurpose = localStorage.getItem('auth_purpose')
        
        // Debug logging
        console.log('OAuth Callback Debug:', {
          urlParams: { code: !!code, state: !!state, error: errorParam },
          localStorage: { connectorId, storedConnectorType, authPurpose },
          fullUrl: window.location.href
        })
        
        // Use state parameter as connection_id if localStorage is missing
        const finalConnectorId = connectorId || state
        const finalConnectorType = storedConnectorType || 'app_auth'
        const finalAuthPurpose = authPurpose || 'app_auth'
        
        setConnectorType(finalConnectorType)
        setIsAppAuth(finalAuthPurpose === 'app_auth' || finalConnectorType === 'app_auth')
        
        if (errorParam) {
          throw new Error(`OAuth error: ${errorParam}`)
        }
        
        if (!code || !state || !finalConnectorId) {
          console.error('Missing OAuth callback parameters:', {
            code: !!code,
            state: !!state, 
            finalConnectorId: !!finalConnectorId
          })
          throw new Error('Missing required parameters for OAuth callback')
        }
        
        // Send callback data to backend
        const response = await fetch('/api/auth/callback', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            connection_id: finalConnectorId,
            authorization_code: code,
            state: state
          }),
        })
        
        const result = await response.json()
        
        if (response.ok) {
          setStatus("success")
          
          if (result.purpose === 'app_auth' || isAppAuth) {
            // App authentication - refresh auth context and redirect to home
            await refreshAuth()
            
            // Clean up localStorage
            localStorage.removeItem('connecting_connector_id')
            localStorage.removeItem('connecting_connector_type')
            localStorage.removeItem('auth_purpose')
            
            // Redirect to home page after app login
            setTimeout(() => {
              router.push('/')
            }, 2000)
          } else {
            // Connector authentication - redirect to connectors page
            // Clean up localStorage
            localStorage.removeItem('connecting_connector_id')
            localStorage.removeItem('connecting_connector_type')
            localStorage.removeItem('auth_purpose')
            
            // Redirect to connectors page after a short delay
            setTimeout(() => {
              router.push('/connectors?oauth_success=true')
            }, 2000)
          }
        } else {
          throw new Error(result.error || 'Authentication failed')
        }
        
      } catch (err) {
        console.error('OAuth callback error:', err)
        setError(err instanceof Error ? err.message : 'Unknown error occurred')
        setStatus("error")
        
        // Clean up localStorage on error too
        localStorage.removeItem('connecting_connector_id')
        localStorage.removeItem('connecting_connector_type')
        localStorage.removeItem('auth_purpose')
      }
    }
    
    handleCallback()
  }, [searchParams, router, refreshAuth])

  const getTitle = () => {
    if (status === "processing") {
      return isAppAuth ? "Signing In..." : "Connecting..."
    }
    if (status === "success") {
      return isAppAuth ? "Sign In Successful!" : "Connection Successful!"
    }
    if (status === "error") {
      return isAppAuth ? "Sign In Failed" : "Connection Failed"
    }
  }

  const getDescription = () => {
    if (status === "processing") {
      return isAppAuth ? "Please wait while we sign you in..." : "Please wait while we complete the connection..."
    }
    if (status === "success") {
      return "You will be redirected shortly."
    }
    if (status === "error") {
      return isAppAuth ? "There was an issue signing you in." : "There was an issue with the connection."
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="flex items-center justify-center gap-2">
            {status === "processing" && (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                {getTitle()}
              </>
            )}
            {status === "success" && (
              <>
                <CheckCircle className="h-5 w-5 text-green-500" />
                {getTitle()}
              </>
            )}
            {status === "error" && (
              <>
                <XCircle className="h-5 w-5 text-red-500" />
                {getTitle()}
              </>
            )}
          </CardTitle>
          <CardDescription>
            {getDescription()}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status === "error" && (
            <div className="space-y-4">
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <p className="text-sm text-red-600">{error}</p>
              </div>
              <Button 
                onClick={() => router.push(isAppAuth ? '/' : '/connectors')} 
                variant="outline" 
                className="w-full"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                {isAppAuth ? 'Back to Home' : 'Back to Connectors'}
              </Button>
            </div>
          )}
          {status === "success" && (
            <div className="text-center">
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <p className="text-sm text-green-600">
                  {isAppAuth ? 'Redirecting to home...' : 'Redirecting to connectors...'}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
} 