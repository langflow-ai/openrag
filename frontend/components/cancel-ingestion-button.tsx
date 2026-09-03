"use client";

import { RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CancelIngestionButtonProps {
  taskId: string;
  onCancel: (taskId: string) => Promise<void>;
}

export function CancelIngestionButton({
  taskId,
  onCancel,
}: CancelIngestionButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      await onCancel(taskId);
    } finally {
      setLoading(false);
    }
  };

  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="hover:bg-transparent text-muted-foreground hover:text-destructive"
            disabled={loading}
            onClick={handleClick}
            aria-label="Cancel ingestion"
            data-testid="cancel-ingestion-button"
          >
            {loading ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <XCircle className="h-4 w-4" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">Cancel ingestion</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
