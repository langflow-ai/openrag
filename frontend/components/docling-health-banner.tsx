"use client";

import { AlertTriangle, ExternalLink, Copy } from "lucide-react";
import { useDoclingHealthQuery } from "@/src/app/api/queries/useDoclingHealthQuery";
import { Banner, BannerIcon, BannerTitle, BannerAction } from "@/components/ui/banner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useState } from "react";

interface DoclingHealthBannerProps {
  className?: string;
}

// DoclingSetupDialog component
interface DoclingSetupDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
}

function DoclingSetupDialog({
  open,
  onOpenChange,
  className
}: DoclingSetupDialogProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText("uv run openrag");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("max-w-lg", className)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            docling-serve is stopped. Knowledge ingest is unavailable.
          </DialogTitle>
          <DialogDescription>
            Start docling-serve by running:
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-muted px-3 py-2.5 rounded-md text-sm font-mono">
              uv run openrag
            </code>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCopy}
              className="shrink-0"
              title={copied ? "Copied!" : "Copy to clipboard"}
            >
              <Copy className="h-4 w-4" />
            </Button>
          </div>

          <DialogDescription>
            Then, select <span className="font-semibold text-foreground">Start Native Services</span> in the TUI. Once docling-serve is running, refresh OpenRAG.
          </DialogDescription>
        </div>

        <DialogFooter>
          <Button
            variant="default"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DoclingHealthBanner({ className }: DoclingHealthBannerProps) {
  const { data: health, isLoading, isError } = useDoclingHealthQuery();
  const [showDialog, setShowDialog] = useState(false);

  const isHealthy = health?.status === "healthy" && !isError;
  const isUnhealthy = health?.status === "unhealthy" || isError;

  // Only show banner when service is unhealthy
  if (isLoading || isHealthy) {
    return null;
  }

  if (isUnhealthy) {
    return (
      <>
        <Banner
          className={cn(
            "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border-amber-200 dark:border-amber-800",
            className
          )}
        >
          <BannerIcon
            icon={AlertTriangle}
          />
          <BannerTitle className="font-medium">
            docling-serve native service is stopped. Knowledge ingest is unavailable.
          </BannerTitle>
          <BannerAction
            onClick={() => setShowDialog(true)}
            className="bg-foreground text-background hover:bg-primary/90"
          >
            Setup Docling Serve
            <ExternalLink className="h-3 w-3 ml-1" />
          </BannerAction>
        </Banner>

        <DoclingSetupDialog
          open={showDialog}
          onOpenChange={setShowDialog}
        />
      </>
    );
  }

  return null;
}