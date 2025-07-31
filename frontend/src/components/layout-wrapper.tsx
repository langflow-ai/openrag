"use client"

import { usePathname } from "next/navigation"
import { Bell, BellRing } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Navigation } from "@/components/navigation"
import { ModeToggle } from "@/components/mode-toggle"
import { UserNav } from "@/components/user-nav"
import { TaskNotificationMenu } from "@/components/task-notification-menu"
import { useTask } from "@/contexts/task-context"

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { tasks, isMenuOpen, toggleMenu } = useTask()
  
  // List of paths that should not show navigation
  const authPaths = ['/login', '/auth/callback']
  const isAuthPage = authPaths.includes(pathname)
  
  // Calculate active tasks for the bell icon
  const activeTasks = tasks.filter(task => 
    task.status === 'pending' || task.status === 'running' || task.status === 'processing'
  )
  
  if (isAuthPage) {
    // For auth pages, render without navigation
    return (
      <div className="h-full">
        {children}
      </div>
    )
  }
  
  // For all other pages, render with full navigation and task menu
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
              {/* Task Notification Bell */}
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleMenu}
                className="relative p-2"
              >
                {activeTasks.length > 0 ? (
                  <BellRing className="h-4 w-4 text-blue-500" />
                ) : (
                  <Bell className="h-4 w-4 text-muted-foreground" />
                )}
                {activeTasks.length > 0 && (
                  <Badge 
                    variant="secondary" 
                    className="absolute -top-1 -right-1 h-5 w-5 flex items-center justify-center p-0 text-xs bg-blue-500 text-white border-0"
                  >
                    {activeTasks.length}
                  </Badge>
                )}
              </Button>
              <UserNav />
              <ModeToggle />
            </nav>
          </div>
        </div>
      </header>
      <div className="hidden md:flex md:w-72 md:flex-col md:fixed md:top-14 md:bottom-0 md:left-0 z-[80] border-r border-border/40">
        <Navigation />
      </div>
      <main className={`md:pl-72 ${isMenuOpen ? 'md:pr-80' : ''}`}>
        <div className="flex flex-col h-[calc(100vh-3.6rem)]">
          <div className="flex-1 overflow-y-auto scrollbar-hide">
            <div className="container py-6 lg:py-8">
              {children}
            </div>
          </div>
        </div>
      </main>
      <TaskNotificationMenu />
    </div>
  )
} 