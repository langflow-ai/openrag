"use client"

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'

interface User {
  user_id: string
  email: string
  name: string
  picture?: string
  provider: string
  last_login?: string
}

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  login: () => void
  logout: () => Promise<void>
  refreshAuth: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const checkAuth = async () => {
    try {
      const response = await fetch('/api/auth/me')
      const data = await response.json()
      
      if (data.authenticated && data.user) {
        setUser(data.user)
      } else {
        setUser(null)
      }
    } catch (error) {
      console.error('Auth check failed:', error)
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }

  const login = () => {
    // Use the correct auth callback URL, not connectors callback
    const redirectUri = `${window.location.origin}/auth/callback`
    
    console.log('Starting login with redirect URI:', redirectUri)
    
    fetch('/api/auth/init', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        connector_type: 'google_drive',
        purpose: 'app_auth',
        name: 'App Authentication',
        redirect_uri: redirectUri
      }),
    })
    .then(response => response.json())
    .then(result => {
      console.log('Auth init response:', result)
      
      if (result.oauth_config) {
        // Store that this is for app authentication
        localStorage.setItem('auth_purpose', 'app_auth')
        localStorage.setItem('connecting_connector_id', result.connection_id)
        localStorage.setItem('connecting_connector_type', 'app_auth')
        
        console.log('Stored localStorage items:', {
          auth_purpose: localStorage.getItem('auth_purpose'),
          connecting_connector_id: localStorage.getItem('connecting_connector_id'),
          connecting_connector_type: localStorage.getItem('connecting_connector_type')
        })
        
        const authUrl = `${result.oauth_config.authorization_endpoint}?` +
          `client_id=${result.oauth_config.client_id}&` +
          `response_type=code&` +
          `scope=${result.oauth_config.scopes.join(' ')}&` +
          `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
          `access_type=offline&` +
          `prompt=consent&` +
          `state=${result.connection_id}`
        
        console.log('Redirecting to OAuth URL:', authUrl)
        window.location.href = authUrl
      } else {
        console.error('No oauth_config in response:', result)
      }
    })
    .catch(error => {
      console.error('Login failed:', error)
    })
  }

  const logout = async () => {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
      })
      setUser(null)
    } catch (error) {
      console.error('Logout failed:', error)
    }
  }

  const refreshAuth = async () => {
    await checkAuth()
  }

  useEffect(() => {
    checkAuth()
  }, [])

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    login,
    logout,
    refreshAuth,
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
} 