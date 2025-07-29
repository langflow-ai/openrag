"use client"

import { useEffect, useState, useRef } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Loader2, CheckCircle, XCircle, ArrowLeft } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"

export default function AuthCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refreshAuth } = useAuth()
  const [status, setStatus] = useState<"processing" | "success" | "error">("processing")
  const [error, setError] = useState<string | null>(null)
  const hasProcessed = useRef(false)

  useEffect(() => {
    // Prevent double execution in React Strict Mode
    if (hasProcessed.current) return
    hasProcessed.current = true

    const handleCallback = async () => {
      try {
        // Get parameters from URL
        const code = searchParams.get('code')
        const state = searchParams.get('state')
        const errorParam = searchParams.get('error')
        
        // Get stored auth info
        const connectorId = localStorage.getItem('connecting_connector_id')
        const storedConnectorType = localStorage.getItem('connecting_connector_type')
        const authPurpose = localStorage.getItem('auth_purpose')
        
        // Debug logging
        console.log('Auth Callback Debug:', {
          urlParams: { code: !!code, state: !!state, error: errorParam },
          localStorage: { connectorId, storedConnectorType, authPurpose },
          fullUrl: window.location.href
        })
        
        // Use state parameter as connection_id if localStorage is missing
        const finalConnectorId = connectorId || state
        
        if (errorParam) {
          throw new Error(`OAuth error: ${errorParam}`)
        }
        
        if (!code || !state || !finalConnectorId) {
          console.error('Missing auth callback parameters:', {
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
        
        if (response.ok && result.purpose === 'app_auth') {
          setStatus("success")
          
          // Refresh auth context to pick up the new user
          await refreshAuth()
          
          // Clean up localStorage
          localStorage.removeItem('connecting_connector_id')
          localStorage.removeItem('connecting_connector_type')
          localStorage.removeItem('auth_purpose')
          
          // Get redirect URL from login page
          const redirectTo = searchParams.get('redirect') || '/'
          
          // Redirect to the original page or home
          setTimeout(() => {
            router.push(redirectTo)
          }, 2000)
        } else {
          throw new Error(result.error || 'Authentication failed')
        }
        
      } catch (err) {
        console.error('Auth callback error:', err)
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

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="flex items-center justify-center gap-2">
            {status === "processing" && (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Signing you in...
              </>
            )}
            {status === "success" && (
              <>
                <CheckCircle className="h-5 w-5 text-green-500" />
                Welcome to GenDB!
              </>
            )}
            {status === "error" && (
              <>
                <XCircle className="h-5 w-5 text-red-500" />
                Sign In Failed
              </>
            )}
          </CardTitle>
          <CardDescription>
            {status === "processing" && "Please wait while we complete your sign in..."}
            {status === "success" && "You will be redirected shortly."}
            {status === "error" && "There was an issue signing you in."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status === "error" && (
            <div className="space-y-4">
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <p className="text-sm text-red-600">{error}</p>
              </div>
              <Button 
                onClick={() => router.push('/login')} 
                variant="outline" 
                className="w-full"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Login
              </Button>
            </div>
          )}
          {status === "success" && (
            <div className="text-center">
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <p className="text-sm text-green-600">
                  Redirecting you to the app...
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
} 