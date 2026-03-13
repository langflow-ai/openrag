"use client";

import { Bell, Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface TaskPanelHeaderProps {
  activeCount?: number;
  isFetching?: boolean;
  onClose: () => void;
}

export function TaskPanelHeader({
  activeCount = 0,
  isFetching = false,
  onClose,
}: TaskPanelHeaderProps) {
  return (
    <div className="p-4 border-t border-muted" data-testid="tasks-panel-header">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold" data-testid="tasks-panel-title">
            Tasks
          </h3>
          {isFetching && (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
          )}
          {activeCount > 0 && (
            <Badge variant="secondary" className="bg-blue-500/10 text-blue-500">
              {activeCount}
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          onClick={onClose}
          aria-label="Close task panel"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
