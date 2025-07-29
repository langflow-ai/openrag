"use client"

import { usePathname } from "next/navigation"
import { Navigation } from "@/components/navigation"
import { ModeToggle } from "@/components/mode-toggle"
import { UserNav } from "@/components/user-nav"

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  
  // List of paths that should not show navigation
  const authPaths = ['/login', '/auth/callback']
  const isAuthPage = authPaths.includes(pathname)
  
  if (isAuthPage) {
    // For auth pages, render without navigation
    return (
      <div className="h-full">
        {children}
      </div>
    )
  }
  
  // For all other pages, render with full navigation
  return (
    <div className="h-full relative">
      <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background">
        <div className="flex h-14 items-center px-4">
          <div className="flex items-center">
            <h1 className="text-lg font-semibold tracking-tight text-white">
              GenDB
            </h1>
          </div>
          <div className="flex flex-1 items-center justify-end space-x-2">
            <nav className="flex items-center space-x-2">
              <UserNav />
              <ModeToggle />
            </nav>
          </div>
        </div>
      </header>
      <div className="hidden md:flex md:w-72 md:flex-col md:fixed md:top-14 md:bottom-0 md:left-0 z-[80] border-r border-border/40">
        <Navigation />
      </div>
      <main className="md:pl-72">
        <div className="flex flex-col h-[calc(100vh-3.6rem)]">
          <div className="flex-1 overflow-y-auto">
            <div className="container py-6 lg:py-8">
              {children}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
} 