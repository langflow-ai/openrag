"use client"

import { useEffect } from "react"
import { useRouter, usePathname } from "next/navigation"
import { useAuth } from "@/contexts/auth-context"
import { Loader2 } from "lucide-react"

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isLoading, isAuthenticated } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  
  console.log("ProtectedRoute - isLoading:", isLoading, "isAuthenticated:", isAuthenticated, "pathname:", pathname)

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      // Redirect to login with current path as redirect parameter
      const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`
      router.push(redirectUrl)
    }
  }, [isLoading, isAuthenticated, router, pathname])

  // Show loading state while checking authentication
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  // Don't render anything if not authenticated (will redirect)
  if (!isAuthenticated) {
    return null
  }

  // Render protected content
  return <>{children}</>
} 