"use client"

import { useState } from 'react'
import { Bell, BellRing, CheckCircle, XCircle, Clock, Loader2, ChevronDown, ChevronUp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useTask, Task } from '@/contexts/task-context'

export function TaskNotificationMenu() {
  const { tasks, isFetching, isMenuOpen, cancelTask } = useTask()
  const [isExpanded, setIsExpanded] = useState(false)

  // Don't render if menu is closed
  if (!isMenuOpen) return null

  const activeTasks = tasks.filter(task => 
    task.status === 'pending' || task.status === 'running' || task.status === 'processing'
  )
  const recentTasks = tasks.filter(task => 
    task.status === 'completed' || task.status === 'failed' || task.status === 'error'
  ).slice(0, 5) // Show last 5 completed/failed tasks

  const getTaskIcon = (status: Task['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
      case 'error':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'pending':
        return <Clock className="h-4 w-4 text-yellow-500" />
      case 'running':
      case 'processing':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-gray-500" />
    }
  }

  const getStatusBadge = (status: Task['status']) => {
    switch (status) {
      case 'completed':
        return <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">Completed</Badge>
      case 'failed':
      case 'error':
        return <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">Failed</Badge>
      case 'pending':
        return <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">Pending</Badge>
      case 'running':
      case 'processing':
        return <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">Processing</Badge>
      default:
        return <Badge variant="outline" className="bg-gray-500/10 text-gray-500 border-gray-500/20">Unknown</Badge>
    }
  }

  const formatTaskProgress = (task: Task) => {
    const total = task.total_files || 0
    const processed = task.processed_files || 0
    const successful = task.successful_files || 0
    const failed = task.failed_files || 0
    const skipped = Math.max(0, processed - successful - failed) // Calculate skipped
    
    if (total > 0) {
      return {
        basic: `${processed}/${total} files`,
        detailed: {
          total,
          processed,
          successful,
          failed,
          skipped,
          remaining: total - processed
        }
      }
    }
    return null
  }

  const formatRelativeTime = (dateString: string) => {
    // Handle different timestamp formats
    let date: Date
    
    // If it's a number (Unix timestamp), convert it
    if (/^\d+$/.test(dateString)) {
      const timestamp = parseInt(dateString)
      // If it looks like seconds (less than 10^13), convert to milliseconds
      date = new Date(timestamp < 10000000000 ? timestamp * 1000 : timestamp)
    } 
    // If it's a decimal number (Unix timestamp with decimals)
    else if (/^\d+\.\d+$/.test(dateString)) {
      const timestamp = parseFloat(dateString)
      // Convert seconds to milliseconds
      date = new Date(timestamp * 1000)
    }
    // Otherwise, try to parse as ISO string or other date format
    else {
      date = new Date(dateString)
    }
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
      console.warn('Invalid date format:', dateString)
      return 'Unknown time'
    }
    
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMinutes = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMinutes < 1) return 'Just now'
    if (diffMinutes < 60) return `${diffMinutes}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    return `${diffDays}d ago`
  }

  return (
    <div className="fixed top-14 right-0 z-40 w-80 h-[calc(100vh-3.5rem)] bg-background border-l border-border/40">
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="p-4 border-b border-border/40">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {activeTasks.length > 0 ? (
                <BellRing className="h-5 w-5 text-blue-500" />
              ) : (
                <Bell className="h-5 w-5 text-muted-foreground" />
              )}
              <h3 className="font-semibold">Tasks</h3>
              {isFetching && (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              )}
            </div>
            {activeTasks.length > 0 && (
              <Badge variant="secondary" className="bg-blue-500/10 text-blue-500">
                {activeTasks.length}
              </Badge>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Active Tasks */}
          {activeTasks.length > 0 && (
            <div className="p-4 space-y-3">
              <h4 className="text-sm font-medium text-muted-foreground">Active Tasks</h4>
              {activeTasks.map((task) => (
                <Card key={task.task_id} className="bg-card/50">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm flex items-center gap-2">
                        {getTaskIcon(task.status)}
                        Task {task.task_id.substring(0, 8)}...
                      </CardTitle>
                    </div>
                    <CardDescription className="text-xs">
                      Started {formatRelativeTime(task.created_at)}
                    </CardDescription>
                  </CardHeader>
                  {formatTaskProgress(task) && (
                    <CardContent className="pt-0">
                      <div className="space-y-2">
                        <div className="text-xs text-muted-foreground">
                          Progress: {formatTaskProgress(task)?.basic}
                        </div>
                        {formatTaskProgress(task)?.detailed && (
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div className="flex items-center gap-1">
                              <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                              <span className="text-green-600">
                                {formatTaskProgress(task)?.detailed.successful} success
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <div className="w-2 h-2 bg-red-500 rounded-full"></div>
                              <span className="text-red-600">
                                {formatTaskProgress(task)?.detailed.failed} failed
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <div className="w-2 h-2 bg-yellow-500 rounded-full"></div>
                              <span className="text-yellow-600">
                                {formatTaskProgress(task)?.detailed.skipped} skipped
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <div className="w-2 h-2 bg-gray-400 rounded-full"></div>
                              <span className="text-muted-foreground">
                                {formatTaskProgress(task)?.detailed.remaining} pending
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                      {/* Cancel button in bottom right */}
                      {(task.status === 'pending' || task.status === 'running' || task.status === 'processing') && (
                        <div className="flex justify-end mt-3">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => cancelTask(task.task_id)}
                            className="h-7 px-3 text-xs"
                            title="Cancel task"
                          >
                            <X className="h-3 w-3 mr-1" />
                            Cancel
                          </Button>
                        </div>
                      )}
                    </CardContent>
                  )}
                  {/* Cancel button for tasks without progress */}
                  {!formatTaskProgress(task) && (task.status === 'pending' || task.status === 'running' || task.status === 'processing') && (
                    <CardContent className="pt-0">
                      <div className="flex justify-end">
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => cancelTask(task.task_id)}
                          className="h-7 px-3 text-xs"
                          title="Cancel task"
                        >
                          <X className="h-3 w-3 mr-1" />
                          Cancel
                        </Button>
                      </div>
                    </CardContent>
                  )}
                </Card>
              ))}
            </div>
          )}

          {/* Recent Tasks */}
          {recentTasks.length > 0 && (
            <div className="p-4 space-y-3 border-t border-border/40">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-muted-foreground">Recent Tasks</h4>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="h-6 w-6 p-0"
                >
                  {isExpanded ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                </Button>
              </div>
              
              {isExpanded && (
                <div className="space-y-2 transition-all duration-200">
                  {recentTasks.map((task) => (
                    <div
                      key={task.task_id}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50 transition-colors"
                    >
                      {getTaskIcon(task.status)}
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium truncate">
                          Task {task.task_id.substring(0, 8)}...
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {formatRelativeTime(task.updated_at)}
                        </div>
                        {/* Show final results for completed tasks */}
                        {task.status === 'completed' && formatTaskProgress(task)?.detailed && (
                          <div className="text-xs text-muted-foreground mt-1">
                            {formatTaskProgress(task)?.detailed.successful} success, {' '}
                            {formatTaskProgress(task)?.detailed.failed} failed, {' '}
                            {formatTaskProgress(task)?.detailed.skipped} skipped
                          </div>
                        )}
                        {task.status === 'failed' && task.error && (
                          <div className="text-xs text-red-600 mt-1 truncate">
                            {task.error}
                          </div>
                        )}
                      </div>
                      {getStatusBadge(task.status)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Empty State */}
          {activeTasks.length === 0 && recentTasks.length === 0 && (
            <div className="p-8 text-center">
              <Bell className="h-12 w-12 text-muted-foreground/50 mx-auto mb-4" />
              <h4 className="text-sm font-medium text-muted-foreground mb-2">No tasks yet</h4>
              <p className="text-xs text-muted-foreground">
                Task notifications will appear here when you upload files or sync connectors.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
} 